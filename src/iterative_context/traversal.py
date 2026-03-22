# iterative-context/src/iterative_context/traversal.py

from __future__ import annotations

import copy
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
    candidates = get_frontier(graph)
    if not candidates:
        raise ValueError("No pending nodes available for selection")
    scored = [(node, score_fn(node, graph, step)) for node in candidates]
    graph.graph["last_scores"] = [{"id": node.id, "score": score} for node, score in scored]
    return max(scored, key=lambda x: (x[1], x[0].id))[0]


class ExpansionPolicy(Protocol):
    def expand(self, node: GraphNode, graph: Graph) -> Sequence[GraphEvent]:
        ...


class DefaultExpansionPolicy:
    def expand(self, node: GraphNode, graph: Graph) -> Sequence[GraphEvent]:
        return expand_node(
            {"id": node.id, "state": node.state},
            graph,
        )


def run_traversal(
    graph: Graph, steps: int, expansion_policy: ExpansionPolicy, score_fn: ScoreFn
) -> Graph:
    """Run N expansion steps."""
    graph.graph.setdefault("graph_steps", [copy.deepcopy(graph)])
    score_history = graph.graph.setdefault("score_history", [])
    for step in range(steps):
        candidates = get_frontier(graph)
        if not candidates:
            break
        node = select_next_node(graph, step, score_fn)
        score_history.append(graph.graph.get("last_scores", []))
        events = expansion_policy.expand(node, graph)
        apply_events(graph, events)
        graph.graph["graph_steps"].append(copy.deepcopy(graph))
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
