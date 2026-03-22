#!/usr/bin/env python3
"""
Temporary integration test: end-to-end Dodge chat (SQLite → Gemini SQL → SQLite → Gemini answer).

Requires GEMINI_API_KEY or GOOGLE_API_KEY in the environment.

Run from project root:
  python tests/verify_flow.py

On failure, prints the full traceback (e.g. missing API key, Gemini error, SQL error).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "o2c_context.db"


def step_connect_sqlite() -> str:
    """(a) Connect to SQLite and return a sample salesOrder id."""
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"Missing database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            'SELECT salesOrder FROM sales_order_headers WHERE salesOrder IS NOT NULL '
            "AND TRIM(CAST(salesOrder AS TEXT)) != '' AND UPPER(TRIM(CAST(salesOrder AS TEXT))) != 'N/A' "
            "LIMIT 1"
        ).fetchone()
        if not row:
            raise RuntimeError("No sales orders in sales_order_headers")
        return str(row[0])
    finally:
        conn.close()


def main() -> int:
    print("verify_flow: Dodge AI pipeline check\n")

    try:
        print("[a] Connecting to SQLite & sampling Sales Order ID...")
        so_id = step_connect_sqlite()
        print(f"    OK — using salesOrder = {so_id!r}\n")

        question = f"Who is the customer for Sales Order {so_id}?"
        print(f"[b-d] Running backend pipeline for: {question!r}\n")

        from api.chat_service import run_dodge_chat  # noqa: E402

        result = run_dodge_chat(question)

        print("[b] SQL generation + execution: OK (no exception)")
        sql = result.get("sql_query", "")
        if sql:
            print(f"    Generated SQL (preview): {sql[:200]}{'...' if len(sql) > 200 else ''}\n")
        else:
            print("    (sql_query empty — model may have failed or skipped SQL)\n")

        print("[c] Gemini (Antigravity) humanize step completed.\n")

        print("[d] Validating JSON-shaped response...")
        required = ("response", "sql_query", "nodes_to_highlight")
        missing = [k for k in required if k not in result]
        if missing:
            raise AssertionError(f"Missing keys: {missing}; got: {list(result.keys())}")

        if not isinstance(result["response"], str):
            raise TypeError("response must be str")
        if not isinstance(result["sql_query"], str):
            raise TypeError("sql_query must be str")
        if not isinstance(result["nodes_to_highlight"], list):
            raise TypeError("nodes_to_highlight must be list")

        print("    OK — response keys:", json.dumps({k: result[k] for k in required}, indent=2)[:800])
        print("\n=== ALL STEPS PASSED ===")
        return 0

    except Exception:
        print("\n*** FAILURE — traceback:\n")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
