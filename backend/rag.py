import os
import uuid
from pypdf import PdfReader
from google import genai
from google.genai import types
from qdrant_client import QdrantClient, models

COLLECTION_NAME = "usakti_kb"
VECTOR_SIZE = 3072  # Default dimension for gemini-embedding-001

def ensure_collection(qdrant: QdrantClient):
    collections = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION_NAME not in collections:
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=VECTOR_SIZE,
                distance=models.Distance.COSINE
            )
        )

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> list[str]:
    text = " ".join(text.split())  # Normalize whitespace
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return [c.strip() for c in chunks if len(c.strip()) > 30]

def extract_text_from_file(file_path: str) -> str:
    if file_path.lower().endswith(".pdf"):
        reader = PdfReader(file_path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

def ingest_document(file_path: str, filename: str, ai_client: genai.Client, qdrant: QdrantClient) -> int:
    ensure_collection(qdrant)
    raw_text = extract_text_from_file(file_path)
    chunks = chunk_text(raw_text)
    if not chunks:
        return 0

    # Embed chunks in batches of 50 using gemini-embedding-001
    points = []
    batch_size = 50
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        embed_res = ai_client.models.embed_content(
            model="gemini-embedding-001",
            contents=batch,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT")
        )
        for chunk_str, emb in zip(batch, embed_res.embeddings):
            points.append(
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=emb.values,
                    payload={
                        "source": filename,
                        "text": chunk_str
                    }
                )
            )

    qdrant.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
    return len(points)

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

def retrieve_context(query: str, ai_client: genai.Client, qdrant: QdrantClient, top_k: int = 4) -> list[dict]:
    ensure_collection(qdrant)
    embed_res = ai_client.models.embed_content(
        model="gemini-embedding-001",
        contents=query,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
    )
    query_vector = embed_res.embeddings[0].values

    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
        score_threshold=0.45  # Filter out completely irrelevant matches
    )

    return [
        {
            "source": hit.payload.get("source", "Unknown"),
            "text": hit.payload.get("text", ""),
            "score": round(hit.score, 3)
        }
        for hit in results.points
    ]