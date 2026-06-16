"""
ml/surprise_score.py
─────────────────────
Week 5: Earnings Surprise Score engine.

Joins NLP signals against stock price movements to answer:
"Did the tone of this earnings filing predict the stock reaction?"

Earnings Surprise Score formula (0–100):
  score = (sentiment_delta * 0.35)
        + (hedging_ratio_inverse * 0.30)
        + (guidance_score_norm * 0.20)
        + (vader_delta * 0.15)

Higher score = more positive surprise signal.
Score > 60 = bullish signal
Score < 40 = bearish signal
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import duckdb
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler

logger = logging.getLogger(__name__)

DUCKDB_PATH = os.getenv("DUCKDB_PATH", "data/warehouse.db")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")


# ── DuckDB schema ─────────────────────────────────────────────────────────────

def init_surprise_tables(db_path: str = DUCKDB_PATH) -> None:
    """Create earnings surprise score tables."""
    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS earnings_surprise_scores (
            filing_id               VARCHAR PRIMARY KEY,
            ticker                  VARCHAR NOT NULL,
            filing_type             VARCHAR,
            filed_date              DATE,
            period_of_report        DATE,

            -- NLP signals
            finbert_positive        DOUBLE,
            finbert_negative        DOUBLE,
            finbert_sentiment       VARCHAR,
            vader_compound          DOUBLE,
            hedging_ratio           DOUBLE,
            guidance_score          DOUBLE,

            -- Quarter-over-quarter deltas
            sentiment_delta         DOUBLE,
            vader_delta             DOUBLE,
            hedging_delta           DOUBLE,

            -- Stock price reactions
            price_1d_before         DOUBLE,
            price_1d_after          DOUBLE,
            pct_change_1d           DOUBLE,
            pct_change_5d           DOUBLE,
            beat_market_1d          BOOLEAN,

            -- Earnings Surprise Score
            surprise_score          DOUBLE,
            surprise_label          VARCHAR,   -- bullish / neutral / bearish
            is_anomaly              BOOLEAN,

            computed_at             TIMESTAMP DEFAULT current_timestamp
        )
    """)
    con.close()
    logger.info("Surprise score tables initialised")


# ── Data joining ──────────────────────────────────────────────────────────────

def build_feature_table(db_path: str = DUCKDB_PATH) -> pd.DataFrame:
    """
    Join nlp_signals with stock_prices to build the feature table.
    Matches each filing to the stock price movement in the 5 days after filing.

    This is the key analytical join — connecting language signals to market outcomes.
    """
    con = duckdb.connect(db_path, read_only=True)

    df = con.execute("""
        WITH nlp AS (
            SELECT
                n.filing_id,
                n.ticker,
                n.filing_type,
                n.filed_date,
                n.period_of_report,
                n.finbert_positive,
                n.finbert_negative,
                n.finbert_neutral,
                n.finbert_sentiment,
                n.vader_compound,
                n.hedging_ratio,
                n.guidance_score,
                n.hedging_score,
                n.word_count,

                -- Quarter-over-quarter deltas using window functions
                n.finbert_positive - LAG(n.finbert_positive) OVER (
                    PARTITION BY n.ticker, n.filing_type
                    ORDER BY n.filed_date
                ) AS sentiment_delta,

                n.vader_compound - LAG(n.vader_compound) OVER (
                    PARTITION BY n.ticker, n.filing_type
                    ORDER BY n.filed_date
                ) AS vader_delta,

                n.hedging_ratio - LAG(n.hedging_ratio) OVER (
                    PARTITION BY n.ticker, n.filing_type
                    ORDER BY n.filed_date
                ) AS hedging_delta

            FROM nlp_signals n
            WHERE n.word_count > 100
        ),

        prices AS (
            SELECT
                ticker,
                price_date,
                close,
                pct_change_1d,
                pct_change_5d
            FROM stock_prices
            WHERE close IS NOT NULL
        )

        SELECT
            nlp.*,
            p_after.close        AS price_after,
            p_after.pct_change_1d AS stock_pct_1d,
            p_after.pct_change_5d AS stock_pct_5d,

            -- Did this stock beat the market? (simple binary label)
            CASE
                WHEN p_after.pct_change_1d > 0.005 THEN TRUE
                ELSE FALSE
            END AS beat_market_1d

        FROM nlp
        -- Join to stock price on filing date or next trading day
        LEFT JOIN prices p_after
            ON nlp.ticker = p_after.ticker
            AND p_after.price_date = (
                SELECT MIN(price_date)
                FROM stock_prices sp
                WHERE sp.ticker = nlp.ticker
                AND sp.price_date >= nlp.filed_date
                AND sp.price_date <= CAST(nlp.filed_date AS DATE) + INTERVAL '5 days'
            )
        WHERE p_after.close IS NOT NULL

        ORDER BY nlp.filed_date DESC
    """).df()

    con.close()
    logger.info("Built feature table: %d rows", len(df))
    return df


# ── Earnings Surprise Score ───────────────────────────────────────────────────

def compute_surprise_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the proprietary Earnings Surprise Score for each filing.

    Formula:
      score = (sentiment_delta_norm * 0.35)
            + (hedging_inverse_norm * 0.30)
            + (guidance_norm * 0.20)
            + (vader_delta_norm * 0.15)

    All components normalized to 0–1 before weighting.
    Final score scaled to 0–100.

    Why these weights?
    - sentiment_delta (35%): biggest weight — shift in tone is strongest signal
    - hedging_inverse (30%): less hedging = more confident = positive signal
    - guidance_score (20%): positive forward language matters but less than tone shift
    - vader_delta (15%): supporting signal, lower weight due to neutrality in SEC filings
    """
    df = df.copy()

    # Fill nulls for first filing of each ticker (no prior quarter to delta against)
    df["sentiment_delta"] = df["sentiment_delta"].fillna(0)
    df["vader_delta"] = df["vader_delta"].fillna(0)
    df["hedging_delta"] = df["hedging_delta"].fillna(0)

    scaler = MinMaxScaler()

    features = pd.DataFrame({
        "sentiment_delta":   df["sentiment_delta"].fillna(0),
        "hedging_inverse":   1 - df["hedging_ratio"].fillna(0.5),  # inverse: low hedging = good
        "guidance_score":    df["guidance_score"].fillna(0),
        "vader_delta":       df["vader_delta"].fillna(0),
    })

    # Normalize each feature to 0–1
    features_norm = pd.DataFrame(
        scaler.fit_transform(features),
        columns=features.columns,
        index=features.index,
    )

    # Weighted sum → scale to 0–100
    df["surprise_score"] = (
        features_norm["sentiment_delta"]  * 0.35 +
        features_norm["hedging_inverse"]  * 0.30 +
        features_norm["guidance_score"]   * 0.20 +
        features_norm["vader_delta"]      * 0.15
    ) * 100

    df["surprise_score"] = df["surprise_score"].round(2)

    # Label
    df["surprise_label"] = pd.cut(
        df["surprise_score"],
        bins=[0, 40, 60, 100],
        labels=["bearish", "neutral", "bullish"],
    ).astype(str)

    logger.info(
        "Score distribution:\n%s",
        df["surprise_label"].value_counts().to_string()
    )
    return df


# ── Backtesting ───────────────────────────────────────────────────────────────

def backtest(df: pd.DataFrame) -> dict:
    """
    Validate: does a high Earnings Surprise Score predict positive stock returns?

    Method:
    - Binary classification: score > 60 = bullish prediction
    - Label: did stock go up > 0.5% next day?
    - Metrics: precision, recall, AUC-ROC
    - Train/test split: 80/20 chronological (not random — avoids data leakage)
    """
    df_valid = df.dropna(subset=["surprise_score", "beat_market_1d"])

    if len(df_valid) < 20:
        logger.warning("Too few samples for backtesting (%d)", len(df_valid))
        return {}

    # Chronological split — never shuffle financial time series data
    df_valid = df_valid.sort_values("filed_date")
    split_idx = int(len(df_valid) * 0.8)
    train = df_valid.iloc[:split_idx]
    test = df_valid.iloc[split_idx:]

    # Simple threshold classifier: score > 60 = bullish
    y_pred = (test["surprise_score"] > 60).astype(int)
    y_true = test["beat_market_1d"].astype(int)

    # Precision among bullish calls
    bullish_calls = test[test["surprise_score"] > 60]
    precision = (bullish_calls["beat_market_1d"].sum() / len(bullish_calls)
                 if len(bullish_calls) > 0 else 0)

    # AUC-ROC
    try:
        auc = roc_auc_score(y_true, test["surprise_score"] / 100)
    except Exception:
        auc = 0.5

    metrics = {
        "total_filings":        len(df_valid),
        "test_filings":         len(test),
        "bullish_calls":        len(bullish_calls),
        "precision_bullish":    round(precision, 4),
        "auc_roc":              round(auc, 4),
        "baseline_win_rate":    round(df_valid["beat_market_1d"].mean(), 4),
        "avg_score_winners":    round(df_valid[df_valid["beat_market_1d"]]["surprise_score"].mean(), 2),
        "avg_score_losers":     round(df_valid[~df_valid["beat_market_1d"]]["surprise_score"].mean(), 2),
    }

    logger.info("Backtest results:\n%s", "\n".join(f"  {k}: {v}" for k, v in metrics.items()))
    return metrics


# ── Anomaly detection ─────────────────────────────────────────────────────────

def detect_anomalies(df: pd.DataFrame, db_path: str = DUCKDB_PATH) -> pd.DataFrame:
    """
    Use Isolation Forest to flag unusual earnings events.
    An anomaly = filing where the combination of signals is statistically unusual.

    Examples of anomalies this catches:
    - Sudden huge positive sentiment shift (unexpected good news)
    - Extreme hedging spike (management panic)
    - Massive score drop from prior quarter
    """
    feature_cols = [
        "surprise_score", "sentiment_delta", "hedging_ratio",
        "guidance_score", "vader_compound",
    ]

    df_clean = df.dropna(subset=feature_cols).copy()

    if len(df_clean) < 10:
        logger.warning("Too few samples for anomaly detection")
        df["is_anomaly"] = False
        return df

    X = df_clean[feature_cols].values

    # contamination=0.05 means we expect ~5% of filings to be anomalous
    iso = IsolationForest(contamination=0.05, random_state=42, n_estimators=100)
    df_clean["is_anomaly"] = iso.fit_predict(X) == -1

    anomalies = df_clean[df_clean["is_anomaly"]]
    logger.info("Found %d anomalous filings (%.1f%%)",
                len(anomalies), len(anomalies) / len(df_clean) * 100)

    if not anomalies.empty:
        logger.info("Top anomalies:\n%s",
            anomalies[["ticker", "filed_date", "surprise_score", "sentiment_delta"]]
            .head(10).to_string())

    # Merge back
    df = df.merge(
        df_clean[["filing_id", "is_anomaly"]],
        on="filing_id", how="left"
    )
    df["is_anomaly"] = df["is_anomaly"].fillna(False)

    return df, iso


# ── MLflow tracking ───────────────────────────────────────────────────────────

def track_with_mlflow(metrics: dict, model, df: pd.DataFrame) -> None:
    """Log experiment to MLflow for reproducibility."""
    try:
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment("earnings-surprise-score")

        with mlflow.start_run(run_name=f"surprise_score_{datetime.utcnow().strftime('%Y%m%d_%H%M')}"):
            mlflow.log_params({
                "weights": "sentiment_delta=0.35, hedging_inv=0.30, guidance=0.20, vader_delta=0.15",
                "anomaly_contamination": 0.05,
                "score_threshold_bullish": 60,
                "score_threshold_bearish": 40,
                "total_filings": len(df),
            })
            mlflow.log_metrics(metrics)
            mlflow.sklearn.log_model(model, "isolation_forest")

        logger.info("MLflow run logged successfully")
    except Exception as e:
        logger.warning("MLflow logging failed (is MLflow running?): %s", e)


# ── Store results ─────────────────────────────────────────────────────────────

def store_scores(df: pd.DataFrame, db_path: str = DUCKDB_PATH) -> None:
    """Store computed scores in DuckDB."""
    con = duckdb.connect(db_path)
    con.execute("DELETE FROM earnings_surprise_scores")  # fresh load each run
    con.execute("""
        INSERT INTO earnings_surprise_scores (
            filing_id, ticker, filing_type, filed_date, period_of_report,
            finbert_positive, finbert_negative, finbert_sentiment,
            vader_compound, hedging_ratio, guidance_score,
            sentiment_delta, vader_delta, hedging_delta,
            pct_change_1d, pct_change_5d,
            beat_market_1d, surprise_score, surprise_label, is_anomaly
        )
        SELECT
            filing_id, ticker, filing_type,
            CAST(filed_date AS DATE),
            CAST(period_of_report AS DATE),
            finbert_positive, finbert_negative, finbert_sentiment,
            vader_compound, hedging_ratio, guidance_score,
            sentiment_delta, vader_delta, hedging_delta,
            stock_pct_1d, stock_pct_5d,
            beat_market_1d, surprise_score, surprise_label, is_anomaly
        FROM df
        WHERE surprise_score IS NOT NULL
    """)
    total = con.execute("SELECT COUNT(*) FROM earnings_surprise_scores").fetchone()[0]
    con.close()
    logger.info("Stored %d surprise scores in DuckDB", total)


# ── Main ──────────────────────────────────────────────────────────────────────

def run_surprise_score_pipeline(db_path: str = DUCKDB_PATH) -> pd.DataFrame:
    """
    Full Week 5 pipeline:
    1. Build feature table (join NLP signals + stock prices)
    2. Compute Earnings Surprise Score
    3. Backtest against actual stock moves
    4. Detect anomalies with Isolation Forest
    5. Log to MLflow
    6. Store in DuckDB
    """
    init_surprise_tables(db_path)

    # Step 1: Build features
    logger.info("Building feature table...")
    df = build_feature_table(db_path)

    if df.empty:
        logger.error("No data returned from feature table — check NLP signals and stock prices")
        return pd.DataFrame()

    # Step 2: Compute scores
    logger.info("Computing Earnings Surprise Scores...")
    df = compute_surprise_score(df)

    # Step 3: Backtest
    logger.info("Backtesting...")
    metrics = backtest(df)

    # Step 4: Anomaly detection
    logger.info("Running anomaly detection...")
    df, iso_model = detect_anomalies(df, db_path)

    # Step 5: MLflow
    track_with_mlflow(metrics, iso_model, df)

    # Step 6: Store
    store_scores(df, db_path)

    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    df = run_surprise_score_pipeline()

    print("\n=== TOP 10 BULLISH SIGNALS ===")
    print(df[df["surprise_label"] == "bullish"]
          .sort_values("surprise_score", ascending=False)
          [["ticker", "filed_date", "surprise_score", "sentiment_delta",
            "hedging_ratio", "stock_pct_1d"]]
          .head(10).to_string())

    print("\n=== TOP 10 BEARISH SIGNALS ===")
    print(df[df["surprise_label"] == "bearish"]
          .sort_values("surprise_score")
          [["ticker", "filed_date", "surprise_score", "sentiment_delta",
            "hedging_ratio", "stock_pct_1d"]]
          .head(10).to_string())

    print("\n=== ANOMALOUS FILINGS ===")
    print(df[df["is_anomaly"]]
          [["ticker", "filed_date", "surprise_score", "sentiment_delta"]]
          .to_string())