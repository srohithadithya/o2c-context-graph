# O2C Context Graph

An interactive, AI-powered Order-to-Cash data explorer. Ingest SAP-style JSONL extracts into a local SQLite database, visualise entity relationships on a force-directed graph, and ask natural-language questions via **Dodge AI** — a Gemini-backed assistant that writes SQL, runs it, and returns human-readable answers with graph highlights.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Browser (React 19 + Vite + Tailwind CSS)                    │
│  ┌────────────────────────┐  ┌─────────────────────────────┐ │
│  │  Force-directed graph  │  │  Dodge AI chat panel         │ │
│  │  (react-force-graph-2d)│  │  NL → SQL → answer + glow   │ │
│  └────────┬───────────────┘  └──────────┬──────────────────┘ │
│           │ GET /api/graph/data         │ POST /api/chat     │
└───────────┼─────────────────────────────┼────────────────────┘
            ▼                             ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI  (api/index.py — single Vercel serverless handler)  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │ sqlite_graph  │  │ graph_engine │  │ chat_service       │ │
│  │ (SQL payload) │  │ (NetworkX)   │  │ (Gemini SQL + NL)  │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬─────────────┘ │
│         │                 │                  │               │
│         ▼                 ▼                  ▼               │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────┐  │
│  │ o2c_context  │   │ data/raw/*   │   │ Google Gemini    │  │
│  │   .db        │   │ (19 JSONL    │   │ (gemini-2.0-     │  │
│  │ (SQLite)     │   │  folders)    │   │  flash)          │  │
│  └─────────────┘   └──────────────┘   └──────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer     | Technology                                                       |
| --------- | ---------------------------------------------------------------- |
| Frontend  | React 19, TypeScript, Vite 6, Tailwind CSS 3, react-force-graph-2d |
| Backend   | FastAPI, Python 3.9+, Pydantic                                  |
| Database  | SQLite (file-local, read-only at runtime)                        |
| AI        | Google Gemini (`google-generativeai`, default model `gemini-2.0-flash`) |
| Graph     | NetworkX (server-side analysis), react-force-graph-2d (client)   |
| Deploy    | Vercel Serverless Functions                                      |

---

## Data Model — 19 SAP O2C Entity Tables

The raw data lives as JSONL files under `data/raw/`, one folder per entity. The ingestion pipeline flattens, deduplicates, and writes them into `o2c_context.db`.

```
Sales Domain          Logistics              Finance / AR           Master Data
─────────────         ──────────             ──────────────         ───────────
sales_order_headers   outbound_delivery_     billing_document_      products
sales_order_items       headers                headers              product_descriptions
sales_order_          outbound_delivery_     billing_document_      product_plants
  schedule_lines        items                  items                product_storage_
                                             billing_document_        locations
                                               cancellations        plants
                                             journal_entry_items_   business_partners
                                               accounts_receivable  business_partner_
                                             payments_accounts_       addresses
                                               receivable           customer_company_
                                                                      assignments
                                                                    customer_sales_area_
                                                                      assignments
```

All join rules are codified in `api/graph_mapping.py` and injected into every Gemini prompt so the AI avoids Cartesian products.

---

## Project Structure

```
o2c-context-graph/
├── api/                         # FastAPI backend (Vercel serverless)
│   ├── index.py                 #   App entry — all /api/* routes
│   ├── chat_service.py          #   Dodge AI: NL → SQL → humanized answer
│   ├── dodge_system.py          #   System persona for Gemini
│   ├── graph_engine.py          #   NetworkX graph build & serialization
│   ├── graph_mapping.py         #   19-table join catalog (predicates)
│   ├── ingest.py                #   JSONL streaming for NetworkX
│   ├── ingest_sqlite.py         #   JSONL → SQLite ingestion pipeline
│   ├── sqlite_graph.py          #   SQLite helpers + force-layout payload
│   ├── bootstrap_env.py         #   .env loader for local dev
│   └── o2c_schema_knowledge_base.md  # Schema reference
├── src/                         # React frontend
│   ├── App.tsx                  #   Main app — graph + Dodge AI panel
│   ├── main.tsx                 #   React entry point
│   └── index.css                #   Tailwind directives
├── data/raw/                    # 19 JSONL entity folders (gitignored DB)
├── scripts/
│   └── diagnose_o2c_db.py       # Data health report (row counts, fill rates)
├── tests/
│   └── verify_flow.py           # End-to-end Dodge AI integration test
├── vercel.json                  # Vercel deployment config
├── vite.config.ts               # Vite + API proxy config
├── tailwind.config.js           # Tailwind theme (IBM Plex fonts)
├── requirements.txt             # Python dependencies
├── package.json                 # Node dependencies
└── ping_api.py                  # Quick Gemini API connectivity check
```

---

## Getting Started

### Prerequisites

- **Node.js** ≥ 20 LTS
- **Python** ≥ 3.9
- A **Google Gemini API key** (for the chat feature)

### 1. Clone & install

```bash
git clone https://github.com/srohithadithya/o2c-context-graph.git
cd o2c-context-graph

# Node
npm install

# Python
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and set:
#   GEMINI_API_KEY=your_key_here
```

### 3. Ingest data into SQLite

Place your JSONL files under `data/raw/<entity_folder>/` (19 folders), then run:

```bash
python -m api.ingest_sqlite
```

This creates `o2c_context.db` at the project root.

### 4. Run the app locally

Start the backend:

```bash
uvicorn api.index:app --reload --port 8000
```

Start the frontend (in a separate terminal):

```bash
npm run dev
```

Open **http://localhost:5173**. The Vite dev server proxies `/api/*` requests to the FastAPI backend on port 8000.

---

## API Endpoints

| Method | Path                   | Description                                        |
| ------ | ---------------------- | -------------------------------------------------- |
| GET    | `/api/health`          | Service health check                               |
| GET    | `/api/graph/data`      | Force-layout nodes & links from SQLite (for the UI) |
| GET    | `/api/graph`           | Full NetworkX graph as JSON (JSONL or SQLite)       |
| GET    | `/api/graph/summary`   | Graph stats (node/edge counts, density, top nodes)  |
| GET    | `/api/graph/join-rules`| Canonical O2C join predicates                      |
| GET    | `/api/ingest/stats`    | Folder/file/line counts from `data/raw`            |
| POST   | `/api/ingest/run`      | Trigger JSONL ingest and return graph summary       |
| POST   | `/api/chat`            | Send a natural-language question to Dodge AI        |

### Chat request

```json
{ "message": "How many sales orders were created in March 2025?" }
```

### Chat response

```json
{
  "response": "There were 42 sales orders created in March 2025.",
  "sql_query": "SELECT COUNT(*) ...",
  "nodes_to_highlight": ["sales_order_headers:1234"]
}
```

---

## Scripts & Utilities

| Script                         | Purpose                                              |
| ------------------------------ | ---------------------------------------------------- |
| `python -m api.ingest_sqlite`  | Ingest JSONL → SQLite (`o2c_context.db`)             |
| `python scripts/diagnose_o2c_db.py` | Data health: row counts, join-key fill rates, orphan checks |
| `python tests/verify_flow.py`  | End-to-end test: SQLite → Gemini SQL → answer        |
| `python ping_api.py`           | Quick Gemini API key connectivity test               |

---

## Deployment (Vercel)

The project is pre-configured for Vercel:

- `vercel.json` routes all `/api/*` traffic to the FastAPI handler.
- Static assets are served from the Vite `dist/` build.
- `o2c_context.db` is bundled into the serverless function via `includeFiles`.
- Set `GEMINI_API_KEY` in Vercel → Project → Settings → Environment Variables.

```bash
npm run build        # Build the frontend
vercel --prod        # Deploy
```

---

## Environment Variables

| Variable        | Required | Default               | Description                        |
| --------------- | -------- | --------------------- | ---------------------------------- |
| `GEMINI_API_KEY` | Yes      | —                     | Google Gemini API key              |
| `GOOGLE_API_KEY` | No       | —                     | Fallback alias for Gemini key      |
| `GEMINI_MODEL`   | No       | `gemini-2.0-flash`    | Gemini model ID                    |
| `O2C_DB_PATH`    | No       | `./o2c_context.db`    | Path to SQLite database            |
| `O2C_RAW_ROOT`   | No       | `./data/raw`          | Root directory for JSONL data      |
| `CORS_ORIGINS`   | No       | `*`                   | Comma-separated allowed origins    |

---

## License

MIT
