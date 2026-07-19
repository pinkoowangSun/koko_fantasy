"""Document ingestion and Q&A via ChromaDB + DeepSeek."""
import asyncio
from pathlib import Path
import chromadb
from openai import AsyncOpenAI
from app.config import settings

_chroma = chromadb.PersistentClient(path=str(settings.VECTORS_DIR))
_ai = AsyncOpenAI(api_key=settings.DEEPSEEK_API_KEY, base_url=settings.DEEPSEEK_BASE_URL)


def _get_collection(user_id: int):
    return _chroma.get_or_create_collection(f"user_{user_id}")


def _chunk_text(text: str, size: int = 400, overlap: int = 50) -> list[str]:
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunks.append(" ".join(words[i : i + size]))
        i += size - overlap
    return [c for c in chunks if c.strip()]


def extract_text(file_path: str, mime_type: str | None) -> str:
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf" or mime_type == "application/pdf":
        import fitz
        doc = fitz.open(file_path)
        return "\n".join(page.get_text() for page in doc)

    if suffix == ".docx" or "wordprocessingml" in (mime_type or ""):
        from docx import Document
        return "\n".join(p.text for p in Document(file_path).paragraphs)

    if suffix in (".txt", ".md") or (mime_type or "").startswith("text/"):
        return path.read_text(encoding="utf-8", errors="ignore")

    return ""


async def index_document(user_id: int, doc_id: int, text: str, meta: dict):
    collection = _get_collection(user_id)
    chunks = _chunk_text(text)
    if not chunks:
        return

    ids = [f"doc_{doc_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [{**meta, "chunk_index": i} for i in range(len(chunks))]

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: collection.upsert(documents=chunks, ids=ids, metadatas=metadatas),
    )


async def delete_document_index(user_id: int, doc_id: int) -> None:
    """Idempotently remove every vector chunk belonging to one document."""
    collection = _get_collection(user_id)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: collection.delete(where={"doc_id": doc_id}),
    )


async def query_and_answer(user_id: int, question: str, doc_id: int | None = None) -> str:
    collection = _get_collection(user_id)
    where = {"doc_id": doc_id} if doc_id else None

    loop = asyncio.get_event_loop()
    try:
        results = await loop.run_in_executor(
            None,
            lambda: collection.query(
                query_texts=[question],
                n_results=5,
                where=where,
            ),
        )
    except Exception:
        return "No indexed documents found. Upload and index documents first."

    docs = results.get("documents", [[]])[0]
    if not docs:
        return "I couldn't find relevant information in your documents."

    context = "\n\n---\n\n".join(docs)
    resp = await _ai.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=[
            {
                "role": "system",
                "content": "Answer the question using only the provided document context. "
                           "Be precise. If the answer isn't in the context, say so.",
            },
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content
