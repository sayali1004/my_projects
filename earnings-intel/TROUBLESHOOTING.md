# Engineering Challenges & Solutions

Real issues encountered during development and how they were resolved.

## 1. Port Conflicts — Native Services Blocking Docker

**Problem:** `make up` failed with `bind: address already in use` on ports 5432, 6379, and 5000. A native PostgreSQL 17 instance, Redis, and macOS AirPlay (port 5000) were already listening.

**Diagnosis:** `netstat -an | grep <port>` and `ps aux | grep postgres` identified the culprits.

**Fix:** Remapped host ports in `docker-compose.yml` — only the left side (host) changes, container ports stay the same:
```yaml
- "5433:5432"   # Postgres
- "6380:6379"   # Redis
- "5001:5000"   # MLflow
```
Internal Docker networking (`postgres:5432`) is unaffected since services communicate over the Docker bridge network.

---

## 2. Docker Mount Failure — File vs Directory

**Problem:** Prometheus failed to start: `mount src=.../prometheus.yml: not a directory`. Docker auto-created a directory at the mount path because the source file didn't exist.

**Fix:** Two-step — (1) `rm -rf` the directory Docker created, (2) create the actual `prometheus.yml` config file before running `docker compose up`.

**Takeaway:** When Docker mounts a host path that doesn't exist, it creates a directory — not a file. Always ensure config files exist before starting containers.

---

## 3. Airflow Init Exit 127 — YAML Folding vs Bash Parsing

**Problem:** `airflow-init` container exited with code 127 (`command not found`). The multi-line `airflow users create` command in `docker-compose.yml` was broken by YAML's `>` (folded scalar) — each `--flag` became a separate bash command.

**Fix:** Collapsed the entire `airflow users create` command onto a single line inside the `bash -c` string. YAML's `>` folds newlines into spaces, but bash inside `docker compose` doesn't always handle the resulting whitespace correctly with multi-line arguments.

---

## 4. EDGAR 404s — Wrong Base Domain

**Problem:** All filing fetches returned 404. URLs were constructed as `https://data.sec.gov/Archives/edgar/data/...` but filing documents live at `https://www.sec.gov/Archives/...`.

**Diagnosis:** `data.sec.gov` serves the EDGAR API (submissions JSON, company facts). The actual filing HTML documents are hosted on `www.sec.gov`.

**Fix:** Changed `fetch_filing_text()` to use `www.sec.gov` for document URLs while keeping `data.sec.gov` for API calls.

---

## 5. Wasted Retries on 404s

**Problem:** Every 404 was retried 3 times with exponential backoff (1s, 2s, 4s). With hundreds of filings, this added minutes of pointless waiting.

**Fix:** Added early exit in `_edgar_get()` — 404 responses raise immediately without retry. Only transient errors (429, 500, timeouts) are retried.

---

## 6. iXBRL Text Extraction — XBRL Data Instead of Prose

**Problem:** FinBERT scored 0/342 filings. The stored text was raw XBRL data values (`aapl-20260328\nfalse\n2026\nQ2\n0000320193...`) instead of readable prose.

**Root cause chain:**
1. Modern SEC filings use inline XBRL (iXBRL) — a hybrid XML/HTML format
2. Using BeautifulSoup's XML parser extracted XBRL tag values (numbers, dates, URIs)
3. Using the HTML parser with `get_text(separator="\n")` fragmented text into single-word lines (each inline XBRL tag became its own line)
4. Even after fixing extraction, the MD&A section was a single 18,000-char line with no newline breaks

**Fix (3 layers):**
- **Parser:** Always use `lxml` (HTML parser). Extract text from leaf-level `<div>` elements (no nested divs) + `<ix:nonnumeric>` tags, with deduplication
- **Chunker:** Added sentence splitting (`re.split(r'(?<=[.!?])\s+')`) as fallback when paragraphs exceed 150 words — handles iXBRL documents where the entire section is one text block
- **Re-fetch:** FinBERT runner detects XBRL-formatted text in MinIO and re-fetches directly from EDGAR with the corrected parser

---

## 7. HuggingFace Model Downloads Hanging

**Problem:** `SentenceTransformerEmbeddingFunction('all-MiniLM-L6-v2')` hung indefinitely — no progress, no error.

**Cause:** Unauthenticated HuggingFace Hub requests are rate-limited and can stall silently during model downloads (~90MB).

**Fix:** Pre-downloaded the model separately using `huggingface_hub.snapshot_download()` which shows progress and handles retries. Once cached locally (`~/.cache/huggingface/`), subsequent loads are instant.

---

## 8. FastAPI Startup Blocking on Model Load

**Problem:** `uvicorn rag.rag_server:app` hung on `Waiting for application startup` — the `@app.on_event("startup")` handler loaded the embedding model synchronously, blocking the async event loop.

**Fix:** Replaced startup event with lazy initialization — `_init_chroma()` loads the model on the first request instead of at server start. Guarded by a `if chroma_collection is not None: return` check so initialization only happens once.

---

## 9. Python Module Resolution — Missing `__init__.py`

**Problem:** `ModuleNotFoundError: No module named 'ingestion.edgar_client'` and similar errors for `nlp.finbert_runner`.

**Cause:** Python files were either in the project root (not inside their package directories) or the package directories lacked `__init__.py` files.

**Fix:** Moved source files into their package directories (`ingestion/`, `nlp/`) and added empty `__init__.py` files to make Python treat them as importable packages.

---

## 10. SQL Ambiguous Column Reference

**Problem:** NLP pipeline query failed with `Binder Error: Ambiguous reference to column name "ticker"` when joining `raw_filings` and `nlp_signals` — both tables have a `ticker` column.

**Fix:** Prefixed all column references in `WHERE` clauses with table aliases (`r.ticker`, `r.filing_type` instead of bare `ticker`, `filing_type`). Always alias columns in JOINs to avoid ambiguity.

---

## 11. Docker File Sharing Permissions on macOS

**Problem:** `docker compose up` failed with `mkdir /host_mnt/Users/.../Desktop: operation not permitted`. Docker Desktop didn't have access to the macOS Desktop folder.

**Fix:** Added `/Users/sayalishelke/Desktop` to Docker Desktop → Settings → Resources → File Sharing, then restarted Docker.

**Takeaway:** macOS restricts folder access for sandboxed apps. Docker Desktop needs explicit file sharing permissions for project directories outside the default allowed paths.

---

## 12. FinBERT Runner — MinIO Connection Errors Outside Docker

**Problem:** Running `finbert_runner.py` locally (outside Docker) failed with 237 `Could not connect to the endpoint URL` errors when trying to reach MinIO.

**Diagnosis:** MinIO was accessible on `localhost:9000` (confirmed via `curl`), but the boto3 client inside the FinBERT runner was timing out on specific object GET requests. The files existed inside MinIO (ingested via Docker) but some keys were stale or had path mismatches.

**Fix:** Added XBRL detection logic — when stored text looks like XBRL data (`xbrli:` or `fasb.org` markers in the first 500 chars), the runner re-fetches directly from SEC EDGAR using `fetch_filing_text()` with the corrected iXBRL parser, bypassing MinIO entirely.

---

## 13. Missing Function Parameter — TypeError

**Problem:** `run_finbert_pipeline(filing_types_override=['10-Q', '10-K'])` raised `TypeError: got an unexpected keyword argument 'filing_types_override'`.

**Fix:** Added the `filing_types_override` parameter to the function signature with a default of `None`, falling back to `TARGET_FILING_TYPES` when not provided. Always design batch pipeline functions with overridable defaults for testability.

---

## 14. Shell Quoting — zsh Invalid Mode Specification

**Problem:** Running `run_finbert_pipeline(filing_types_override=['10-Q', '10-K'])` directly in zsh failed with `zsh: invalid mode specification`. The square brackets and quotes confused the shell parser.

**Fix:** Wrapped the Python code inside `python3 -c "..."` with double quotes on the outside and single quotes for Python strings inside. Shell quoting rules: outer `"` for the `-c` argument, inner `'` for Python string literals.

---

## 15. Git Push — cp -r Killed (Exit 137) on Large .venv

**Problem:** `cp -r` of the project directory was killed by the OS (exit code 137 = SIGKILL, out of memory) because it tried to copy the 1.5GB `.venv` virtual environment folder.

**Fix:** Switched to `rsync` with exclusions:
```bash
rsync -a --exclude='.venv' --exclude='logs' --exclude='data' --exclude='__pycache__' source/ dest/
```
Only source code and config files are synced — large generated/cached directories are excluded.

---

## 16. `ingest_batch()` Returns Data but Prints Nothing

**Problem:** Running `ingest_batch()` via `python -c` showed no output. The function returns a DataFrame but doesn't print it — the return value is silently discarded in a `-c` script.

**Fix:** Capture the return value and print explicitly:
```python
summary = ingest_batch(tickers=SP500_TICKERS, lookback_days=1095)
print(summary.to_string())
```
**Takeaway:** Python's `-c` flag doesn't auto-print expression results like the REPL does. Always add explicit `print()` calls.

---

## 17. RAG Server — `NameError: name 'app' is not defined`

**Problem:** `uvicorn rag.rag_server:app` crashed on import with `NameError: name 'app' is not defined`. The file started with `@app.on_event("startup")` but had no imports, no `app = FastAPI()`, and no endpoint definitions.

**Cause:** The `rag_server.py` file was incomplete — only the startup hook was written, missing all boilerplate.

**Fix:** Added the full server structure: imports (`FastAPI`, `chromadb`, `pydantic`), the `app = FastAPI()` instantiation, request/response models, and all endpoint definitions before any decorators that reference `app`.

**Takeaway:** Python executes module-level code top-to-bottom on import. Decorators like `@app.on_event()` fail if `app` hasn't been defined yet above them.

---

## 18. FastAPI Async Startup Hanging on Synchronous Model Load

**Problem:** `uvicorn` printed `Waiting for application startup` and hung forever. The `@app.on_event("startup")` handler called `SentenceTransformerEmbeddingFunction()` which blocks the thread downloading/loading the ML model — but `startup` runs inside the async event loop.

**Fix:** Replaced `@app.on_event("startup")` with a lazy `_init_chroma()` function called on first request. Guarded by `if chroma_collection is not None: return` to ensure one-time initialization.

**Takeaway:** Never put heavy synchronous I/O (model loading, large downloads) inside async startup events. Use lazy initialization or `run_in_executor()` to avoid blocking the event loop.

---

## 19. Dashboard 404 — Missing API Endpoints

**Problem:** The React dashboard loaded but the leaderboard showed 0 entries. The frontend called `/leaderboard`, `/ticker/{ticker}`, `/anomalies`, and `/ask` but the FastAPI server only had `/health` and `/query`.

**Fix:** Added all four missing endpoints to `rag_server.py`:
- `/leaderboard` — aggregates `earnings_surprise_scores` by ticker
- `/ticker/{ticker}` — returns full filing history for a company
- `/anomalies` — returns filings flagged by Isolation Forest
- `/ask` — RAG endpoint (ChromaDB retrieval + Ollama generation)

Also added `CORSMiddleware` with `allow_origins=["*"]` since the dashboard (port 5173) and API (port 8000) are on different ports — without CORS headers, the browser blocks cross-origin requests.

---

## 20. npm Install Failure — Wrong Directory

**Problem:** `npm install` failed with `ENOENT: no such file or directory, open '.../quarter_findings/package.json'`. Running npm from the Python project root instead of the `dashboard/` subfolder.

**Fix:** `cd dashboard` before running `npm install` or `npm run dev`. The React app has its own `package.json` inside `dashboard/`.

**Takeaway:** Monorepos with mixed languages (Python + Node) have separate dependency roots. Always `cd` into the correct subfolder for each package manager.

---

## 21. `ModuleNotFoundError: No module named 'rag'`

**Problem:** `uvicorn rag.rag_server:app` failed with `ModuleNotFoundError` when run from the `dashboard/` directory.

**Cause:** Python resolves module imports relative to the current working directory. Running from `dashboard/` meant Python looked for `dashboard/rag/` which doesn't exist.

**Fix:** Always run `uvicorn` from the project root (`quarter_findings/`) where the `rag/` package directory exists.

**Takeaway:** For projects with multiple services (API + frontend), document which directory each command should be run from. Use `Makefile` targets or scripts to abstract this away.
