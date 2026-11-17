import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File, Header, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from pydantic import BaseModel, Field
import httpx
from google import genai
from google.genai import types
from google.genai.errors import APIError
from qdrant_client import QdrantClient
import redis
import re
from rag import ensure_collection, ingest_document, delete_document, retrieve_context
from tools import STUDENT_TOOLS, LAST_TRIGGERED_UI, ROLE_MENUS, SUBMENU_MAP
import base64
import hmac
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "/app/data/chatbot.db"
UPLOAD_DIR = "/app/data/uploads"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

AUTH_SECRET = os.getenv("CHAT_AUTH_SECRET")
ALLOW_UNVERIFIED = os.getenv("ALLOW_UNVERIFIED_ROLES")

# Format: "menu_name_lower": ("submenu_key", "Display Name", {"allowed_roles"})
EXACT_MENU_TRIGGERS = {
    # Mahasiswa-only
    "kartu rencana studi (krs)": ("krs", "Kartu Rencana Studi (KRS)", {"mahasiswa"}),
    "krs": ("krs", "Kartu Rencana Studi (KRS)", {"mahasiswa"}),
    "kartu hasil studi (khs)": ("khs", "Kartu Hasil Studi (KHS)", {"mahasiswa"}),
    "khs": ("khs", "Kartu Hasil Studi (KHS)", {"mahasiswa"}),
    "pembayaran": ("pembayaran", "Pembayaran", {"mahasiswa"}),
    "cuti akademik": ("cuti", "Cuti Akademik", {"mahasiswa"}),
    "cuti": ("cuti", "Cuti Akademik", {"mahasiswa"}),
    "transkrip nilai": ("transkrip", "Transkrip Nilai", {"mahasiswa"}),
    "kartu peserta ujian": ("kartu_ujian", "Kartu Peserta Ujian", {"mahasiswa"}),
    "tugas akhir": ("tugas_akhir", "Tugas Akhir", {"mahasiswa"}),
    "wisuda": ("wisuda", "Wisuda", {"mahasiswa"}),
    "skpi": ("skpi", "SKPI", {"mahasiswa"}),
    "konseling": ("konseling", "Konseling", {"mahasiswa"}),
    "pertukaran mahasiswa": ("pertukaran", "Pertukaran Mahasiswa", {"mahasiswa"}),
    "fast track": ("fast_track", "Fast Track", {"mahasiswa"}),
    "profil": ("profil", "Profil", {"mahasiswa"}),

    # Dosen & Dosen Wali
    "jadwal mengajar": ("jadwal_mengajar", "Jadwal Mengajar", {"dosen", "dosenwali"}),
    "input nilai": ("input_nilai", "Input Nilai", {"dosen", "dosenwali"}),
    "bimbingan tugas akhir": ("bimbingan_ta", "Bimbingan Tugas Akhir", {"dosen", "dosenwali"}),
    "penelitian & pengabdian": ("penelitian", "Penelitian & Pengabdian", {"dosen", "dosenwali"}),
    "profil dosen": ("profil_dosen", "Profil Dosen", {"dosen", "dosenwali"}),

    # Dosen Wali only
    "approval krs mahasiswa": ("approval_krs", "Approval KRS Mahasiswa", {"dosenwali"}),
    "monitoring khs mahasiswa": ("monitoring_khs", "Monitoring KHS Mahasiswa", {"dosenwali"}),
    "persetujuan cuti mahasiswa": ("persetujuan_cuti", "Persetujuan Cuti Mahasiswa", {"dosenwali"}),
    "perwalian akademik": ("perwalian", "Perwalian Akademik", {"dosenwali"}),
}

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

def verify_user_token(token: str) -> dict | None:
    try:
        payload_b64, sig = token.split(".", 1)
        expected = hmac.new(AUTH_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None

class ChatRequest(BaseModel):
    session_id: str = "default"
    message: str = Field(..., min_length=1, max_length=800)
    token: str | None = None
    id_login: str | None = None
    role: str = "guest"

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
    faculty: str = Form(default="UMUM"),
    major: str = Form(default="UMUM"),
    x_admin_password: str | None = Header(default=None)
):
    verify_admin(x_admin_password)
    if not file.filename.lower().endswith((".pdf", ".txt", ".md")):
        raise HTTPException(status_code=400, detail="Only PDF, TXT, and MD files are supported.")

    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    delete_document(file.filename, qdrant)
    chunks_added = ingest_document(
        file_path, file.filename, ai_client, qdrant,
        faculty=faculty, major=major
    )

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
def chat_endpoint(req: ChatRequest, request: Request):
    start_time = time.time()

    # 1. Resolve verified identity & role FIRST
    verified = verify_user_token(req.token) if req.token else None
    if verified:
        id_login = verified.get("id_login")
        user_role = verified.get("role", "guest").lower().strip()
        user_major = verified.get("major", "UMUM").upper().strip()
    elif ALLOW_UNVERIFIED and req.role.lower() in ROLE_MENUS:
        id_login = req.id_login
        user_role = req.role.lower().strip()
        user_major = getattr(req, "major", "UMUM").upper().strip()
    else:
        id_login = None
        user_role = "guest"
        user_major = "UMUM"

    # 2. Now check deterministic menus using the verified user_role
    clean_msg = req.message.strip().lower()

    # 2A. Instant deterministic Main Menu response
    if clean_msg in ("menu apa saja yang tersedia?", "menu apa aja yg tersedia?", "daftar menu", "menu"):
        buttons = ROLE_MENUS.get(user_role, ROLE_MENUS["guest"])
        return {
            "reply": "Silakan pilih layanan yang ingin Anda akses melalui tombol di bawah ini:",
            "custom": {"buttons": buttons},
            "resolved_role": user_role,
            "sources": [],
            "latency_ms": 1
        }

    # 2B. Instant deterministic 4 Sub-Menus (Prosedur, Persyaratan, Transaksi, Hasil)
    if clean_msg in EXACT_MENU_TRIGGERS:
        cat_key, display_name, allowed_roles = EXACT_MENU_TRIGGERS[clean_msg]
        if user_role not in allowed_roles:
            allowed_menus = ROLE_MENUS.get(user_role, ROLE_MENUS["guest"])
            return {
                "reply": f"Maaf, menu {display_name} tidak tersedia untuk role {user_role.upper()}. Silakan pilih menu yang tersedia untuk Anda:",
                "custom": {"buttons": allowed_menus},
                "resolved_role": user_role,
                "sources": [],
                "latency_ms": 1
            }
        buttons = SUBMENU_MAP.get(
            cat_key,
            [f"Prosedur {display_name}", f"Persyaratan {display_name}", f"Transaksi {display_name}", f"Hasil {display_name}"]
        )
        return {
            "reply": f"Silakan pilih salah satu sub-menu {display_name} di bawah ini:",
            "custom": {"buttons": buttons},
            "resolved_role": user_role,
            "sources": [],
            "latency_ms": 1
        }
    faq_key = make_faq_cache_key(user_role, req.message)

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
        matches = retrieve_context(
            f"[{user_role}] {req.message}",
            ai_client,
            qdrant,
            major=user_major,
            top_k=5
        )
        if matches:
            context_block = "\n\n".join([f"[Sumber: {m['source']}]\n{m['text']}" for m in matches])
            sources_used = list(dict.fromkeys([m["source"] for m in matches]))
        else:
            context_block = "(Tidak ada dokumen panduan yang cocok.)"
            sources_used = []

        # Inside chat_endpoint in backend/main.py:
        LAST_TRIGGERED_UI.pop(req.session_id, None)

        augmented_prompt = (
            f"{base_prompt}\n\n"
            f"=== INFO PENGGUNA ===\n"
            f"Session ID: {req.session_id} | Role: {user_role.upper()} | IdLogin: {id_login or 'Guest'}\n\n"
f"=== ATURAN NAVIGASI MENU STANDAR USAKTI ===\n"
f"1. Jika pengguna bertanya 'menu apa saja yang tersedia' atau meminta daftar layanan, WAJIB panggil `show_menu_buttons(session_id='{req.session_id}', category='main', role='{user_role}')`.\n"
            f"2. Jika pengguna memilih/menyebut topik layanan secara umum (misal hanya mengetik 'KRS', 'Kartu Rencana Studi (KRS)', 'KHS', 'Pembayaran', 'Cuti') TANPA menyebut prosedur/syarat/transaksi/hasil, WAJIB panggil `show_menu_buttons(session_id='{req.session_id}', category=...)` agar muncul 4 sub-menu standar (Prosedur, Persyaratan, Transaksi, Hasil).\n"
            f"3. Jika pengguna memilih/bertanya 'Prosedur' atau 'Persyaratan', jelaskan dengan ringkas dan jelas berdasarkan dokumen kampus / API SISMOB.\n"
            f"4. Jika pengguna memilih/bertanya 'Transaksi' atau 'Hasil' (misal 'Hasil KHS', 'Transaksi KRS'), WAJIB panggil `trigger_ui_context(session_id='{req.session_id}', menu_context=...)` dan beri 1 kalimat pengantar singkat.\n\n"
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
        reply = re.sub(r'\*\*(.*?)\*\*', r'\1', reply)
        reply = re.sub(r'\*(.*?)\*', r'\1', reply)
        reply = reply.replace('`', '').replace('### ', '').replace('## ', '')
        custom_payload = LAST_TRIGGERED_UI.pop(req.session_id, {})
        # custom_payload = {"context": triggered_ctx} if triggered_ctx else {}

        # Save conversation history
        history_list.append({"role": "user", "text": req.message})
        history_list.append({"role": "model", "text": reply})
        cache.setex(f"chat_hist:{req.session_id}", 3600, json.dumps(history_list[-20:]))

        # Cache standalone FAQ responses for 24h (only if first turn & no personal ID used)
        if len(history_list) == 2 and not req.id_login and not custom_payload:
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

# --- RASA REST COMPATIBILITY ADAPTER ---
class RasaWebhookRequest(BaseModel):
    sender: str = "default"
    message: str
    metadata: dict | None = None

@app.post("/webhooks/rest/webhook")
def rasa_compatible_webhook(req: RasaWebhookRequest, request: Request):
    meta = req.metadata or {}
    internal_req = ChatRequest(
        session_id=req.sender,
        message=req.message,
        token=meta.get("token"),
        id_login=meta.get("id_login") or req.sender,
        role=meta.get("role", "mahasiswa")
    )
    res = chat_endpoint(internal_req, request)

    # Format output identically to Rasa Pro REST channel
    rasa_messages = []
    msg_obj = {"recipient_id": req.sender, "text": res["reply"]}

    custom = res.get("custom") or {}
    if custom.get("buttons"):
        msg_obj["buttons"] = [{"title": b, "payload": b} for b in custom["buttons"]]

    rasa_messages.append(msg_obj)

    if custom.get("context"):
        rasa_messages.append({
            "recipient_id": req.sender,
            "custom": {"context": custom["context"]}
        })

    return rasa_messages
#---------------------------------

@app.get("/chat", response_class=HTMLResponse)
def chat_ui():
    with open("/app/chat.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/widget.js")
def embed_widget(request: Request):
    base_url = str(request.base_url).rstrip("/")
    js_code = f"""
    (function() {{
      const btn = document.createElement('div');
      btn.innerHTML = '💬';
      Object.assign(btn.style, {{
        position: 'fixed', bottom: '20px', right: '20px', width: '56px', height: '56px',
        borderRadius: '50%', background: '#1e3a8a', color: '#fff', fontSize: '26px',
        display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
        boxShadow: '0 4px 12px rgba(0,0,0,0.25)', zIndex: 99999
      }});

      const frame = document.createElement('iframe');
      frame.src = '{base_url}/chat';
      Object.assign(frame.style, {{
        position: 'fixed', bottom: '88px', right: '20px', width: '370px', height: '540px',
        maxWidth: '92vw', maxHeight: '75vh', border: 'none', borderRadius: '14px',
        boxShadow: '0 8px 24px rgba(0,0,0,0.2)', display: 'none', zIndex: 99999
      }});

      btn.onclick = () => {{
        frame.style.display = frame.style.display === 'none' ? 'block' : 'none';
      }};

      document.body.appendChild(btn);
      document.body.appendChild(frame);
    }})();
    """
    return Response(content=js_code, media_type="application/javascript")