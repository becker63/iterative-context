"""MCP surface integration tests."""
# pyright: reportPrivateUsage=false
from __future__ import annotations

import json

import pytest

from iterative_context import server
from iterative_context.exploration import _set_active_graph
from iterative_context.graph_models import Graph, GraphNode
from iterative_context.server import IterativeContextToolRuntime, call_tool, list_tools
from iterative_context.test_helpers.graph_dsl import build_graph


def _make_graph_with_symbols() -> Graph:
    graph = build_graph(
        {
            "nodes": [
                {"id": "A", "kind": "symbol", "state": "pending"},
                {"id": "B", "kind": "symbol", "state": "pending"},
            ],
            "edges": [
                {"source": "A", "target": "B", "kind": "calls"},
            ],
        }
    )
    graph.nodes["A"]["symbol"] = "expand_node"
    graph.nodes["A"]["file"] = "src/iterative_context/expansion.py"
    graph.nodes["B"]["symbol"] = "other_symbol"
    graph.nodes["B"]["file"] = "src/iterative_context/other.py"
    return graph


@pytest.mark.anyio
async def test_list_tools_definitions() -> None:
    tools = await list_tools()
    names = {tool.name for tool in tools}
    assert names == {"resolve", "expand", "resolve_and_expand"}

    resolve_tool = next(tool for tool in tools if tool.name == "resolve")
    assert resolve_tool.inputSchema["required"] == ["symbol"]
    assert resolve_tool.inputSchema["properties"]["symbol"]["type"] == "string"

    expand_tool = next(tool for tool in tools if tool.name == "expand")
    assert expand_tool.inputSchema["properties"]["depth"]["type"] == "integer"
    assert "node_id" in expand_tool.inputSchema["required"]


@pytest.mark.anyio
async def test_call_tool_resolve_serializes_node() -> None:
    _set_active_graph(_make_graph_with_symbols())

    response = await call_tool("resolve", {"symbol": "expand_node"})
    payload = json.loads(response[0].text)

    assert payload["node"]["id"] == "A"
    assert payload["node"]["symbol"] == "expand_node"
    assert "file" in payload["node"]
    assert payload["full_graph"]["nodes"]
    assert payload["score_source"] == "local_policy"


@pytest.mark.anyio
async def test_call_tool_expand_returns_graph() -> None:
    _set_active_graph(_make_graph_with_symbols())

    response = await call_tool("expand", {"node_id": "A", "depth": 1})
    payload = json.loads(response[0].text)
    graph = payload["graph"]

    assert graph["metadata"]["expanded_from"] == "A"
    assert graph["metadata"]["depth"] == 1
    assert graph["nodes"]
    assert payload["full_graph"]["nodes"]
    assert payload["score_source"] == "local_policy"


@pytest.mark.anyio
async def test_call_tool_resolve_and_expand() -> None:
    _set_active_graph(_make_graph_with_symbols())

    response = await call_tool("resolve_and_expand", {"symbol": "expand_node", "depth": 1})
    payload = json.loads(response[0].text)

    assert payload["graph"]["metadata"]["expanded_from"] == "A"
    assert payload["graph"]["nodes"]
    assert payload["full_graph"]["nodes"]
    assert payload["score_source"] == "local_policy"


@pytest.mark.anyio
async def test_call_tool_unknown_returns_error() -> None:
    _set_active_graph(_make_graph_with_symbols())

    response = await call_tool("unknown_tool", {})
    payload = json.loads(response[0].text)

    assert "error" in payload
    assert "unknown" in payload["error"].lower()
    assert payload["score_source"] == "local_policy"


@pytest.mark.anyio
async def test_runtime_uses_injected_score_fn(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_active_graph(_make_graph_with_symbols())
    score_calls: list[str] = []

    def score_fn(node: GraphNode, graph: Graph, step: int) -> float:
        score_calls.append(node.id)
        return 1.0

    # If the injected scorer is used, the local policy should never be consulted.
    def fail_local_policy() -> None:  # pragma: no cover - defensive guard
        raise AssertionError("local policy should not be loaded when score_fn is injected")

    monkeypatch.setattr(server, "load_local_policy", fail_local_policy)

    runtime = IterativeContextToolRuntime(score_fn=score_fn)
    response = await runtime.call_tool("expand", {"node_id": "A", "depth": 1})
    payload = json.loads(response[0].text)

    assert score_calls
    assert payload["graph"]["metadata"]["expanded_from"] == "A"
    assert payload["score_source"] == "injected"


@pytest.mark.anyio
async def test_runtime_uses_local_policy_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_active_graph(_make_graph_with_symbols())
    score_calls: list[str] = []

    def local_score(node: GraphNode, graph: Graph, step: int) -> float:
        score_calls.append(node.id)
        return 2.0

    monkeypatch.setattr(server, "load_local_policy", lambda: local_score)

    runtime = IterativeContextToolRuntime()
    response = await runtime.call_tool("expand", {"node_id": "A", "depth": 1})
    payload = json.loads(response[0].text)

    assert score_calls
    assert payload["score_source"] == "local_policy"


@pytest.mark.anyio
async def test_runtime_falls_back_to_default_when_policy_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_active_graph(_make_graph_with_symbols())
    score_calls: list[str] = []

    def default_score(node: GraphNode, graph: Graph, step: int) -> float:
        score_calls.append(node.id)
        return 3.0

    monkeypatch.setattr(server, "load_local_policy", lambda: None)
    monkeypatch.setattr(server, "default_score_fn", default_score)

    runtime = IterativeContextToolRuntime()
    response = await runtime.call_tool("expand", {"node_id": "A", "depth": 1})
    payload = json.loads(response[0].text)

    assert score_calls
    assert payload["score_source"] == "default"
