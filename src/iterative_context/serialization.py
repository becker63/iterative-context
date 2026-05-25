from __future__ import annotations

from typing import Any, cast

from iterative_context.graph_models import Graph, GraphEdge, GraphNode
from iterative_context.path_ids import file_for_node_id, node_label_for_id


def _unwrap_node(data: Any) -> tuple[GraphNode, dict[str, Any]]:
    if isinstance(data, dict) and "data" in data:
        typed_data = cast(dict[str, Any], data)
        node = cast(GraphNode, typed_data["data"])
        extras = {k: v for k, v in typed_data.items() if k != "data"}
        return node, extras
    if isinstance(data, dict):
        typed_data = cast(dict[str, Any], data)
        node = cast(GraphNode, typed_data)
        return node, typed_data
    return cast(GraphNode, data), {}


def serialize_node(node: GraphNode, extras: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convert a GraphNode into a JSON-serializable dict."""
    extras = extras or {}
    symbol_value = extras.get("symbol")
    file_value = extras.get("file")

    payload: dict[str, Any] = {
        "id": node.id,
        "symbol": symbol_value if isinstance(symbol_value, str) else node_label_for_id(node.id),
        "kind": node.kind,
        "state": node.state,
    }
    if isinstance(file_value, str):
        payload["file"] = file_value
    else:
        inferred_file = file_for_node_id(node.id)
        if inferred_file is not None:
            payload["file"] = inferred_file
    tokens = getattr(node, "tokens", None)
    if tokens is not None:
        payload["tokens"] = tokens
    return payload


def serialize_graph(graph: Graph, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Serialize a NetworkX graph into deterministic JSON structures."""
    nodes: list[dict[str, Any]] = []
    for _, data in graph.nodes(data=True):
        node_obj, extras = _unwrap_node(data)
        nodes.append(serialize_node(node_obj, extras))

    edges: list[dict[str, Any]] = []
    for source, target, raw_data in graph.edges(data=True):
        edge_kind_value: str | None = None
        typed_edge: dict[str, Any] = raw_data
        embedded = typed_edge.get("data")
        if isinstance(embedded, GraphEdge):
            edge_kind_value = embedded.kind
        else:
            raw_kind = typed_edge.get("kind")
            edge_kind_value = raw_kind if isinstance(raw_kind, str) else None
        edges.append(
            {
                "source": cast(str, source),
                "target": cast(str, target),
                "type": edge_kind_value if isinstance(edge_kind_value, str) else "references",
            }
        )

    nodes.sort(key=lambda n: n["id"])
    edges.sort(key=lambda e: (e["source"], e["target"], e["type"]))

    return {"nodes": nodes, "edges": edges, "metadata": metadata or {}}


def _relativize_path(path: str, repo_root: str | None) -> str:
    normalized = path.replace("\\", "/")
    if repo_root:
        root = repo_root.rstrip("/") + "/"
        if normalized.startswith(root):
            return normalized[len(root) :]
    return normalized


def serialize_graph_summary(
    graph: Graph | None,
    metadata: dict[str, Any] | None = None,
    *,
    max_files: int = 48,
    max_symbols: int = 64,
) -> dict[str, Any]:
    """Compact repo-wide graph digest for tool payloads.

    Full node/edge lists are omitted; use the bounded ``graph`` field from
    expand/resolve_and_expand for neighborhood detail.
    """
    meta = dict(metadata or {})
    repo_root = meta.get("repo_root")
    repo_root_str = repo_root if isinstance(repo_root, str) else None

    if graph is None:
        return {
            "format": "summary_v1",
            "node_count": 0,
            "edge_count": 0,
            "nodes_by_kind": {},
            "nodes_by_state": {},
            "edges_by_kind": {},
            "files_sample": [],
            "files_total": 0,
            "symbols_sample": [],
            "symbols_total": 0,
            "metadata": meta,
        }

    nodes_by_kind: dict[str, int] = {}
    nodes_by_state: dict[str, int] = {}
    files: set[str] = set()
    symbols: set[str] = set()

    for _, data in graph.nodes(data=True):
        node_obj, extras = _unwrap_node(data)
        kind = node_obj.kind
        nodes_by_kind[kind] = nodes_by_kind.get(kind, 0) + 1
        nodes_by_state[node_obj.state] = nodes_by_state.get(node_obj.state, 0) + 1

        file_value = extras.get("file")
        if isinstance(file_value, str) and file_value.strip():
            files.add(_relativize_path(file_value.strip(), repo_root_str))
        else:
            node_id = str(node_obj.id)
            if node_id.endswith(".py") or "/" in node_id:
                files.add(_relativize_path(node_id, repo_root_str))

        symbol_value = extras.get("symbol")
        if isinstance(symbol_value, str) and symbol_value.strip():
            symbols.add(symbol_value.strip())
        elif kind in {"symbol", "function", "type"}:
            symbols.add(str(node_obj.id))

    edges_by_kind: dict[str, int] = {}
    for _, _, raw_data in graph.edges(data=True):
        typed_edge: dict[str, Any] = raw_data
        edge_kind_value: str | None = None
        embedded = typed_edge.get("data")
        if isinstance(embedded, GraphEdge):
            edge_kind_value = embedded.kind
        else:
            raw_kind = typed_edge.get("kind")
            edge_kind_value = raw_kind if isinstance(raw_kind, str) else None
        edge_kind = edge_kind_value if isinstance(edge_kind_value, str) else "references"
        edges_by_kind[edge_kind] = edges_by_kind.get(edge_kind, 0) + 1

    files_sorted = sorted(files)
    symbols_sorted = sorted(symbols)
    files_total = len(files_sorted)
    symbols_total = len(symbols_sorted)

    payload: dict[str, Any] = {
        "format": "summary_v1",
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "nodes_by_kind": dict(sorted(nodes_by_kind.items())),
        "nodes_by_state": dict(sorted(nodes_by_state.items())),
        "edges_by_kind": dict(sorted(edges_by_kind.items())),
        "files_sample": files_sorted[: max(0, max_files)],
        "files_total": files_total,
        "symbols_sample": symbols_sorted[: max(0, max_symbols)],
        "symbols_total": symbols_total,
        "metadata": meta,
    }
    if files_total > max_files:
        payload["files_truncated"] = True
    if symbols_total > max_symbols:
        payload["symbols_truncated"] = True
    return payload


__all__ = ["serialize_node", "serialize_graph", "serialize_graph_summary"]
