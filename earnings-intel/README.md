# Earnings Intelligence Engine

> Ingest every public earnings call + SEC filing → extract NLP signals → surface insights via live dashboard + RAG chatbot.

---

## Week 1 — Get the pipeline running

### Prerequisites

| Tool | Version | Install |
|---|---|---|
| Docker Desktop | 4.x+ | [docker.com](https://www.docker.com/products/docker-desktop) |
| Python | 3.11+ | [python.org](https://www.python.org) |
| dbt Core | 1.8+ | `pip install dbt-duckdb` |
| Git | any | [git-scm.com](https://git-scm.com) |

**System requirements:** 8 GB RAM minimum (16 GB recommended), 20 GB free disk.

---

### Step 1 — Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/earnings-intel.git
cd earnings-intel

# Set up your environment
cp .env.template .env
```

Open `.env` and update **one required field**:
```
EDGAR_USER_AGENT=EarningsIntel your@real-email.com
```
The SEC requires a real User-Agent or they will block you.

---

### Step 2 — Start all services

```bash
make up
```

Wait ~60 seconds for Airflow to initialise, then verify everything is running:

```bash
make ps
```

You should see 8–9 containers in `healthy` or `running` state.

**Service URLs:**

| Service | URL | Credentials |
|---|---|---|
| Airflow | http://localhost:8080 | admin / admin |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |
| Redpanda UI | http://localhost:8081 | — |
| MLflow | http://localhost:5000 | — |
| Grafana | http://localhost:3000 | admin / admin |

---

### Step 3 — Initialise the DuckDB warehouse

```bash
make init-db
```

This creates the `raw_filings`, `stock_prices`, and `ingestion_log` tables in DuckDB.

---

### Step 4 — Run a smoke test

```bash
make ingest-test
```

This pulls AAPL and MSFT filings from the last 6 months and stores them in MinIO + DuckDB. You should see output like:

```
2024-01-15 06:00:12 INFO ── Ingesting AAPL ──
2024-01-15 06:00:14 INFO Found 3 ['10-Q', '10-K', '8-K'] filings for AAPL
2024-01-15 06:00:18 INFO Stored AAPL 10-Q (2023-10-27) — 48,312 words in 3.2s
2024-01-15 06:00:21 INFO Stored AAPL 8-K (2023-11-02) — 2,841 words in 1.1s
```

Verify files landed in MinIO: open http://localhost:9001 → buckets → `earnings-raw-filings`.

---

### Step 5 — Create the Airflow pool

Airflow needs a `edgar_pool` to control EDGAR request concurrency:

1. Open http://localhost:8080
2. Go to **Admin → Pools**
3. Click **+** → Name: `edgar_pool`, Slots: `5`
4. Save

---

### Step 6 — Enable the DAG

1. Open http://localhost:8080
2. Find `edgar_ingestion_daily`
3. Toggle it **ON** (the blue switch)
4. Click the DAG name → **Trigger DAG** (▶) to run it immediately

Watch it run: each ticker gets its own task in the `ingest_filings` task group.

---

### Step 7 — Query your data

```bash
# Open DuckDB CLI in the container
docker compose exec airflow-scheduler python -c "
import duckdb
con = duckdb.connect('/opt/airflow/data/warehouse.db')
print(con.execute('''
    SELECT ticker, filing_type, filed_date, word_count
    FROM raw_filings
    ORDER BY filed_date DESC
    LIMIT 20
''').df().to_string())
"
```

---

## Project structure

```
earnings-intel/
├── dags/
│   └── edgar_ingestion_dag.py    ← Airflow DAG (daily schedule)
├── ingestion/
│   ├── edgar_client.py           ← SEC EDGAR API client + MinIO + DuckDB
│   └── price_fetcher.py          ← yfinance stock price downloader
├── dbt_project/
│   ├── models/
│   │   ├── staging/              ← Week 1: stg_raw_filings.sql
│   │   ├── intermediate/         ← Week 3+: NLP signal models
│   │   └── marts/                ← Week 3+: earnings_surprise_scores
│   └── dbt_project.yml
├── monitoring/
│   ├── grafana/                  ← Dashboard configs
│   └── prometheus/               ← Metrics scraping config
├── docker-compose.yml
├── Makefile                      ← All commands in one place
├── .env.template                 ← Copy to .env and fill in
└── README.md
```

---

## Cloud migration (Week 7+)

Every service maps 1:1 to a cloud equivalent. The only change needed is updating `.env`:

| Local | AWS | GCP |
|---|---|---|
| Redpanda | Kinesis | Pub/Sub |
| DuckDB | Redshift / Athena | BigQuery |
| MinIO | S3 | Cloud Storage |
| Airflow (Docker) | MWAA | Cloud Composer |
| MLflow | SageMaker | Vertex AI |
| Redis | ElastiCache | Memorystore |

---

## Roadmap

| Week | Focus |
|---|---|
| ✅ 1–2 | SEC EDGAR ingestion, DuckDB schema, MinIO storage, Airflow DAG |
| 3–4 | NLP signal extraction: FinBERT sentiment, VADER tone, dbt transforms |
| 5–6 | Market correlation: yfinance returns vs NLP signals, Earnings Surprise Score |
| 7–8 | RAG chatbot (ChromaDB + Ollama), React dashboard, CI/CD, deploy |
