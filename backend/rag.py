import os
import uuid
from pypdf import PdfReader
from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchAny

COLLECTION_NAME = "usakti_kb"
EMBED_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
VECTOR_SIZE = 768

# Initialize once at module import (downloads & caches ONNX model on first boot)
embed_model = TextEmbedding(model_name=EMBED_MODEL_NAME)

def ensure_collection(qdrant: QdrantClient):
    collections = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION_NAME in collections:
        info = qdrant.get_collection(COLLECTION_NAME)
        existing_size = info.config.params.vectors.size
        if existing_size != VECTOR_SIZE:
            qdrant.delete_collection(COLLECTION_NAME)
            collections.remove(COLLECTION_NAME)

    if COLLECTION_NAME not in collections:
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=VECTOR_SIZE,
                distance=models.Distance.COSINE
            )
        )

def chunk_text(text: str, chunk_size: int = 450, overlap: int = 80) -> list[str]:
    words = text.split()
    chunks = []
    step = max(1, chunk_size - overlap)
    for i in range(0, len(words), step):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks

def extract_text(file_path: str) -> str:
    if file_path.lower().endswith(".pdf"):
        reader = PdfReader(file_path)
        pages = []
        for idx, page in enumerate(reader.pages, start=1):
            txt = page.extract_text() or ""
            if txt.strip():
                pages.append(f"[Halaman {idx}]\n{txt}")
        return "\n\n".join(pages)
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def ingest_document(
    file_path: str,
    filename: str,
    ai_client,  # Kept in signature so main.py calls don't break
    qdrant: QdrantClient,
    faculty: str = "UMUM",
    major: str = "UMUM"
) -> int:
    ensure_collection(qdrant)
    raw_text = extract_text(file_path)
    chunks = chunk_text(raw_text)
    if not chunks:
        return 0

    major_list = [m.strip().upper() for m in major.split(",") if m.strip()] or ["UMUM"]
    batch_size = 32
    total_indexed = 0

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        # fastembed returns a generator of numpy float32 arrays
        vectors = list(embed_model.embed(batch))

        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vec.tolist(),
                payload={
                    "source": filename,
                    "faculty": faculty.upper().strip(),
                    "major": major_list,
                    "text": chunk
                }
            )
            for chunk, vec in zip(batch, vectors)
        ]
        qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
        total_indexed += len(points)

    return total_indexed

def delete_document(filename: str, qdrant: QdrantClient):
    ensure_collection(qdrant)
    qdrant.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="source",
                        match=models.MatchValue(value=filename)
                    )
                ]
            )
        )
    )

def retrieve_context(
    query: str,
    ai_client,  # Kept in signature so main.py calls don't break
    qdrant: QdrantClient,
    major: str | None = None,
    top_k: int = 5
) -> list[dict]:
    ensure_collection(qdrant)
    query_vec = next(embed_model.embed([query])).tolist()

    allowed_majors = ["UMUM"]
    if major and major.upper() != "UMUM":
        allowed_majors.append(major.upper().strip())

    query_filter = Filter(
        must=[
            FieldCondition(
                key="major",
                match=MatchAny(any=allowed_majors)
            )
        ]
    )

    hits = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vec,
        query_filter=query_filter,
        limit=top_k
    ).points

    return [
        {
            "source": h.payload.get("source", "unknown"),
            "major": h.payload.get("major", "UMUM"),
            "text": h.payload.get("text", ""),
            "score": h.score
        }
        for h in hits
    ]