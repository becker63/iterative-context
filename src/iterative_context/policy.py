"""Example behavior policy."""

from __future__ import annotations

from iterative_context.anchor_policy import (
    AnchorCandidate,
    AnchorDecision,
    ResolvePolicyState,
    query_id_for_label,
)
from iterative_context.graph_models import Graph, GraphNode
from iterative_context.scoring import score_degree


def resolve_policy(
    query: str,
    candidates: list[AnchorCandidate],
    state: ResolvePolicyState,
) -> AnchorDecision:
    del state
    if not candidates:
        return AnchorDecision(
            status="not_found",
            query_id=query_id_for_label(query),
            query_label=query,
            candidates=[],
            selected_anchor_id=None,
            reason="no_candidates",
        )
    chosen = candidates[0]
    return AnchorDecision(
        status="resolved",
        query_id=query_id_for_label(query),
        query_label=query,
        candidates=candidates[:3],
        selected_anchor_id=chosen.node_id,
        reason="top_candidate",
    )


def lookahead_policy(node: GraphNode, graph: Graph, step: int) -> float:
    """Deterministic traversal lookahead policy used by the example module."""
    return score_degree(node, graph, step)


__all__ = ["resolve_policy", "lookahead_policy"]
