from __future__ import annotations

from iterative_context.store import GraphStore
from iterative_context.test_helpers.graph_dsl import build_graph


def _store_with_symbols(*symbols: tuple[str, str]) -> GraphStore:
    nodes = [{"id": node_id, "kind": "symbol", "state": "pending"} for node_id, _ in symbols]
    graph = build_graph({"nodes": nodes, "edges": []})
    for node_id, symbol in symbols:
        graph.nodes[node_id]["symbol"] = symbol
    return GraphStore(graph)


def test_resolve_candidates_ambiguous_tie_band() -> None:
    store = _store_with_symbols(
        ("a", "fetch_user_data"),
        ("b", "fetch_user_info"),
    )
    candidates = store.resolve_candidates("fetch_user", limit=8)
    assert len(candidates) == 2
    assert all("node_id" in c and "symbol" in c and "score" in c for c in candidates)


def test_resolve_candidates_below_threshold_returns_top_n() -> None:
    store = _store_with_symbols(
        ("a", "alpha_one"),
        ("b", "beta_two"),
        ("c", "gamma_three"),
    )
    candidates = store.resolve_candidates("zzz_unrelated", limit=3)
    assert len(candidates) == 3
    assert candidates[0]["score"] >= candidates[1]["score"]


def test_resolve_unique_winner_has_no_candidates_payload() -> None:
    store = _store_with_symbols(("a", "expand_node"), ("b", "other_symbol"))
    node = store.resolve("expand_node")
    assert node is not None
    assert store.resolve_candidates("expand_node") == []
