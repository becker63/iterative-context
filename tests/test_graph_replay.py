# pyright: reportPrivateUsage=false, reportMissingTypeStubs=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportGeneralTypeIssues=false, reportUnusedFunction=false
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from pytest_snapshot.plugin import Snapshot

from iterative_context import exploration, server
from iterative_context.exploration import _repo_signature, _set_active_graph
from iterative_context.graph_models import AddNodesEvent, Graph, PendingNode, UpdateNodeEvent
from iterative_context.graph_replay import (
    FrontierCandidate,
    FrontierDecision,
    GraphReplayRecorder,
)
from iterative_context.server import IterativeContextToolRuntime
from iterative_context.test_helpers.graph_dsl import build_graph


@pytest.fixture(autouse=True)
def _reset_active_graph() -> Iterator[None]:
    exploration._clear_active_graph()
    server._default_runtime.clear_policy_install()
    yield
    exploration._clear_active_graph()
    server._default_runtime.clear_policy_install()


def _make_graph_with_symbols() -> Graph:
    graph = build_graph(
        {
            "nodes": [
                {"id": "A", "kind": "symbol", "state": "pending"},
                {"id": "B", "kind": "symbol", "state": "pending"},
                {"id": "C", "kind": "symbol", "state": "pending"},
                {"id": "D", "kind": "symbol", "state": "pending"},
                {"id": "E", "kind": "symbol", "state": "pending"},
            ],
            "edges": [
                {"source": "A", "target": "B", "kind": "calls"},
                {"source": "B", "target": "C", "kind": "references"},
            ],
        }
    )
    graph.nodes["A"]["symbol"] = "expand_node"
    graph.nodes["A"]["file"] = "src/iterative_context/expansion.py"
    graph.nodes["B"]["symbol"] = "expand_other"
    graph.nodes["B"]["file"] = "src/iterative_context/other.py"
    graph.nodes["C"]["symbol"] = "fetch_user_data"
    graph.nodes["D"]["symbol"] = "fetch_user_info"
    graph.nodes["E"]["symbol"] = "fuzzy_target"
    return graph


def _activate_graph_with_symbols() -> None:
    graph = _make_graph_with_symbols()
    signature = _repo_signature(Path.cwd())
    _set_active_graph(graph, repo_root=Path.cwd().resolve(), signature=signature)


def _write_policy(root: Path, *, score_value: float = 7.0) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "policy.py"
    path.write_text(
        (
            "def lookahead_policy(node, graph, step):\n"
            "    if node.id == 'E':\n"
            "        return 20.0\n"
            f"    return {score_value}\n"
            "\n"
            "def resolve_policy(query, candidates, state):\n"
            "    exact = [\n"
            "        candidate\n"
            "        for candidate in candidates\n"
            "        if (candidate.metadata or {}).get('match_source') == 'exact_symbol'\n"
            "    ]\n"
            "    if len(exact) == 1:\n"
            "        chosen = exact[0]\n"
            "        return {\n"
            "            'status': 'resolved',\n"
            "            'query_label': query,\n"
            "            'candidates': [chosen],\n"
            "            'selected_anchor_id': chosen.node_id,\n"
            "            'reason': 'exact_symbol_match',\n"
            "        }\n"
            "    if query == 'fetch_user':\n"
            "        return {\n"
            "            'status': 'ambiguous',\n"
            "            'query_label': query,\n"
            "            'candidates': candidates[:2],\n"
            "            'selected_anchor_id': None,\n"
            "            'reason': 'ambiguous_top_candidates',\n"
            "        }\n"
            "    if query == 'zzz_no_match':\n"
            "        return {\n"
            "            'status': 'not_found',\n"
            "            'query_label': query,\n"
            "            'candidates': [],\n"
            "            'selected_anchor_id': None,\n"
            "            'reason': 'no_candidates',\n"
            "        }\n"
            "    chosen = candidates[0]\n"
            "    return {\n"
            "        'status': 'resolved',\n"
            "        'query_label': query,\n"
            "        'candidates': candidates[:3],\n"
            "        'selected_anchor_id': chosen.node_id,\n"
            "        'reason': 'top_candidate',\n"
            "        'shallow_expand': False,\n"
            "    }\n"
        ),
        encoding="utf-8",
    )
    return path


async def _install_test_policy(
    tmp_path: Path,
    *,
    runtime: IterativeContextToolRuntime | None = None,
) -> IterativeContextToolRuntime:
    policy_path = _write_policy(tmp_path)
    tool_runtime = runtime or server._default_runtime
    payload = tool_runtime.admin_install_policy(
        {"policy_path": str(policy_path), "policy_id": "policy-v1"}
    )
    assert payload["ok"] is True
    return tool_runtime


async def _collect(
    runtime: IterativeContextToolRuntime,
    *,
    trace_id: str = "round-001/match-a/challenger/attempt-001",
    metadata: dict[str, object] | None = None,
    clear_after_collect: bool = True,
) -> dict[str, Any]:
    response = await runtime.call_tool(
        "collect_graph_trace",
        {
            "trace_id": trace_id,
            "metadata": metadata or {},
            "clear_after_collect": clear_after_collect,
        },
    )
    return cast(dict[str, Any], json.loads(response[0].text))


@pytest.mark.anyio
async def test_collect_graph_trace_empty_trace_valid(tmp_path: Path) -> None:
    runtime = await _install_test_policy(tmp_path, runtime=IterativeContextToolRuntime())

    payload = await _collect(
        runtime,
        metadata={"match_id": "match-a", "role": "challenger", "attempt_id": "attempt-001"},
    )

    assert payload["kind"] == "searchbench.graph_replay.v1"
    assert payload["source"] == "iterative-context"
    assert payload["traceId"] == "round-001/match-a/challenger/attempt-001"
    assert payload["matchId"] == "match-a"
    assert payload["role"] == "challenger"
    assert payload["attemptId"] == "attempt-001"
    assert payload["events"] == []
    assert payload["summary"]["eventCount"] == 0


@pytest.mark.anyio
async def test_collect_graph_trace_clear_after_collect_resets_events(tmp_path: Path) -> None:
    _activate_graph_with_symbols()
    runtime = await _install_test_policy(tmp_path, runtime=IterativeContextToolRuntime())

    await runtime.call_tool("resolve", {"symbol": "expand_node"})
    payload = await _collect(runtime)
    assert payload["summary"]["eventCount"] > 0

    second = await _collect(runtime)
    assert second["events"] == []
    assert second["summary"]["eventCount"] == 0


@pytest.mark.anyio
async def test_collect_graph_trace_clear_false_is_idempotent(tmp_path: Path) -> None:
    _activate_graph_with_symbols()
    runtime = await _install_test_policy(tmp_path, runtime=IterativeContextToolRuntime())

    await runtime.call_tool("resolve", {"symbol": "expand_node"})
    first = await _collect(runtime, clear_after_collect=False)
    second = await _collect(runtime, clear_after_collect=False)

    assert first["events"] == second["events"]
    assert first["summary"] == second["summary"]


@pytest.mark.anyio
async def test_collect_graph_trace_does_not_inline_into_normal_tool_responses(
    tmp_path: Path,
) -> None:
    _activate_graph_with_symbols()
    runtime = await _install_test_policy(tmp_path, runtime=IterativeContextToolRuntime())

    for tool_name, arguments in (
        ("resolve", {"symbol": "expand_node"}),
        ("expand", {"node_id": "A", "depth": 1}),
        ("resolve_and_expand", {"symbol": "expand_node", "depth": 1}),
    ):
        response = await runtime.call_tool(tool_name, arguments)
        payload = cast(dict[str, Any], json.loads(response[0].text))
        assert "events" not in payload
        assert "summary" not in payload


@pytest.mark.anyio
async def test_collect_graph_trace_ambiguous_does_not_fabricate_selected_anchor(
    tmp_path: Path,
) -> None:
    _activate_graph_with_symbols()
    runtime = await _install_test_policy(tmp_path, runtime=IterativeContextToolRuntime())

    await runtime.call_tool("resolve", {"query": "fetch_user"})
    payload = await _collect(runtime)

    node_events = [event for event in payload["events"] if event["type"] == "addNodes"]
    update_events = [event for event in payload["events"] if event["type"] == "updateNode"]
    assert node_events
    assert all(event["patch"].get("state") != "anchor" for event in update_events)


@pytest.mark.anyio
async def test_collect_graph_trace_not_found_has_no_anchor_nodes(tmp_path: Path) -> None:
    _activate_graph_with_symbols()
    runtime = await _install_test_policy(tmp_path, runtime=IterativeContextToolRuntime())

    await runtime.call_tool("resolve", {"query": "zzz_no_match"})
    payload = await _collect(runtime)

    assert payload["summary"]["anchorNotFound"] == 1
    assert all(event["type"] != "addNodes" for event in payload["events"])


@pytest.mark.anyio
async def test_collect_graph_trace_invalid_metadata_is_typed_error(tmp_path: Path) -> None:
    runtime = await _install_test_policy(tmp_path, runtime=IterativeContextToolRuntime())

    response = await runtime.call_tool(
        "collect_graph_trace",
        {"trace_id": "round-001/match-a/challenger/attempt-001", "metadata": "bad"},
    )
    payload = cast(dict[str, Any], json.loads(response[0].text))

    assert payload["error_code"] == "graph_replay_request_invalid"


@pytest.mark.anyio
async def test_collect_graph_trace_invalid_recorder_state_is_typed_error(
    tmp_path: Path,
) -> None:
    runtime = await _install_test_policy(tmp_path, runtime=IterativeContextToolRuntime())
    runtime._graph_replay._events = cast(Any, "bad")

    response = await runtime.call_tool(
        "collect_graph_trace",
        {"trace_id": "round-001/match-a/challenger/attempt-001"},
    )
    payload = cast(dict[str, Any], json.loads(response[0].text))

    assert payload["error_code"] == "graph_replay_invalid"


@pytest.mark.anyio
async def test_resolve_and_expand_trace_snapshot(tmp_path: Path, snapshot: Snapshot) -> None:
    _activate_graph_with_symbols()
    runtime = await _install_test_policy(tmp_path, runtime=IterativeContextToolRuntime())

    await runtime.call_tool("resolve_and_expand", {"symbol": "expand_node", "depth": 2})
    payload = await _collect(
        runtime,
        metadata={
            "match_id": "match-a",
            "role": "challenger",
            "attempt_id": "attempt-001",
            "round_id": "round-001",
        },
    )

    assert str(Path.cwd()) not in json.dumps(payload, sort_keys=True)
    snapshot.assert_match(
        json.dumps(payload, sort_keys=True, indent=2),
        "graph-replay.json",
    )


def test_frontier_recorder_adds_hidden_selected_candidate_before_resolved() -> None:
    recorder = GraphReplayRecorder(max_visible_pending=2)
    recorder.observe_frontier_decision(
        FrontierDecision(
            step=0,
            candidates=[
                FrontierCandidate("A", "alpha", "symbol", 5.0, 1),
                FrontierCandidate("B", "beta", "symbol", 4.0, 2),
                FrontierCandidate("C", "charlie", "symbol", 3.0, 3),
            ],
            selected_node_id="C",
        )
    )
    recorder.observe_expansion(
        "C",
        [UpdateNodeEvent(id="C", patch={"state": "resolved", "tokens": 1})],
        build_graph({"nodes": [{"id": "C", "kind": "symbol", "state": "pending"}]}),
    )

    payload = recorder.collect(
        trace_id="trace-001",
        metadata={},
        policy_id="policy-v1",
        clear_after_collect=False,
    )

    add_nodes = next(event for event in payload["events"] if event["type"] == "addNodes")
    update = next(event for event in payload["events"] if event["type"] == "updateNode")
    assert [node["id"] for node in add_nodes["nodes"]] == ["A", "C"]
    assert update["id"] == "C"
    assert update["patch"]["state"] == "resolved"


def test_recorder_prune_node_emits_pruned_update() -> None:
    recorder = GraphReplayRecorder()
    recorder.add_nodes(
        [
            {"id": "A", "kind": "symbol", "state": "pending", "label": "alpha"},
        ],
        reason="frontier_visible",
    )
    recorder.prune_node("A", reason="frontier_pruned")
    payload = recorder.collect(
        trace_id="trace-002",
        metadata={},
        policy_id="policy-v1",
        clear_after_collect=False,
    )

    updates = [event for event in payload["events"] if event["type"] == "updateNode"]
    assert len(updates) == 1
    assert updates[0]["patch"]["state"] == "pruned"


def test_observe_expansion_emits_discovered_nodes_and_edges() -> None:
    recorder = GraphReplayRecorder()
    graph = build_graph({"nodes": [{"id": "A", "kind": "symbol", "state": "pending"}]})
    recorder.add_nodes(
        [{"id": "A", "kind": "symbol", "state": "pending"}],
        reason="frontier_visible",
    )
    recorder.observe_expansion(
        "A",
        [
            AddNodesEvent(nodes=[PendingNode(id="A_child", kind="symbol")]),
        ],
        graph,
    )
    payload = recorder.collect(
        trace_id="trace-003",
        metadata={},
        policy_id="policy-v1",
        clear_after_collect=False,
    )

    add_nodes = [event for event in payload["events"] if event["type"] == "addNodes"]
    assert any(node["id"] == "A_child" for event in add_nodes for node in event["nodes"])
