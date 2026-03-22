# iterative-context/src/iterative_context/traversal.py

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol, cast

from iterative_context.expansion import expand_node
from iterative_context.graph_models import Graph, GraphEvent, GraphNode
from iterative_context.test_helpers.graph_dsl import apply_events

ScoreFn = Callable[[GraphNode, Graph, int], float]


def get_frontier(graph: Graph) -> list[GraphNode]:
    """Return pending nodes eligible for expansion, sorted deterministically by id."""
    frontier: list[GraphNode] = []
    for _, data in graph.nodes(data=True):
        node = cast(GraphNode, data["data"] if isinstance(data, dict) and "data" in data else data)
        if getattr(node, "state", None) == "pending":
            frontier.append(node)
    frontier.sort(key=lambda n: n.id)
    return frontier


def score_node(node: GraphNode, graph: Graph, step: int) -> float:
    """Assign a deterministic score to a node."""
    score = 0.0
    if node.state == "pending":
        score += 5.0
    if getattr(node, "state", None) == "anchor":
        score += 10.0

    degree = graph.in_degree(node.id) + graph.out_degree(node.id)
    score += degree * 0.5

    tokens = getattr(node, "tokens", None)
    if tokens is not None:
        score += min(tokens, 50) * 0.1

    return score


def select_next_node(graph: Graph, step: int, score_fn: ScoreFn) -> GraphNode:
    """Select the best node to expand."""
    frontier = get_frontier(graph)
    if not frontier:
        raise ValueError("No pending nodes available for selection")
    return max(frontier, key=lambda n: (score_fn(n, graph, step), n.id))


class ExpansionPolicy(Protocol):
    def expand(self, node: GraphNode, graph: Graph) -> Sequence[GraphEvent]:
        ...


class DefaultExpansionPolicy:
    def expand(self, node: GraphNode, graph: Graph) -> Sequence[GraphEvent]:
        return expand_node(
            {"id": node.id, "state": node.state},
            list(graph.nodes),
        )


def run_traversal(
    graph: Graph, steps: int, expansion_policy: ExpansionPolicy, score_fn: ScoreFn
) -> Graph:
    """Run N expansion steps."""
    for step in range(steps):
        frontier = get_frontier(graph)
        if not frontier:
            break
        node = select_next_node(graph, step, score_fn)
        events = expansion_policy.expand(node, graph)
        apply_events(graph, events)
    return graph


__all__ = [
    "get_frontier",
    "score_node",
    "ScoreFn",
    "select_next_node",
    "ExpansionPolicy",
    "DefaultExpansionPolicy",
    "run_traversal",
]
