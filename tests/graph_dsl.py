# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
"""Deterministic, declarative helpers for building and mutating graphs in tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, NotRequired, TypedDict, cast

import networkx as nx

from iterative_context.graph_models import Graph

type GraphType = Graph


class EvidenceSpec(TypedDict):
    snippet: str
    file: NotRequired[str | None]
    startLine: NotRequired[int | None]


class NodeSpec(TypedDict):
    id: str
    kind: Literal["symbol", "function", "file", "type"]
    state: Literal["pending", "pruned", "anchor", "resolved"]
    label: NotRequired[str | None]
    tokens: NotRequired[int | None]
    evidence: NotRequired[EvidenceSpec]


class EdgeSpec(TypedDict):
    source: str
    target: str
    kind: Literal["calls", "imports", "references"]
    id: NotRequired[str | None]
    primary: NotRequired[bool | None]


class AddNodesEventSpec(TypedDict):
    type: Literal["addNodes"]
    nodes: list[str]
    reason: NotRequired[str | None]


class AddEdgesEventSpec(TypedDict):
    type: Literal["addEdges"]
    edges: list[EdgeSpec]
    reason: NotRequired[str | None]


class UpdateNodeEventSpec(TypedDict):
    type: Literal["updateNode"]
    id: str
    patch: dict[str, Any]


class IterationEventSpec(TypedDict):
    type: Literal["iteration"]
    step: int
    description: NotRequired[str | None]


EventSpec = AddNodesEventSpec | AddEdgesEventSpec | UpdateNodeEventSpec | IterationEventSpec


class GraphSpec(TypedDict, total=False):
    nodes: list[NodeSpec]
    edges: list[EdgeSpec]


def _default_node(node_id: str) -> NodeSpec:
    """Produce a minimal pending node spec for the given id."""
    return {"id": node_id, "kind": "symbol", "state": "pending"}


def _require_keys(label: str, obj: Mapping[str, Any], keys: tuple[str, ...]) -> None:
    missing = [key for key in keys if key not in obj]
    if missing:
        raise ValueError(f"{label} missing required keys: {', '.join(missing)}")


def build_graph(dsl: GraphSpec) -> GraphType:
    """Construct a NetworkX DiGraph from a declarative DSL spec."""
    graph: GraphType = nx.DiGraph()

    for node in dsl.get("nodes", []):
        _require_keys("Node spec", node, ("id", "kind", "state"))
        graph.add_node(node["id"], **node)

    for edge in dsl.get("edges", []):
        _require_keys("Edge spec", edge, ("source", "target", "kind"))
        if edge["source"] not in graph.nodes or edge["target"] not in graph.nodes:
            raise ValueError(f"Edge references unknown nodes: {edge['source']} -> {edge['target']}")
        edge_data = {k: v for k, v in edge.items() if k not in ("source", "target")}
        graph.add_edge(edge["source"], edge["target"], kind=edge["kind"], **edge_data)

    return graph


def apply_events(graph: GraphType, events: list[EventSpec]) -> GraphType:
    """Apply a sequence of DSL events to mutate the graph in place."""
    for event in events:
        event_type = event["type"]
        if event_type == "addNodes":
            add_nodes = cast(AddNodesEventSpec, event)
            for node_id in add_nodes["nodes"]:
                if node_id in graph.nodes:
                    continue
                graph.add_node(node_id, **_default_node(node_id))
        elif event_type == "addEdges":
            add_edges = cast(AddEdgesEventSpec, event)
            for edge in add_edges["edges"]:
                if edge["source"] not in graph.nodes or edge["target"] not in graph.nodes:
                    raise ValueError(
                        f"Edge references unknown nodes: {edge['source']} -> {edge['target']}"
                    )
                edge_data = {k: v for k, v in edge.items() if k not in ("source", "target", "kind")}
                graph.add_edge(edge["source"], edge["target"], kind=edge["kind"], **edge_data)
        elif event_type == "updateNode":
            update_event = cast(UpdateNodeEventSpec, event)
            node_id = update_event["id"]
            if node_id not in graph.nodes:
                raise ValueError(f"UpdateNode references unknown node: {node_id}")
            graph.nodes[node_id].update(update_event["patch"])
        elif event_type == "iteration":
            # Iteration events are observational; no graph mutation required.
            continue
        else:
            raise ValueError(f"Unknown event type '{event_type}'")
    return graph


def replay_with_snapshots(graph: GraphType, events: list[EventSpec]) -> list[GraphType]:
    """Apply events stepwise, returning graph copies after each step (including initial)."""
    snapshots: list[GraphType] = [graph.copy()]
    for event in events:
        apply_events(graph, [event])
        snapshots.append(graph.copy())
    return snapshots


__all__ = [
    "build_graph",
    "apply_events",
    "replay_with_snapshots",
    "GraphSpec",
    "EventSpec",
    "GraphType",
]
