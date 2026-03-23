"""
Dodge AI chat: NL → SQL (Groq) → SQLite → humanized answer (Groq).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from groq import Groq

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


def _groq_api_key() -> str | None:
    return os.environ.get("GROQ_API_KEY")


def _model_name() -> str:
    return os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    m = _SQL_JSON_BLOCK.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        return {}


def _generate_sql(
    client: Groq,
    user_message: str,
    schema_text: str,
) -> str:
    system_prompt = (
        f"{DODGE_SYSTEM_INSTRUCTION}\n\n"
        f"## Database schema (SQLite)\n{schema_text}\n\n"
        "## Instructions\n"
        "Generate a single read-only SELECT query that answers the user's question.\n"
        "Respond with a JSON object containing a 'sql_query' key: {\"sql_query\": \"...\"}.\n"
        "The query must be a single SELECT (no semicolons inside)."
    )
    
    resp = client.chat.completions.create(
        model=_model_name(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        response_format={"type": "json_object"},
    )
    text = resp.choices[0].message.content or "{}"
    data = _parse_json_object(text)
    q = data.get("sql_query", "")
    if not isinstance(q, str):
        raise ValueError("Model returned invalid sql_query")
    return q.strip()


def _humanize(
    client: Groq,
    user_message: str,
    sql_query: str,
    rows: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    payload = json.dumps(rows, ensure_ascii=False, default=str)
    max_chars = 14_000
    if len(payload) > max_chars:
        payload = payload[:max_chars] + "\n... [truncated for context]"

    system_prompt = (
        f"{DODGE_SYSTEM_INSTRUCTION}\n\n"
        "## Instructions\n"
        "Write a clear, professional answer for a finance/O2C user.\n"
        "Respond with a JSON object containing keys: 'answer' (string) and 'nodes_to_highlight' (array of strings).\n"
        "Use exact graph node ids (e.g. table:key) when referencing documents that should glow in the UI; "
        "use an empty array if none apply."
    )
    
    user_prompt = (
        "## Conversation\n"
        f"User question:\n{user_message}\n\n"
        f"Executed SQL:\n{sql_query}\n\n"
        f"Result rows (JSON):\n{payload}"
    )

    resp = client.chat.completions.create(
        model=_model_name(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"},
    )
    text = resp.choices[0].message.content or "{}"
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
    key = _groq_api_key()
    if not key:
        raise RuntimeError("Set GROQ_API_KEY")

    client = Groq(api_key=key)

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
            sql_query = _generate_sql(client, user_message, schema_text)
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
            answer, nodes = _humanize(client, user_message, sql_query, rows)
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
