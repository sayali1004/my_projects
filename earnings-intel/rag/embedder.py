"""
rag/embedder.py
────────────────
Embeds all SEC filing text into ChromaDB vector store.
Uses sentence-transformers (free, runs locally).

Cloud swap: replace ChromaDB with Pinecone or AWS OpenSearch.
Replace sentence-transformers with AWS Bedrock embeddings.
"""

from __future__ import annotations

import logging
import os
import re

import boto3
import chromadb
import duckdb
from botocore.client import Config
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

DUCKDB_PATH = os.getenv("DUCKDB_PATH", "data/warehouse.db")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
RAW_BUCKET = "earnings-raw-filings"
CHROMA_PATH = os.getenv("CHROMA_PATH", "data/chroma")


def get_minio_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def chunk_text(text: str, chunk_size: int = 300, overlap: int = 50) -> list[str]:
    """
    Split text into overlapping chunks of ~300 words.
    Overlap ensures context isn't lost at chunk boundaries.
    """
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if len(chunk.split()) >= 30:  # skip tiny chunks
            chunks.append(chunk)
    return chunks


def build_vector_store(
    tickers: list[str] | None = None,
    filing_types: list[str] = ["10-Q", "10-K"],
    max_chunks_per_filing: int = 20,
    db_path: str = DUCKDB_PATH,
) -> chromadb.Collection:
    """
    Embed all filings into ChromaDB.
    Uses all-MiniLM-L6-v2 — fast, free, 384-dim embeddings.
    Downloads ~90MB on first run, cached after that.
    """
    os.makedirs(CHROMA_PATH, exist_ok=True)

    # ChromaDB persistent client
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    # Embedding function — sentence-transformers (free, local)
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    # Get or create collection
    collection = client.get_or_create_collection(
        name="earnings_filings",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    existing_count = collection.count()
    logger.info("Existing chunks in ChromaDB: %d", existing_count)

    # Fetch filings to embed
    con = duckdb.connect(db_path, read_only=True)
    ticker_filter = f"AND ticker IN ({','.join(repr(t) for t in tickers)})" if tickers else ""
    type_filter = f"AND filing_type IN ({','.join(repr(t) for t in filing_types)})"

    filings = con.execute(f"""
        SELECT id, ticker, filing_type, filed_date, minio_key
        FROM raw_filings
        WHERE minio_key IS NOT NULL
          {ticker_filter}
          {type_filter}
        ORDER BY filed_date DESC
    """).df()
    con.close()

    logger.info("Embedding %d filings...", len(filings))
    minio = get_minio_client()

    total_chunks = 0
    for i, row in filings.iterrows():
        # Skip if already embedded
        existing = collection.get(where={"filing_id": row["id"]})
        if existing["ids"]:
            continue

        try:
            key = row["minio_key"].replace(f"s3://{RAW_BUCKET}/", "")
            text = minio.get_object(
                Bucket=RAW_BUCKET, Key=key
            )["Body"].read().decode("utf-8")

            chunks = chunk_text(text)[:max_chunks_per_filing]
            if not chunks:
                continue

            # Add to ChromaDB
            collection.add(
                documents=chunks,
                ids=[f"{row['id']}_chunk_{j}" for j in range(len(chunks))],
                metadatas=[{
                    "filing_id": row["id"],
                    "ticker": row["ticker"],
                    "filing_type": row["filing_type"],
                    "filed_date": str(row["filed_date"]),
                } for _ in chunks],
            )
            total_chunks += len(chunks)

            if (i + 1) % 10 == 0:
                logger.info("[%d/%d] Embedded %d total chunks", i + 1, len(filings), total_chunks)

        except Exception as e:
            logger.error("Failed to embed %s: %s", row["ticker"], e)

    logger.info("Done — %d total chunks in ChromaDB", collection.count())
    return collection


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Smoke test — embed just AAPL and MSFT first
    collection = build_vector_store(tickers=["AAPL", "MSFT"])
    print(f"Total chunks: {collection.count()}")

    # Test retrieval
    results = collection.query(
        query_texts=["iPhone revenue growth and margin trends"],
        n_results=3,
    )
    print("\nTest query results:")
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        print(f"  [{meta['ticker']} {meta['filed_date']}] {doc[:100]}...")