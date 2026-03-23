"""
SQLite helpers: schema digest for LLM, read-only SQL validation, graph payload for the UI.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Literal

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

NodeType = Literal["order", "payment", "delivery", "billing", "master", "entity"]

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

BILLING_TABLES = (
    "billing_document_cancellations",
    "billing_document_headers",
    "billing_document_items",
)

MASTER_TABLES = (
    "business_partners",
    "business_partner_addresses",
    "customer_company_assignments",
    "customer_sales_area_assignments",
    "plants",
    "products",
    "product_descriptions",
    "product_plants",
    "product_storage_locations",
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


def _table_type(table: str) -> NodeType:
    t = table.lower()
    if t in ORDER_TABLES:
        return "order"
    if t in PAYMENT_TABLES:
        return "payment"
    if t in DELIVERY_TABLES:
        return "delivery"
    if t in BILLING_TABLES:
        return "billing"
    if t in MASTER_TABLES:
        return "master"
    return "entity"


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
        if "_rowid_key" in d:
            key = str(d["_rowid_key"])
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
    from .graph_mapping import O2C_JOIN_PATHS

    existing = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }

    domain_tables = list(existing)

    if not domain_tables:
        return {"nodes": [], "links": []}

    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    # In-memory storage of rows for fast joining
    table_data: dict[str, list[tuple[str, dict[str, Any]]]] = {}

    for table in domain_tables:
        ntype = _table_type(table) or "entity"
        table_data[table] = []
        try:
            cur = conn.execute(f'SELECT rowid as _rowid_key, * FROM "{table}"')
        except sqlite3.Error:
            continue
        for row in cur:
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
                    "group": ntype,
                }
            )
            table_data[table].append((nid, d))

    seen_links: set[tuple[str, str, str]] = set()

    for jp in O2C_JOIN_PATHS:
        if jp.left_table not in table_data or jp.right_table not in table_data:
            continue
        
        # Build an index on the left table's join keys to speed up matching
        # Key: tuple of predicate values
        left_index: dict[tuple[Any, ...], list[str]] = {}
        for l_nid, l_dict in table_data[jp.left_table]:
            key = tuple(str(l_dict.get(p.left_column, "")) for p in jp.predicates)
            # Only index if all keys are present and non-empty/non-None
            if all(k != "" and k != "None" for k in key):
                left_index.setdefault(key, []).append(l_nid)
                
        # Probe from the right table
        for r_nid, r_dict in table_data[jp.right_table]:
            key = tuple(str(r_dict.get(p.right_column, "")) for p in jp.predicates)
            if key in left_index:
                for l_nid in left_index[key]:
                    if l_nid != r_nid:
                        lk = (l_nid, r_nid, jp.id)
                        if lk not in seen_links:
                            seen_links.add(lk)
                            links.append({
                                "source": l_nid,
                                "target": r_nid,
                                "label": jp.id,
                            })

    return {"nodes": nodes, "links": links}
