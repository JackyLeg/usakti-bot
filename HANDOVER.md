# Universitas Trisakti AI Chatbot — Handover & Operations Guide

## 1. Architecture Overview
- **Backend API (`backend/main.py`):** FastAPI + Google GenAI SDK (`gemini-3.5-flash-lite` & `gemini-embedding-001`).
- **Vector Database (`qdrant`):** Stores embedded campus policy documents (`usakti_kb` collection).
- **Cache & Session Memory (`redis`):** Stores multi-turn chat history (1h TTL), FAQ cache (24h TTL), and rate limits.
- **Database (`data/chatbot.db`):** SQLite database storing chat logs, uploaded document metadata, and editable system prompts.

## 2. Admin Management (No Coding Required)
1. Open `http://<SERVER_IP>:8000/admin` in a web browser.
2. Enter `ADMIN_PASSWORD` (configured in `.env`).
3. **Update Knowledge Base:** Upload new `.pdf`, `.txt`, or `.md` files via **Upload & Index**, or click **Hapus** to remove outdated documents.
4. **Update Bot Rules:** Edit the text inside **System Prompt & Aturan Bot** and click **Simpan Prompt**.
5. **Export Reports:** Click **Download CSV** under **Riwayat Interaksi Terbaru** to export chat logs to Excel.

## 3. Frontend Integration
- **Website Embed:** Add `<script src="http://<SERVER_IP>:8000/widget.js"></script>` before `</body>` on any university web page.
- **Mobile App WebView:** Load `http://<SERVER_IP>:8000/chat?id_login=<NIM_OR_NIK>&role=<mahasiswa|dosen|dosenwali>`.
  - When a user clicks a service action button (`Hasil` / `Transaksi`), the WebView dispatches `{"type": "USAKTI_BOT_ACTION", "context": "<menu_name>"}` to `ReactNativeWebView.postMessage`, `window.Android.onBotAction`, or `window.webkit.messageHandlers.botAction`.

## 4. Server Operations & Backups
- **Start / Restart:** `docker compose up -d --build`
- **View Logs:** `docker compose logs -f backend`
- **Stop:** `docker compose down`
- **Backup:** Periodically back up the `./data/` folder (SQLite DB + uploaded files) and `./qdrant_storage/` folder.