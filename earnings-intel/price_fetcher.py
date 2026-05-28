"""
ingestion/price_fetcher.py
──────────────────────────
Pulls daily stock price data from Yahoo Finance (free, no API key).
Stores OHLCV data in DuckDB for later correlation against NLP signals.

Cloud swap: replace yfinance with AWS Data Exchange or Google Cloud
           Financial Data for production-grade reliability.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta

import duckdb
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

DUCKDB_PATH = os.getenv("DUCKDB_PATH", "/opt/airflow/data/warehouse.db")


def init_price_table(db_path: str = DUCKDB_PATH) -> None:
    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS stock_prices (
            ticker          VARCHAR NOT NULL,
            price_date      DATE NOT NULL,
            open            DOUBLE,
            high            DOUBLE,
            low             DOUBLE,
            close           DOUBLE,
            adj_close       DOUBLE,
            volume          BIGINT,
            pct_change_1d   DOUBLE,   -- next-day return (filled later)
            pct_change_5d   DOUBLE,   -- 5-day return (filled later)
            fetched_at      TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (ticker, price_date)
        )
    """)
    con.close()


def fetch_prices(
    tickers: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    db_path: str = DUCKDB_PATH,
) -> pd.DataFrame:
    """
    Download OHLCV data from Yahoo Finance and store in DuckDB.

    Args:
        tickers:    List of ticker symbols
        start_date: ISO date string (defaults to 365 days ago)
        end_date:   ISO date string (defaults to today)
        db_path:    Path to DuckDB file

    Returns:
        DataFrame of all fetched prices
    """
    if not start_date:
        start_date = (date.today() - timedelta(days=365)).isoformat()
    if not end_date:
        end_date = date.today().isoformat()

    logger.info("Fetching prices for %d tickers: %s → %s", len(tickers), start_date, end_date)

    # yfinance batch download — much faster than one-by-one
    raw = yf.download(
        tickers=tickers,
        start=start_date,
        end=end_date,
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    if raw.empty:
        logger.warning("No price data returned from yfinance")
        return pd.DataFrame()

    # Reshape: yfinance returns MultiIndex columns when >1 ticker
    records = []
    for ticker in tickers:
        try:
            if len(tickers) == 1:
                df = raw.copy()
            else:
                df = raw.xs(ticker, axis=1, level=1)

            df = df.reset_index()
            df.columns = [c.lower().replace(" ", "_") for c in df.columns]
            df["ticker"] = ticker
            df["price_date"] = pd.to_datetime(df["date"]).dt.date
            df = df.drop(columns=["date"], errors="ignore")

            # Calculate forward returns (next-day and 5-day)
            df = df.sort_values("price_date")
            df["pct_change_1d"] = df["close"].pct_change(1).shift(-1).round(6)
            df["pct_change_5d"] = df["close"].pct_change(5).shift(-5).round(6)

            records.append(df)
        except Exception as e:
            logger.error("Price fetch failed for %s: %s", ticker, e)

    if not records:
        return pd.DataFrame()

    all_prices = pd.concat(records, ignore_index=True)

    # Store in DuckDB
    con = duckdb.connect(db_path)
    con.execute("""
        INSERT OR REPLACE INTO stock_prices
            (ticker, price_date, open, high, low, close, adj_close,
             volume, pct_change_1d, pct_change_5d)
        SELECT
            ticker, price_date,
            open, high, low, close,
            close AS adj_close,   -- yfinance auto_adjust=True means close IS adj_close
            CAST(volume AS BIGINT),
            pct_change_1d, pct_change_5d
        FROM all_prices
    """)
    con.close()

    logger.info("Stored %d price rows for %d tickers", len(all_prices), len(tickers))
    return all_prices


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from ingestion.edgar_client import init_duckdb, SP500_TICKERS
    init_duckdb()
    init_price_table()
    df = fetch_prices(SP500_TICKERS[:5])
    print(df.tail(10).to_string())
