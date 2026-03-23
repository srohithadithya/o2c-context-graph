"""
FastAPI app for Vercel Serverless (`api/index.py` → single handler).

- All routes are under `/api/...` so Vercel rewrites `/api/:path*` → this app.
- Export: ``app``

Ingest pipelines (do not confuse):

- ``ingest_sqlite.py`` — JSONL under ``data/raw`` → **SQLite** ``o2c_context.db`` (Dodge AI / SQL + ``/api/graph`` fallback).
- ``ingest.py`` — streams JSONL for **NetworkX** summary (expects ``entities``/``edges`` in lines; flat SAP rows → empty graph).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .chat_service import run_dodge_chat
from .graph_engine import (
    graph_from_raw_folders,
    networkx_from_sqlite_payload,
    networkx_graph_to_json,
    summarize_graph,
)
from .graph_mapping import join_paths_as_dicts
from .ingest import ingest_stats, run_ingest
from .sqlite_graph import build_graph_payload, default_db_path, get_connection

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="O2C Context Graph API",
    version="0.2.0",
    description="Vercel serverless: Gemini chat, NetworkX graph JSON, SQLite viz.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        description="User message; sent to Google Gemini (Antigravity) with Dodge SQL pipeline.",
    )


class ChatResponse(BaseModel):
    """Gemini-powered assistant response (SQL + optional graph highlights)."""

    response: str = Field(..., description="Natural-language answer from Gemini.")
    sql_query: str = ""
    nodes_to_highlight: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "o2c-context-graph"}


# ---------------------------------------------------------------------------
# Ingest (JSONL → graph summary)
# ---------------------------------------------------------------------------


@app.get("/api/ingest/stats")
def ingest_stats_endpoint() -> dict[str, Any]:
    root = os.environ.get("O2C_RAW_ROOT")
    return ingest_stats(root)


@app.post("/api/ingest/run")
def ingest_run() -> dict[str, Any]:
    root = os.environ.get("O2C_RAW_ROOT")
    return run_ingest(root)


# ---------------------------------------------------------------------------
# Graph — NetworkX (JSONL-derived)
# ---------------------------------------------------------------------------


@app.get("/api/graph")
def graph_networkx() -> dict[str, Any]:
    """
    NetworkX graph as JSON: ``{ "Nodes": [...], "Edges": [...] }``.

    1. If JSONL under ``data/raw`` contains ``entities`` / ``edges`` payloads, those are used.
    2. Otherwise, if ``o2c_context.db`` exists, builds a graph from SQLite domain rows
       (same projection as ``/api/graph/data``).
    """
    root = os.environ.get("O2C_RAW_ROOT")
    built = graph_from_raw_folders(root)
    if built.node_count > 0:
        return networkx_graph_to_json(built.graph)

    db_path = Path(os.environ.get("O2C_DB_PATH", str(default_db_path()))).resolve()
    if db_path.is_file():
        with get_connection(db_path) as conn:
            payload = build_graph_payload(conn, max_nodes=500)
        g = networkx_from_sqlite_payload(payload)
        return networkx_graph_to_json(g)

    return {"Nodes": [], "Edges": []}


@app.get("/api/graph/summary")
def graph_summary() -> dict[str, Any]:
    root = os.environ.get("O2C_RAW_ROOT")
    built = graph_from_raw_folders(root)
    summary = summarize_graph(built.graph)
    return {
        "nodes": built.node_count,
        "edges": built.edge_count,
        "source_files": built.source_files,
        **summary,
    }


@app.get("/api/graph/data")
def graph_data(max_nodes: int = 500) -> dict[str, Any]:
    """
    Force-layout payload from SQLite (order / payment / delivery coloring) for the UI.
    """
    db_path = Path(os.environ.get("O2C_DB_PATH", str(default_db_path()))).resolve()
    if not db_path.is_file():
        return {"nodes": [], "links": [], "warning": "o2c_context.db not found"}
    cap = min(max(1, max_nodes), 500)
    with get_connection(db_path) as conn:
        return build_graph_payload(conn, max_nodes=cap)


@app.get("/api/graph/join-rules")
def graph_join_rules() -> dict[str, Any]:
    """Canonical O2C join predicates (same rules appended to Gemini SQL prompts)."""
    return {"join_paths": join_paths_as_dicts()}


@app.get("/api/node/{node_id}")
def get_node_details(node_id: str) -> dict[str, Any]:
    """Fetch full details for a node."""
    if ":" not in node_id:
        raise HTTPException(status_code=400, detail="Invalid node ID format")
    
    table, key_str = node_id.split(":", 1)
    
    from .sqlite_graph import _pk_columns
    db_path = Path(os.environ.get("O2C_DB_PATH", str(default_db_path()))).resolve()
    if not db_path.is_file():
        raise HTTPException(status_code=404, detail="DB not found")
        
    with get_connection(db_path) as conn:
        existing = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        if table not in existing:
            raise HTTPException(status_code=404, detail="Table not found")
            
        pks = _pk_columns(conn, table)
        if not pks:
            cur = conn.execute(f'SELECT rowid as _rowid_key, * FROM "{table}" WHERE rowid = ?', (key_str,))
        else:
            keys = key_str.split("|")
            if len(keys) != len(pks):
                raise HTTPException(status_code=400, detail="Mismatched PK elements")
            conds = " AND ".join(f'"{c}" = ?' for c in pks)
            cur = conn.execute(f'SELECT * FROM "{table}" WHERE {conds}', keys)
            
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Node data not found")
            
        return {"id": node_id, "table": table, "data": dict(row)}


# ---------------------------------------------------------------------------
# Chat — Groq SQLite
# ---------------------------------------------------------------------------


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """
    POST body: ``{ "message": "..." }``.

    Calls **Groq** (``groq``; set ``GROQ_API_KEY``)
    to generate SQL, runs it on ``o2c_context.db``, then Groq again to humanize the reply.
    """
    try:
        out = run_dodge_chat(req.message)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return ChatResponse(**out)
