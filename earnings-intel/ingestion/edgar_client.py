"""
ingestion/edgar_client.py
─────────────────────────
Pulls filings from SEC EDGAR Full-Text Search API and EDGAR XBRL API.
100% free — no API key needed. SEC requires a User-Agent header.

EDGAR rate limit: max 10 requests/second.
We stay at ~3 req/sec to be polite and avoid 429s.

Cloud swap: replace MinIO calls with boto3 pointing at S3.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Generator

import boto3
import duckdb
import pandas as pd
import requests
from botocore.client import Config
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── Config (all overridable via env vars) ────────────────────────────────────

EDGAR_BASE = "https://data.sec.gov"
EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"
EDGAR_FULL_TEXT = "https://efts.sec.gov/LATEST/search-index?q=%22earnings%22"

USER_AGENT = os.getenv(
    "EDGAR_USER_AGENT",
    "EarningsIntel research@youremail.com",  # CHANGE THIS — SEC requires it
)
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
DUCKDB_PATH = os.getenv("DUCKDB_PATH", "/opt/airflow/data/warehouse.db")

RAW_BUCKET = "earnings-raw-filings"
TRANSCRIPT_BUCKET = "earnings-transcripts"
PROCESSED_BUCKET = "earnings-processed"

# S&P 500 sample — extend to full list in production
SP500_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "BRK-B", "JPM", "JNJ", "V", "PG", "MA", "HD", "CVX",
    "MRK", "ABBV", "PFE", "BAC", "KO", "PEP", "AVGO", "COST",
    "TMO", "WMT", "MCD", "CSCO", "ACN", "DHR", "ABT",
]

FILING_TYPES = ["10-Q", "10-K", "8-K"]


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class Filing:
    cik: str
    ticker: str
    company_name: str
    filing_type: str
    filed_date: str
    period_of_report: str
    accession_number: str
    primary_document: str
    raw_text: str = ""
    minio_key: str = ""
    word_count: int = 0
    fetch_duration_sec: float = 0.0
    metadata: dict = field(default_factory=dict)


# ── MinIO client ─────────────────────────────────────────────────────────────

def get_minio_client() -> boto3.client:
    """
    Returns a boto3 S3 client pointed at MinIO.
    Cloud swap: remove endpoint_url + config params, point at real AWS.
    """
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def ensure_buckets(client: boto3.client) -> None:
    existing = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
    for bucket in [RAW_BUCKET, TRANSCRIPT_BUCKET, PROCESSED_BUCKET]:
        if bucket not in existing:
            client.create_bucket(Bucket=bucket)
            logger.info("Created bucket: %s", bucket)


def upload_to_minio(client: boto3.client, bucket: str, key: str, content: str) -> str:
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="text/plain",
    )
    return f"s3://{bucket}/{key}"


# ── EDGAR helpers ─────────────────────────────────────────────────────────────

def _edgar_get(url: str, params: dict | None = None, retries: int = 3) -> requests.Response:
    """
    Polite EDGAR request with retry + rate limiting.
    SEC enforces 10 req/sec; we stay at ~3 req/sec.
    """
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** attempt * 5
                logger.warning("Rate limited by EDGAR. Waiting %ds…", wait)
                time.sleep(wait)
                continue
            if resp.status_code == 404:
                raise requests.HTTPError(f"404 Not Found: {url}", response=resp)
            resp.raise_for_status()
            time.sleep(0.35)  # ~3 req/sec
            return resp
        except requests.RequestException as e:
            if attempt == retries - 1 or (hasattr(e.response, 'status_code') and e.response.status_code == 404):
                raise
            logger.warning("EDGAR request failed (attempt %d): %s", attempt + 1, e)
            time.sleep(2 ** attempt)


def get_cik_for_ticker(ticker: str) -> str | None:
    """
    Resolve a ticker symbol to a zero-padded 10-digit CIK.
    Uses EDGAR company search endpoint (free, no auth).
    """
    url = f"{EDGAR_BASE}/submissions/"
    # EDGAR's company search by ticker
    search_url = "https://www.sec.gov/cgi-bin/browse-edgar"
    params = {
        "company": "",
        "CIK": ticker,
        "type": "",
        "dateb": "",
        "owner": "include",
        "count": "1",
        "search_text": "",
        "action": "getcompany",
        "output": "atom",
    }
    try:
        resp = _edgar_get(search_url, params=params)
        soup = BeautifulSoup(resp.text, "xml")
        cik_tag = soup.find("cik")
        if cik_tag:
            return cik_tag.text.strip().zfill(10)
    except Exception as e:
        logger.error("CIK lookup failed for %s: %s", ticker, e)
    return None


def get_company_submissions(cik: str) -> dict:
    """
    Fetch all submission metadata for a company from EDGAR.
    Returns the full JSON including recent filings.
    """
    url = f"{EDGAR_BASE}/submissions/CIK{cik}.json"
    resp = _edgar_get(url)
    return resp.json()


def get_recent_filings(
    cik: str,
    ticker: str,
    filing_types: list[str] = FILING_TYPES,
    lookback_days: int = 90,
) -> list[Filing]:
    """
    Returns recent filings for a company, filtered by type and date window.
    """
    submissions = get_company_submissions(cik)
    company_name = submissions.get("name", ticker)
    recent = submissions.get("filings", {}).get("recent", {})

    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    periods = recent.get("reportDate", [])
    accessions = recent.get("accessionNumber", [])
    documents = recent.get("primaryDocument", [])

    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    filings = []

    for form, filed, period, acc, doc in zip(forms, dates, periods, accessions, documents):
        if form not in filing_types:
            continue
        if filed < cutoff:
            continue
        filings.append(Filing(
            cik=cik,
            ticker=ticker,
            company_name=company_name,
            filing_type=form,
            filed_date=filed,
            period_of_report=period,
            accession_number=acc,
            primary_document=doc,
            metadata={"source": "edgar", "ingested_at": datetime.utcnow().isoformat()},
        ))

    logger.info("Found %d %s filings for %s (CIK %s)", len(filings), filing_types, ticker, cik)
    return filings


def fetch_filing_text(cik: str, accession_number: str, primary_document: str) -> str:
    """
    Downloads the raw text of a filing document from EDGAR.
    Strips HTML tags to get clean plain text.
    """
    acc_clean = accession_number.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{primary_document}"

    try:
        resp = _edgar_get(url)
        # Strip HTML/XML if it's an HTML filing
        if primary_document.endswith((".htm", ".html")):
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup(["script", "style", "header", "footer", "nav"]):
                tag.decompose()
            # Extract from leaf divs (no nested divs) + iXBRL narrative tags
            # This avoids duplicate text from nested div structures
            prose_blocks = []
            seen = set()
            candidates = (
                soup.find_all("div", recursive=True) +
                soup.find_all("ix:nonnumeric") +
                soup.find_all("p")
            )
            for tag in candidates:
                if tag.name == "div" and tag.find("div"):
                    continue  # skip parent divs, only leaf divs
                tag_text = tag.get_text(separator=" ", strip=True)
                if tag_text in seen:
                    continue
                seen.add(tag_text)
                words = tag_text.split()
                if 15 <= len(words) <= 300:
                    prose_blocks.append(tag_text)
            text = "\n".join(prose_blocks) if prose_blocks else soup.get_text(separator="\n", strip=True)
        else:
            text = resp.text

        # Basic cleanup
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)

    except Exception as e:
        logger.error("Failed to fetch filing %s/%s: %s", accession_number, primary_document, e)
        return ""


# ── DuckDB schema bootstrap ──────────────────────────────────────────────────

def init_duckdb(db_path: str = DUCKDB_PATH) -> None:
    """
    Creates the raw_filings table in DuckDB if it doesn't exist.
    This is your warehouse landing zone — the staging layer.
    Cloud swap: point duckdb.connect() at MotherDuck or replace with BigQuery client.
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS raw_filings (
            id                  VARCHAR PRIMARY KEY,
            cik                 VARCHAR NOT NULL,
            ticker              VARCHAR NOT NULL,
            company_name        VARCHAR,
            filing_type         VARCHAR NOT NULL,
            filed_date          DATE NOT NULL,
            period_of_report    DATE,
            accession_number    VARCHAR NOT NULL,
            primary_document    VARCHAR,
            minio_key           VARCHAR,
            word_count          INTEGER,
            fetch_duration_sec  DOUBLE,
            ingested_at         TIMESTAMP DEFAULT current_timestamp,
            metadata            JSON
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_log (
            run_id       VARCHAR,
            ticker       VARCHAR,
            status       VARCHAR,
            filings_found   INTEGER,
            filings_stored  INTEGER,
            error_msg    VARCHAR,
            started_at   TIMESTAMP,
            finished_at  TIMESTAMP
        )
    """)
    con.close()
    logger.info("DuckDB schema initialised at %s", db_path)


def upsert_filing(filing: Filing, db_path: str = DUCKDB_PATH) -> None:
    """Insert or replace a filing record in DuckDB."""
    filing_id = f"{filing.cik}_{filing.accession_number}"
    con = duckdb.connect(db_path)
    con.execute("""
        INSERT OR REPLACE INTO raw_filings
        (id, cik, ticker, company_name, filing_type, filed_date,
         period_of_report, accession_number, primary_document,
         minio_key, word_count, fetch_duration_sec, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        filing_id,
        filing.cik,
        filing.ticker,
        filing.company_name,
        filing.filing_type,
        filing.filed_date,
        filing.period_of_report or None,
        filing.accession_number,
        filing.primary_document,
        filing.minio_key,
        filing.word_count,
        filing.fetch_duration_sec,
        json.dumps(filing.metadata),
    ])
    con.close()


# ── Main ingestion function ───────────────────────────────────────────────────

def ingest_ticker(
    ticker: str,
    minio_client: boto3.client,
    lookback_days: int = 90,
    db_path: str = DUCKDB_PATH,
) -> dict:
    """
    Full ingestion pipeline for one ticker:
      1. Resolve ticker → CIK
      2. Fetch recent filings metadata
      3. Download raw text for each filing
      4. Store text in MinIO (raw bucket)
      5. Store metadata in DuckDB

    Returns a summary dict for logging.
    """
    started = datetime.utcnow()
    result = {"ticker": ticker, "filings_found": 0, "filings_stored": 0, "errors": []}

    # Step 1: CIK lookup
    cik = get_cik_for_ticker(ticker)
    if not cik:
        result["errors"].append(f"CIK not found for {ticker}")
        logger.warning("Skipping %s — CIK not found", ticker)
        return result

    # Step 2: Fetch recent filings list
    filings = get_recent_filings(cik, ticker, lookback_days=lookback_days)
    result["filings_found"] = len(filings)

    if not filings:
        logger.info("No recent filings for %s", ticker)
        return result

    # Step 3 + 4 + 5: Download, store, index
    for filing in filings:
        try:
            t0 = time.time()
            text = fetch_filing_text(filing.cik, filing.accession_number, filing.primary_document)
            filing.fetch_duration_sec = round(time.time() - t0, 2)

            if not text:
                logger.warning("Empty text for %s/%s — skipping", ticker, filing.accession_number)
                continue

            filing.word_count = len(text.split())

            # MinIO key: ticker/type/date/accession.txt
            minio_key = (
                f"{ticker}/{filing.filing_type}/"
                f"{filing.filed_date}/{filing.accession_number}.txt"
            )
            filing.minio_key = upload_to_minio(minio_client, RAW_BUCKET, minio_key, text)

            upsert_filing(filing, db_path=db_path)
            result["filings_stored"] += 1
            logger.info(
                "Stored %s %s (%s) — %d words in %.1fs",
                ticker, filing.filing_type, filing.filed_date,
                filing.word_count, filing.fetch_duration_sec,
            )

            # Publish event to Kafka/Redpanda
            try:
                from streaming.producer import publish_filing_ingested
                publish_filing_ingested(
                    filing_id=filing.id,
                    ticker=ticker,
                    filing_type=filing.filing_type,
                    filed_date=filing.filed_date,
                    minio_key=filing.minio_key,
                    word_count=filing.word_count,
                )
            except Exception:
                pass  # streaming is optional — don't fail ingestion

        except Exception as e:
            err_msg = f"{filing.accession_number}: {e}"
            result["errors"].append(err_msg)
            logger.error("Failed filing %s: %s", ticker, err_msg)

    return result


def ingest_batch(
    tickers: list[str] = SP500_TICKERS,
    lookback_days: int = 90,
    db_path: str = DUCKDB_PATH,
) -> pd.DataFrame:
    """
    Ingest all tickers in batch.
    Returns a DataFrame summary of the run — useful for Airflow XComs.
    """
    init_duckdb(db_path)
    minio_client = get_minio_client()
    ensure_buckets(minio_client)

    results = []
    for ticker in tickers:
        logger.info("── Ingesting %s ──", ticker)
        result = ingest_ticker(ticker, minio_client, lookback_days=lookback_days, db_path=db_path)
        results.append(result)

    summary = pd.DataFrame(results)
    logger.info(
        "Ingestion complete: %d tickers, %d filings stored, %d errors",
        len(summary),
        summary["filings_stored"].sum(),
        summary["errors"].apply(len).sum(),
    )
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Quick smoke test: ingest just AAPL and MSFT
    summary = ingest_batch(tickers=["AAPL", "MSFT"], lookback_days=180)
    print(summary.to_string())
