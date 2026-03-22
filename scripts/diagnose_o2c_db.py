#!/usr/bin/env python3
"""
QA: Data health report for o2c_context.db — row counts, join-key fill rates, orphan checks.
Run from project root: python scripts/diagnose_o2c_db.py
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

# Project root (parent of scripts/)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.ingest_sqlite import ENTITY_FOLDERS, _sanitize_table_name  # noqa: E402

DB_PATH = ROOT / "o2c_context.db"
JOIN_KEY_THRESHOLD = 0.90

# Keys that may legitimately be sparse (e.g. AR lines not tied to a sales order).
OPTIONAL_JOIN_KEYS: frozenset[tuple[str, str]] = frozenset(
    {
        ("payments_accounts_receivable", "salesDocument"),
        ("payments_accounts_receivable", "salesDocumentItem"),
    }
)

# Critical join / document keys per table (must exist in schema; unknown cols skipped at runtime).
CRITICAL_JOIN_KEYS: dict[str, tuple[str, ...]] = {
    "billing_document_cancellations": ("billingDocument", "accountingDocument"),
    "billing_document_headers": ("billingDocument", "accountingDocument"),
    "billing_document_items": ("billingDocument", "billingDocumentItem", "referenceSdDocument"),
    "business_partner_addresses": ("businessPartner", "addressId"),
    "business_partners": ("businessPartner", "customer"),
    "customer_company_assignments": ("customer", "companyCode"),
    "customer_sales_area_assignments": (
        "customer",
        "salesOrganization",
        "distributionChannel",
        "division",
    ),
    "journal_entry_items_accounts_receivable": (
        "companyCode",
        "fiscalYear",
        "accountingDocument",
        "customer",
    ),
    "outbound_delivery_headers": ("deliveryDocument",),
    "outbound_delivery_items": (
        "deliveryDocument",
        "deliveryDocumentItem",
        "referenceSdDocument",
    ),
    "payments_accounts_receivable": (
        "accountingDocument",
        "customer",
        "salesDocument",
    ),
    "plants": ("plant",),
    "product_descriptions": ("product", "language"),
    "product_plants": ("product", "plant"),
    "product_storage_locations": ("product", "plant", "storageLocation"),
    "products": ("product",),
    "sales_order_headers": ("salesOrder",),
    "sales_order_items": ("salesOrder", "salesOrderItem"),
    "sales_order_schedule_lines": ("salesOrder", "salesOrderItem", "scheduleLine"),
}


def _is_missing_sql_expr(column: str) -> str:
    """SQLite expression: treat NULL, '', whitespace, 'N/A' as missing (ingest backfill)."""
    c = f'"{column}"'
    return f"({c} IS NULL OR TRIM(CAST({c} AS TEXT)) = '' OR UPPER(TRIM(CAST({c} AS TEXT))) = 'N/A')"


def table_name(entity_folder: str) -> str:
    return _sanitize_table_name(entity_folder)


def main() -> int:
    print("=" * 72)
    print("O2C DATA HEALTH REPORT")
    print("=" * 72)
    print(f"Database: {DB_PATH.resolve()}\n")

    if not DB_PATH.is_file():
        print("CRITICAL ERROR: o2c_context.db not found. Run: python -m api.ingest_sqlite")
        return 2

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # --- Table inventory (all user tables) ---
    all_tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]

    expected_tables = {table_name(e) for e in ENTITY_FOLDERS}
    row_counts: dict[str, int] = {}

    print("--- TABLE ROW COUNTS ---\n")
    critical_empty: list[str] = []

    for entity in ENTITY_FOLDERS:
        t = table_name(entity)
        if t not in all_tables:
            print(f"  {t}: MISSING TABLE (CRITICAL)")
            critical_empty.append(t)
            row_counts[t] = 0
            continue
        n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        row_counts[t] = n
        status = ""
        if n == 0:
            status = "  <<< CRITICAL ERROR: ZERO ROWS"
            critical_empty.append(t)
        print(f"  {t}: {n:,}{status}")

    extra = [x for x in all_tables if x not in expected_tables]
    if extra:
        print("\n  (Additional tables in DB not in ENTITY_FOLDERS:)", ", ".join(extra))

    # --- Join key fill rates ---
    print("\n--- JOIN KEY FILL RATE (target: >= 90% non-missing per column) ---\n")

    join_failures: list[str] = []

    for entity in ENTITY_FOLDERS:
        t = table_name(entity)
        if t not in all_tables or row_counts.get(t, 0) == 0:
            continue

        cols_present = {
            r[1] for r in conn.execute(f'PRAGMA table_info("{t}")').fetchall()
        }
        keys = CRITICAL_JOIN_KEYS.get(t, ())
        if not keys:
            continue

        total = row_counts[t]
        for col in keys:
            if col not in cols_present:
                print(f"  {t}.{col}: SKIP (column absent)")
                continue
            if (t, col) in OPTIONAL_JOIN_KEYS:
                missing_expr = _is_missing_sql_expr(col)
                missing = conn.execute(
                    f'SELECT COUNT(*) FROM "{t}" WHERE {missing_expr}'
                ).fetchone()[0]
                rate = (total - missing) / total if total else 0.0
                print(
                    f"  {t}.{col}: {rate:.1%} populated ({total - missing}/{total}) "
                    f"[OPTIONAL, not enforced at 90%]"
                )
                continue
            missing_expr = _is_missing_sql_expr(col)
            missing = conn.execute(
                f'SELECT COUNT(*) FROM "{t}" WHERE {missing_expr}'
            ).fetchone()[0]
            rate = (total - missing) / total if total else 0.0
            ok = rate >= JOIN_KEY_THRESHOLD
            flag = "OK" if ok else "FAIL (<90%)"
            print(f"  {t}.{col}: {rate:.1%} populated ({total - missing}/{total}) [{flag}]")
            if not ok:
                join_failures.append(f"{t}.{col} ({rate:.1%})")

    # --- Broken threads: SO items without header ---
    print("\n--- BROKEN THREADS ---\n")
    so_items = table_name("sales_order_items")
    so_headers = table_name("sales_order_headers")

    if so_items in all_tables and so_headers in all_tables:
        orphan = conn.execute(
            f"""
            SELECT COUNT(*) FROM "{so_items}" i
            LEFT JOIN "{so_headers}" h ON i.salesOrder = h.salesOrder
            WHERE h.salesOrder IS NULL
            """
        ).fetchone()[0]
        total_items = row_counts.get(so_items, 0)
        print(
            f"  sales_order_items rows with NO matching sales_order_headers (on salesOrder): "
            f"{orphan:,} / {total_items:,}"
        )
        if orphan > 0:
            examples = conn.execute(
                f"""
                SELECT i.salesOrder FROM "{so_items}" i
                LEFT JOIN "{so_headers}" h ON i.salesOrder = h.salesOrder
                WHERE h.salesOrder IS NULL
                LIMIT 5
                """
            ).fetchall()
            print(f"  Example orphan SalesOrder keys: {[r[0] for r in examples]}")
    else:
        print("  SKIP (sales_order_headers / sales_order_items missing)")

    conn.close()

    # --- Summary ---
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)

    if critical_empty:
        print(
            "\n*** CRITICAL ERROR: The following expected tables have 0 rows or are missing:"
        )
        for t in critical_empty:
            print(f"    - {t}")
    else:
        print("\n  All 19 entity tables exist with at least 1 row.")

    if join_failures:
        print("\n*** WARNING: Join keys below 90% populated:")
        for j in join_failures:
            print(f"    - {j}")
    else:
        print("\n  All checked join key columns meet the 90% threshold (or table empty/skipped).")

    print()
    return 1 if critical_empty else 0


if __name__ == "__main__":
    raise SystemExit(main())
