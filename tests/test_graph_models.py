# pyright: reportMissingTypeStubs=false, reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
"""Tests for the deterministic graph DSL and snapshot integration."""

from graph_dsl import EventSpec, GraphType, build_graph, replay_with_snapshots
from snapshot_graph import GraphSnapshot, normalize_graph


def test_node_variants(snapshot_graph: GraphSnapshot):
    g: GraphType = build_graph({"nodes": [{"id": "n1", "kind": "symbol", "state": "pending"}]})
    snapshot_graph.assert_graph(g)


def test_edge_and_events(snapshot_graph: GraphSnapshot):
    events: list[EventSpec] = [
        {"type": "addNodes", "nodes": ["n5"]},
        {"type": "addEdges", "edges": [{"source": "n1", "target": "n2", "kind": "calls"}]},
        {"type": "updateNode", "id": "n5", "patch": {"state": "resolved", "tokens": 3}},
        {"type": "iteration", "step": 1},
    ]
    g: GraphType = build_graph(
        {
            "nodes": [
                {"id": "n5", "kind": "symbol", "state": "pending"},
                {"id": "n1", "kind": "symbol", "state": "pending"},
                {"id": "n2", "kind": "symbol", "state": "pending"},
            ],
            "edges": [],
        }
    )
    steps = replay_with_snapshots(g, events)
    snapshot_graph.assert_graph(steps[-1])
    snapshot_graph._assert([normalize_graph(step) for step in steps], "graph_steps")
