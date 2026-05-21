from __future__ import annotations

from dataclasses import dataclass

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - dev without optional dep
    fuzz = None  # type: ignore[assignment]


@dataclass(frozen=True)
class RankedCandidate:
    node_id: str
    symbol: str
    score: float
    reason: str


def _fallback_score(query: str, symbol: str) -> float:
    q = query.lower()
    s = symbol.lower()
    if q == s:
        return 100.0
    if q in s:
        return 80.0
    if s in q:
        return 60.0
    return 0.0


def rank_symbol_candidates(query: str, symbols: list[tuple[str, str]]) -> list[RankedCandidate]:
    """
    Rank (node_id, symbol) pairs for a query.

    Uses RapidFuzz token_set_ratio when installed; otherwise deterministic substring tiers.
    """
    q = (query or "").strip()
    if not q:
        return []
    ranked: list[RankedCandidate] = []
    for node_id, symbol in symbols:
        sym = (symbol or "").strip()
        if not sym:
            continue
        if fuzz is not None:
            score = float(fuzz.token_set_ratio(q, sym))
            reason = "rapidfuzz_token_set_ratio"
        else:
            score = _fallback_score(q, sym)
            reason = "substring_tier"
        ranked.append(RankedCandidate(node_id=node_id, symbol=sym, score=score, reason=reason))
    ranked.sort(key=lambda c: (-c.score, c.symbol, c.node_id))
    return ranked


def pick_unique_or_ambiguous(
    query: str, symbols: list[tuple[str, str]], *, min_score: float = 70.0, gap: float = 5.0
) -> tuple[RankedCandidate | None, list[RankedCandidate]]:
    ranked = [c for c in rank_symbol_candidates(query, symbols) if c.score >= min_score]
    if not ranked:
        return None, []
    if len(ranked) == 1:
        return ranked[0], []
    if ranked[0].score - ranked[1].score >= gap:
        return ranked[0], []
    return None, ranked[:8]
