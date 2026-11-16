import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
import httpx
from google import genai
from google.genai import types
from google.genai.errors import APIError
from qdrant_client import QdrantClient
import redis

from rag import ensure_collection, ingest_document, delete_document, retrieve_context
from tools import STUDENT_TOOLS, LAST_TRIGGERED_UI

DB_PATH = "/app/data/chatbot.db"
UPLOAD_DIR = "/app/data/uploads"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            user_message TEXT,
            bot_response TEXT,
            sources TEXT,
            latency_ms INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE,
            chunk_count INTEGER,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.execute("""
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('system_prompt', 'Kamu adalah asisten virtual resmi Universitas Trisakti. Jawablah pertanyaan mahasiswa, dosen, dan calon mahasiswa secara ramah, akurat, dan ringkas berdasarkan KONTEKS DOKUMEN KAMPUS yang diberikan. Jika informasi tidak ada di dalam konteks, katakan dengan jujur bahwa kamu belum memiliki data tersebut dan arahkan pengguna untuk menghubungi BAAK / layanan informasi kampus. Jangan mengarang aturan atau jadwal.')
    """)
    conn.commit()
    conn.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_collection(qdrant)
    yield

app = FastAPI(title="Usakti AI Chatbot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Force HTTP/1.1 + IPv4 local bind for fast Docker networking
transport = httpx.HTTPTransport(local_address="0.0.0.0", http2=False)
http_client = httpx.Client(transport=transport, timeout=httpx.Timeout(30.0, connect=10.0))

ai_client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options=types.HttpOptions(httpx_client=http_client)
)
qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://qdrant:6333"))
cache = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)

def verify_admin(x_admin_password: str | None):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid admin password")

class ChatRequest(BaseModel):
    session_id: str = "default"
    message: str
    id_login: str | None = None
    role: str = "mahasiswa"

class SettingsRequest(BaseModel):
    system_prompt: str

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "qdrant_collections": len(qdrant.get_collections().collections),
        "redis_ping": cache.ping()
    }

# --- ADMIN WEB UI & ENDPOINTS ---

@app.get("/admin", response_class=HTMLResponse)
def admin_ui():
    with open("/app/admin.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/admin/upload")
async def upload_document(
    file: UploadFile = File(...),
    x_admin_password: str | None = Header(default=None)
):
    verify_admin(x_admin_password)
    if not file.filename.lower().endswith((".pdf", ".txt", ".md")):
        raise HTTPException(status_code=400, detail="Only PDF, TXT, and MD files are supported.")

    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    delete_document(file.filename, qdrant)
    chunks_added = ingest_document(file_path, file.filename, ai_client, qdrant)

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO documents (filename, chunk_count) VALUES (?, ?)",
        (file.filename, chunks_added)
    )
    conn.commit()
    conn.close()
    cache.flushdb()
    return {"filename": file.filename, "chunks_indexed": chunks_added}

@app.get("/api/admin/documents")
def list_documents(x_admin_password: str | None = Header(default=None)):
    verify_admin(x_admin_password)
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT filename, chunk_count, uploaded_at FROM documents ORDER BY uploaded_at DESC").fetchall()
    conn.close()
    return [{"filename": r[0], "chunk_count": r[1], "uploaded_at": r[2]} for r in rows]

@app.delete("/api/admin/documents/{filename}")
def remove_document(filename: str, x_admin_password: str | None = Header(default=None)):
    verify_admin(x_admin_password)
    delete_document(filename, qdrant)
    file_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM documents WHERE filename = ?", (filename,))
    conn.commit()
    conn.close()
    cache.flushdb()
    return {"deleted": filename}

@app.get("/api/admin/settings")
def get_settings(x_admin_password: str | None = Header(default=None)):
    verify_admin(x_admin_password)
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT value FROM settings WHERE key = 'system_prompt'").fetchone()
    conn.close()
    return {"system_prompt": row[0] if row else ""}

@app.post("/api/admin/settings")
def update_settings(req: SettingsRequest, x_admin_password: str | None = Header(default=None)):
    verify_admin(x_admin_password)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('system_prompt', ?)", (req.system_prompt,))
    conn.commit()
    conn.close()
    cache.flushdb()
    return {"status": "updated"}

@app.get("/api/admin/logs")
def get_logs(x_admin_password: str | None = Header(default=None)):
    verify_admin(x_admin_password)
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT created_at, user_message, bot_response, sources, latency_ms FROM chat_logs ORDER BY id DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return [
        {"created_at": r[0], "user_message": r[1], "bot_response": r[2], "sources": r[3], "latency_ms": r[4]}
        for r in rows
    ]

@app.get("/api/admin/logs/csv")
def export_logs_csv(x_admin_password: str | None = Header(default=None)):
    verify_admin(x_admin_password)
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, created_at, session_id, user_message, bot_response, sources, latency_ms FROM chat_logs ORDER BY id DESC"
    ).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Timestamp", "Session", "User Message", "Bot Response", "Sources", "Latency (ms)"])
    writer.writerows(rows)
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=usakti_chat_logs.csv"}
    )

# --- CHAT ENDPOINT WITH FAQ CACHE & RATE-LIMIT GUARD ---

def make_faq_cache_key(role: str, message: str) -> str:
    normalized = f"{role.lower().strip()}:{' '.join(message.lower().split())}"
    return "faq_cache:" + hashlib.sha256(normalized.encode()).hexdigest()

@app.post("/api/chat")
def chat_endpoint(req: ChatRequest):
    start_time = time.time()
    faq_key = make_faq_cache_key(req.role, req.message)

    # 1. Check Redis FAQ cache first (saves free API quota & responds in <10ms!)
    cached_raw = cache.get(faq_key)
    if cached_raw:
        cached_data = json.loads(cached_raw)
        latency = int((time.time() - start_time) * 1000)
        return {
            "reply": cached_data["reply"],
            "custom": cached_data["custom"],
            "sources": cached_data["sources"],
            "cached": True,
            "latency_ms": latency
        }

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT value FROM settings WHERE key = 'system_prompt'").fetchone()
    base_prompt = row[0] if row else "Kamu adalah asisten virtual resmi Universitas Trisakti."

    try:
        # 2. Retrieve relevant docs from Qdrant
        matches = retrieve_context(f"[{req.role}] {req.message}", ai_client, qdrant, top_k=4)
        if matches:
            context_block = "\n\n".join([f"[Sumber: {m['source']}]\n{m['text']}" for m in matches])
            sources_used = list(dict.fromkeys([m["source"] for m in matches]))
        else:
            context_block = "(Tidak ada dokumen panduan yang cocok.)"
            sources_used = []

        LAST_TRIGGERED_UI.pop(req.session_id, None)

        augmented_prompt = (
            f"{base_prompt}\n\n"
            f"=== INFO PENGGUNA ===\n"
            f"Session ID: {req.session_id} | Role: {req.role.upper()} | IdLogin: {req.id_login or 'Guest'}\n\n"
            f"=== ATURAN RESPONS SINGKAT ===\n"
            f"1. Jawab dengan RINGKAS, PADAT, dan TO THE POINT (maksimal 2-3 kalimat pendek, jangan bertele-tele).\n"
            f"2. Jika pengguna meminta melihat hasil/data layanan (contoh: 'hasil KHS', 'lihat KRS', 'tagihan pembayaran', 'status cuti'), "
            f"WAJIB panggil tool `trigger_ui_context(session_id='{req.session_id}', menu_context=...)` dan cukup berikan 1 kalimat pengantar singkat karena aplikasi akan langsung menampilkan tombol/halaman datanya.\n"
            f"3. Hanya jelaskan langkah-langkah panjang jika pengguna secara spesifik bertanya 'prosedur' atau 'syarat'.\n\n"
            f"=== KONTEKS DOKUMEN KAMPUS ===\n{context_block}\n"
            f"=============================="
        )

        # 3. Load multi-turn history from Redis
        raw_hist = cache.get(f"chat_hist:{req.session_id}")
        history_list = json.loads(raw_hist) if raw_hist else []
        contents = [
            types.Content(role=h["role"], parts=[types.Part.from_text(text=h["text"])])
            for h in history_list
        ]
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=req.message)]))

        # 4. Generate response with Gemini + Tools
        response = ai_client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=augmented_prompt,
                tools=STUDENT_TOOLS,
                temperature=0.2,
            )
        )
        reply = response.text

        triggered_ctx = LAST_TRIGGERED_UI.pop(req.session_id, None)
        custom_payload = {"context": triggered_ctx} if triggered_ctx else {}

        # Save conversation history
        history_list.append({"role": "user", "text": req.message})
        history_list.append({"role": "model", "text": reply})
        cache.setex(f"chat_hist:{req.session_id}", 3600, json.dumps(history_list[-20:]))

        # Cache standalone FAQ responses for 24h (only if first turn & no personal ID used)
        if len(history_list) == 2 and not req.id_login:
            cache.setex(
                faq_key,
                86400,
                json.dumps({"reply": reply, "custom": custom_payload, "sources": sources_used})
            )

    except APIError as e:
        conn.close()
        if e.code == 429:
            return {
                "reply": "Maaf, sistem asisten virtual sedang menerima banyak pertanyaan sekaligus. Silakan coba kirim ulang pertanyaan Anda dalam beberapa detik.",
                "custom": {},
                "sources": [],
                "latency_ms": int((time.time() - start_time) * 1000)
            }
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

    latency = int((time.time() - start_time) * 1000)
    conn.execute(
        "INSERT INTO chat_logs (session_id, user_message, bot_response, sources, latency_ms) VALUES (?, ?, ?, ?, ?)",
        (req.session_id, req.message, reply, ", ".join(sources_used), latency)
    )
    conn.commit()
    conn.close()

    return {
        "reply": reply,
        "custom": custom_payload,
        "sources": sources_used,
        "cached": False,
        "latency_ms": latency
    }