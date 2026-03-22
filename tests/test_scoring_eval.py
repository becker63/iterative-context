# pyright: reportMissingTypeStubs=false
import json

from hypothesis import given
from hypothesis import strategies as st
from pytest_snapshot.plugin import Snapshot

from iterative_context.graph_models import Graph, GraphNode
from iterative_context.scoring import score_degree, score_v1
from iterative_context.scoring_eval import compare_scorings
from iterative_context.test_helpers import GraphType, build_graph, normalize_graph
from iterative_context.traversal import ScoreFn, select_next_node


def test_scoring_changes_traversal(snapshot: Snapshot) -> None:
    def graph_factory() -> GraphType:
        return build_graph({"nodes": [{"id": "A", "kind": "symbol", "state": "pending"}]})  # type: ignore[arg-type]

    results = compare_scorings(
        graph_factory,
        {
            "v1": score_v1,
            "degree": score_degree,
        },
        steps=3,
    )

    normalized = {name: normalize_graph(g) for name, g in results.items()}
    snapshot.assert_match(json.dumps(normalized, sort_keys=True, indent=2), "scoring_comparison")


@given(
    st.tuples(
        st.text(min_size=1, max_size=3),
        st.text(min_size=1, max_size=3),
    ).filter(lambda t: t[0] != t[1])
)
def test_selects_highest_score(strings: tuple[str, str]) -> None:
    a, b = strings
    graph: GraphType = build_graph(
        {
            "nodes": [
                {"id": a, "kind": "symbol", "state": "pending"},
                {"id": b, "kind": "symbol", "state": "pending"},
            ]
        }
    )  # type: ignore[arg-type]

    def by_length(node: GraphNode, graph: Graph, step: int) -> float:
        return float(len(node.id))

    score_fn: ScoreFn = by_length
    selected = select_next_node(graph, step=0, score_fn=score_fn)

    expected = max([a, b], key=lambda s: (len(s), s))
    assert selected.id == expected
