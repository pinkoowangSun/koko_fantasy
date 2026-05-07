import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.document import Document
from app.models.user import User
from app.routers.auth import require_approved
from app.schemas.document import DocumentQARequest, DocumentResponse
from app.services.rag_service import extract_text, index_document, query_and_answer

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.get("/", response_model=List[DocumentResponse])
async def list_documents(
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document)
        .where(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
    )
    return result.scalars().all()


@router.post("/", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    source: str = Form("web"),
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported file type")

    user_dir = settings.DOCUMENTS_DIR / str(current_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename or "file").suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    file_path = user_dir / stored_name
    file_path.write_bytes(content)

    doc = Document(
        user_id=current_user.id,
        stored_name=stored_name,
        original_name=file.filename,
        file_path=str(file_path),
        file_size=len(content),
        mime_type=file.content_type,
        description=description,
        source=source,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    try:
        text = extract_text(str(file_path), file.content_type)
        if text.strip():
            await index_document(
                current_user.id, doc.id, text,
                {"doc_id": doc.id, "original_name": file.filename or ""},
            )
            doc.indexed = True
            await db.commit()
    except Exception as exc:
        print(f"[rag] indexing failed for doc {doc.id}: {exc}")

    return doc


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: int,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.user_id == current_user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    doc_id: int,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.user_id == current_user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "Document not found")

    # Guard against path traversal before unlinking
    user_dir = settings.DOCUMENTS_DIR.resolve() / str(current_user.id)
    resolved = Path(doc.file_path).resolve()
    if not str(resolved).startswith(str(user_dir)):
        raise HTTPException(400, "Invalid file path")

    resolved.unlink(missing_ok=True)
    await db.delete(doc)
    await db.commit()


@router.post("/qa")
async def document_qa(
    body: DocumentQARequest,
    current_user: User = Depends(require_approved),
):
    answer = await query_and_answer(current_user.id, body.question, body.document_id)
    return {"answer": answer}
