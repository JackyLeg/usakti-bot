# Universitas Trisakti AI Chatbot — Handover & Operations Guide

## 1. Architecture Overview
- **Backend API (`backend/main.py` & `backend/rag.py`):** FastAPI + Google GenAI SDK (`gemini-3.5-flash-lite` for chat & tool calling) paired with local `fastembed` (`sentence-transformers/paraphrase-multilingual-mpnet-base-v2`, 768 dimensions) for zero-quota Indonesian/multilingual embeddings.
- **Vector Database (`qdrant`):** Stores embedded campus policy and curriculum documents (`usakti_kb` collection) with `faculty` and `major` metadata filtering.
- **Cache & Session Memory (`redis`):** Stores multi-turn chat history (1h TTL), role- and major-scoped FAQ cache (24h TTL), and rate limits.
- **Database (`data/chatbot.db`):** SQLite database storing chat logs, uploaded document metadata (`filename`, `chunk_count`, `faculty`, `major`, `notes`), and editable system prompts.

## 2. Admin Management (No Coding Required)
1. Open `http://<SERVER_IP>:8000/admin` in a web browser.
2. Enter `ADMIN_PASSWORD` (configured in `.env`) and press **Enter** or click **Masuk**.
3. **Update Knowledge Base:**
   - Choose a `.pdf`, `.txt`, or `.md` file.
   - Select the **Fakultas** acronym (`UMUM`, `FH`, `FEB`, `FK`, `FKG`, `FTSP`, `FTI`, `FTKE`, `FALTL`, or `FSRD`), choose the **Program Studi** (default `UMUM`), and optionally fill in **Catatan Tambahan**.
   - Click **Upload & Index** (or press **Enter**). Indexing runs in the background and updates the table automatically once finished.
   - Use the search bar to filter documents by filename, faculty, major, or notes, click column headers to sort, or click **Hapus** to remove outdated documents.
4. **Update Bot Rules:** Edit the text inside **System Prompt & Aturan Bot** and click **Simpan Prompt**.
5. **Export Reports:** Click **Download CSV** under **Riwayat Interaksi Terbaru** to export chat logs to Excel.

## 3. Frontend Integration
- **Website Embed:** Add `<script src="http://<SERVER_IP>:8000/widget.js"></script>` before `</body>` on any university web page.
- **Mobile App WebView:** Load `http://<SERVER_IP>:8000/chat?id_login=<NIM_OR_NIK>&role=<mahasiswa|dosen|dosenwali>&major=<PROGRAM_STUDI>` (for example, `&major=INFORMATIKA`).
  - When a user clicks a service action button (`Hasil` / `Transaksi`), the WebView dispatches `{"type": "USAKTI_BOT_ACTION", "context": "<menu_name>"}` to `ReactNativeWebView.postMessage`, `window.Android.onBotAction`, or `window.webkit.messageHandlers.botAction`.

## 4. Server Operations & Backups
- **Start / Restart:** `docker compose up -d --build`
- **View Logs:** `docker compose logs -f backend`
- **Stop:** `docker compose down`
- **Backup:** Periodically back up the `./data/` folder (SQLite DB + uploaded files), the `./qdrant_storage/` folder, and the `fastembed_cache` Docker volume.