"""
streaming/producer.py
──────────────────────
Kafka producer for the earnings pipeline.
Publishes events to Redpanda when filings are ingested or scored.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from kafka import KafkaProducer

logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")

TOPIC_FILINGS_INGESTED = "filings-ingested"
TOPIC_FILINGS_SCORED = "filings-scored"

_producer = None


def get_producer() -> KafkaProducer:
    global _producer
    if _producer is None:
        _producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        logger.info("Kafka producer connected to %s", KAFKA_BOOTSTRAP)
    return _producer


def publish_filing_ingested(
    filing_id: str,
    ticker: str,
    filing_type: str,
    filed_date: str,
    minio_key: str,
    word_count: int,
) -> None:
    producer = get_producer()
    event = {
        "event": "filing_ingested",
        "filing_id": filing_id,
        "ticker": ticker,
        "filing_type": filing_type,
        "filed_date": filed_date,
        "minio_key": minio_key,
        "word_count": word_count,
        "timestamp": datetime.utcnow().isoformat(),
    }
    producer.send(TOPIC_FILINGS_INGESTED, key=ticker, value=event)
    producer.flush()
    logger.debug("Published filing_ingested: %s %s", ticker, filing_id)


def publish_filing_scored(
    filing_id: str,
    ticker: str,
    filing_type: str,
    surprise_score: float,
    surprise_label: str,
    sentiment: str,
) -> None:
    producer = get_producer()
    event = {
        "event": "filing_scored",
        "filing_id": filing_id,
        "ticker": ticker,
        "filing_type": filing_type,
        "surprise_score": surprise_score,
        "surprise_label": surprise_label,
        "sentiment": sentiment,
        "timestamp": datetime.utcnow().isoformat(),
    }
    producer.send(TOPIC_FILINGS_SCORED, key=ticker, value=event)
    producer.flush()
    logger.debug("Published filing_scored: %s score=%.1f", ticker, surprise_score)
