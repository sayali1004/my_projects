"""
streaming/consumer.py
──────────────────────
Kafka consumer for the earnings pipeline.
Listens for filing_ingested events and triggers NLP + surprise scoring.

Architecture:
  EDGAR ingestion → [filings-ingested] → NLP pipeline → [filings-scored] → dashboard

Run:
  python -m streaming.consumer
"""

from __future__ import annotations

import json
import logging
import os
import time

from kafka import KafkaConsumer, KafkaAdminClient
from kafka.admin import NewTopic

logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
DUCKDB_PATH = os.getenv("DUCKDB_PATH", "data/warehouse.db")

TOPIC_FILINGS_INGESTED = "filings-ingested"
TOPIC_FILINGS_SCORED = "filings-scored"


def ensure_topics():
    try:
        admin = KafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP)
        existing = admin.list_topics()
        topics_to_create = []
        for topic in [TOPIC_FILINGS_INGESTED, TOPIC_FILINGS_SCORED]:
            if topic not in existing:
                topics_to_create.append(NewTopic(name=topic, num_partitions=3, replication_factor=1))
        if topics_to_create:
            admin.create_topics(topics_to_create)
            logger.info("Created topics: %s", [t.name for t in topics_to_create])
        else:
            logger.info("Topics already exist")
        admin.close()
    except Exception as e:
        logger.error("Failed to create topics: %s", e)


def process_filing_event(event: dict) -> None:
    filing_id = event["filing_id"]
    ticker = event["ticker"]
    filing_type = event["filing_type"]

    logger.info("Processing event: %s %s (%s)", ticker, filing_type, filing_id)

    try:
        from nlp.nlp_pipeline import run_nlp_pipeline
        logger.info("[NLP] Running sentiment analysis for %s", ticker)
        run_nlp_pipeline(tickers=[ticker], filing_types=[filing_type], use_finbert=False)
    except Exception as e:
        logger.error("[NLP] Failed for %s: %s", ticker, e)

    try:
        from ml.surprise_score import compute_surprise_scores
        logger.info("[ML] Computing surprise score for %s", ticker)
        compute_surprise_scores(tickers=[ticker])
    except Exception as e:
        logger.error("[ML] Failed for %s: %s", ticker, e)

    try:
        from streaming.producer import publish_filing_scored
        import duckdb
        con = duckdb.connect(DUCKDB_PATH, read_only=True)
        row = con.execute(
            "SELECT surprise_score, surprise_label, finbert_sentiment FROM earnings_surprise_scores WHERE filing_id = ?",
            [filing_id]
        ).fetchone()
        con.close()
        if row:
            publish_filing_scored(
                filing_id=filing_id,
                ticker=ticker,
                filing_type=filing_type,
                surprise_score=row[0],
                surprise_label=row[1],
                sentiment=row[2],
            )
            logger.info("[STREAM] Published scored event: %s score=%.1f", ticker, row[0])
    except Exception as e:
        logger.error("[STREAM] Failed to publish scored event: %s", e)


def run_consumer():
    ensure_topics()

    logger.info("Starting consumer — listening on %s", TOPIC_FILINGS_INGESTED)
    consumer = KafkaConsumer(
        TOPIC_FILINGS_INGESTED,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="earnings-nlp-pipeline",
        auto_offset_reset="earliest",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        consumer_timeout_ms=-1,
    )

    for message in consumer:
        event = message.value
        logger.info(
            "Received: %s %s (partition=%d offset=%d)",
            event.get("ticker"), event.get("event"),
            message.partition, message.offset,
        )
        t0 = time.time()
        process_filing_event(event)
        logger.info("Processed in %.1fs", time.time() - t0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_consumer()
