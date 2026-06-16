"""
nlp/finbert_runner.py
──────────────────────
Optimized FinBERT runner for EarningsEdge.

Optimizations:
  1. Extracts only MD&A section (~2000 words vs 40,000)
  2. Only processes 10-Q and 10-K filings (skips 8-K)
  3. Batches 8 paragraphs per forward pass
  4. Skips filings already scored (idempotent)
  5. Saves progress every 10 filings (safe to restart)

Runtime estimate:
  ~300 filings (10-Q + 10-K) x 10 paragraphs x 2s = ~1.5 hours on CPU
  Run overnight: python3 -m nlp.finbert_runner
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime

import boto3
import duckdb
from botocore.client import Config

logger = logging.getLogger(__name__)

DUCKDB_PATH = os.getenv("DUCKDB_PATH", "data/warehouse.db")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
RAW_BUCKET = "earnings-raw-filings"

# Only process these — 8-K is too short for meaningful FinBERT signal
TARGET_FILING_TYPES = ["10-Q", "10-K"]

# MD&A section markers — this is where management tone lives
MDNA_START_MARKERS = [
    "management's discussion and analysis",
    "management's discussion",
    "management discussion and analysis",
    "item 2.",
    "item 2:",
]

MDNA_END_MARKERS = [
    "item 3",
    "quantitative and qualitative disclosures",
    "financial statements and supplementary",
    "part ii",
]


# ── MD&A extraction ───────────────────────────────────────────────────────────

def extract_mdna(text: str, max_chars: int = 8000) -> str:
    """
    Extract the Management Discussion & Analysis section from a filing.

    Why MD&A?
    - Written by management (not lawyers/accountants)
    - Contains forward-looking statements and tone signals
    - Most signal-rich section for earnings surprise prediction
    - Typically 2,000–5,000 words vs 40,000 for full 10-K

    Falls back to first 8,000 chars if MD&A section not found.
    """
    text_lower = text.lower()

    # Find start of MD&A
    start_pos = -1
    for marker in MDNA_START_MARKERS:
        pos = text_lower.find(marker)
        if pos != -1:
            start_pos = pos
            break

    if start_pos == -1:
        logger.debug("MD&A section not found — using first %d chars", max_chars)
        return " ".join(text.split()[:3000])

    # Find end of MD&A
    end_pos = start_pos + max_chars  # default: cap at max_chars
    for marker in MDNA_END_MARKERS:
        pos = text_lower.find(marker, start_pos + 500)  # skip 500 chars to avoid false match
        if pos != -1 and pos < end_pos:
            end_pos = pos
            break

    extracted = text[start_pos:end_pos]
    logger.debug(
        "MD&A extracted: %d chars (from pos %d to %d)",
        len(extracted), start_pos, end_pos
    )
    return extracted


def chunk_mdna(text: str, min_words: int = 20, max_words: int = 150) -> list[str]:
    """Split MD&A text into paragraphs suitable for FinBERT."""
    import re
    paragraphs = []
    for para in text.split("\n"):
        para = para.strip()
        words = para.split()
        if min_words <= len(words) <= max_words:
            paragraphs.append(para)
        elif len(words) > max_words:
            # Long line — break into sentences (handles iXBRL single-block text)
            for sent in re.split(r'(?<=[.!?])\s+', para):
                sent_words = sent.split()
                if min_words <= len(sent_words) <= max_words:
                    paragraphs.append(sent)
    return paragraphs[:15]  # cap at 15 paragraphs per filing


# ── FinBERT model ─────────────────────────────────────────────────────────────

def load_finbert():
    """Load FinBERT from HuggingFace (cached after first download)."""
    from transformers import pipeline
    logger.info("Loading FinBERT — first run downloads ~500MB, cached after that...")
    classifier = pipeline(
        "text-classification",
        model="ProsusAI/finbert",
        top_k=None,
        truncation=True,
        max_length=512,
    )
    logger.info("FinBERT ready")
    return classifier


def score_paragraphs(classifier, paragraphs: list[str]) -> tuple[float, float, float, str]:
    """
    Run FinBERT on paragraphs in batches of 8.
    Returns (avg_positive, avg_negative, avg_neutral, dominant_label)
    """
    if not paragraphs:
        return 0.0, 0.0, 1.0, "neutral"

    pos_list, neg_list, neu_list = [], [], []
    batch_size = 8

    for i in range(0, len(paragraphs), batch_size):
        batch = paragraphs[i:i + batch_size]
        try:
            results = classifier(batch)
            for result in results:
                scores = {r["label"].lower(): r["score"] for r in result}
                pos_list.append(scores.get("positive", 0.0))
                neg_list.append(scores.get("negative", 0.0))
                neu_list.append(scores.get("neutral", 0.0))
        except Exception as e:
            logger.warning("FinBERT batch error: %s", e)

    if not pos_list:
        return 0.0, 0.0, 1.0, "neutral"

    avg_pos = round(sum(pos_list) / len(pos_list), 4)
    avg_neg = round(sum(neg_list) / len(neg_list), 4)
    avg_neu = round(sum(neu_list) / len(neu_list), 4)
    dominant = max({"positive": avg_pos, "negative": avg_neg, "neutral": avg_neu},
                   key=lambda k: {"positive": avg_pos, "negative": avg_neg, "neutral": avg_neu}[k])

    return avg_pos, avg_neg, avg_neu, dominant


# ── Main runner ───────────────────────────────────────────────────────────────

def run_finbert_pipeline(
    tickers: list[str] | None = None,
    db_path: str = DUCKDB_PATH,
    save_every: int = 10,
    filing_types_override: list[str] | None = None,
) -> None:
    """
    Run optimized FinBERT on MD&A sections of 10-Q and 10-K filings.

    Args:
        tickers:               Specific tickers to process. None = all tickers.
        db_path:               DuckDB path.
        save_every:            Commit to DuckDB every N filings (safe restart on failure).
        filing_types_override: Override default TARGET_FILING_TYPES if provided.
    """
    filing_types = filing_types_override or TARGET_FILING_TYPES
    # MinIO client
    minio = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )

    con = duckdb.connect(db_path)

    # Find filings that need FinBERT (already have VADER, missing FinBERT scores)
    ticker_filter = f"AND r.ticker IN ({','.join(repr(t) for t in tickers)})" if tickers else ""
    type_filter = f"AND r.filing_type IN ({','.join(repr(t) for t in filing_types)})"

    filings = con.execute(f"""
        SELECT
            n.filing_id, r.ticker, r.filing_type, r.filed_date, r.minio_key,
            r.cik, r.accession_number, r.primary_document,
            n.vader_compound, n.vader_positive, n.vader_negative, n.vader_neutral,
            n.hedging_score, n.guidance_score, n.hedging_ratio, n.word_count
        FROM nlp_signals n
        JOIN raw_filings r ON n.filing_id = r.id
        WHERE n.finbert_sentiment = 'neutral'
          AND n.finbert_positive = 0
          AND n.finbert_negative = 0
          {ticker_filter}
          {type_filter}
        ORDER BY r.filed_date DESC
    """).df()

    total = len(filings)
    logger.info("Found %d filings needing FinBERT scoring", total)

    if total == 0:
        logger.info("All filings already scored with FinBERT")
        con.close()
        return

    # Load FinBERT
    classifier = load_finbert()

    processed = 0
    errors = 0
    t_start = time.time()

    for i, row in filings.iterrows():
        try:
            t0 = time.time()

            # Fetch filing text from MinIO
            key = row["minio_key"].replace(f"s3://{RAW_BUCKET}/", "")
            text = minio.get_object(
                Bucket=RAW_BUCKET, Key=key
            )["Body"].read().decode("utf-8")

            # If stored text is XBRL data (not prose), re-fetch from EDGAR with clean parsing
            if text and (text[:200].count('\n') > 10 or 'xbrli:' in text[:500] or 'fasb.org' in text[:500]):
                from ingestion.edgar_client import fetch_filing_text
                logger.debug("XBRL text detected for %s — re-fetching from EDGAR", row["ticker"])
                text = fetch_filing_text(row["cik"], row["accession_number"], row["primary_document"])

            # Extract MD&A section only
            mdna_text = extract_mdna(text)
            paragraphs = chunk_mdna(mdna_text)

            if not paragraphs:
                logger.warning("No paragraphs extracted for %s %s", row["ticker"], row["filing_type"])
                continue

            # Run FinBERT
            avg_pos, avg_neg, avg_neu, dominant = score_paragraphs(classifier, paragraphs)

            # Update existing nlp_signals row with FinBERT scores
            con.execute("""
                UPDATE nlp_signals SET
                    finbert_positive  = ?,
                    finbert_negative  = ?,
                    finbert_neutral   = ?,
                    finbert_sentiment = ?,
                    paragraph_count   = ?,
                    processed_at      = ?
                WHERE filing_id = ?
            """, [
                avg_pos, avg_neg, avg_neu, dominant,
                len(paragraphs),
                datetime.utcnow().isoformat(),
                row["filing_id"],
            ])

            processed += 1
            elapsed = round(time.time() - t0, 1)
            total_elapsed = round(time.time() - t_start)
            remaining = round((total_elapsed / processed) * (total - processed)) if processed > 0 else 0

            logger.info(
                "[%d/%d] %s %s (%s) → %s (pos=%.3f neg=%.3f) | %ss | ~%dm remaining",
                processed, total,
                row["ticker"], row["filing_type"], str(row["filed_date"])[:10],
                dominant, avg_pos, avg_neg, elapsed,
                remaining // 60,
            )

        except Exception as e:
            errors += 1
            logger.error("Error on %s: %s", row["ticker"], e)

    con.close()

    logger.info(
        "FinBERT complete — %d scored, %d errors, %.1f min total",
        processed, errors,
        (time.time() - t_start) / 60,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("logs/finbert_run.log"),  # saves progress to log file
        ]
    )
    logger.info("Starting optimized FinBERT pipeline...")
    run_finbert_pipeline()