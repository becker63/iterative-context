# iterative-context/src/iterative_context/scoring_eval.py

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

from iterative_context.graph_models import Graph
from iterative_context.scoring import score_v1
from iterative_context.traversal import DefaultExpansionPolicy, ScoreFn, run_traversal


def run_with_scoring(
    graph_factory: Callable[[], Graph],
    score_fn: ScoreFn,
    steps: int,
) -> Graph:
    graph = graph_factory()
    return run_traversal(
        graph,
        steps=steps,
        expansion_policy=DefaultExpansionPolicy(),
        score_fn=score_fn,
    )


def compare_scorings(
    graph_factory: Callable[[], Graph],
    scoring_fns: dict[str, ScoreFn],
    steps: int,
) -> dict[str, dict[str, object]]:
    results: dict[str, dict[str, object]] = {}

    for name, fn in scoring_fns.items():
        graph = run_with_scoring(graph_factory, fn, steps)
        step_graphs = graph.graph.get("graph_steps", [])
        score_history = graph.graph.get("score_history", [])
        results[name] = {
            "final_graph": graph,
            "steps": step_graphs,
            "scores": deepcopy(score_history),
        }

    return results


__all__ = ["run_with_scoring", "compare_scorings", "score_v1"]
