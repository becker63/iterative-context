from iterative_context.fuzzy_rank import pick_unique_or_ambiguous, rank_symbol_candidates


def test_rank_symbol_candidates_orders_by_score() -> None:
    ranked = rank_symbol_candidates(
        "foo_bar",
        [("n1", "other"), ("n2", "foo_bar"), ("n3", "foo")],
    )
    assert ranked[0].symbol == "foo_bar"


def test_pick_unique_winner_on_large_gap() -> None:
    winner, amb = pick_unique_or_ambiguous(
        "Target",
        [("a", "Target"), ("b", "target_helper"), ("c", "unrelated")],
        min_score=50.0,
        gap=10.0,
    )
    assert winner is not None
    assert amb == []
