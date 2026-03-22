import pytest

from iterative_context.exploration import expand
from iterative_context.graph_models import Graph
from iterative_context.store import GraphStore
from iterative_context.test_helpers.graph_dsl import build_graph


@pytest.fixture
def graph_fixture() -> Graph:
    return build_graph(
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


def test_neighborhood_does_not_mutate(graph_fixture: Graph) -> None:
    graph = graph_fixture
    store = GraphStore(graph)

    before_nodes = set(graph.nodes)
    before_edges = set(graph.edges)

    store.get_neighborhood(next(iter(graph.nodes)), radius=2)

    assert set(graph.nodes) == before_nodes
    assert set(graph.edges) == before_edges


def test_expand_grows_graph(graph_fixture: Graph) -> None:
    graph = graph_fixture

    initial_nodes = set(graph.nodes)

    result = expand([next(iter(graph.nodes))], graph, depth=2)

    assert len(graph.nodes) >= len(initial_nodes)
    assert isinstance(result, set)
