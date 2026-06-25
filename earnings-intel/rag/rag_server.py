"""
rag/rag_server.py
──────────────────
FastAPI server for earnings filing RAG queries.
Uses ChromaDB for retrieval + Ollama for generation.
"""

from __future__ import annotations

import logging
import os

import chromadb
import duckdb
from chromadb.utils import embedding_functions
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger(__name__)

CHROMA_PATH = os.getenv("CHROMA_PATH", "data/chroma")
DUCKDB_PATH = os.getenv("DUCKDB_PATH", "data/warehouse.db")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

app = FastAPI(title="EarningsEdge RAG API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

chroma_collection = None
ef = None


class QueryRequest(BaseModel):
    question: str
    ticker: str | None = None
    n_results: int = 5


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict]


def _init_chroma():
    """Lazy init — avoids blocking async startup with model load."""
    global chroma_collection, ef
    if chroma_collection is not None:
        return
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    chroma_collection = client.get_or_create_collection(
        name="earnings_filings",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )
    logger.info("ChromaDB loaded — %d chunks", chroma_collection.count())


@app.get("/health")
async def health():
    _init_chroma()
    return {"status": "ok", "chunks": chroma_collection.count()}


def _query_duckdb(sql: str, params=None):
    con = duckdb.connect(DUCKDB_PATH, read_only=True)
    result = con.execute(sql, params or []).df()
    con.close()
    return result


@app.get("/leaderboard")
async def leaderboard():
    df = _query_duckdb("""
        SELECT
            ticker,
            ROUND(AVG(surprise_score), 1) as avg_score,
            ROUND(AVG(pct_change_1d), 4) as avg_return_1d,
            COUNT(*) as filings,
            SUM(CASE WHEN surprise_label = 'bullish' THEN 1 ELSE 0 END) as bullish_count,
            SUM(CASE WHEN surprise_label = 'bearish' THEN 1 ELSE 0 END) as bearish_count,
            SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END) as anomaly_count
        FROM earnings_surprise_scores
        GROUP BY ticker
        ORDER BY avg_score DESC
    """)
    return df.to_dict(orient="records")


@app.get("/ticker/{ticker}")
async def ticker_detail(ticker: str):
    history = _query_duckdb("""
        SELECT
            filing_id, filing_type, filed_date, surprise_score, surprise_label,
            finbert_sentiment, vader_compound, hedging_ratio, sentiment_delta,
            pct_change_1d as return_1d_pct, is_anomaly
        FROM earnings_surprise_scores
        WHERE ticker = ?
        ORDER BY filed_date DESC
    """, [ticker.upper()])

    if history.empty:
        return {"ticker": ticker, "avg_score": 0, "total_filings": 0, "history": []}

    return {
        "ticker": ticker.upper(),
        "avg_score": round(float(history["surprise_score"].mean()), 1),
        "total_filings": len(history),
        "history": history.to_dict(orient="records"),
    }


@app.get("/anomalies")
async def anomalies():
    df = _query_duckdb("""
        SELECT
            ticker, filing_type, filed_date, surprise_score, surprise_label,
            sentiment_delta, hedging_ratio, pct_change_1d as return_1d_pct
        FROM earnings_surprise_scores
        WHERE is_anomaly = true
        ORDER BY filed_date DESC
    """)
    return df.to_dict(orient="records")


@app.post("/ask", response_model=QueryResponse)
async def ask(req: QueryRequest):
    _init_chroma()
    where_filter = {"ticker": req.ticker} if req.ticker else None

    results = chroma_collection.query(
        query_texts=[req.question],
        n_results=req.n_results,
        where=where_filter,
    )

    sources = []
    context_parts = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        sources.append(meta)
        context_parts.append(f"[{meta['ticker']} {meta['filed_date']}] {doc}")

    context = "\n\n".join(context_parts)

    try:
        import httpx
        prompt = (
            f"You are a financial analyst. Based on these SEC filing excerpts, "
            f"answer the question concisely.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {req.question}\n\nAnswer:"
        )
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": "llama3.2", "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            answer = resp.json().get("response", "No response from model")
    except Exception as e:
        logger.warning("Ollama unavailable: %s — returning context only", e)
        answer = f"(LLM unavailable) Top filing excerpts:\n{context[:1000]}"

    return QueryResponse(answer=answer, sources=sources)


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    _init_chroma()
    where_filter = {"ticker": req.ticker} if req.ticker else None

    results = chroma_collection.query(
        query_texts=[req.question],
        n_results=req.n_results,
        where=where_filter,
    )

    sources = []
    context_parts = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        sources.append(meta)
        context_parts.append(f"[{meta['ticker']} {meta['filed_date']}] {doc}")

    context = "\n\n".join(context_parts)

    try:
        import httpx
        prompt = (
            f"You are a financial analyst. Based on these SEC filing excerpts, "
            f"answer the question concisely.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {req.question}\n\nAnswer:"
        )
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": "llama3.2", "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            answer = resp.json().get("response", "No response from model")
    except Exception as e:
        logger.warning("Ollama unavailable: %s — returning context only", e)
        answer = f"(LLM unavailable) Top filing excerpts:\n{context[:1000]}"

    return QueryResponse(answer=answer, sources=sources)
