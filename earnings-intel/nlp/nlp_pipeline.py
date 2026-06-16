"""
nlp/nlp_pipeline.py
────────────────────
Week 3: NLP signal extraction pipeline.

For each filing in DuckDB:
  1. Fetch raw text from MinIO
  2. Chunk into paragraphs
  3. Run FinBERT sentiment per paragraph → average score
  4. Run VADER tone scoring → compound score
  5. Detect hedging language → hedging score per 1000 words
  6. Store signals in DuckDB nlp_signals table

FinBERT is a BERT model fine-tuned on financial text (10-Ks, earnings calls).
It understands "headwinds", "challenging environment", "robust growth" better
than generic sentiment models.

Cloud swap: replace local HuggingFace model with AWS Comprehend or
            Google Natural Language API for production scale.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import boto3
import duckdb
import pandas as pd
from botocore.client import Config
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
DUCKDB_PATH = os.getenv("DUCKDB_PATH", "data/warehouse.db")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
RAW_BUCKET = "earnings-raw-filings"

# Hedging words commonly used when management is uncertain or cautious
HEDGING_WORDS = [
    "may", "might", "could", "would", "should", "possibly", "potentially",
    "uncertain", "uncertainty", "risk", "risks", "challenge", "challenges",
    "headwind", "headwinds", "difficult", "difficulty", "volatile", "volatility",
    "concern", "concerns", "cautious", "caution", "subject to", "dependent on",
    "no assurance", "cannot predict", "forward-looking", "contingent",
    "adverse", "unfavorable", "weakness", "weaknesses", "pressure", "pressures"
]

# Positive guidance words — management confidence signals
GUIDANCE_POSITIVE_WORDS = [
    "growth", "increase", "expand", "strong", "robust", "record", "exceed",
    "outperform", "momentum", "opportunity", "confident", "optimistic",
    "accelerate", "improve", "gain", "beat", "raised guidance", "above expectations"
]


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class NLPSignal:
    filing_id: str
    ticker: str
    filing_type: str
    filed_date: str
    period_of_report: str

    # FinBERT scores (averaged across paragraphs)
    finbert_positive: float = 0.0
    finbert_negative: float = 0.0
    finbert_neutral: float = 0.0
    finbert_sentiment: str = "neutral"  # dominant sentiment label

    # VADER scores
    vader_compound: float = 0.0
    vader_positive: float = 0.0
    vader_negative: float = 0.0
    vader_neutral: float = 0.0

    # Hedging + guidance signals
    hedging_score: float = 0.0        # hedging words per 1000 words
    guidance_score: float = 0.0       # positive guidance words per 1000 words
    hedging_ratio: float = 0.0        # hedging / (hedging + guidance) — key signal

    # Document stats
    word_count: int = 0
    paragraph_count: int = 0
    processed_at: str = ""
    error: str = ""


# ── MinIO client ──────────────────────────────────────────────────────────────

def get_minio_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def fetch_text_from_minio(minio_client, minio_key: str) -> str:
    """Fetch raw filing text from MinIO."""
    # minio_key format: s3://bucket/path → strip the s3://bucket/ prefix
    key = minio_key.replace(f"s3://{RAW_BUCKET}/", "")
    try:
        response = minio_client.get_object(Bucket=RAW_BUCKET, Key=key)
        return response["Body"].read().decode("utf-8")
    except Exception as e:
        logger.error("Failed to fetch %s from MinIO: %s", minio_key, e)
        return ""


# ── Text processing ───────────────────────────────────────────────────────────

def chunk_into_paragraphs(text: str, min_words: int = 20, max_words: int = 200) -> list[str]:
    """
    Split filing text into meaningful paragraphs for NLP processing.
    Filters out very short lines (page numbers, headers) and very long ones.
    """
    paragraphs = []
    for para in text.split("\n"):
        para = para.strip()
        words = para.split()
        if min_words <= len(words) <= max_words:
            paragraphs.append(para)
    return paragraphs


def compute_hedging_score(text: str) -> tuple[float, float, float]:
    """
    Count hedging and positive guidance words per 1000 words.
    Returns (hedging_score, guidance_score, hedging_ratio)
    """
    text_lower = text.lower()
    words = text_lower.split()
    total_words = max(len(words), 1)

    hedging_count = sum(
        text_lower.count(word) for word in HEDGING_WORDS
    )
    guidance_count = sum(
        text_lower.count(word) for word in GUIDANCE_POSITIVE_WORDS
    )

    hedging_score = round((hedging_count / total_words) * 1000, 4)
    guidance_score = round((guidance_count / total_words) * 1000, 4)

    total = hedging_count + guidance_count
    hedging_ratio = round(hedging_count / total, 4) if total > 0 else 0.5

    return hedging_score, guidance_score, hedging_ratio


# ── FinBERT ───────────────────────────────────────────────────────────────────

def load_finbert():
    """
    Load FinBERT model from HuggingFace.
    Downloads on first run (~500MB), cached locally after that.
    Cloud swap: replace with boto3 call to AWS Comprehend DetectSentiment.
    """
    try:
        from transformers import pipeline
        logger.info("Loading FinBERT model (first run downloads ~500MB)...")
        classifier = pipeline(
            "text-classification",
            model="ProsusAI/finbert",
            top_k=None,           # return all 3 labels
            truncation=True,
            max_length=512,
        )
        logger.info("FinBERT loaded successfully")
        return classifier
    except ImportError:
        logger.warning("transformers not installed — using VADER only")
        return None
    except Exception as e:
        logger.error("FinBERT load failed: %s", e)
        return None


def run_finbert(classifier, paragraphs: list[str]) -> tuple[float, float, float, str]:
    """
    Run FinBERT on a list of paragraphs, return averaged scores.
    Returns (positive, negative, neutral, dominant_label)
    """
    if not classifier or not paragraphs:
        return 0.0, 0.0, 1.0, "neutral"

    pos_scores, neg_scores, neu_scores = [], [], []

    # Process in batches of 8 to avoid OOM
    batch_size = 8
    for i in range(0, min(len(paragraphs), 40), batch_size):  # cap at 40 paragraphs
        batch = paragraphs[i:i + batch_size]
        try:
            results = classifier(batch)
            for result in results:
                scores = {r["label"].lower(): r["score"] for r in result}
                pos_scores.append(scores.get("positive", 0.0))
                neg_scores.append(scores.get("negative", 0.0))
                neu_scores.append(scores.get("neutral", 0.0))
        except Exception as e:
            logger.warning("FinBERT batch failed: %s", e)

    if not pos_scores:
        return 0.0, 0.0, 1.0, "neutral"

    avg_pos = round(sum(pos_scores) / len(pos_scores), 4)
    avg_neg = round(sum(neg_scores) / len(neg_scores), 4)
    avg_neu = round(sum(neu_scores) / len(neu_scores), 4)

    # Dominant label
    scores_map = {"positive": avg_pos, "negative": avg_neg, "neutral": avg_neu}
    dominant = max(scores_map, key=scores_map.get)

    return avg_pos, avg_neg, avg_neu, dominant


# ── VADER ─────────────────────────────────────────────────────────────────────

def run_vader(analyzer, text: str) -> tuple[float, float, float, float]:
    """
    Run VADER on full filing text.
    Returns (compound, positive, negative, neutral)
    """
    # VADER works on shorter text — use first 5000 words
    truncated = " ".join(text.split()[:5000])
    scores = analyzer.polarity_scores(truncated)
    return (
        round(scores["compound"], 4),
        round(scores["pos"], 4),
        round(scores["neg"], 4),
        round(scores["neu"], 4),
    )


# ── DuckDB schema ─────────────────────────────────────────────────────────────

def init_nlp_tables(db_path: str = DUCKDB_PATH) -> None:
    """Create NLP signal tables in DuckDB."""
    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS nlp_signals (
            filing_id           VARCHAR PRIMARY KEY,
            ticker              VARCHAR NOT NULL,
            filing_type         VARCHAR,
            filed_date          DATE,
            period_of_report    DATE,

            -- FinBERT scores
            finbert_positive    DOUBLE,
            finbert_negative    DOUBLE,
            finbert_neutral     DOUBLE,
            finbert_sentiment   VARCHAR,

            -- VADER scores
            vader_compound      DOUBLE,
            vader_positive      DOUBLE,
            vader_negative      DOUBLE,
            vader_neutral       DOUBLE,

            -- Hedging signals
            hedging_score       DOUBLE,
            guidance_score      DOUBLE,
            hedging_ratio       DOUBLE,

            -- Document stats
            word_count          INTEGER,
            paragraph_count     INTEGER,
            processed_at        TIMESTAMP,
            error               VARCHAR
        )
    """)

    # Quarter-over-quarter delta view — computed automatically
    con.execute("""
        CREATE VIEW IF NOT EXISTS nlp_signals_with_delta AS
        SELECT
            s.*,
            s.vader_compound - LAG(s.vader_compound) OVER (
                PARTITION BY s.ticker, s.filing_type
                ORDER BY s.filed_date
            ) AS vader_delta,
            s.hedging_ratio - LAG(s.hedging_ratio) OVER (
                PARTITION BY s.ticker, s.filing_type
                ORDER BY s.filed_date
            ) AS hedging_delta,
            s.finbert_positive - LAG(s.finbert_positive) OVER (
                PARTITION BY s.ticker, s.filing_type
                ORDER BY s.filed_date
            ) AS finbert_delta
        FROM nlp_signals s
    """)
    con.close()
    logger.info("NLP tables initialised")


def upsert_signal(signal: NLPSignal, db_path: str = DUCKDB_PATH) -> None:
    """Insert or replace an NLP signal record."""
    con = duckdb.connect(db_path)
    con.execute("""
        INSERT OR REPLACE INTO nlp_signals VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?
        )
    """, [
        signal.filing_id, signal.ticker, signal.filing_type,
        signal.filed_date, signal.period_of_report,
        signal.finbert_positive, signal.finbert_negative,
        signal.finbert_neutral, signal.finbert_sentiment,
        signal.vader_compound, signal.vader_positive,
        signal.vader_negative, signal.vader_neutral,
        signal.hedging_score, signal.guidance_score, signal.hedging_ratio,
        signal.word_count, signal.paragraph_count,
        signal.processed_at or datetime.utcnow().isoformat(),
        signal.error,
    ])
    con.close()


# ── Main processing function ──────────────────────────────────────────────────

def process_filing(
    filing_row: dict,
    minio_client,
    finbert_classifier,
    vader_analyzer,
    db_path: str = DUCKDB_PATH,
) -> NLPSignal:
    """
    Full NLP pipeline for one filing.
    1. Fetch text from MinIO
    2. Chunk into paragraphs
    3. Run FinBERT + VADER + hedging detector
    4. Store in DuckDB
    """
    signal = NLPSignal(
        filing_id=filing_row["id"],
        ticker=filing_row["ticker"],
        filing_type=filing_row["filing_type"],
        filed_date=str(filing_row["filed_date"]),
        period_of_report=str(filing_row.get("period_of_report", "")),
        processed_at=datetime.utcnow().isoformat(),
    )

    try:
        # Step 1: Fetch text
        text = fetch_text_from_minio(minio_client, filing_row["minio_key"])
        if not text:
            signal.error = "empty_text"
            return signal

        # Step 2: Chunk
        paragraphs = chunk_into_paragraphs(text)
        signal.word_count = len(text.split())
        signal.paragraph_count = len(paragraphs)

        # Step 3a: FinBERT
        signal.finbert_positive, signal.finbert_negative, \
            signal.finbert_neutral, signal.finbert_sentiment = \
            run_finbert(finbert_classifier, paragraphs)

        # Step 3b: VADER
        signal.vader_compound, signal.vader_positive, \
            signal.vader_negative, signal.vader_neutral = \
            run_vader(vader_analyzer, text)

        # Step 3c: Hedging
        signal.hedging_score, signal.guidance_score, signal.hedging_ratio = \
            compute_hedging_score(text)

    except Exception as e:
        signal.error = str(e)
        logger.error("Failed to process %s: %s", signal.filing_id, e)

    return signal


def run_nlp_pipeline(
    tickers: Optional[list[str]] = None,
    filing_types: list[str] = ["10-Q", "10-K", "8-K"],
    use_finbert: bool = True,
    db_path: str = DUCKDB_PATH,
) -> pd.DataFrame:
    """
    Run NLP pipeline on all unprocessed filings.
    Skips filings already in nlp_signals table (idempotent).
    """
    init_nlp_tables(db_path)

    con = duckdb.connect(db_path)

    # Find filings not yet processed
    ticker_filter = f"AND r.ticker IN ({','.join(repr(t) for t in tickers)})" if tickers else ""
    type_filter = f"AND r.filing_type IN ({','.join(repr(t) for t in filing_types)})"

    filings = con.execute(f"""
        SELECT r.*
        FROM raw_filings r
        LEFT JOIN nlp_signals n ON r.id = n.filing_id
        WHERE n.filing_id IS NULL
          AND r.minio_key IS NOT NULL
          AND r.word_count > 100
          {ticker_filter}
          {type_filter}
        ORDER BY r.filed_date DESC
    """).df()
    con.close()

    logger.info("Found %d unprocessed filings", len(filings))

    if filings.empty:
        logger.info("All filings already processed")
        return pd.DataFrame()

    # Load models
    minio_client = get_minio_client()
    vader_analyzer = SentimentIntensityAnalyzer()
    finbert_classifier = load_finbert() if use_finbert else None

    results = []
    for i, row in filings.iterrows():
        logger.info(
            "[%d/%d] Processing %s %s (%s)",
            i + 1, len(filings),
            row["ticker"], row["filing_type"], row["filed_date"]
        )
        t0 = time.time()
        signal = process_filing(
            row.to_dict(), minio_client,
            finbert_classifier, vader_analyzer,
            db_path=db_path
        )
        upsert_signal(signal, db_path=db_path)
        elapsed = round(time.time() - t0, 1)
        logger.info(
            "  → sentiment=%s vader=%.3f hedging=%.3f (%ss)",
            signal.finbert_sentiment, signal.vader_compound,
            signal.hedging_ratio, elapsed
        )
        results.append({
            "ticker": signal.ticker,
            "filing_type": signal.filing_type,
            "filed_date": signal.filed_date,
            "sentiment": signal.finbert_sentiment,
            "vader_compound": signal.vader_compound,
            "hedging_ratio": signal.hedging_ratio,
            "error": signal.error,
        })

    summary = pd.DataFrame(results)
    logger.info(
        "NLP complete: %d processed, %d errors",
        len(summary), summary["error"].astype(bool).sum()
    )
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Smoke test on 3 tickers without FinBERT first (faster)
    summary = run_nlp_pipeline(
        tickers=["AAPL", "MSFT", "GOOGL"],
        use_finbert=False,  # set True after confirming VADER works
    )
    print(summary.to_string())
