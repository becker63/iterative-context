from iterative_context.test_helpers import GraphSnapshot, GraphType, build_graph
from iterative_context.traversal import DefaultExpansionPolicy, run_traversal, select_next_node


def test_selects_highest_score():
    spec = {
        "nodes": [
            {"id": "A", "kind": "symbol", "state": "pending", "tokens": 0},
            {"id": "B", "kind": "symbol", "state": "pending", "tokens": 20},
            {"id": "C", "kind": "symbol", "state": "pending", "tokens": 5},
        ],
        "edges": [
            {"source": "A", "target": "B", "kind": "calls"},
            {"source": "B", "target": "C", "kind": "calls"},
        ],
    }
    graph = build_graph(spec)  # type: ignore[arg-type]

    selected = select_next_node(graph, step=0)
    assert selected.id == "B"


def test_selection_deterministic():
    spec = {
        "nodes": [
            {"id": "A", "kind": "symbol", "state": "pending", "tokens": 0},
            {"id": "B", "kind": "symbol", "state": "pending", "tokens": 10},
        ],
        "edges": [{"source": "A", "target": "B", "kind": "calls"}],
    }
    graph = build_graph(spec)  # type: ignore[arg-type]

    sel1 = select_next_node(graph, step=1)
    sel2 = select_next_node(graph, step=1)
    assert sel1.id == sel2.id


def test_selection_not_affected_by_irrelevant_node():
    base_spec = {
        "nodes": [
            {"id": "A", "kind": "symbol", "state": "pending", "tokens": 0},
            {"id": "B", "kind": "symbol", "state": "pending", "tokens": 30},
        ],
        "edges": [{"source": "A", "target": "B", "kind": "calls"}],
    }
    base_graph = build_graph(base_spec)  # type: ignore[arg-type]
    base_selected = select_next_node(base_graph, step=0)

    noisy_spec = {
        "nodes": [
            *base_spec["nodes"],
            {"id": "Z", "kind": "symbol", "state": "pending", "tokens": 0},
        ],
        "edges": base_spec["edges"],
    }
    noisy_graph = build_graph(noisy_spec)  # type: ignore[arg-type]
    noisy_selected = select_next_node(noisy_graph, step=0)

    assert base_selected.id == noisy_selected.id


def test_traversal_changes_with_scoring(snapshot_graph: GraphSnapshot):
    graph: GraphType = build_graph({"nodes": [{"id": "A", "kind": "symbol", "state": "pending"}]})  # type: ignore[arg-type]
    policy = DefaultExpansionPolicy()
    run_traversal(graph, steps=2, expansion_policy=policy)
    snapshot_graph.assert_graph(graph)  # type: ignore[arg-type]
