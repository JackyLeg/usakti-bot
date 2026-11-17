# Usakti Bot

Usakti Bot is a university chatbot platform for Universitas Trisakti built with FastAPI, Google Gemini, Qdrant, Redis, and SQLite. It helps students, lecturers, and academic advisors ask questions about campus services and procedures using a retrieval-augmented generation (RAG) workflow backed by official university knowledge documents.

## Overview

This project provides:

- A chatbot API for academic and student service inquiries
- Role-aware responses for guest, mahasiswa, dosen, and dosenwali users
- Vector-based retrieval over campus documents with Qdrant
- Admin management for knowledge base uploads and prompt updates
- Embedded chat widget support for websites and mobile webviews
- Chat logs, document metadata, and system prompt management via SQLite

## Key Features

- RAG-based answer generation using Google Gemini with document context
- Local semantic search with Qdrant and FastEmbed
- Role-specific menu system for university services
- Submenu flow for common academic tasks such as KRS, KHS, pembayaran, cuti, and wisuda
- Admin web dashboard at /admin for:
  - uploading PDF/TXT/MD documents
  - indexing them into the vector database
  - managing system prompt rules
  - reviewing recent chat logs and exporting CSV reports
- Embeddable chat widget and web chat view for integration into university websites/apps
- Redis-based cache for quick FAQ responses and chat history

## Architecture

The project is organized around a dockerized microservice stack:

- backend: FastAPI application and chat logic
- qdrant: vector database for document retrieval
- redis: cache and short-lived chat/session data
- data: SQLite database and uploaded files

Main backend components:

- backend/main.py: API, chat endpoint, admin endpoints, widget routes
- backend/rag.py: document ingestion and retrieval logic
- backend/tools.py: menu definitions and UI-trigger helpers
- backend/admin.html: admin dashboard frontend
- backend/chat.html: embedded web chat interface

## Project Structure

```text
usakti-bot/
├── .env.example
├── docker-compose.yml
├── extract_rasa.py
├── HANDOVER.md
├── backend/
│   ├── Dockerfile
│   ├── admin.html
│   ├── chat.html
│   ├── main.py
│   ├── old-main.py
│   ├── old-rag.py
│   ├── rag.py
│   ├── requirements.txt
│   └── tools.py
├── data/
├── qdrant_storage/
└── uploads/
```

## Tech Stack

- Python 3.x
- FastAPI
- Uvicorn
- Google GenAI SDK
- Qdrant Client
- Redis
- SQLite
- FastEmbed
- Docker / Docker Compose

## Requirements

Before running the project, make sure you have:

- Docker and Docker Compose installed
- A Google Gemini API key
- A valid environment configuration in a .env file
- Qdrant and Redis available through the Docker Compose setup

## Configuration

Copy the sample environment file:

```bash
cp .env.example .env
```

Then update the values in .env, especially:

```env
GEMINI_API_KEY=your_gemini_api_key_here
ADMIN_PASSWORD=your_admin_password_here
QDRANT_URL=http://qdrant:6333
REDIS_URL=redis://redis:6379/0
CHAT_AUTH_SECRET=your_chat_auth_secrets_here
ALLOW_UNVERIFIED_ROLES=false
FASTEMBED_CACHE_PATH=/app/fastembed_cache
```

## Running the Project

From the project root:

```bash
docker compose up -d --build
```

This starts:

- backend service on port 8000
- qdrant service
- redis service

Check application health:

```bash
curl http://localhost:8000/health
```

## Admin Dashboard

Open the admin panel in a browser:

```text
http://localhost:8000/admin
```

Use the ADMIN_PASSWORD from your .env file to log in. From there you can:

- upload campus documents
- select faculty and study program metadata
- index the documents into the vector store
- edit the bot system prompt
- inspect chat logs
- export interaction logs to CSV

## Chat Endpoints

Main API endpoints include:

- GET /health — health check for backend, Qdrant, and Redis
- POST /api/chat — main chatbot endpoint
- GET /admin — admin dashboard HTML
- POST /api/admin/upload — document upload for indexing
- GET /api/admin/documents — list indexed documents
- GET /api/admin/settings — bot settings
- POST /api/admin/settings — update bot settings
- GET /api/admin/logs — recent chat logs
- GET /api/admin/logs/csv — export CSV logs
- GET /chat — embedded chat page
- GET /widget.js — embeddable chat widget script
- POST /webhooks/rest/webhook — Rasa-compatible webhook endpoint

Example request to the main chat API:

```json
{
  "session_id": "user-session-001",
  "message": "Bagaimana prosedur KRS?",
  "role": "mahasiswa",
  "major": "INFORMATIKA"
}
```

## Usage Notes

The chatbot supports different user roles and service flows:

- guest: general information and registration-related assistance
- mahasiswa: KRS, KHS, pembayaran, cuti, transkrip, wisuda, and more
- dosen: academic-related support for teaching and faculty workflows
- dosenwali: additional advising and approval workflows

It also exposes a standard service-menu system using menu and submenu triggers, so the frontend can show structured options in a consistent UI.

## Data and Storage

- SQLite database: data/chatbot.db
- Uploaded document files: data/uploads
- Vector storage: qdrant_storage/
- Redis cache: in-memory service from Docker Compose

## Operational Commands

Start services:

```bash
docker compose up -d --build
```

View logs:

```bash
docker compose logs -f backend
```

Stop services:

```bash
docker compose down
```

## Notes

This project is designed for a university environment and is strongly tied to Universitas Trisakti-specific workflows, terminology, and academic service processes. The knowledge base should be updated regularly with the latest policies, procedures, and supporting documents.

The repository also contains migration-related support for Rasa data extraction via extract_rasa.py, indicating the system was previously or partially integrated with Rasa-based knowledge and conversation flows.

## License

License information is not specified in the project files available in this repository.
