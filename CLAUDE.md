# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Personal RAG — a local-first Retrieval-Augmented Generation system with Chinese language optimizations. Upload documents (PDF, DOCX, TXT, images, video/audio), index them into a vector store, then ask questions with source citations tracked inline.

## Development commands

### Backend (Python/FastAPI)

```bash
cd backend
pip install -r requirements.txt        # Install dependencies
python run.py                           # Start at http://localhost:8000
python run.py --reload                  # Development mode with hot-reload
python run.py --port 8080               # Custom port
```

API docs at `http://localhost:8000/docs` (Swagger).

### Frontend (React/TypeScript)

```bash
cd frontend
npm install                             # Install dependencies
npm run dev                             # Dev server at http://localhost:5173
npm run build                           # Production build (tsc + vite)
npm run lint                            # Lint with oxlint
```

Vite proxies `/api`, `/files`, and `/health` to `http://127.0.0.1:8000`.

### Tests

No test suite is set up yet. Tests are listed as technical debt in the README (pytest for backend, Vitest + Testing Library for frontend, Playwright for E2E).

## Architecture

### Backend layers (`backend/app/`)

```
api/          → REST route handlers (thin — they call services)
schemas/      → Pydantic request/response models
services/     → Core business logic (parser, chunker, embedder, retriever, generator, indexer, citation)
providers/    → LLM/Embedding abstraction (Ollama, OpenAI, Anthropic)
db/           → SQLAlchemy ORM models + FAISS vector store wrapper
```

**RAG pipeline** (orchestrated by `services/indexer.py` — `IndexingPipeline`):
1. **Parse** — `services/parser/registry.py` maps file extension → parser. Parsers implement `BaseParser.parse(path) → ParsedDocument`. Optional parsers (image OCR via Tesseract/PaddleOCR, media transcription via faster-whisper) register only if their dependencies import successfully in `main.py` lifespan.
2. **Chunk** — `services/chunker.py` does recursive character splitting with Chinese-aware delimiters: `\n\n → \n → 。→ ！→ ？→ . → ! → ? → space`
3. **Embed** — `services/embedder.py` batches texts through the active embedding provider (default Ollama `nomic-embed-text`, 768-dim)
4. **Store** — `db/vector_store.py` (`VectorStore`) uses FAISS `IndexIDMap(IndexFlatIP)` with L2-normalized vectors (inner product = cosine similarity), persisted to `data/faiss/`. Chunk metadata stored in SQLite `chunks` table.

**Query flow** (`api/chat.py` via SSE):
1. Embed question → FAISS search (top_k=8) → fetch metadata from SQLite → take top 4
2. Build RAG prompt with `[Source N]` blocks → stream via LLM provider
3. `services/citation.py` (`CitationParser`) detects `[N]` markers in token stream
4. SSE events: `token` (text fragment), `citation` (reference marker found), `done` (final citations list), `error`

**Provider abstraction** (`providers/base.py`):
- `LLMProvider` interface: `chat()` and `chat_stream()` (async generator)
- `EmbeddingProvider` interface: `embed(texts) → list[list[float]]`
- Implementations: `providers/ollama.py`, `providers/openai_provider.py`, `providers/anthropic_provider.py`
- Selected at runtime via settings (`llm_provider`, `embedding_provider`) or database settings table

**Database** (5 tables in SQLite, `data/app.db`):
- `documents` — file metadata, status (`uploaded → parsing → indexed | error`), hash dedup
- `chunks` — text segments with page/timestamp metadata, FK to documents
- `conversations` — chat sessions with model/provider tracking
- `messages` — user/assistant messages with citation JSON
- `settings` — key-value config store (overrides `.env` defaults)

**Key singletons** (imported, not DI-injected): `vector_store`, `embedding_service`, `indexing_pipeline`, `parser_registry`. Database sessions use FastAPI `Depends(get_db)`.

### Frontend layers (`frontend/src/`)

```
api/         → Axios client + SSE streaming (fetch ReadableStream)
store/       → Zustand stores: chatStore, documentStore, sidebarStore, settingsStore
components/  → React components organized by domain: chat/, documents/, citations/, settings/, layout/
```

**State management**: 4 independent Zustand stores — no single global store. The `chatStore` manages streaming state and citation tracking. SSE consumption uses `fetch()` with a `ReadableStream` reader, parsing `text/event-stream` line-by-line.

**Layout**: CSS Grid three-column layout (`AppShell.tsx`). Left sidebar (uploads + document list), center (chat), right sidebar (citation panel — slides in on demand).

## Key patterns

- **Parser registry**: New file types → add a parser class extending `BaseParser`, register in `main.py` lifespan. The registry maps file extensions to parser instances.
- **Configuration**: `pydantic-settings` loads from `backend/.env`, overridden by `settings` DB table values at request time. `backend/app/config.py` defines defaults.
- **SSE streaming protocol**: The chat endpoint uses `sse-starlette`. Four event types: `token`, `citation`, `done`, `error`. The frontend's `chat.ts` API client wraps `fetch` + `ReadableStream`.
- **FAISS vector store**: `VectorStore` is a drop-in replacement for ChromaDB with the same query return shape (`{"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}`). Text/metadata are NOT stored in FAISS — they live in SQLite, filled in by the retriever.
- **File deduplication**: SHA-256 hash checked before indexing. If a file with the same hash already exists and is `indexed`, the upload returns the existing document ID.

## Practical notes

- **No `.env` file by default**: The backend runs on defaults (Ollama at `localhost:11434`, `qwen2.5:14b`). Copy `backend/.env.example` to `backend/.env` to customize — see `backend/app/config.py` for all settings.
- **Vector store history**: The system originally used ChromaDB but switched to FAISS. The config field `chroma_dir` still carries that legacy name — it actually stores FAISS indexes at `data/faiss/`. The `data/chroma/` directory (with `.gitkeep`) is a stale artifact.
- **Runtime data**: `backend/data/` contains `uploads/`, `faiss/`, `transcripts/`, and `app.db` (all gitignored). Created automatically on first startup.
- **Optional dependencies**: Tesseract OCR and PaddleOCR require separate system-level installs. faster-whisper needs `ffmpeg` on PATH. The app starts fine without them — image and media parsers simply won't register.
- **`scripts/` directory** listed in the README does not exist on disk.
- **Claude Code settings** at `.claude/settings.local.json` — project-specific harness configuration.
