# api/routes/documents.py
import io
import logging
import time
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from agents.document_agent import (
    DocumentAgent, DocumentProcessingError, SUPPORTED_DOCUMENT_MIME_TYPES,
    validate_docx_container,
)
from api.dependencies import DB, ReadUser, WriteUser
from api.response_models import DocumentResponse, SearchResponse, UploadResponse
from config.settings import get_settings
from connectors.storage_connector import get_storage_connector
from core.audit_logger import get_audit_logger
from database.repositories import CaseRepository, DocumentRepository

router = APIRouter(prefix="/documents", tags=["Documents"])
logger = logging.getLogger(__name__)
audit_logger = get_audit_logger()
settings = get_settings()
ALLOWED_TYPES = SUPPORTED_DOCUMENT_MIME_TYPES
EXPECTED_EXTENSIONS = {
    "application/pdf": {".pdf"},
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {".docx"},
    "text/plain": {".txt"},
}


@router.post(
    "/upload", status_code=status.HTTP_202_ACCEPTED, response_model=UploadResponse
)
async def upload_document(
    current_user: WriteUser,
    db: DB,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    document_type: str = Form(..., min_length=1, max_length=100),
    case_id: Optional[UUID] = Form(None),
    contract_id: Optional[str] = Form(None, max_length=200),
):
    """
    Upload a text-bearing PDF, DOCX, or UTF-8 text document.

    Returns immediately with 202 Accepted. Parsing, chunking, and embedding
    run as a background task via the task queue. Poll GET /documents/{id}
    and inspect metadata.processing_status for completion or failure.
    """
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{file.content_type}' not supported. "
                   f"Allowed: {sorted(ALLOWED_TYPES)}",
        )

    if not file.filename:
        raise HTTPException(status_code=400, detail="A file name is required")
    from pathlib import Path
    if Path(file.filename).suffix.lower() not in EXPECTED_EXTENSIONS[file.content_type]:
        raise HTTPException(status_code=400, detail="File extension does not match content type")
    if not document_type.strip():
        raise HTTPException(status_code=400, detail="document_type must not be empty")

    tenant_id = str(current_user.tenant_id)
    normalized_case_id = str(case_id) if case_id else None
    if normalized_case_id and not await CaseRepository(db, tenant_id).get(normalized_case_id):
        raise HTTPException(status_code=404, detail="Case not found")

    file_bytes = await file.read(settings.MAX_DOCUMENT_BYTES + 1)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Document must not be empty")
    if len(file_bytes) > settings.MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="Document exceeds configured size limit")
    if file.content_type == "application/pdf" and not file_bytes.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="File content is not a valid PDF signature")
    if (
        file.content_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        and not file_bytes.startswith(b"PK")
    ):
        raise HTTPException(status_code=400, detail="File content is not a valid DOCX container")
    if file.content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            validate_docx_container(file_bytes, settings.MAX_DOCUMENT_BYTES * 5)
        except DocumentProcessingError as exc:
            raise HTTPException(status_code=400, detail="DOCX container failed safety validation") from exc
    storage = get_storage_connector()
    storage_result = await storage.save_file(
        tenant_id=tenant_id,
        file_obj=io.BytesIO(file_bytes),
        original_filename=file.filename or "document",
        content_type=file.content_type,
    )

    # Create DB record — tenant_id passed at construction, not as a method arg
    try:
        doc_repo = DocumentRepository(db, tenant_id)
        document = await doc_repo.create(
            data={
                "case_id": normalized_case_id,
                "contract_id": contract_id,
                "document_type": document_type.strip(),
                "file_name": file.filename,
                "file_path": storage_result["file_path"],
                "file_size": int(storage_result["file_size"]),
                "mime_type": file.content_type,
                "doc_metadata": {"processing_status": "processing"},
            }
        )
        await db.commit()
        await db.refresh(document)
    except Exception:
        await db.rollback()
        try:
            await storage.delete_file(storage_result["file_path"], tenant_id=tenant_id)
        except Exception as cleanup_exc:
            logger.error("Failed to clean up rejected upload (%s)", type(cleanup_exc).__name__)
        raise

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
        document_type=document_type.strip(),
        case_id=normalized_case_id,
        contract_id=contract_id,
    )

    return {
        "document_id": str(document.id),
        "file_name": file.filename,
        "document_type": document_type.strip(),
        "status": "processing",
        "message": "Document accepted. Poll GET /documents/{id} for processing_status.",
    }


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    current_user: ReadUser,
    db: DB,
):
    tenant_id = str(current_user.tenant_id)
    document_id = str(document_id)
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
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    case_id: Optional[UUID] = None
    top_k: int = Field(default=5, ge=1, le=20)


@router.post("/search", response_model=SearchResponse)
async def search_documents(
    payload: SearchRequest,
    current_user: ReadUser,
    db: DB,
):
    """Semantic search across tenant's documents using embeddings."""
    from connectors.llm_connector import (
        LLMRequestError,
        LLMResponseError,
        LLMUnavailableError,
        get_llm_connector,
    )

    tenant_id = str(current_user.tenant_id)
    chunks = await DocumentRepository(db, tenant_id).get_all_chunks_for_tenant(
        str(payload.case_id) if payload.case_id else None
    )
    if not chunks:
        return {"results": []}

    try:
        llm = get_llm_connector()
        query_embedding = await llm.embed_text(payload.query)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Embedding service is not configured") from exc
    except LLMRequestError as exc:
        raise HTTPException(status_code=503, detail="Embedding service is temporarily unavailable") from exc
    except LLMResponseError as exc:
        raise HTTPException(status_code=502, detail="Embedding service returned an invalid response") from exc

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

    results = DocumentAgent().search_chunks(
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
