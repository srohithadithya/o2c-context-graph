"""
O2C JSONL → **SQLite** — primary data store for Dodge AI (SQL) and SQLite-backed graph.

Glob-scans 19 entity folders under ``data/raw``, flattens nested JSON into wide rows,
cleans dates/nulls, deduplicates by latest timestamp, and writes one table per entity
into ``o2c_context.db``.

**Not** the same as ``ingest.py`` (that module only streams JSONL for NetworkX graphs).

CLI: ``python -m api.ingest_sqlite`` (optional ``--raw-root``, ``--db``).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import warnings
from glob import glob
from pathlib import Path
from typing import Any

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_ROOT = _PROJECT_ROOT / "data" / "raw"
DEFAULT_DB_PATH = _PROJECT_ROOT / "o2c_context.db"

# Matches the 19 top-level folders under data/raw (O2C domain buckets).
ENTITY_FOLDERS: tuple[str, ...] = (
    "billing_document_cancellations",
    "billing_document_headers",
    "billing_document_items",
    "business_partners",
    "business_partner_addresses",
    "customer_company_assignments",
    "customer_sales_area_assignments",
    "journal_entry_items_accounts_receivable",
    "outbound_delivery_headers",
    "outbound_delivery_items",
    "payments_accounts_receivable",
    "plants",
    "products",
    "product_descriptions",
    "product_plants",
    "product_storage_locations",
    "sales_order_headers",
    "sales_order_items",
    "sales_order_schedule_lines",
)

# Columns used to resolve a row version for deduplication (first match wins).
_TIMESTAMP_NAMES: tuple[str, ...] = (
    "timestamp",
    "updated_at",
    "modified_at",
    "changed_at",
    "last_modified",
    "last_changed",
    "change_timestamp",
    "created_at",
    "creation_date",
    "posting_date",
    "document_date",
    "billing_date",
    "delivery_date",
    "order_date",
    "creationdate",
    "lastchangedate",
    "changedon",
    "postingdate",
    "documentdate",
    "deliverydate",
    "orderdate",
    "confirmeddeliverydate",
    "requesteddeliverydate",
    "ts",
    "datetime",
    "date_time",
)

# Column names that look like business keys, not event times (avoid false positives).
_TIMESTAMP_DENY_SUBSTR: tuple[str, ...] = (
    "salesorder",
    "purchaseorder",
    "billingdocument",
    "deliverydocument",
    "materialdocument",
    "invoicedocument",
    "documentnumber",
    "partnernumber",
    "customernumber",
    "materialnumber",
    "productnumber",
    "plant",
    "quantity",
    "amount",
    "price",
    "currency",
    "guid",
    "uuid",
)

_TS_NAME_PATTERN = re.compile(
    r"(?:date|time|timestamp|stamp|_ts$|^ts$|datetime|changedon|posting)",
    re.IGNORECASE,
)

# SAP / O2C fields that are stable business keys but do not end in Id/Number/Key.
_BUSINESS_KEY_NAMES: frozenset[str] = frozenset(
    {
        "salesorder",
        "salesdocument",
        "billingdocument",
        "deliverydocument",
        "material",
        "plant",
        "customer",
        "partner",
        "product",
        "salesorderitem",
        "scheduleline",
        "deliverydocumentitem",
        "billingdocumentitem",
        "outbounddelivery",
        "journalentry",
        "accountingdocument",
        "purchaseorder",
    }
)

_CAMEL_KEY_SUFFIX = re.compile(r"(?:Id|Number|Key)$")
_SNAKE_KEY_SUFFIX = re.compile(r"(?:_id|_number|_key)$", re.IGNORECASE)

# Natural keys for dedupe (first column that exists after flattening).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ingest_sqlite")


def _glob_jsonl_files(raw_root: Path, entity: str) -> list[Path]:
    pattern = str(raw_root / entity / "**" / "*.jsonl")
    paths = sorted(Path(p) for p in glob(pattern, recursive=True))
    return [p for p in paths if p.is_file()]


def _load_jsonl_as_dataframe(paths: list[Path]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in paths:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    log.warning("Skip bad JSON in %s line %s: %s", path, line_no, e)
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
                else:
                    log.debug("Skip non-object line in %s:%s", path, line_no)

    if not rows:
        return pd.DataFrame()

    df = pd.json_normalize(rows, sep="_")
    _coerce_nested_objects_to_json_strings(df)
    return df


def _coerce_nested_objects_to_json_strings(df: pd.DataFrame) -> None:
    """Lists/dicts in cells become JSON text so SQLite stores stable scalars."""

    def to_json_if_needed(v: Any) -> Any:
        if isinstance(v, (list, dict)):
            return json.dumps(v, ensure_ascii=False, default=str)
        return v

    for col in df.columns:
        sample = df[col].dropna().head(50)
        if sample.empty:
            continue
        if any(isinstance(x, (list, dict)) for x in sample):
            df[col] = df[col].apply(to_json_if_needed)


def _find_column_case_insensitive(df: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    lower_map = {str(c).lower().replace("_", ""): c for c in df.columns}
    for name in names:
        key = name.lower().replace("_", "")
        if key in lower_map:
            return lower_map[key]
    return None


def _column_name_suggests_timestamp(name: str) -> bool:
    compact = re.sub(r"[\s_\-]", "", str(name).lower())
    if any(d in compact for d in _TIMESTAMP_DENY_SUBSTR):
        return False
    return bool(_TS_NAME_PATTERN.search(str(name)))


def _to_datetime_utc(s: pd.Series) -> pd.Series:
    """Parse datetimes with minimal noisy warnings (wide JSONL mixes formats)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        try:
            return pd.to_datetime(s, errors="coerce", utc=True, format="mixed")
        except (TypeError, ValueError):
            return pd.to_datetime(s, errors="coerce", utc=True)


def _resolve_timestamp_column(df: pd.DataFrame) -> str | None:
    col = _find_column_case_insensitive(df, _TIMESTAMP_NAMES)
    if col is not None:
        return col
    # Prefer columns whose names look like dates/times and parse reliably.
    best_col: str | None = None
    best_ratio = 0.0
    for c in df.columns:
        if str(c).startswith("_"):
            continue
        if not _column_name_suggests_timestamp(str(c)):
            continue
        parsed = _to_datetime_utc(df[c])
        ratio = float(parsed.notna().sum()) / max(len(df), 1)
        if ratio > best_ratio and ratio >= 0.4:
            best_ratio = ratio
            best_col = c
    return best_col


def _looks_like_key_column(name: str) -> bool:
    """Identify stable key columns without matching accidental 'id' substrings inside words."""
    s = str(name)
    cl = re.sub(r"[\s_\-]", "", s.lower())
    if cl in _BUSINESS_KEY_NAMES:
        return True
    if _CAMEL_KEY_SUFFIX.search(s):
        return True
    if _SNAKE_KEY_SUFFIX.search(s):
        return True
    if cl in ("id", "guid", "uuid"):
        return True
    return False


def _dedupe_key_columns(df: pd.DataFrame, ts_col: str | None) -> list[str]:
    """
    Build a stable dedupe subset: prefer explicit ids, else composite key-like columns
    (SAP-style document + line keys), else fall back to all non-timestamp fields.
    """
    for c in df.columns:
        if str(c).lower() in ("id", "_id", "guid", "uuid"):
            return [c]

    keys: list[str] = []
    for c in df.columns:
        if ts_col is not None and c == ts_col:
            continue
        if _looks_like_key_column(c):
            keys.append(c)

    if keys:
        return sorted(keys, key=lambda x: str(x).lower())[:16]

    return [c for c in df.columns if c != ts_col]


def _dedupe_latest_by_timestamp(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    ts_col = _resolve_timestamp_column(df)
    key_cols = _dedupe_key_columns(df, ts_col)
    out = df.copy()

    if ts_col is not None:
        sort_ts = _to_datetime_utc(out[ts_col])
        out = out.assign(_ingest_sort_ts=sort_ts)
        out = out.sort_values("_ingest_sort_ts", ascending=True, na_position="first")
        out = out.drop_duplicates(subset=key_cols, keep="last")
        out = out.drop(columns=["_ingest_sort_ts"])
        shown = key_cols[:10]
        if len(key_cols) > 10:
            shown = shown + [f"... (+{len(key_cols) - 10} more)"]
        log.info(
            "Dedupe: timestamp=%r keys=%s (%s rows → %s rows)",
            ts_col,
            shown,
            len(df),
            len(out),
        )
    else:
        log.warning(
            "No timestamp column found; deduping on key columns only (keep last in file order)."
        )
        out = out.drop_duplicates(subset=key_cols, keep="last")

    return out.reset_index(drop=True)


def _column_looks_datetime_series(s: pd.Series, col_name: str) -> bool:
    if pd.api.types.is_datetime64_any_dtype(s):
        return True
    if not _column_name_suggests_timestamp(col_name):
        return False
    non_null = s.dropna()
    if non_null.empty:
        return False
    parsed = _to_datetime_utc(s)
    ok = float(parsed.notna().sum()) / max(len(s), 1)
    return ok >= 0.4 and ok > 0


def _format_ts_iso(ts: pd.Timestamp) -> str:
    if pd.isna(ts):
        return "N/A"
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    # ISO 8601 UTC with Z suffix
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f").rstrip("0").rstrip(".") + "Z"


def _normalize_dates_to_iso8601(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in list(out.columns):
        s = out[col]
        if not _column_looks_datetime_series(s, str(col)):
            continue
        parsed = _to_datetime_utc(s)
        out[col] = parsed.apply(_format_ts_iso)
    return out


def _scalar_to_na(v: Any) -> Any:
    if v is None:
        return "N/A"
    if isinstance(v, float) and pd.isna(v):
        return "N/A"
    if isinstance(v, str) and v.strip().lower() in ("nan", "none", "null"):
        return "N/A"
    return v


def _fill_nulls_with_na(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out = out.where(pd.notnull(out), "N/A")
    for col in out.columns:
        out[col] = out[col].map(_scalar_to_na)
    return out


def _sanitize_table_name(entity: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", entity.strip())
    if safe and safe[0].isdigit():
        safe = f"t_{safe}"
    return safe or "entity"


def ingest_entity_folder(
    raw_root: Path,
    entity: str,
    conn: sqlite3.Connection,
) -> int:
    paths = _glob_jsonl_files(raw_root, entity)
    if not paths:
        log.info("No JSONL files for %s — skipping table.", entity)
        return 0

    log.info("Loading %s file(s) for %s", len(paths), entity)
    df = _load_jsonl_as_dataframe(paths)
    if df.empty:
        log.info("No rows parsed for %s — skipping table.", entity)
        return 0

    df = _dedupe_latest_by_timestamp(df)
    df = _normalize_dates_to_iso8601(df)
    df = _fill_nulls_with_na(df)

    table = _sanitize_table_name(entity)
    df.to_sql(table, conn, if_exists="replace", index=False)
    return len(df)


def run_ingestion(
    raw_root: Path | None = None,
    db_path: Path | None = None,
) -> dict[str, int]:
    raw = (raw_root or DEFAULT_RAW_ROOT).resolve()
    db = (db_path or DEFAULT_DB_PATH).resolve()

    if not raw.is_dir():
        raise FileNotFoundError(f"Raw root not found: {raw}")

    counts: dict[str, int] = {}
    with sqlite3.connect(db) as conn:
        for entity in ENTITY_FOLDERS:
            entity_dir = raw / entity
            if not entity_dir.is_dir():
                log.warning("Missing folder (expected entity dir): %s", entity_dir)
                counts[entity] = 0
                continue
            n = ingest_entity_folder(raw, entity, conn)
            counts[entity] = n

    log.info("SQLite database written to: %s", db)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest O2C JSONL folders into SQLite.")
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=None,
        help=f"Root containing entity folders (default: {DEFAULT_RAW_ROOT})",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help=f"Output SQLite path (default: {DEFAULT_DB_PATH})",
    )
    args = parser.parse_args()

    counts = run_ingestion(raw_root=args.raw_root, db_path=args.db)

    print("\n--- Row counts per table ---")
    for entity in ENTITY_FOLDERS:
        table = _sanitize_table_name(entity)
        print(f"{table}: {counts.get(entity, 0)}")


if __name__ == "__main__":
    main()
