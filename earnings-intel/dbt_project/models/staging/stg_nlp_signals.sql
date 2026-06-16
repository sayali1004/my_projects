-- models/staging/stg_nlp_signals.sql
-- ─────────────────────────────────────
-- Cleans and standardises raw nlp_signals from the NLP pipeline.

WITH source AS (
    SELECT * FROM {{ source('raw', 'nlp_signals') }}
)

SELECT
    filing_id,
    UPPER(ticker)                           AS ticker,
    UPPER(filing_type)                      AS filing_type,
    CAST(filed_date AS DATE)                AS filed_date,
    CAST(period_of_report AS DATE)          AS period_of_report,
    DATE_TRUNC('quarter', filed_date)       AS filing_quarter,

    COALESCE(finbert_positive, 0.0)         AS finbert_positive,
    COALESCE(finbert_negative, 0.0)         AS finbert_negative,
    COALESCE(finbert_neutral, 1.0)          AS finbert_neutral,
    COALESCE(finbert_sentiment, 'neutral')  AS finbert_sentiment,

    COALESCE(vader_compound, 0.0)           AS vader_compound,
    COALESCE(vader_positive, 0.0)           AS vader_positive,
    COALESCE(vader_negative, 0.0)           AS vader_negative,
    COALESCE(vader_neutral, 1.0)            AS vader_neutral,

    COALESCE(hedging_score, 0.0)            AS hedging_score,
    COALESCE(guidance_score, 0.0)           AS guidance_score,
    COALESCE(hedging_ratio, 0.5)            AS hedging_ratio,

    word_count,
    paragraph_count,
    CAST(processed_at AS TIMESTAMP)         AS processed_at,
    error

FROM source
WHERE filing_id IS NOT NULL
  AND ticker IS NOT NULL
