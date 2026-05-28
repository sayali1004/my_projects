# Makefile — Earnings Intelligence Engine
# Run `make help` to see all commands.

.PHONY: help up down logs ps init-db ingest-test dbt-run dbt-test clean

help:
	@echo ""
	@echo "  Earnings Intelligence Engine — Commands"
	@echo "  ──────────────────────────────────────────"
	@echo "  make up           Start all services (Airflow, MinIO, Redpanda, etc.)"
	@echo "  make down         Stop all services (keeps volumes)"
	@echo "  make destroy      Stop all services AND delete all data volumes"
	@echo "  make logs         Tail logs from all services"
	@echo "  make ps           Show running container status"
	@echo ""
	@echo "  make init-db      Bootstrap DuckDB schema (run once after 'make up')"
	@echo "  make ingest-test  Run AAPL + MSFT ingestion as a smoke test"
	@echo "  make prices-test  Pull price data for top 5 tickers"
	@echo ""
	@echo "  make dbt-run      Run all dbt models"
	@echo "  make dbt-test     Run dbt data quality tests"
	@echo "  make dbt-docs     Generate and serve dbt docs at localhost:8082"
	@echo ""
	@echo "  make clean        Remove Python caches and temp files"
	@echo ""

up:
	@echo "Starting all services…"
	docker compose up -d --build
	@echo ""
	@echo "  Services starting up:"
	@echo "  Airflow UI      → http://localhost:8080  (admin/admin)"
	@echo "  MinIO Console   → http://localhost:9001  (minioadmin/minioadmin)"
	@echo "  Redpanda UI     → http://localhost:8081"
	@echo "  MLflow UI       → http://localhost:5000"
	@echo "  Grafana         → http://localhost:3000  (admin/admin)"
	@echo "  Prometheus      → http://localhost:9090"
	@echo ""
	@echo "  Wait ~60 seconds for Airflow to initialise, then visit http://localhost:8080"

down:
	docker compose down

destroy:
	docker compose down -v
	@echo "All data volumes deleted."

logs:
	docker compose logs -f --tail=50

ps:
	docker compose ps

init-db:
	docker compose exec airflow-scheduler python -c \
		"from ingestion.edgar_client import init_duckdb; \
		 from ingestion.price_fetcher import init_price_table; \
		 init_duckdb(); init_price_table(); print('DB initialised.')"

ingest-test:
	@echo "Running smoke test ingestion for AAPL + MSFT…"
	docker compose exec airflow-scheduler python -m ingestion.edgar_client

prices-test:
	@echo "Fetching price data for top 5 tickers…"
	docker compose exec airflow-scheduler python -m ingestion.price_fetcher

dbt-run:
	cd dbt_project && dbt run

dbt-test:
	cd dbt_project && dbt test

dbt-docs:
	cd dbt_project && dbt docs generate && dbt docs serve --port 8082

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "target" -path "*/dbt_project/*" -exec rm -rf {} + 2>/dev/null || true
