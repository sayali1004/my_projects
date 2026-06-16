"""
dags/nlp_signals_dag.py
────────────────────────
Airflow DAG: Daily NLP signal extraction.
Runs after edgar_ingestion_daily completes.
Processes any filings not yet in nlp_signals table.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sensors.external_task import ExternalTaskSensor

sys.path.insert(0, "/opt/airflow")
logger = logging.getLogger(__name__)
DUCKDB_PATH = os.getenv("DUCKDB_PATH", "/opt/airflow/data/warehouse.db")

default_args = {
    "owner": "earnings-intel",
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
    "execution_timeout": timedelta(hours=4),
}


def task_run_nlp(**context) -> dict:
    from nlp.nlp_pipeline import run_nlp_pipeline
    summary = run_nlp_pipeline(
        use_finbert=True,
        db_path=DUCKDB_PATH,
    )
    processed = len(summary) if not summary.empty else 0
    errors = int(summary["error"].astype(bool).sum()) if not summary.empty else 0
    context["ti"].xcom_push(key="processed", value=processed)
    context["ti"].xcom_push(key="errors", value=errors)
    return {"processed": processed, "errors": errors}


def task_validate_nlp(**context) -> None:
    import duckdb
    con = duckdb.connect(DUCKDB_PATH, read_only=True)
    total = con.execute("SELECT COUNT(*) FROM nlp_signals").fetchone()[0]
    avg_sentiment = con.execute("""
        SELECT finbert_sentiment, COUNT(*) as cnt
        FROM nlp_signals
        GROUP BY finbert_sentiment
        ORDER BY cnt DESC
    """).df()
    con.close()
    logger.info("Total NLP signals in DB: %d", total)
    logger.info("Sentiment distribution:\n%s", avg_sentiment.to_string())


with DAG(
    dag_id="nlp_signals_daily",
    description="Daily NLP signal extraction on new filings",
    schedule="0 8 * * *",       # 2 hours after ingestion DAG
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["nlp", "signals", "week3"],
    default_args=default_args,
) as dag:

    wait_for_ingestion = ExternalTaskSensor(
        task_id="wait_for_ingestion",
        external_dag_id="edgar_ingestion_daily",
        external_task_id="notify_summary",
        timeout=3600,
        mode="reschedule",
    )

    run_nlp = PythonOperator(
        task_id="run_nlp_pipeline",
        python_callable=task_run_nlp,
    )

    validate = PythonOperator(
        task_id="validate_nlp_signals",
        python_callable=task_validate_nlp,
        trigger_rule="all_done",
    )

    wait_for_ingestion >> run_nlp >> validate
