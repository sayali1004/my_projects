import os
import uuid
import shutil
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.database import get_db, Document
from vault.ingest import ingest_document, delete_document_chunks

router = APIRouter()

VAULT_PATH = os.getenv("VAULT_PATH", "./vault")
ALLOWED_TYPES = {"pdf", "docx", "txt", "png", "jpg", "jpeg"}


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    project_id: str  = Form(None),
    scope: str       = Form("project"),   # "project" or "global"
    db: AsyncSession = Depends(get_db)
):
    """Upload a document to the vault and ingest it into ChromaDB."""

    # Validate file type
    ext = file.filename.split(".")[-1].lower()
    if ext not in ALLOWED_TYPES:
        raise HTTPException(400, f"File type .{ext} not supported. Use: {ALLOWED_TYPES}")

    # Save file to disk
    doc_id    = str(uuid.uuid4())
    save_dir  = os.path.join(VAULT_PATH, project_id or "global")
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, f"{doc_id}.{ext}")

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Ingest into ChromaDB (parse → chunk → embed → store)
    chunk_count = 0
    if ext in {"pdf", "docx", "txt"}:
        chunk_count = ingest_document(
            file_path=file_path,
            file_name=file.filename,
            file_type=ext,
            document_id=doc_id,
            project_id=project_id,
            scope=scope
        )

    # Save metadata to SQLite
    doc = Document(
        id=doc_id,
        name=file.filename,
        file_type=ext,
        file_path=file_path,
        scope=scope,
        project_id=project_id,
        chunk_count=str(chunk_count)
    )
    db.add(doc)
    await db.commit()

    return {
        "id":          doc_id,
        "name":        file.filename,
        "file_type":   ext,
        "scope":       scope,
        "project_id":  project_id,
        "chunk_count": chunk_count,
        "message":     f"Uploaded and indexed {chunk_count} chunks. Ready for retrieval."
    }


@router.get("/documents")
async def list_documents(
    project_id: str  = None,
    scope: str       = None,
    db: AsyncSession = Depends(get_db)
):
    """List all documents in the vault, optionally filtered by project or scope."""
    query = select(Document)

    if project_id:
        query = query.where(Document.project_id == project_id)
    if scope:
        query = query.where(Document.scope == scope)

    result = await db.execute(query)
    docs   = result.scalars().all()

    return [
        {
            "id":          d.id,
            "name":        d.name,
            "file_type":   d.file_type,
            "scope":       d.scope,
            "project_id":  d.project_id,
            "chunk_count": d.chunk_count,
            "created_at":  d.created_at.isoformat()
        }
        for d in docs
    ]


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete a document from vault, disk, and ChromaDB."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc    = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(404, "Document not found")

    # Remove from ChromaDB
    delete_document_chunks(document_id, doc.project_id, doc.scope)

    # Remove from disk
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)

    # Remove from database
    await db.delete(doc)
    await db.commit()

    return {"message": f"Document {doc.name} deleted from vault"}
