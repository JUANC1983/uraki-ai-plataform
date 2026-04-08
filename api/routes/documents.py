# api/routes/documents.py
import io
import time
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from api.dependencies import DB, CurrentUser
from connectors.storage_connector import get_storage_connector
from core.audit_logger import get_audit_logger
from database.repositories import DocumentRepository

router = APIRouter(prefix="/documents", tags=["Documents"])
audit_logger = get_audit_logger()

ALLOWED_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
    "image/jpeg",
    "image/png",
}


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    current_user: CurrentUser,
    db: DB,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    case_id: Optional[str] = Form(None),
    contract_id: Optional[str] = Form(None),
):
    """
    Upload a document (PDF, DOCX, image).

    Returns immediately with 202 Accepted. Parsing, chunking, and embedding
    run as a background task via the task queue. Poll GET /documents/{id}
    and check is_embedded == true for completion.
    """
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{file.content_type}' not supported. "
                   f"Allowed: {sorted(ALLOWED_TYPES)}",
        )

    tenant_id = str(current_user.tenant_id)

    # Save raw bytes to storage backend
    storage = get_storage_connector()
    file_bytes = await file.read()
    storage_result = await storage.save_file(
        tenant_id=tenant_id,
        file_obj=io.BytesIO(file_bytes),
        original_filename=file.filename or "document",
        content_type=file.content_type,
    )

    # Create DB record — tenant_id passed at construction, not as a method arg
    doc_repo = DocumentRepository(db, tenant_id)
    document = await doc_repo.create(
        data={
            "case_id": case_id,
            "contract_id": contract_id,
            "document_type": document_type,
            "file_name": file.filename,
            "file_path": storage_result["file_path"],
            "file_size": int(storage_result["file_size"]),
            "mime_type": file.content_type,
        }
    )
    await db.commit()
    await db.refresh(document)

    # Enqueue background processing (parse → chunk → embed)
    from automation.task_queue import get_task_queue
    queue = get_task_queue()
    background_tasks.add_task(
        queue.run,
        "process_document",
        document_id=str(document.id),
        tenant_id=tenant_id,
        file_path=storage_result["file_path"],
        mime_type=file.content_type,
        document_type=document_type,
        case_id=case_id,
    )

    return {
        "document_id": str(document.id),
        "file_name": file.filename,
        "document_type": document_type,
        "status": "processing",
        "message": "Document accepted. Poll GET /documents/{id} — is_embedded=true when ready.",
    }


@router.get("/{document_id}")
async def get_document(
    document_id: str,
    current_user: CurrentUser,
    db: DB,
):
    tenant_id = str(current_user.tenant_id)
    # tenant_id at construction — no extra kwargs needed
    doc_repo = DocumentRepository(db, tenant_id)
    doc = await doc_repo.get(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "id": str(doc.id),
        "document_type": doc.document_type,
        "file_name": doc.file_name,
        "file_size": doc.file_size,
        "mime_type": doc.mime_type,
        "is_embedded": doc.is_embedded,
        "case_id": str(doc.case_id) if doc.case_id else None,
        "contract_id": doc.contract_id,
        "metadata": doc.doc_metadata,
        "created_at": doc.created_at.isoformat(),
    }


class SearchRequest(BaseModel):
    query: str
    case_id: Optional[str] = None
    top_k: int = 5


@router.post("/search")
async def search_documents(
    payload: SearchRequest,
    current_user: CurrentUser,
    db: DB,
):
    """Semantic search across tenant's documents using embeddings."""
    from agents.document_agent import DocumentAgent
    from connectors.llm_connector import get_llm_connector
    from sqlalchemy import select
    from database.models import Document, DocumentChunk

    tenant_id = str(current_user.tenant_id)
    llm = get_llm_connector()

    try:
        query_embedding = await llm.embed_text(payload.query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {exc}")

    query = select(DocumentChunk).where(DocumentChunk.tenant_id == tenant_id)
    if payload.case_id:
        doc_ids_q = select(Document.id).where(
            Document.tenant_id == tenant_id,
            Document.case_id == payload.case_id,
        )
        query = query.where(DocumentChunk.document_id.in_(doc_ids_q))

    result = await db.execute(query)
    chunks = result.scalars().all()

    if not chunks:
        return {"results": []}

    doc_agent = DocumentAgent()
    chunk_data = [
        {
            "content": c.content,
            "clause_label": c.clause_label,
            "embedding": c.embedding,
            "document_id": str(c.document_id),
            "chunk_index": c.chunk_index,
        }
        for c in chunks if c.embedding
    ]

    results = doc_agent.search_chunks(
        query_embedding=query_embedding,
        chunk_embeddings=chunk_data,
        top_k=payload.top_k,
    )

    return {"results": [
        {
            "document_id": r["document_id"],
            "clause_label": r.get("clause_label"),
            "content": r["content"][:500],
            "score": round(r["score"], 4),
        }
        for r in results
    ]}
