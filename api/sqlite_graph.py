"""
SQLite helpers: schema digest for LLM, read-only SQL validation, graph payload for the UI.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Literal

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

NodeType = Literal["order", "payment", "delivery"]

ORDER_TABLES = (
    "sales_order_headers",
    "sales_order_items",
    "sales_order_schedule_lines",
)
PAYMENT_TABLES = (
    "payments_accounts_receivable",
    "journal_entry_items_accounts_receivable",
)
DELIVERY_TABLES = (
    "outbound_delivery_headers",
    "outbound_delivery_items",
)

_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|VACUUM|REINDEX|PRAGMA|REPLACE|TRUNCATE)\b",
    re.IGNORECASE,
)


def default_db_path() -> Path:
    return _PROJECT_ROOT / "o2c_context.db"


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = (db_path or default_db_path()).resolve()
    uri = f"{path.as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def schema_digest(conn: sqlite3.Connection, max_tables: int = 40) -> str:
    """Compact DDL + column listing for Gemini SQL generation."""
    rows = conn.execute(
        """
        SELECT name, sql FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    parts: list[str] = []
    for name, sql in rows[:max_tables]:
        if sql:
            parts.append(sql.strip() + ";")
        cols = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
        col_lines = [f"  {c[1]} {c[2]}" + (" PK" if c[5] else "") for c in cols]
        parts.append(f"-- columns for {name}:\n" + "\n".join(col_lines))

    return "\n\n".join(parts)


def is_safe_select(sql: str) -> bool:
    s = sql.strip().rstrip(";")
    if not s:
        return False
    if not s.lstrip().upper().startswith("SELECT"):
        return False
    if ";" in s[6:]:
        return False
    if _FORBIDDEN_SQL.search(s):
        return False
    return True


def run_select(conn: sqlite3.Connection, sql: str, max_rows: int = 500) -> list[dict[str, Any]]:
    """Execute a validated SELECT and return rows as dicts."""
    if not is_safe_select(sql):
        raise ValueError("Only single-statement SELECT queries are allowed.")
    capped = f"SELECT * FROM ({sql}) AS _q LIMIT {int(max_rows)}"
    cur = conn.execute(capped)
    cols = [d[0] for d in cur.description]
    out: list[dict[str, Any]] = []
    for row in cur.fetchall():
        out.append({cols[i]: row[i] for i in range(len(cols))})
    return out


def _table_type(table: str) -> NodeType | None:
    t = table.lower()
    if t in ORDER_TABLES:
        return "order"
    if t in PAYMENT_TABLES:
        return "payment"
    if t in DELIVERY_TABLES:
        return "delivery"
    return None


def _pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [r[1] for r in rows if r[5]]


def _row_label(row: sqlite3.Row, max_len: int = 48) -> str:
    d = dict(row)
    for _k, v in sorted(d.items()):
        if v is None or v == "N/A":
            continue
        s = str(v).strip()
        if len(s) > 1:
            return (s[:max_len] + "…") if len(s) > max_len else s
    return "row"


def _node_id(table: str, row: sqlite3.Row, conn: sqlite3.Connection) -> str:
    pks = _pk_columns(conn, table)
    d = dict(row)
    if pks:
        key = "|".join(str(d.get(c, "")) for c in pks)
    else:
        key = str(row[0])
    safe_table = table.replace(" ", "_")
    return f"{safe_table}:{key}"


def _find_sales_order_value(d: dict[str, Any]) -> str | None:
    for k, v in d.items():
        if v in (None, "", "N/A"):
            continue
        kl = k.lower().replace("_", "")
        if "salesorder" in kl and "item" not in kl:
            return str(v)
    return None


def _find_delivery_doc_value(d: dict[str, Any]) -> str | None:
    for k, v in d.items():
        if v in (None, "", "N/A"):
            continue
        kl = k.lower().replace("_", "")
        if "deliverydocument" in kl or kl == "delivery":
            return str(v)
        if "outbounddelivery" in kl:
            return str(v)
    return None


def build_graph_payload(
    conn: sqlite3.Connection,
    max_nodes: int = 500,
) -> dict[str, Any]:
    """
    Build nodes/links for react-force-graph from O2C tables.
    """
    existing = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }

    domain_tables: list[str] = []
    for group in (ORDER_TABLES, PAYMENT_TABLES, DELIVERY_TABLES):
        for t in group:
            if t in existing:
                domain_tables.append(t)

    if not domain_tables:
        return {"nodes": [], "links": []}

    per_table = max(1, max_nodes // len(domain_tables))
    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    sales_order_header_by_so: dict[str, str] = {}
    outbound_delivery_header_by_doc: dict[str, str] = {}

    for table in domain_tables:
        ntype = _table_type(table)
        if ntype is None:
            continue
        try:
            cur = conn.execute(f'SELECT * FROM "{table}" LIMIT {per_table}')
        except sqlite3.Error:
            continue
        for row in cur:
            if len(nodes) >= max_nodes:
                break
            nid = _node_id(table, row, conn)
            if nid in seen_ids:
                continue
            seen_ids.add(nid)
            d = dict(row)
            label = _row_label(row)
            nodes.append(
                {
                    "id": nid,
                    "type": ntype,
                    "label": f"{table}: {label}",
                    "table": table,
                }
            )

            if table == "sales_order_headers":
                so = _find_sales_order_value(d)
                if so:
                    sales_order_header_by_so[so] = nid

            if table == "outbound_delivery_headers":
                dv = _find_delivery_doc_value(d)
                if dv:
                    outbound_delivery_header_by_doc[dv] = nid

    # Second pass for edges (only when endpoints exist)
    id_set = {n["id"] for n in nodes}
    seen_links: set[tuple[str, str, str]] = set()

    for table in domain_tables:
        if table not in ("sales_order_items", "outbound_delivery_items"):
            continue
        try:
            cur = conn.execute(f'SELECT * FROM "{table}" LIMIT {per_table}')
        except sqlite3.Error:
            continue
        for row in cur:
            child_id = _node_id(table, row, conn)
            if child_id not in id_set:
                continue
            d = dict(row)
            if table == "sales_order_items":
                so = _find_sales_order_value(d)
                if so and so in sales_order_header_by_so:
                    tgt = sales_order_header_by_so[so]
                    if tgt in id_set and tgt != child_id:
                        lk = (child_id, tgt, "order_line")
                        if lk not in seen_links:
                            seen_links.add(lk)
                            links.append(
                                {
                                    "source": child_id,
                                    "target": tgt,
                                    "label": "order_line",
                                }
                            )
            elif table == "outbound_delivery_items":
                dv = _find_delivery_doc_value(d)
                if dv and dv in outbound_delivery_header_by_doc:
                    tgt = outbound_delivery_header_by_doc[dv]
                    if tgt in id_set and tgt != child_id:
                        lk = (child_id, tgt, "delivery_line")
                        if lk not in seen_links:
                            seen_links.add(lk)
                            links.append(
                                {
                                    "source": child_id,
                                    "target": tgt,
                                    "label": "delivery_line",
                                }
                            )

    return {"nodes": nodes, "links": links}
