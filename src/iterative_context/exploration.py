# pyright: reportUnusedFunction=false

from copy import deepcopy
from typing import Literal, cast

from iterative_context.graph_models import Graph, GraphNode
from iterative_context.scoring import score_v1
from iterative_context.store import GraphStore
from iterative_context.test_helpers.snapshot_graph import normalize_graph
from iterative_context.traversal import DefaultExpansionPolicy, run_traversal

GraphSnapshotDict = dict[str, list[dict[str, object]]]
Strategy = Literal["default"]

_active_graph: Graph | None = None
_active_store: GraphStore | None = None


def _set_active_graph(graph: Graph) -> None:  # noqa: PLW0603
    global _active_graph, _active_store  # noqa: PLW0603
    _active_graph = graph
    _active_store = GraphStore(graph)


def resolve(symbol: str) -> GraphNode | None:
    """Public resolve: pure lookup via the active store."""
    if _active_store is None:
        return None
    return _active_store.resolve(symbol)


def expand(
    node_id: str,
    depth: int = 1,
    policy: Strategy = "default",
) -> GraphSnapshotDict:
    """
    Deterministic bounded expansion using internal traversal.

    Returns a normalized GraphSnapshot (dict) of the explored subgraph.
    """
    if _active_graph is None:
        return {"nodes": [], "edges": []}

    # Limit traversal to the connected neighborhood to avoid unrelated drift.
    base_reachable: set[str] = set()
    queue: list[tuple[str, int]] = [(node_id, 0)]
    while queue:
        current, dist = queue.pop(0)
        if current in base_reachable:
            continue
        base_reachable.add(current)
        if dist >= depth:
            continue
        for succ in _active_graph.successors(current):
            queue.append((cast(str, succ), dist + 1))
        for pred in _active_graph.predecessors(current):
            queue.append((cast(str, pred), dist + 1))

    working = cast(Graph, deepcopy(_active_graph.subgraph(base_reachable).copy()))
    steps = max(depth, 0)

    run_traversal(
        working,
        steps=steps,
        expansion_policy=DefaultExpansionPolicy(),
        score_fn=score_v1,
    )

    visited: set[str] = set()
    frontier: list[tuple[str, int]] = [(node_id, 0)]
    while frontier:
        current, dist = frontier.pop(0)
        if current in visited:
            continue
        visited.add(current)
        if dist >= steps:
            continue
        for succ in working.successors(current):
            frontier.append((cast(str, succ), dist + 1))
        for pred in working.predecessors(current):
            frontier.append((cast(str, pred), dist + 1))

    subgraph = working.subgraph(visited).copy()
    return normalize_graph(subgraph)


def resolve_and_expand(
    symbol: str,
    depth: int = 1,
    policy: Strategy = "default",
) -> GraphSnapshotDict:
    """Composition only: resolve first, then expand deterministically."""
    node = resolve(symbol)
    if node is None:
        return {"nodes": [], "edges": []}
    return expand(node.id, depth=depth, policy=policy)
