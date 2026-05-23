from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, cast

POLICY_INTERFACE_VERSION = "iterative_context.behavior_policy.v1"


@dataclass(frozen=True)
class AnchorCandidate:
    node_id: str
    label: str | None
    kind: str | None
    score: float | None
    rank: int | None
    reason: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class AnchorDecision:
    status: Literal["resolved", "ambiguous", "not_found"]
    query_id: str
    query_label: str | None
    candidates: list[AnchorCandidate]
    selected_anchor_id: str | None
    reason: str | None
    shallow_expand: bool = False
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class ResolveCandidateCounts:
    total: int
    exact_symbol: int
    fuzzy_symbol: int
    file_substring: int


@dataclass(frozen=True)
class ResolvePolicyState:
    query_label: str
    repo_metadata: dict[str, object]
    candidate_limit: int
    fuzzy_min_score: float
    fuzzy_gap: float
    candidate_counts: ResolveCandidateCounts
    active_policy_id: str | None
    policy_interface_version: str


def query_id_for_label(query: str) -> str:
    q = (query or "").strip()
    digest = hashlib.sha256(q.encode("utf-8")).hexdigest()
    return f"anchor-query:{digest[:16]}"


def anchor_candidate_to_dict(candidate: AnchorCandidate) -> dict[str, object]:
    payload: dict[str, object] = {
        "node_id": candidate.node_id,
        "label": candidate.label,
        "kind": candidate.kind,
        "score": candidate.score,
        "rank": candidate.rank,
        "reason": candidate.reason,
    }
    if candidate.metadata is not None:
        payload["metadata"] = candidate.metadata
    return payload


def anchor_decision_to_dict(decision: AnchorDecision) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": decision.status,
        "query_id": decision.query_id,
        "query_label": decision.query_label,
        "candidates": [anchor_candidate_to_dict(candidate) for candidate in decision.candidates],
        "selected_anchor_id": decision.selected_anchor_id,
        "reason": decision.reason,
        "shallow_expand": decision.shallow_expand,
    }
    if decision.metadata is not None:
        payload["metadata"] = decision.metadata
    return payload


def _coerce_metadata(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("metadata must be a mapping when provided")
    return cast(dict[str, object], value)


def anchor_candidate_from_value(value: object) -> AnchorCandidate:
    if isinstance(value, AnchorCandidate):
        return value
    if not isinstance(value, dict):
        raise ValueError("anchor candidate must be a dict or AnchorCandidate")
    typed_value = cast(dict[str, object], value)

    node_id = typed_value.get("node_id")
    if not isinstance(node_id, str) or not node_id.strip():
        raise ValueError("anchor candidate node_id must be a non-empty string")

    label = typed_value.get("label")
    kind = typed_value.get("kind")
    score = typed_value.get("score")
    rank = typed_value.get("rank")
    reason = typed_value.get("reason")
    return AnchorCandidate(
        node_id=node_id.strip(),
        label=label if isinstance(label, str) else None,
        kind=kind if isinstance(kind, str) else None,
        score=float(score) if isinstance(score, int | float) else None,
        rank=int(rank) if isinstance(rank, int) else None,
        reason=reason if isinstance(reason, str) else None,
        metadata=_coerce_metadata(typed_value.get("metadata")),
    )


def anchor_decision_from_value(
    value: object,
    *,
    query: str,
    fallback_candidates: list[AnchorCandidate],
) -> AnchorDecision:
    if isinstance(value, AnchorDecision):
        decision = value
    elif isinstance(value, dict):
        typed_value = cast(dict[str, object], value)
        status = typed_value.get("status")
        if status not in {"resolved", "ambiguous", "not_found"}:
            raise ValueError("anchor decision status must be resolved, ambiguous, or not_found")
        selected_anchor_id = typed_value.get("selected_anchor_id")
        if selected_anchor_id is not None and not isinstance(selected_anchor_id, str):
            raise ValueError("selected_anchor_id must be a string when provided")

        raw_candidates = typed_value.get("candidates", fallback_candidates)
        if not isinstance(raw_candidates, list):
            raise ValueError("anchor decision candidates must be a list")
        raw_candidate_items = cast(list[object], raw_candidates)
        candidates = [anchor_candidate_from_value(item) for item in raw_candidate_items]
        query_id = typed_value.get("query_id")
        query_label = typed_value.get("query_label")
        reason = typed_value.get("reason")
        shallow_expand = typed_value.get("shallow_expand", False)
        if not isinstance(shallow_expand, bool):
            raise ValueError("anchor decision shallow_expand must be a bool")
        typed_status = cast(Literal["resolved", "ambiguous", "not_found"], status)
        normalized_query_id = (
            query_id
            if isinstance(query_id, str) and query_id.strip()
            else query_id_for_label(query)
        )
        normalized_selected_anchor_id = (
            selected_anchor_id.strip() if isinstance(selected_anchor_id, str) else None
        )
        decision = AnchorDecision(
            status=typed_status,
            query_id=normalized_query_id,
            query_label=query_label if isinstance(query_label, str) else query,
            candidates=candidates,
            selected_anchor_id=normalized_selected_anchor_id,
            reason=reason if isinstance(reason, str) else None,
            shallow_expand=shallow_expand,
            metadata=_coerce_metadata(typed_value.get("metadata")),
        )
    else:
        raise ValueError("anchor decision must be a dict or AnchorDecision")

    if decision.status == "resolved":
        if not decision.selected_anchor_id:
            raise ValueError("resolved anchor decision requires selected_anchor_id")
    elif decision.selected_anchor_id is not None:
        raise ValueError(f"{decision.status} anchor decision must not set selected_anchor_id")
    return decision

__all__ = [
    "POLICY_INTERFACE_VERSION",
    "AnchorCandidate",
    "AnchorDecision",
    "ResolveCandidateCounts",
    "ResolvePolicyState",
    "query_id_for_label",
    "anchor_candidate_to_dict",
    "anchor_candidate_from_value",
    "anchor_decision_to_dict",
    "anchor_decision_from_value",
]
