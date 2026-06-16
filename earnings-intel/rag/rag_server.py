"""
rag/rag_server.py
──────────────────
FastAPI RAG server for EarningsEdge.

Endpoints:
  POST /ask          — answer a question about any company's filings
  GET  /scores       — return top earnings surprise scores
  GET  /leaderboard  — return score leaderboard by ticker
  GET  /anomalies    — return anomalous filings
  GET  /health       — health check

RAG flow:
  1. Embed the user question with sentence-transformers
  2. Retrieve top-5 most relevant filing chunks from ChromaDB
  3. Build a context-aware prompt with retrieved chunks
  4. Send to Ollama (Llama 3.1, runs locally, free)
  5. Return grounded answer with source citations

Cloud swap: replace Ollama with AWS Bedrock (Claude/Llama) or
            Google Vertex AI for production deployment.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import chromadb
import duckdb
import httpx
import pandas as pd
from chromadb.utils import embedding_functions
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DUCKDB_PATH = os.getenv("DUCKDB_PATH", "data/warehouse.db")
CHROMA_PATH = os.getenv("CHROMA_PATH", "data/chroma")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

app = FastAPI(
    title="EarningsEdge API",
    description="Financial intelligence platform powered by SEC filings + NLP",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global clients (loaded once at startup) ───────────────────────────────────

chroma_collection = None
ef = None


@app.on_event("startup")
async def startup():
    global chroma_collection, ef
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


# ── Request/Response models ───────────────────────────────────────────────────

class QuestionRequest(BaseModel):
    question: str
    ticker: str | None = None      # optional — filter to specific company
    filing_type: str | None = None # optional — filter to 10-Q, 10-K, 8-K
    n_results: int = 5


class Source(BaseModel):
    ticker: str
    filed_date: str
    filing_type: str
    excerpt: str


class AnswerResponse(BaseModel):
    question: str
    answer: str
    sources: list[Source]
    model: str
    retrieved_chunks: int


# ── RAG core ─────────────────────────────────────────────────────────────────

def retrieve_context(
    question: str,
    ticker: str | None = None,
    filing_type: str | None = None,
    n_results: int = 5,
) -> tuple[list[str], list[dict]]:
    """Retrieve relevant chunks from ChromaDB."""
    where = {}
    if ticker:
        where["ticker"] = ticker.upper()
    if filing_type:
        where["filing_type"] = filing_type.upper()

    results = chroma_collection.query(
        query_texts=[question],
        n_results=n_results,
        where=where if where else None,
    )

    documents = results["documents"][0] if results["documents"] else []
    metadatas = results["metadatas"][0] if results["metadatas"] else []
    return documents, metadatas


def build_prompt(question: str, chunks: list[str], metadatas: list[dict]) -> str:
    """Build a grounded RAG prompt."""
    context_parts = []
    for chunk, meta in zip(chunks, metadatas):
        context_parts.append(
            f"[{meta['ticker']} | {meta['filing_type']} | {meta['filed_date']}]\n{chunk}"
        )
    context = "\n\n---\n\n".join(context_parts)

    return f"""You are a financial analyst assistant with access to SEC filing excerpts.
Answer the question based ONLY on the provided context.
If the answer is not in the context, say "I don't have enough information in the filings to answer that."
Never make up financial figures or dates.

CONTEXT FROM SEC FILINGS:
{context}

QUESTION: {question}

ANSWER (be specific, cite the company and date when referencing information):"""


async def call_ollama(prompt: str) -> str:
    """Call Ollama API (local LLM, free)."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,  # low temp = factual, grounded answers
                    "num_predict": 512,
                },
            },
        )
        response.raise_for_status()
        return response.json()["response"].strip()


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "chroma_chunks": chroma_collection.count() if chroma_collection else 0,
        "ollama_url": OLLAMA_URL,
        "model": OLLAMA_MODEL,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/ask", response_model=AnswerResponse)
async def ask(request: QuestionRequest):
    """Answer a question grounded in SEC filing text."""
    if not chroma_collection or chroma_collection.count() == 0:
        raise HTTPException(503, "Vector store not ready — run embedder.py first")

    # Retrieve context
    chunks, metadatas = retrieve_context(
        request.question,
        ticker=request.ticker,
        filing_type=request.filing_type,
        n_results=request.n_results,
    )

    if not chunks:
        raise HTTPException(404, "No relevant filing chunks found for this query")

    # Call LLM
    prompt = build_prompt(request.question, chunks, metadatas)
    try:
        answer = await call_ollama(prompt)
    except Exception as e:
        raise HTTPException(503, f"Ollama unavailable: {e}. Install with: ollama pull llama3.1")

    sources = [
        Source(
            ticker=m["ticker"],
            filed_date=m["filed_date"],
            filing_type=m["filing_type"],
            excerpt=doc[:200] + "...",
        )
        for doc, m in zip(chunks, metadatas)
    ]

    return AnswerResponse(
        question=request.question,
        answer=answer,
        sources=sources,
        model=OLLAMA_MODEL,
        retrieved_chunks=len(chunks),
    )


@app.get("/scores")
async def get_scores(
    ticker: str | None = None,
    label: str | None = None,
    limit: int = 50,
):
    """Return earnings surprise scores."""
    con = duckdb.connect(DUCKDB_PATH, read_only=True)
    ticker_filter = f"AND ticker = '{ticker.upper()}'" if ticker else ""
    label_filter = f"AND surprise_label = '{label}'" if label else ""

    df = con.execute(f"""
        SELECT ticker, filing_type, filed_date,
               ROUND(surprise_score, 2) as surprise_score,
               surprise_label, is_anomaly,
               ROUND(pct_change_1d * 100, 3) as return_1d_pct,
               ROUND(sentiment_delta, 4) as sentiment_delta,
               ROUND(hedging_ratio, 4) as hedging_ratio
        FROM earnings_surprise_scores
        WHERE surprise_score IS NOT NULL
          {ticker_filter}
          {label_filter}
        ORDER BY surprise_score DESC
        LIMIT {limit}
    """).df()
    con.close()
    return df.to_dict(orient="records")


@app.get("/leaderboard")
async def get_leaderboard():
    """Return avg surprise score leaderboard by ticker — for dashboard."""
    con = duckdb.connect(DUCKDB_PATH, read_only=True)
    df = con.execute("""
        SELECT
            ticker,
            ROUND(AVG(surprise_score), 2)       AS avg_score,
            ROUND(AVG(pct_change_1d * 100), 3)  AS avg_return_1d,
            COUNT(*)                             AS filings,
            SUM(CASE WHEN surprise_label = 'bullish' THEN 1 ELSE 0 END) AS bullish_count,
            SUM(CASE WHEN surprise_label = 'bearish' THEN 1 ELSE 0 END) AS bearish_count,
            SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END)                 AS anomaly_count
        FROM earnings_surprise_scores
        GROUP BY ticker
        ORDER BY avg_score DESC
    """).df()
    con.close()
    return df.to_dict(orient="records")


@app.get("/anomalies")
async def get_anomalies():
    """Return anomalous filings detected by Isolation Forest."""
    con = duckdb.connect(DUCKDB_PATH, read_only=True)
    df = con.execute("""
        SELECT ticker, filing_type, filed_date,
               ROUND(surprise_score, 2) as surprise_score,
               ROUND(sentiment_delta, 4) as sentiment_delta,
               ROUND(hedging_ratio, 4) as hedging_ratio,
               ROUND(pct_change_1d * 100, 3) as return_1d_pct
        FROM earnings_surprise_scores
        WHERE is_anomaly = TRUE
        ORDER BY filed_date DESC
    """).df()
    con.close()
    return df.to_dict(orient="records")


@app.get("/ticker/{ticker}")
async def get_ticker_history(ticker: str):
    """Return full score history for a ticker — for company detail view."""
    con = duckdb.connect(DUCKDB_PATH, read_only=True)
    df = con.execute("""
        SELECT filing_type, filed_date,
               ROUND(surprise_score, 2) as surprise_score,
               surprise_label,
               ROUND(sentiment_delta, 4) as sentiment_delta,
               ROUND(hedging_ratio, 4) as hedging_ratio,
               ROUND(vader_compound, 4) as vader_compound,
               ROUND(pct_change_1d * 100, 3) as return_1d_pct,
               is_anomaly
        FROM earnings_surprise_scores
        WHERE ticker = ?
        ORDER BY filed_date DESC
    """, [ticker.upper()]).df()
    con.close()

    if df.empty:
        raise HTTPException(404, f"No data found for ticker {ticker}")

    return {
        "ticker": ticker.upper(),
        "total_filings": len(df),
        "avg_score": round(df["surprise_score"].mean(), 2),
        "history": df.to_dict(orient="records"),
    }


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)