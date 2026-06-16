-- models/intermediate/int_company_signals.sql
-- ─────────────────────────────────────────────
-- Aggregates NLP signals per company per quarter.
-- This is the table that feeds the Earnings Surprise Score in Week 5.

WITH signals AS (
    SELECT * FROM {{ ref('stg_nlp_signals') }}
),

-- Quarter-over-quarter deltas
with_deltas AS (
    SELECT
        *,
        vader_compound - LAG(vader_compound) OVER (
            PARTITION BY ticker, filing_type
            ORDER BY filed_date
        ) AS vader_delta,

        hedging_ratio - LAG(hedging_ratio) OVER (
            PARTITION BY ticker, filing_type
            ORDER BY filed_date
        ) AS hedging_delta,

        finbert_positive - LAG(finbert_positive) OVER (
            PARTITION BY ticker, filing_type
            ORDER BY filed_date
        ) AS finbert_delta

    FROM signals
)

SELECT
    ticker,
    filing_type,
    filed_date,
    period_of_report,
    filing_quarter,

    -- Raw scores
    finbert_positive,
    finbert_negative,
    finbert_neutral,
    finbert_sentiment,
    vader_compound,
    hedging_score,
    guidance_score,
    hedging_ratio,

    -- Quarter-over-quarter deltas (key signals for surprise detection)
    COALESCE(vader_delta, 0)    AS vader_delta,
    COALESCE(hedging_delta, 0)  AS hedging_delta,
    COALESCE(finbert_delta, 0)  AS finbert_delta,

    -- Composite caution flag: high hedging + negative sentiment shift
    CASE
        WHEN hedging_ratio > 0.6 AND vader_delta < -0.1 THEN 'high_caution'
        WHEN hedging_ratio > 0.5 OR vader_delta < -0.05 THEN 'moderate_caution'
        WHEN guidance_score > hedging_score AND vader_delta > 0.05 THEN 'bullish'
        ELSE 'neutral'
    END AS tone_flag,

    word_count,
    paragraph_count,
    processed_at

FROM with_deltas
WHERE error IS NULL OR error = ''
