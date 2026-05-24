# iterative-context/src/iterative_context/traversal.py

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Protocol, cast

from iterative_context.expansion import expand_node
from iterative_context.graph_models import Graph, GraphEvent, GraphNode
from iterative_context.graph_replay import FrontierCandidate, FrontierDecision, GraphReplayObserver
from iterative_context.scoring import default_score_fn
from iterative_context.selection_policy import CallableSelectionPolicy
from iterative_context.test_helpers.graph_dsl import apply_events
from iterative_context.types import SelectionCallable


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


def select_next_node(
    candidates: Sequence[GraphNode],
    graph: Graph,
    step: int,
    score_fn: SelectionCallable,
) -> GraphNode:
    """Select the best node to expand using a scoring callable."""
    graph.graph["last_scores"] = [
        {"id": node.id, "score": score_fn(node, graph, step)} for node in candidates
    ]
    return max(candidates, key=lambda n: (score_fn(n, graph, step), n.id))


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
    graph: Graph,
    steps: int,
    expansion_policy: ExpansionPolicy | None = None,
    score_fn: SelectionCallable | None = None,
    observer: GraphReplayObserver | None = None,
) -> Graph:
    """Run N expansion steps using the provided scoring policy."""
    policy_wrapper = CallableSelectionPolicy(score_fn or default_score_fn)
    active_expansion_policy = expansion_policy or DefaultExpansionPolicy()
    graph.graph.setdefault("graph_steps", [copy.deepcopy(graph)])
    score_history = graph.graph.setdefault("score_history", [])
    for step in range(steps):
        candidates = get_frontier(graph)
        if not candidates:
            break
        ranked_candidates = _rank_frontier_candidates(
            candidates,
            graph,
            step,
            policy_wrapper.score,
        )
        graph.graph["last_scores"] = [
            {"id": candidate.node_id, "score": candidate.score, "rank": candidate.rank}
            for candidate in ranked_candidates
        ]
        node = next(
            candidate
            for candidate in candidates
            if candidate.id == ranked_candidates[0].node_id
        )
        if observer is not None:
            observer.observe_frontier_decision(
                FrontierDecision(
                    step=step,
                    source_id=None,
                    candidates=ranked_candidates,
                    visible_candidate_ids=[],
                    selected_id=node.id,
                    pruned_ids=[],
                    frontier_count=len(ranked_candidates),
                    hidden_count=0,
                )
            )
        score_history.append(graph.graph.get("last_scores", []))
        events = active_expansion_policy.expand(node, graph)
        if observer is not None:
            observer.observe_expansion(node.id, list(events), graph)
        apply_events(graph, events)
        graph.graph["graph_steps"].append(copy.deepcopy(graph))
    return graph


def _rank_frontier_candidates(
    candidates: Sequence[GraphNode],
    graph: Graph,
    step: int,
    score_fn: SelectionCallable,
) -> list[FrontierCandidate]:
    scored: list[FrontierCandidate] = []
    for node in candidates:
        raw = cast(object, graph.nodes.get(node.id))
        label = getattr(node, "label", None)
        metadata: dict[str, object] = {}
        source_id: str | None = None
        edge_kind: str | None = None
        if isinstance(raw, dict):
            typed_raw = cast(dict[str, object], raw)
            symbol_value = typed_raw.get("symbol")
            if isinstance(symbol_value, str) and not label:
                label = symbol_value
            if isinstance(symbol_value, str):
                metadata["symbol"] = symbol_value
        source_id, edge_kind = _candidate_source(node.id, graph)
        scored.append(
            FrontierCandidate(
                node_id=node.id,
                label=label,
                kind=node.kind,
                score=score_fn(node, graph, step),
                rank=0,
                edge_kind=edge_kind,
                source_id=source_id,
                metadata=metadata or None,
            )
        )
    ordered = sorted(
        scored,
        key=lambda candidate: (candidate.score, candidate.node_id),
        reverse=True,
    )
    return [
        FrontierCandidate(
            node_id=candidate.node_id,
            label=candidate.label,
            kind=candidate.kind,
            score=candidate.score,
            rank=index,
            edge_kind=candidate.edge_kind,
            source_id=candidate.source_id,
            metadata=candidate.metadata,
        )
        for index, candidate in enumerate(ordered, start=1)
    ]


def _candidate_source(
    node_id: str,
    graph: Graph,
) -> tuple[str | None, str | None]:
    edges: list[tuple[str, str | None, int]] = []
    for source, _, raw in graph.in_edges(node_id, data=True):
        edge_kind: str | None = None
        typed_raw = cast(dict[str, object], raw)
        embedded = typed_raw.get("data")
        if hasattr(embedded, "kind"):
            edge_kind = cast(str | None, getattr(embedded, "kind", None))
        raw_kind = typed_raw.get("kind")
        if edge_kind is None and isinstance(raw_kind, str):
            edge_kind = raw_kind
        source_id = cast(str, source)
        source_data = cast(dict[str, object], graph.nodes.get(source_id, {}))
        source_state_rank = 2
        node_data = source_data.get("data")
        state = getattr(node_data, "state", None)
        if state == "resolved":
            source_state_rank = 0
        elif state == "anchor":
            source_state_rank = 1
        edges.append((source_id, edge_kind, source_state_rank))
    if not edges:
        return None, None
    best_source, best_kind, _ = min(edges, key=lambda item: (item[2], item[0]))
    return best_source, best_kind


__all__ = [
    "get_frontier",
    "score_node",
    "select_next_node",
    "ExpansionPolicy",
    "DefaultExpansionPolicy",
    "run_traversal",
]
