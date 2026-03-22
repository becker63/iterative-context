# pyright: reportMissingTypeStubs=false
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from iterative_context.expansion import expand_node  # type: ignore

node_ids: st.SearchStrategy[str] = st.text(min_size=1, max_size=5)
existing_nodes: st.SearchStrategy[list[str]] = st.lists(node_ids, unique=True, max_size=5)


def _make_node(nid: str) -> dict[str, str]:
    return {"id": nid, "state": "pending"}


node_strategy: st.SearchStrategy[dict[str, str]] = st.builds(_make_node, node_ids)


@given(node_strategy, existing_nodes)
def test_expand_deterministic(node: dict[str, str], existing: list[str]):
    ev1 = expand_node(node, existing)
    ev2 = expand_node(node, existing)
    assert ev1 == ev2


@given(node_ids)
def test_expand_idempotent(node_id: str):
    node: dict[str, str] = {"id": node_id, "state": "pending"}
    existing: list[str] = [node_id, f"{node_id}_child"]

    events = expand_node(node, existing)

    assert len(events) == 1
    assert events[0].type == "updateNode"


@given(node_strategy, existing_nodes)
def test_no_duplicate_nodes(node: dict[str, str], existing: list[str]):
    events: list[Any] = expand_node(node, existing)

    added: set[str] = set()
    for e in events:
        if e.type == "addNodes":
            for n in e.nodes:
                assert n.id not in added
                added.add(n.id)


@given(node_strategy, existing_nodes)
def test_edges_valid(node: dict[str, str], existing: list[str]):
    events: list[Any] = expand_node(node, existing)

    known: set[str] = {node["id"], *existing}

    for e in events:
        if e.type == "addNodes":
            for n in e.nodes:
                known.add(n.id)

        if e.type == "addEdges":
            for edge in e.edges:
                assert edge.source in known
                assert edge.target in known


@given(node_strategy, existing_nodes)
def test_event_ordering(node: dict[str, str], existing: list[str]):
    events: list[Any] = expand_node(node, existing)

    seen_nodes: set[str] = {node["id"], *existing}

    for e in events:
        if e.type == "addNodes":
            for n in e.nodes:
                seen_nodes.add(n.id)

        if e.type == "addEdges":
            for edge in e.edges:
                assert edge.source in seen_nodes
                assert edge.target in seen_nodes


@given(node_strategy, existing_nodes)
def test_no_redundant_addnodes(node: dict[str, str], existing: list[str]):
    events: list[Any] = expand_node(node, existing)

    added: set[str] = set()

    for e in events:
        if e.type == "addNodes":
            for n in e.nodes:
                assert n.id not in added
                added.add(n.id)


@given(node_ids)
def test_single_child(node_id: str):
    node: dict[str, str] = {"id": node_id, "state": "pending"}

    events: list[Any] = expand_node(node, [node_id])

    created: list[str] = [
        n.id
        for e in events
        if e.type == "addNodes"
        for n in e.nodes
    ]

    assert len(created) <= 1


@given(node_strategy, existing_nodes)
def test_update_node_always_present(node: dict[str, str], existing: list[str]):
    events: list[Any] = expand_node(node, existing)

    assert any(e.type == "updateNode" for e in events)
