import pytest

from iterative_context.exploration import expand, resolve, resolve_and_expand
from iterative_context.graph_models import Graph
from iterative_context.store import GraphStore
from iterative_context.test_helpers.graph_dsl import build_graph


def make_graph_with_symbols() -> Graph:
    graph = build_graph(
        {
            "nodes": [
                {"id": "A", "kind": "symbol", "state": "pending"},
                {"id": "B", "kind": "symbol", "state": "pending"},
            ],
            "edges": [
                {"source": "A", "target": "B", "kind": "calls"},
            ],
        }
    )
    graph.nodes["A"]["symbol"] = "expand_node"
    graph.nodes["A"]["file"] = "src/iterative_context/expansion.py"
    graph.nodes["B"]["symbol"] = "other_symbol"
    graph.nodes["B"]["file"] = "src/iterative_context/other.py"
    return graph


@pytest.fixture
def graph_store_fixture() -> tuple[Graph, GraphStore]:
    graph = make_graph_with_symbols()
    store = GraphStore(graph)
    return graph, store


def test_resolve_symbol(graph_store_fixture: tuple[Graph, GraphStore]) -> None:
    _, store = graph_store_fixture

    ids = resolve("expand_node", store)
    assert len(ids) > 0
    assert "A" in ids


def test_resolve_deterministic(graph_store_fixture: tuple[Graph, GraphStore]) -> None:
    _, store = graph_store_fixture
    query = "expand_node"

    assert resolve(query, store) == resolve(query, store)


def test_expand_multi_anchor(graph_store_fixture: tuple[Graph, GraphStore]) -> None:
    graph, _ = graph_store_fixture

    result = expand(["A", "B"], graph, depth=2)

    assert isinstance(result, set)
    assert result  # neighborhood should not be empty


def test_resolve_and_expand_integration(graph_store_fixture: tuple[Graph, GraphStore]) -> None:
    graph, _ = graph_store_fixture

    result = resolve_and_expand("expand_node", graph, depth=2)

    assert isinstance(result, set)
    assert len(result) > 0
