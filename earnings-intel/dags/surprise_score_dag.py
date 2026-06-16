"""
dags/surprise_score_dag.py
───────────────────────────
Airflow DAG: Weekly Earnings Surprise Score computation.
Runs every Sunday after markets close — recomputes scores
for all filings with fresh price data.
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
    "execution_timeout": timedelta(hours=2),
}


def task_run_surprise_scores(**context) -> dict:
    from ml.surprise_score import run_surprise_score_pipeline
    df = run_surprise_score_pipeline(db_path=DUCKDB_PATH)
    result = {
        "total_scored": len(df),
        "bullish": int((df["surprise_label"] == "bullish").sum()),
        "bearish": int((df["surprise_label"] == "bearish").sum()),
        "anomalies": int(df["is_anomaly"].sum()),
    }
    logger.info("Surprise score run complete: %s", result)
    context["ti"].xcom_push(key="result", value=result)
    return result


def task_notify(**context) -> None:
    result = context["ti"].xcom_pull(task_ids="run_surprise_scores", key="result")
    logger.info("""
╔══════════════════════════════════════════╗
║  EarningsEdge — Weekly Surprise Scores   ║
╠══════════════════════════════════════════╣
  Total scored:  %(total_scored)s
  Bullish:       %(bullish)s
  Bearish:       %(bearish)s
  Anomalies:     %(anomalies)s
╚══════════════════════════════════════════╝
    """, result)


with DAG(
    dag_id="surprise_score_weekly",
    description="Weekly Earnings Surprise Score computation",
    schedule="0 20 * * 0",      # Sunday 8pm UTC
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["ml", "scoring", "week5"],
    default_args=default_args,
) as dag:

    run_scores = PythonOperator(
        task_id="run_surprise_scores",
        python_callable=task_run_surprise_scores,
    )

    notify = PythonOperator(
        task_id="notify_results",
        python_callable=task_notify,
        trigger_rule="all_done",
    )

    run_scores >> notify