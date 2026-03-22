"""
JSONL streaming for NetworkX — **not** the SQLite builder.

- Used by ``graph_engine`` / ``/api/graph/summary`` / ``run_ingest``: reads ``*.jsonl``
  and expects optional ``entities`` / ``edges`` arrays per line.
- **SQLite** ``o2c_context.db`` is produced by ``ingest_sqlite.py`` (flattened wide rows).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

# Project root (parent of /api)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_ROOT = _PROJECT_ROOT / "data" / "raw"
EXPECTED_FOLDER_COUNT = 19


@dataclass(frozen=True)
class JsonlRecord:
    """One logical row from a JSONL file."""

    source_path: str
    line_no: int
    data: dict[str, Any]


def raw_root(path: str | None = None) -> Path:
    base = Path(path) if path else DEFAULT_RAW_ROOT
    return base.resolve()


def discover_folder_paths(root: Path | None = None) -> list[Path]:
    """Return sorted subdirectories of data/raw (one per upstream source bucket)."""
    r = raw_root(str(root) if root else None)
    if not r.is_dir():
        return []
    dirs = [p for p in sorted(r.iterdir()) if p.is_dir()]
    return dirs


def iter_jsonl_files(root: Path | None = None) -> Iterator[Path]:
    for folder in discover_folder_paths(root):
        for fp in sorted(folder.glob("*.jsonl")):
            yield fp


def iter_jsonl_records(root: str | None = None) -> Iterator[JsonlRecord]:
    """Stream all JSON objects from all JSONL files under the raw tree."""
    base = raw_root(root)
    for fp in iter_jsonl_files(base):
        yield from records_from_file(fp)


def records_from_file(path: Path) -> Iterator[JsonlRecord]:
    src = str(path)
    with path.open(encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield JsonlRecord(source_path=src, line_no=i, data=obj)


def ingest_stats(root: str | None = None) -> dict[str, Any]:
    """Folder/file/line counts for observability and CI checks."""
    base = raw_root(root)
    folders = discover_folder_paths(base)
    files = list(iter_jsonl_files(base))
    line_total = 0
    for fp in files:
        with fp.open(encoding="utf-8", errors="replace") as f:
            line_total += sum(1 for line in f if line.strip())

    return {
        "raw_root": str(base),
        "folder_count": len(folders),
        "expected_folders": EXPECTED_FOLDER_COUNT,
        "jsonl_files": len(files),
        "non_empty_lines": line_total,
        "folders": [p.name for p in folders],
    }


def run_ingest(root: str | None = None) -> dict[str, Any]:
    """Load JSONL metadata and build graph summary (used by API and CLI)."""
    from .graph_engine import graph_from_raw_folders, summarize_graph

    stats = ingest_stats(root)
    built = graph_from_raw_folders(root)
    summary = summarize_graph(built.graph)
    return {
        **stats,
        "graph": {
            "nodes": built.node_count,
            "edges": built.edge_count,
            "source_files": built.source_files,
            **summary,
        },
    }


def main() -> None:
    root = os.environ.get("O2C_RAW_ROOT")
    out = run_ingest(root)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
