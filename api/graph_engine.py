"""
NetworkX graph layer for the O2C Context Graph.

Builds a directed graph from normalized JSONL records (entities/edges).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import networkx as nx

from .ingest import JsonlRecord, iter_jsonl_records


@dataclass(frozen=True)
class GraphBuildResult:
    graph: nx.DiGraph
    node_count: int
    edge_count: int
    source_files: int


def _node_id(entity_type: str, entity_id: str) -> str:
    return f"{entity_type}:{entity_id}"


def add_record_to_graph(graph: nx.DiGraph, record: JsonlRecord) -> None:
    """Merge a single JSONL record into the graph (idempotent upsert semantics)."""
    payload = record.data
    if not isinstance(payload, dict):
        return

    if "entities" in payload and isinstance(payload["entities"], list):
        for ent in payload["entities"]:
            if not isinstance(ent, dict):
                continue
            eid = ent.get("id")
            etype = ent.get("type", "entity")
            if eid is None:
                continue
            nid = _node_id(str(etype), str(eid))
            graph.add_node(nid, **{"type": etype, "source": record.source_path})
            if "label" in ent:
                graph.nodes[nid]["label"] = ent["label"]

    if "edges" in payload and isinstance(payload["edges"], list):
        for edge in payload["edges"]:
            if not isinstance(edge, dict):
                continue
            src = edge.get("source")
            tgt = edge.get("target")
            st = edge.get("source_type", "entity")
            tt = edge.get("target_type", "entity")
            rel = edge.get("relation", "relates_to")
            if src is None or tgt is None:
                continue
            u = _node_id(str(st), str(src))
            v = _node_id(str(tt), str(tgt))
            graph.add_edge(u, v, relation=str(rel), source=record.source_path)


def build_graph_from_records(records: Iterable[JsonlRecord]) -> GraphBuildResult:
    graph: nx.DiGraph = nx.DiGraph()
    files = 0
    seen_paths: set[str] = set()
    for rec in records:
        if rec.source_path not in seen_paths:
            seen_paths.add(rec.source_path)
            files += 1
        add_record_to_graph(graph, rec)
    return GraphBuildResult(
        graph=graph,
        node_count=graph.number_of_nodes(),
        edge_count=graph.number_of_edges(),
        source_files=files,
    )


def graph_from_raw_folders(root: str | None = None) -> GraphBuildResult:
    """Ingest all JSONL under data/raw/* and build the graph."""
    records = iter_jsonl_records(root)
    return build_graph_from_records(records)


def networkx_from_sqlite_payload(payload: dict[str, Any]) -> nx.DiGraph:
    """
    Build a :class:`networkx.DiGraph` from ``build_graph_payload`` output
    (``nodes`` / ``links`` keys).
    """

    graph: nx.DiGraph = nx.DiGraph()
    for n in payload.get("nodes") or []:
        nid = n.get("id")
        if nid is None:
            continue
        attrs = {k: v for k, v in n.items() if k != "id"}
        graph.add_node(nid, **attrs)
    for link in payload.get("links") or []:
        src, tgt = link.get("source"), link.get("target")
        if src is None or tgt is None:
            continue
        eattrs = {k: v for k, v in link.items() if k not in ("source", "target")}
        graph.add_edge(src, tgt, **eattrs)
    return graph


def networkx_graph_to_json(graph: nx.DiGraph) -> dict[str, Any]:
    """
    Serialize a NetworkX DiGraph for HTTP: capital ``Nodes`` and ``Edges``
    (node/edge attributes preserved; non-JSON values stringified).
    """

    def _clean(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    Nodes: list[dict[str, Any]] = []
    for node_id, attrs in graph.nodes(data=True):
        row: dict[str, Any] = {"id": _clean(node_id)}
        for k, v in attrs.items():
            row[str(k)] = _clean(v)
        Nodes.append(row)

    Edges: list[dict[str, Any]] = []
    for u, v, attrs in graph.edges(data=True):
        e: dict[str, Any] = {"source": _clean(u), "target": _clean(v)}
        for k, v in attrs.items():
            e[str(k)] = _clean(v)
        Edges.append(e)

    return {"Nodes": Nodes, "Edges": Edges}


def summarize_graph(graph: nx.DiGraph, top_k: int = 10) -> dict[str, Any]:
    """Lightweight stats for API responses (no full graph serialization)."""
    if graph.number_of_nodes() == 0:
        return {
            "nodes": 0,
            "edges": 0,
            "density": 0.0,
            "is_weakly_connected": False,
            "top_in_degree": [],
        }

    degree_in = nx.in_degree_centrality(graph)
    top_nodes = sorted(degree_in.items(), key=lambda x: x[1], reverse=True)[:top_k]

    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "density": float(nx.density(graph)),
        "is_weakly_connected": bool(nx.is_weakly_connected(graph)),
        "top_in_degree": [{"node": n, "score": round(s, 6)} for n, s in top_nodes],
    }
