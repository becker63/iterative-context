from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from iterative_context.anchor_policy import AnchorCandidate, AnchorDecision
from iterative_context.graph_models import (
    AddEdgesEvent,
    AddNodesEvent,
    Graph,
    GraphEdge,
    GraphEvent,
    GraphNode,
    UpdateNodeEvent,
)

GRAPH_REPLAY_KIND = "searchbench.graph_replay.v1"
GRAPH_REPLAY_SOURCE = "iterative-context"
DEFAULT_MAX_VISIBLE_PENDING = 4
MAX_METADATA_STRING_LENGTH = 200


@dataclass(frozen=True)
class FrontierCandidate:
    node_id: str
    label: str | None
    kind: str | None
    score: float | None = None
    rank: int | None = None
    edge_kind: str | None = None
    source_id: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class FrontierDecision:
    step: int
    source_id: str | None
    candidates: list[FrontierCandidate]
    visible_candidate_ids: list[str]
    selected_id: str | None
    pruned_ids: list[str]
    frontier_count: int
    hidden_count: int
    reason: str | None = None
    metadata: dict[str, object] | None = None


@dataclass
class GraphReplaySummary:
    event_count: int = 0
    resolve_calls: int = 0
    expand_calls: int = 0
    lookahead_steps: int = 0
    anchor_resolved: int = 0
    anchor_ambiguous: int = 0
    anchor_not_found: int = 0
    visible_frontier_limit: int = DEFAULT_MAX_VISIBLE_PENDING
    frontier_candidate_count: int = 0
    hidden_candidate_count: int = 0
    max_frontier_candidate_count: int = 0
    max_hidden_candidate_count: int = 0

    def to_payload(self) -> dict[str, object]:
        return {
            "eventCount": self.event_count,
            "resolveCalls": self.resolve_calls,
            "expandCalls": self.expand_calls,
            "lookaheadSteps": self.lookahead_steps,
            "anchorResolved": self.anchor_resolved,
            "anchorAmbiguous": self.anchor_ambiguous,
            "anchorNotFound": self.anchor_not_found,
            "visibleCandidateLimit": self.visible_frontier_limit,
            "visibleFrontierLimit": self.visible_frontier_limit,
            "frontierCandidateCount": self.frontier_candidate_count,
            "hiddenCandidateCount": self.hidden_candidate_count,
            "maxFrontierCandidateCount": self.max_frontier_candidate_count,
            "maxHiddenCandidateCount": self.max_hidden_candidate_count,
        }


@dataclass
class GraphReplayPayload:
    trace_id: str
    events: list[dict[str, object]]
    summary: GraphReplaySummary
    match_id: str | None = None
    role: str | None = None
    attempt_id: str | None = None
    policy_id: str | None = None
    source_signature: str | None = None
    graph_signature: str | None = None
    graph_builder: dict[str, object] | None = None
    metadata: dict[str, object] | None = None
    kind: str = GRAPH_REPLAY_KIND
    source: str = GRAPH_REPLAY_SOURCE

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind,
            "source": self.source,
            "traceId": self.trace_id,
            "events": self.events,
            "summary": self.summary.to_payload(),
        }
        if self.match_id is not None:
            payload["matchId"] = self.match_id
        if self.role is not None:
            payload["role"] = self.role
        if self.attempt_id is not None:
            payload["attemptId"] = self.attempt_id
        if self.policy_id is not None:
            payload["policyId"] = self.policy_id
        if self.source_signature is not None:
            payload["sourceSignature"] = self.source_signature
        if self.graph_signature is not None:
            payload["graphSignature"] = self.graph_signature
        if self.graph_builder:
            payload["graphBuilder"] = self.graph_builder
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


class GraphReplayObserver(Protocol):
    def observe_frontier_decision(self, decision: FrontierDecision) -> None:
        ...

    def observe_expansion(self, source_id: str, events: list[GraphEvent], graph: Graph) -> None:
        ...


def _compact_dict(raw: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in raw.items() if value is not None}


def _normalize_kind(raw: str | None) -> str:
    if raw in {"symbol", "function", "file", "type"}:
        return raw
    return "symbol"


def _normalize_node_dict(node: GraphNode) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": node.id,
        "kind": node.kind,
        "state": node.state,
        "label": node.label,
    }
    tokens = getattr(node, "tokens", None)
    if isinstance(tokens, int):
        payload["tokens"] = tokens
    evidence = getattr(node, "evidence", None)
    if evidence is not None and getattr(evidence, "snippet", None):
        payload["evidence"] = _compact_dict(
            {
                "snippet": evidence.snippet,
                "file": evidence.file,
                "startLine": evidence.startLine,
            }
        )
    return _compact_dict(payload)


def _node_from_anchor_candidate(candidate: AnchorCandidate, *, state: str) -> dict[str, object]:
    return _compact_dict(
        {
            "id": candidate.node_id,
            "label": candidate.label,
            "kind": _normalize_kind(candidate.kind),
            "state": state,
        }
    )


def _node_from_frontier_candidate(candidate: FrontierCandidate, *, state: str) -> dict[str, object]:
    return _compact_dict(
        {
            "id": candidate.node_id,
            "label": candidate.label,
            "kind": _normalize_kind(candidate.kind),
            "state": state,
        }
    )


def _frontier_edge_payload(candidate: FrontierCandidate) -> dict[str, object] | None:
    if candidate.source_id is None or candidate.edge_kind is None:
        return None
    return {
        "source": candidate.source_id,
        "target": candidate.node_id,
        "kind": candidate.edge_kind,
    }


def _edge_payload(edge: GraphEdge) -> dict[str, object]:
    return _compact_dict(
        {
            "id": edge.id,
            "source": edge.source,
            "target": edge.target,
            "kind": edge.kind,
            "primary": edge.primary,
        }
    )


class GraphReplayRecorder:
    def __init__(self, *, max_visible_pending: int = DEFAULT_MAX_VISIBLE_PENDING) -> None:
        self.max_visible_pending = max(1, max_visible_pending)
        self.reset()

    def reset(self) -> None:
        self._events: list[dict[str, object]] = []
        self._known_nodes: dict[str, dict[str, object]] = {}
        self._known_edges: set[tuple[str, str, str]] = set()
        self._summary = GraphReplaySummary(
            visible_frontier_limit=self.max_visible_pending,
        )
        self._iteration = 0
        self._visible_pending_ids: list[str] = []

    def note_expand_call(self) -> None:
        self._summary.expand_calls += 1

    def add_nodes(self, nodes: list[dict[str, object]], *, reason: str | None = None) -> None:
        fresh: list[dict[str, object]] = []
        for node in nodes:
            node_id = cast(str | None, node.get("id"))
            if node_id is None or node_id in self._known_nodes:
                continue
            cleaned = _compact_dict(node)
            fresh.append(cleaned)
            self._known_nodes[node_id] = cleaned
        if not fresh:
            return
        event: dict[str, object] = {"type": "addNodes", "nodes": fresh}
        if reason is not None:
            event["reason"] = reason
        self._events.append(event)

    def add_edges(self, edges: list[dict[str, object]], *, reason: str | None = None) -> None:
        fresh: list[dict[str, object]] = []
        for edge in edges:
            source = cast(str | None, edge.get("source"))
            target = cast(str | None, edge.get("target"))
            kind = cast(str | None, edge.get("kind"))
            if source is None or target is None or kind is None:
                continue
            key = (source, target, kind)
            if key in self._known_edges:
                continue
            cleaned = _compact_dict(edge)
            fresh.append(cleaned)
            self._known_edges.add(key)
        if not fresh:
            return
        event: dict[str, object] = {"type": "addEdges", "edges": fresh}
        if reason is not None:
            event["reason"] = reason
        self._events.append(event)

    def update_node(
        self,
        node_id: str,
        patch: dict[str, object],
        *,
        reason: str | None = None,
    ) -> None:
        if node_id not in self._known_nodes:
            return
        cleaned_patch = _compact_dict(patch)
        if not cleaned_patch:
            return
        current = dict(self._known_nodes[node_id])
        current.update(cleaned_patch)
        self._known_nodes[node_id] = current
        state = cleaned_patch.get("state")
        if state in {"resolved", "anchor", "pruned"}:
            self._visible_pending_ids = [
                visible_id for visible_id in self._visible_pending_ids if visible_id != node_id
            ]
        event: dict[str, object] = {"type": "updateNode", "id": node_id, "patch": cleaned_patch}
        if reason is not None:
            event["reason"] = reason
        self._events.append(event)

    def prune_node(self, node_id: str, *, reason: str) -> None:
        self.update_node(node_id, {"state": "pruned"}, reason=reason)

    def set_context(
        self, nodes: list[str], *, reason: str | None = None, tokens: int | None = None
    ) -> None:
        event: dict[str, object] = {"type": "setContext", "nodes": list(dict.fromkeys(nodes))}
        if tokens is not None:
            event["tokens"] = tokens
        if reason is not None:
            event["reason"] = reason
        self._events.append(event)

    def token_add(self, source: str, tokens: int) -> None:
        self._events.append(
            {
                "type": "tokenAdd",
                "source": source,
                "tokens": tokens,
            }
        )

    def observe_anchor_decision(self, decision: AnchorDecision) -> None:
        self._summary.resolve_calls += 1
        self._append_iteration("resolve_query")
        if decision.status == "not_found":
            self._summary.anchor_not_found += 1
            return

        visible = self._bounded_anchor_candidates(
            decision.candidates,
            selected_anchor_id=decision.selected_anchor_id,
        )
        self.add_nodes(
            [
                _node_from_anchor_candidate(candidate, state="pending")
                for candidate in visible
            ],
            reason="anchor_candidates",
        )
        if decision.status == "ambiguous":
            self._summary.anchor_ambiguous += 1
            return

        self._summary.anchor_resolved += 1
        if decision.selected_anchor_id is None:
            return
        self.update_node(
            decision.selected_anchor_id,
            {"state": "anchor"},
            reason="selected_anchor",
        )
        for candidate in visible:
            if candidate.node_id == decision.selected_anchor_id:
                continue
            self.prune_node(candidate.node_id, reason="anchor_candidate_pruned")

    def observe_frontier_decision(self, decision: FrontierDecision) -> None:
        self._summary.lookahead_steps += 1
        self._append_iteration(f"lookahead_step_{decision.step + 1}")
        visible = self._bounded_frontier_candidates(decision)
        hidden_count = max(decision.hidden_count, decision.frontier_count - len(visible), 0)
        self._summary.frontier_candidate_count = decision.frontier_count
        self._summary.hidden_candidate_count = hidden_count
        self._summary.max_frontier_candidate_count = max(
            self._summary.max_frontier_candidate_count,
            decision.frontier_count,
        )
        self._summary.max_hidden_candidate_count = max(
            self._summary.max_hidden_candidate_count,
            hidden_count,
        )
        self.add_nodes(
            [
                _node_from_frontier_candidate(candidate, state="pending")
                for candidate in visible
            ],
            reason="frontier_visible",
        )
        self.add_edges(
            [
                edge_payload
                for candidate in visible
                for edge_payload in [_frontier_edge_payload(candidate)]
                if edge_payload is not None
                and edge_payload["source"] in self._known_nodes
            ],
            reason="frontier_visible",
        )
        for candidate in visible:
            self._record_candidate_score(candidate)
        for node_id in decision.pruned_ids:
            if node_id in self._known_nodes or any(
                candidate.node_id == node_id for candidate in visible
            ):
                self.prune_node(node_id, reason="frontier_pruned")
        self._visible_pending_ids = [
            candidate.node_id
            for candidate in visible
            if candidate.node_id not in set(decision.pruned_ids)
            and self._known_nodes.get(candidate.node_id, {}).get("state")
            not in {"resolved", "anchor", "pruned"}
        ]

    def observe_expansion(self, source_id: str, events: list[GraphEvent], graph: Graph) -> None:
        for event in events:
            if isinstance(event, AddNodesEvent):
                self.add_nodes(
                    [_normalize_node_dict(node) for node in event.nodes],
                    reason=event.reason or "frontier_discovered",
                )
                continue
            if isinstance(event, AddEdgesEvent):
                self.add_edges(
                    [_edge_payload(edge) for edge in event.edges],
                    reason=event.reason or "frontier_discovered",
                )
                continue
            if isinstance(event, UpdateNodeEvent):
                self._ensure_node_known(source_id if event.id == source_id else event.id, graph)
                self.update_node(
                    event.id,
                    cast(dict[str, object], dict(event.patch)),
                    reason=(
                        "frontier_selected"
                        if event.id == source_id and event.patch.get("state") == "resolved"
                        else "frontier_updated"
                    ),
                )
                continue
            iteration_event = event
            self._events.append(
                _compact_dict(
                    {
                        "type": "iteration",
                        "step": iteration_event.step,
                        "description": iteration_event.description,
                    }
                )
            )

    def collect(
        self,
        *,
        trace_id: str,
        metadata: dict[str, object] | None,
        policy_id: str | None,
        source_signature: str | None = None,
        graph_signature: str | None = None,
        graph_builder: dict[str, object] | None = None,
        clear_after_collect: bool,
    ) -> dict[str, object]:
        trace = trace_id.strip()
        if not trace:
            raise ValueError("trace_id must be a non-empty string")
        if not isinstance(getattr(self, "_events", None), list):
            raise ValueError("graph replay recorder is in an invalid state")

        clean_metadata = self._sanitize_metadata(metadata)
        self._summary.event_count = len(self._events)
        payload = GraphReplayPayload(
            trace_id=trace,
            match_id=self._optional_string(clean_metadata, "match_id"),
            role=self._optional_string(clean_metadata, "role"),
            attempt_id=self._optional_string(clean_metadata, "attempt_id"),
            policy_id=policy_id.strip() if policy_id else None,
            source_signature=source_signature.strip() if isinstance(source_signature, str) and source_signature.strip() else None,
            graph_signature=graph_signature.strip() if isinstance(graph_signature, str) and graph_signature.strip() else None,
            graph_builder=dict(graph_builder) if isinstance(graph_builder, dict) else None,
            metadata=self._extension_metadata(clean_metadata),
            events=[dict(event) for event in self._events],
            summary=self._summary,
        )
        result = payload.to_payload()
        if clear_after_collect:
            self.reset()
        return result

    def _append_iteration(self, description: str) -> None:
        self._iteration += 1
        self._events.append(
            {
                "type": "iteration",
                "step": self._iteration,
                "description": description,
            }
        )

    def _bounded_anchor_candidates(
        self,
        candidates: list[AnchorCandidate],
        *,
        selected_anchor_id: str | None,
    ) -> list[AnchorCandidate]:
        visible = list(candidates[: self.max_visible_pending])
        if selected_anchor_id is None:
            return visible
        if any(candidate.node_id == selected_anchor_id for candidate in visible):
            return visible
        for candidate in candidates[self.max_visible_pending :]:
            if candidate.node_id != selected_anchor_id:
                continue
            if visible:
                visible[-1] = candidate
            else:
                visible.append(candidate)
            break
        return visible

    def _bounded_frontier_candidates(
        self, decision: FrontierDecision
    ) -> list[FrontierCandidate]:
        ordered = self._ordered_frontier_candidates(decision.candidates)
        candidates_by_id = {candidate.node_id: candidate for candidate in ordered}
        selected_ids = self._dedupe_ids(
            [decision.selected_id] if decision.selected_id is not None else []
        )
        pruned_ids = self._dedupe_ids(
            [
                node_id
                for node_id in decision.pruned_ids
                if node_id in candidates_by_id and node_id not in selected_ids
            ]
        )
        sticky_ids = self._dedupe_ids(
            [
                node_id
                for node_id in self._visible_pending_ids
                if node_id in candidates_by_id
                and node_id not in selected_ids
                and node_id not in pruned_ids
            ]
        )
        requested_ids = self._dedupe_ids(
            [
                node_id
                for node_id in decision.visible_candidate_ids
                if node_id in candidates_by_id
                and node_id not in selected_ids
                and node_id not in pruned_ids
            ]
        )
        ranked_ids = [
            candidate.node_id
            for candidate in ordered
            if candidate.node_id not in selected_ids
            and candidate.node_id not in pruned_ids
            and candidate.node_id not in sticky_ids
            and candidate.node_id not in requested_ids
        ]

        visible_ids = self._dedupe_ids(selected_ids + pruned_ids + sticky_ids)
        for node_id in requested_ids + ranked_ids:
            if len(visible_ids) >= self.max_visible_pending:
                break
            visible_ids.append(node_id)
        return [candidates_by_id[node_id] for node_id in visible_ids if node_id in candidates_by_id]

    def _ordered_frontier_candidates(
        self, candidates: list[FrontierCandidate]
    ) -> list[FrontierCandidate]:
        return sorted(
            candidates,
            key=lambda candidate: (
                candidate.rank if candidate.rank is not None else 10_000,
                -(candidate.score if candidate.score is not None else float("-inf")),
                candidate.node_id,
            ),
        )

    def _record_candidate_score(self, candidate: FrontierCandidate) -> None:
        patch: dict[str, object] = {}
        if candidate.score is not None:
            patch["score"] = candidate.score
        if candidate.rank is not None:
            patch["rank"] = candidate.rank
        if patch:
            self.update_node(candidate.node_id, patch, reason="candidate_scored")

    def _ensure_node_known(self, node_id: str, graph: Graph) -> None:
        if node_id in self._known_nodes:
            return
        raw = graph.nodes.get(node_id)
        if not isinstance(raw, dict):
            return
        data = raw.get("data")
        if (
            data is None
            or not hasattr(data, "id")
            or not hasattr(data, "state")
            or not hasattr(data, "kind")
        ):
            return
        self.add_nodes([_normalize_node_dict(cast(GraphNode, data))], reason="frontier_visible")

    def _dedupe_ids(self, node_ids: Sequence[str | None]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for raw in node_ids:
            if raw is None:
                continue
            node_id = raw.strip()
            if not node_id or node_id in seen:
                continue
            seen.add(node_id)
            result.append(node_id)
        return result

    def _sanitize_metadata(self, metadata: object) -> dict[str, object]:
        if metadata is None:
            return {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be a mapping when provided")
        clean: dict[str, object] = {}
        typed_metadata = cast(dict[object, object], metadata)
        for key, value in typed_metadata.items():
            if not isinstance(key, str):
                continue
            lowered_key = key.lower()
            if lowered_key in {
                "api_key",
                "provider_key",
                "secret",
                "private_prompt",
                "raw_prompt",
                "source_snippet",
                "env_vars",
                "sourcesignature",
                "graphsignature",
                "graphbuilder",
                "repoidentity",
                "sessionid",
            }:
                raise ValueError(f"metadata key {key!r} is not portable")
            clean[key] = self._sanitize_metadata_value(value, path=key)
        return clean

    def _sanitize_metadata_value(self, value: object, *, path: str) -> object:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return ""
            if "\n" in stripped or "\r" in stripped:
                raise ValueError(f"metadata field {path!r} must be single-line")
            if len(stripped) > MAX_METADATA_STRING_LENGTH:
                raise ValueError(f"metadata field {path!r} is too large")
            if stripped.startswith(("/home/", "/Users/", "/tmp/")):
                raise ValueError(f"metadata field {path!r} contains a non-portable path")
            normalized = stripped.replace("\\", "/")
            if "evidence/bundle/" in normalized or "/projection/" in normalized:
                raise ValueError(f"metadata field {path!r} contains a bundle/projection path")
            if stripped.startswith("sk-") or re.match(r"^[A-Z_][A-Z0-9_]*=.*", stripped):
                raise ValueError(f"metadata field {path!r} contains secret-like content")
            return stripped
        if isinstance(value, list):
            typed_items = cast(list[object], value)
            return [
                self._sanitize_metadata_value(item, path=f"{path}[{index}]")
                for index, item in enumerate(typed_items)
            ]
        if isinstance(value, dict):
            clean: dict[str, object] = {}
            typed_value = cast(dict[object, object], value)
            for key, nested in typed_value.items():
                if not isinstance(key, str):
                    continue
                clean[key] = self._sanitize_metadata_value(nested, path=f"{path}.{key}")
            return clean
        raise ValueError(f"metadata field {path!r} uses unsupported type {type(value).__name__}")

    def _optional_string(self, metadata: object, key: str) -> str | None:
        if not isinstance(metadata, dict):
            return None
        value = cast(dict[object, object], metadata).get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _extension_metadata(self, metadata: dict[str, object]) -> dict[str, object] | None:
        excluded = {"match_id", "role", "attempt_id"}
        extra = {key: value for key, value in metadata.items() if key not in excluded}
        return extra or None


__all__ = [
    "GRAPH_REPLAY_KIND",
    "GRAPH_REPLAY_SOURCE",
    "DEFAULT_MAX_VISIBLE_PENDING",
    "FrontierCandidate",
    "FrontierDecision",
    "GraphReplaySummary",
    "GraphReplayPayload",
    "GraphReplayObserver",
    "GraphReplayRecorder",
]
