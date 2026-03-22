"""
Dodge AI chat: NL → SQL (Gemini) → SQLite → humanized answer (Gemini).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import google.generativeai as genai

from .dodge_system import DODGE_SYSTEM_INSTRUCTION
from .graph_mapping import join_hints_markdown
from .sqlite_graph import (
    default_db_path,
    get_connection,
    is_safe_select,
    run_select,
    schema_digest,
)

_SQL_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _gemini_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _model_name() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    m = _SQL_JSON_BLOCK.search(text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)


def _sql_gen_config() -> genai.GenerationConfig:
    return genai.GenerationConfig(
        response_mime_type="application/json",
        response_schema={
            "type": "object",
            "properties": {
                "sql_query": {"type": "string"},
            },
            "required": ["sql_query"],
        },
    )


def _humanize_config() -> genai.GenerationConfig:
    return genai.GenerationConfig(
        response_mime_type="application/json",
        response_schema={
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "nodes_to_highlight": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["answer", "nodes_to_highlight"],
        },
    )


def _generate_sql(
    model: genai.GenerativeModel,
    user_message: str,
    schema_text: str,
) -> str:
    prompt = (
        f"## Database schema (SQLite)\n{schema_text}\n\n"
        "## Instructions\n"
        "Generate a single read-only SELECT query that answers the user's question.\n"
        "Respond with JSON only matching the schema: {{\"sql_query\": \"...\"}}.\n"
        "The query must be a single SELECT (no semicolons inside). Use LIMIT when listing rows.\n\n"
        f"## User question\n{user_message}"
    )
    resp = model.generate_content(prompt, generation_config=_sql_gen_config())
    text = resp.text or "{}"
    data = _parse_json_object(text)
    q = data.get("sql_query", "")
    if not isinstance(q, str):
        raise ValueError("Model returned invalid sql_query")
    return q.strip()


def _humanize(
    model: genai.GenerativeModel,
    user_message: str,
    sql_query: str,
    rows: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    payload = json.dumps(rows, ensure_ascii=False, default=str)
    max_chars = 14_000
    if len(payload) > max_chars:
        payload = payload[:max_chars] + "\n... [truncated for context]"

    prompt = (
        "## Conversation\n"
        f"User question:\n{user_message}\n\n"
        f"Executed SQL:\n{sql_query}\n\n"
        f"Result rows (JSON):\n{payload}\n\n"
        "## Instructions\n"
        "Write a clear, professional answer for a finance/O2C user.\n"
        "Return JSON only: {\"answer\": \"...\", \"nodes_to_highlight\": [\"node_id\", ...]}.\n"
        "Use exact graph node ids (e.g. table:key) when referencing documents that should glow in the UI; "
        "use an empty array if none apply."
    )
    resp = model.generate_content(prompt, generation_config=_humanize_config())
    text = resp.text or "{}"
    data = _parse_json_object(text)
    answer = str(data.get("answer", ""))
    raw_nodes = data.get("nodes_to_highlight", [])
    if isinstance(raw_nodes, list):
        nodes = [str(x) for x in raw_nodes]
    else:
        nodes = []
    return answer, nodes


def run_dodge_chat(user_message: str) -> dict[str, Any]:
    """
    Returns { response, sql_query, nodes_to_highlight }.
    """
    key = _gemini_api_key()
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY")

    genai.configure(api_key=key)
    model = genai.GenerativeModel(
        model_name=_model_name(),
        system_instruction=DODGE_SYSTEM_INSTRUCTION,
    )

    db_path = Path(os.environ.get("O2C_DB_PATH", str(default_db_path()))).resolve()
    if not db_path.is_file():
        empty = (
            "The O2C SQLite database was not found on the server. "
            "Ingest data into `o2c_context.db` (see `api/ingest_sqlite.py`) and ensure "
            "`O2C_DB_PATH` points to it."
        )
        return {
            "response": empty,
            "sql_query": "",
            "nodes_to_highlight": [],
        }

    with get_connection(db_path) as conn:
        schema_text = (
            schema_digest(conn)
            + "\n\n## JOIN KEY RULES (canonical)\n"
            + join_hints_markdown()
        )
        try:
            sql_query = _generate_sql(model, user_message, schema_text)
        except Exception as e:  # noqa: BLE001 — surface model/parse errors as answer
            return {
                "response": f"I could not generate a valid SQL query: {e}",
                "sql_query": "",
                "nodes_to_highlight": [],
            }

        if not is_safe_select(sql_query):
            return {
                "response": "The generated query was rejected because it is not a safe read-only SELECT.",
                "sql_query": sql_query,
                "nodes_to_highlight": [],
            }

        try:
            rows = run_select(conn, sql_query, max_rows=500)
        except Exception as e:  # noqa: BLE001
            return {
                "response": f"SQL execution failed: {e}",
                "sql_query": sql_query,
                "nodes_to_highlight": [],
            }

        try:
            answer, nodes = _humanize(model, user_message, sql_query, rows)
        except Exception as e:  # noqa: BLE001
            return {
                "response": f"Could not format the answer: {e}. Raw row count: {len(rows)}.",
                "sql_query": sql_query,
                "nodes_to_highlight": [],
            }

        return {
            "response": answer,
            "sql_query": sql_query,
            "nodes_to_highlight": nodes,
        }
