"""
dags/edgar_ingestion_dag.py
────────────────────────────
Airflow DAG: Daily SEC EDGAR filing ingestion pipeline.

Schedule: Daily at 06:00 UTC (after EDGAR's nightly batch processing).
Design:
  1. init_warehouse      — ensure DuckDB schema + MinIO buckets exist
  2. ingest_[ticker]     — one task per ticker (runs in parallel, max 5 at once)
  3. validate_ingestion  — data quality checks on what was stored
  4. notify_summary      — log run stats; extend to Slack/email in production

All tasks are idempotent: re-running a DAG run for the same date is safe.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.task_group import TaskGroup

# Make ingestion module importable inside Airflow container
sys.path.insert(0, "/opt/airflow")

logger = logging.getLogger(__name__)

DUCKDB_PATH = os.getenv("DUCKDB_PATH", "/opt/airflow/data/warehouse.db")

# Tickers to ingest — start with a manageable subset, expand over time
TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "NVDA", "TSLA", "JPM", "JNJ", "V",
]

default_args = {
    "owner": "earnings-intel",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "email_on_failure": False,
    "execution_timeout": timedelta(hours=2),
}


# ── Task functions ────────────────────────────────────────────────────────────

def task_init_warehouse(**context) -> dict:
    """
    Ensure DuckDB schema and MinIO buckets exist before any ingestion.
    Idempotent — safe to run every day.
    """
    from ingestion.edgar_client import init_duckdb, get_minio_client, ensure_buckets

    logger.info("Initialising warehouse at %s", DUCKDB_PATH)
    init_duckdb(DUCKDB_PATH)

    client = get_minio_client()
    ensure_buckets(client)

    return {"status": "ok", "db_path": DUCKDB_PATH}


def task_ingest_ticker(ticker: str, **context) -> dict:
    """
    Ingest all recent filings for a single ticker.
    Runs in parallel across tickers (max_active_tis_per_dag controls concurrency).
    """
    from ingestion.edgar_client import ingest_ticker, get_minio_client

    logical_date = context["logical_date"]
    lookback_days = 7 if logical_date != context["dag"].start_date else 365  # backfill on first run

    logger.info("Starting ingestion for %s (lookback %d days)", ticker, lookback_days)

    minio_client = get_minio_client()
    result = ingest_ticker(
        ticker=ticker,
        minio_client=minio_client,
        lookback_days=lookback_days,
        db_path=DUCKDB_PATH,
    )

    # Push result to XCom so validate task can aggregate
    context["ti"].xcom_push(key=f"result_{ticker}", value=result)

    if result.get("errors"):
        logger.warning("Ingestion errors for %s: %s", ticker, result["errors"])

    return result


def task_validate_ingestion(**context) -> dict:
    """
    Data quality checks after all tickers have been ingested.
    Checks:
      - At least 1 new filing ingested today (warns, does not fail)
      - No ticker had 100% error rate
      - DuckDB row counts are non-zero
    """
    import duckdb

    ti = context["ti"]
    run_date = context["ds"]  # YYYY-MM-DD string

    # Pull all ticker results from XCom
    all_results = []
    for ticker in TICKERS:
        result = ti.xcom_pull(task_ids=f"ingest_filings.ingest_{ticker}", key=f"result_{ticker}")
        if result:
            all_results.append(result)

    total_found = sum(r.get("filings_found", 0) for r in all_results)
    total_stored = sum(r.get("filings_stored", 0) for r in all_results)
    total_errors = sum(len(r.get("errors", [])) for r in all_results)

    logger.info(
        "Validation: %d filings found, %d stored, %d errors",
        total_found, total_stored, total_errors,
    )

    # DuckDB validation queries
    con = duckdb.connect(DUCKDB_PATH, read_only=True)

    total_rows = con.execute("SELECT COUNT(*) FROM raw_filings").fetchone()[0]
    today_rows = con.execute(
        "SELECT COUNT(*) FROM raw_filings WHERE ingested_at::DATE = ?",
        [run_date],
    ).fetchone()[0]

    # Check for any ticker with 0 filings found AND errors
    failed_tickers = [
        r["ticker"] for r in all_results
        if r.get("filings_found", 0) == 0 and r.get("errors")
    ]

    con.close()

    validation_result = {
        "run_date": run_date,
        "total_filings_in_db": total_rows,
        "filings_ingested_today": today_rows,
        "total_errors": total_errors,
        "failed_tickers": failed_tickers,
        "pass": len(failed_tickers) == 0,
    }

    if failed_tickers:
        logger.warning("Tickers with failures: %s", failed_tickers)

    logger.info("Validation result: %s", json.dumps(validation_result, indent=2))
    return validation_result


def task_notify_summary(**context) -> None:
    """
    Log a human-readable run summary.
    Extend this to send a Slack message or email in production.
    """
    ti = context["ti"]
    validation = ti.xcom_pull(task_ids="validate_ingestion")

    if not validation:
        logger.warning("No validation result found — skipping summary")
        return

    summary = f"""
╔══════════════════════════════════════════╗
║  Earnings Intel — Daily Ingestion Run    ║
╠══════════════════════════════════════════╣
  Date:              {validation.get('run_date')}
  Filings stored:    {validation.get('filings_ingested_today', 0)}
  Total in DB:       {validation.get('total_filings_in_db', 0)}
  Errors:            {validation.get('total_errors', 0)}
  Failed tickers:    {', '.join(validation.get('failed_tickers', [])) or 'None'}
  Status:            {'✓ PASS' if validation.get('pass') else '✗ FAIL'}
╚══════════════════════════════════════════╝
    """.strip()

    logger.info("\n%s", summary)

    # TODO Week 4+: add Slack webhook call here
    # requests.post(SLACK_WEBHOOK, json={"text": f"```{summary}```"})


# ── DAG definition ────────────────────────────────────────────────────────────

with DAG(
    dag_id="edgar_ingestion_daily",
    description="Daily ingestion of SEC EDGAR filings into DuckDB + MinIO",
    schedule="0 6 * * *",          # 06:00 UTC daily
    start_date=datetime(2024, 1, 1),
    catchup=False,                  # Don't backfill missed runs automatically
    max_active_runs=1,              # Only one run at a time
    tags=["ingestion", "edgar", "week1"],
    default_args=default_args,
    doc_md=__doc__,
) as dag:

    # Task 1: Init
    init = PythonOperator(
        task_id="init_warehouse",
        python_callable=task_init_warehouse,
    )

    # Task 2: Ingest each ticker in parallel (max 5 concurrent)
    with TaskGroup("ingest_filings") as ingest_group:
        ingest_tasks = []
        for ticker in TICKERS:
            t = PythonOperator(
                task_id=f"ingest_{ticker}",
                python_callable=task_ingest_ticker,
                op_kwargs={"ticker": ticker},
                pool="edgar_pool",   # Create in Airflow UI: Admin > Pools > edgar_pool (size=5)
            )
            ingest_tasks.append(t)

    # Task 3: Validate
    validate = PythonOperator(
        task_id="validate_ingestion",
        python_callable=task_validate_ingestion,
        trigger_rule="all_done",    # Run even if some tickers failed
    )

    # Task 4: Notify
    notify = PythonOperator(
        task_id="notify_summary",
        python_callable=task_notify_summary,
        trigger_rule="all_done",
    )

    # ── DAG dependency graph ──────────────────────────────────────────────────
    init >> ingest_group >> validate >> notify
