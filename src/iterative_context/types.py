from __future__ import annotations

from collections.abc import Callable

from iterative_context.anchor_policy import (
    AnchorCandidate,
    AnchorDecision,
    ResolvePolicyState,
)
from iterative_context.graph_models import Graph, GraphNode

LookaheadPolicyCallable = Callable[[GraphNode, Graph, int], float]
ResolvePolicyCallable = Callable[
    [str, list[AnchorCandidate], ResolvePolicyState],
    AnchorDecision | dict[str, object],
]
SelectionCallable = LookaheadPolicyCallable


__all__ = ["LookaheadPolicyCallable", "ResolvePolicyCallable", "SelectionCallable"]
