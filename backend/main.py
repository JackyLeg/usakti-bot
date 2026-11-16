import os
import sqlite3
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from google.genai import types
from qdrant_client import QdrantClient
import redis

DB_PATH = "/app/data/chatbot.db"

def init_db():
    os.makedirs("/app/data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            user_message TEXT,
            bot_response TEXT,
            latency_ms INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        VALUES ('system_prompt', 'You are the official virtual assistant for our university. Answer clearly, politely, and concisely in the user''s language (Indonesian or English).')
    """)
    conn.commit()
    conn.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Usakti AI Chatbot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize clients
ai_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://qdrant:6333"))
cache = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)

class ChatRequest(BaseModel):
    session_id: str = "default"
    message: str

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "qdrant_collections": len(qdrant.get_collections().collections),
        "redis_ping": cache.ping()
    }

@app.post("/api/chat")
def chat_endpoint(req: ChatRequest):
    start_time = time.time()
    
    # Fetch system prompt from SQLite (editable by future admins)
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT value FROM settings WHERE key = 'system_prompt'").fetchone()
    system_prompt = row[0] if row else "You are a helpful trisakti university assistant, UsaktiBot."

    try:
        response = ai_client.models.generate_content(
            model="gemini-3.8-flash",
            contents=req.message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.3,
            )
        )
        reply = response.text
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

    latency = int((time.time() - start_time) * 1000)

    # Log interaction to SQLite
    conn.execute(
        "INSERT INTO chat_logs (session_id, user_message, bot_response, latency_ms) VALUES (?, ?, ?, ?)",
        (req.session_id, req.message, reply, latency)
    )
    conn.commit()
    conn.close()

    return {"reply": reply, "latency_ms": latency}