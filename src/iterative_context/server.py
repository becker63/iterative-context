# pyright: reportUnusedFunction=false

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from iterative_context import exploration
from iterative_context.serialization import serialize_node
from iterative_context.types import SelectionCallable


def _resolve_symbol(symbol: str) -> dict[str, Any] | None:
    node = exploration.resolve(symbol)
    if node is None:
        return None

    graph = exploration.get_active_graph()
    extras: dict[str, Any] = {}
    if graph is not None and node.id in graph.nodes:
        raw = graph.nodes[node.id]
        extras = {k: v for k, v in raw.items() if k != "data"}

    return serialize_node(node, extras)


def create_mcp_server(score_fn: SelectionCallable | None = None) -> FastMCP:
    mcp = FastMCP("iterative-context", json_response=True)

    @mcp.tool()  # type: ignore[misc]
    def resolve(symbol: str) -> dict[str, Any]:
        exploration.ensure_graph_loaded()
        node = _resolve_symbol(symbol)
        return {"node": node}

    @mcp.tool()  # type: ignore[misc]
    def expand(node_id: str, depth: int) -> dict[str, Any]:
        exploration.ensure_graph_loaded()
        graph = exploration.expand(node_id=node_id, depth=depth, score_fn=score_fn)
        return {"graph": graph}

    @mcp.tool()  # type: ignore[misc]
    def resolve_and_expand(symbol: str, depth: int) -> dict[str, Any]:
        exploration.ensure_graph_loaded()

        node = _resolve_symbol(symbol)
        if node is None:
            return {"graph": {"nodes": [], "edges": [], "metadata": {}}}

        return {"graph": exploration.expand(node["id"], depth=depth, score_fn=score_fn)}

    return mcp


def run_server(score_fn: SelectionCallable | None = None) -> None:
    mcp = create_mcp_server(score_fn)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
