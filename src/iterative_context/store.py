from collections import deque
from typing import Any, cast

from pydantic import BaseModel

from iterative_context.anchor_policy import AnchorCandidate, anchor_candidate_to_dict
from iterative_context.fuzzy_rank import pick_unique_or_ambiguous, rank_symbol_candidates
from iterative_context.graph_models import Graph, GraphEdge, GraphNode


class GraphStore:
    """
    READ-ONLY PROJECTION LAYER.

    This class provides indexed, queryable access to the graph.

    It MUST NOT:
    - mutate the graph
    - emit events
    - perform expansion

    It only answers questions about the current graph state.
    """

    def __init__(self, graph: Graph):
        self.graph = graph

        self.nodes_by_id: dict[str, dict[str, Any]] = {}
        self.nodes_by_symbol: dict[str, list[str]] = {}
        self.nodes_by_file: dict[str, list[str]] = {}
        self.index_by_symbol: dict[str, list[str]] = {}
        self.index_by_file: dict[str, list[str]] = {}

        self.out_edges: dict[str, list[GraphEdge]] = {}
        self.in_edges: dict[str, list[GraphEdge]] = {}

        self._build_indexes()

    def _build_indexes(self) -> None:
        for node_id, data in sorted(self.graph.nodes(data=True), key=lambda item: item[0]):
            node_data = dict(data)
            self.nodes_by_id[node_id] = node_data

            symbol = node_data.get("symbol")
            if isinstance(symbol, str):
                self.nodes_by_symbol.setdefault(symbol, []).append(node_id)
                self.index_by_symbol.setdefault(symbol, []).append(node_id)

            file_value = node_data.get("file")
            if isinstance(file_value, str):
                self.nodes_by_file.setdefault(file_value, []).append(node_id)
                self.index_by_file.setdefault(file_value, []).append(node_id)
        for mapping in (
            self.nodes_by_symbol,
            self.nodes_by_file,
            self.index_by_symbol,
            self.index_by_file,
        ):
            for key in mapping:
                mapping[key] = sorted(mapping[key])

        for src, dst, data in sorted(
            self.graph.edges(data=True), key=lambda item: (item[0], item[1])
        ):
            kind_value = data.get("kind")
            if kind_value not in {"calls", "imports", "references"}:
                data_obj = data.get("data")
                if isinstance(data_obj, GraphEdge):
                    kind_value = data_obj.kind
            kind = kind_value if isinstance(kind_value, str) else "references"

            edge = GraphEdge(
                source=src,
                target=dst,
                kind=kind,  # type: ignore[arg-type]
                id=data.get("id"),
                primary=data.get("primary"),
            )

            self.out_edges.setdefault(src, []).append(edge)
            self.in_edges.setdefault(dst, []).append(edge)

    def find_symbol(self, symbol: str) -> list[str]:
        return list(self.nodes_by_symbol.get(symbol, []))

    def _node_for_id(self, node_id: str) -> GraphNode | None:
        data = self.graph.nodes.get(node_id)
        if data is None:
            return None
        if "data" in data:
            inner = data.get("data")
            if isinstance(inner, BaseModel):
                return cast(GraphNode, inner)
        if isinstance(data, BaseModel):
            return cast(GraphNode, data)
        return None

    def resolve(self, query: str) -> GraphNode | None:
        """
        Deterministic lookup using symbol/file indexes, then bounded fuzzy ranking.

        No traversal or mutation.
        """
        exact = self.index_by_symbol.get(query, [])
        if exact:
            node = self._node_for_id(sorted(exact)[0])
            if node:
                return node

        symbols = self._symbol_index()
        winner, _ambiguous = pick_unique_or_ambiguous(query, symbols)
        if winner is not None:
            return self._node_for_id(winner.node_id)

        lowered = query.lower()
        for path, ids in sorted(self.index_by_file.items(), key=lambda item: item[0]):
            if lowered in path.lower():
                node = self._node_for_id(ids[0])
                if node:
                    return node

        return None

    def collect_anchor_candidates(self, query: str, *, limit: int = 8) -> list[AnchorCandidate]:
        """Collect deterministic anchor evidence for policy-controlled resolution."""
        q = (query or "").strip()
        if not q:
            return []

        out: list[AnchorCandidate] = []
        seen: set[str] = set()

        exact_ids = sorted(self.index_by_symbol.get(q, []))
        for rank, node_id in enumerate(exact_ids, start=1):
            candidate = self._candidate_for_id(
                node_id,
                label=q,
                score=100.0,
                rank=rank,
                reason="exact_symbol_match",
                metadata={"match_source": "exact_symbol"},
            )
            if candidate is not None and candidate.node_id not in seen:
                out.append(candidate)
                seen.add(candidate.node_id)

        symbols = self._symbol_index()
        for rank, ranked in enumerate(rank_symbol_candidates(q, symbols), start=1):
            metadata: dict[str, object] = {"match_source": "fuzzy_symbol", "symbol": ranked.symbol}
            candidate = self._candidate_for_id(
                ranked.node_id,
                label=ranked.symbol,
                score=ranked.score,
                rank=rank,
                reason=ranked.reason,
                metadata=metadata,
            )
            if candidate is not None and candidate.node_id not in seen:
                out.append(candidate)
                seen.add(candidate.node_id)

        lowered = q.lower()
        file_rank = 1
        for path, ids in sorted(self.index_by_file.items(), key=lambda item: item[0]):
            if lowered not in path.lower():
                continue
            for node_id in sorted(ids):
                candidate = self._candidate_for_id(
                    node_id,
                    label=path,
                    score=None,
                    rank=file_rank,
                    reason="file_substring_match",
                    metadata={"match_source": "file_substring", "file": path},
                )
                if candidate is not None and candidate.node_id not in seen:
                    out.append(candidate)
                    seen.add(candidate.node_id)
                    file_rank += 1

        return out[:limit]

    def _symbol_index(self) -> list[tuple[str, str]]:
        symbols: list[tuple[str, str]] = []
        for sym, ids in self.index_by_symbol.items():
            if ids:
                symbols.append((sorted(ids)[0], sym))
        return symbols

    def _candidate_for_id(  # noqa: PLR0913
        self,
        node_id: str,
        *,
        label: str | None,
        score: float | None,
        rank: int | None,
        reason: str | None,
        metadata: dict[str, object] | None,
    ) -> AnchorCandidate | None:
        node = self._node_for_id(node_id)
        if node is None:
            return None
        node_data = self.nodes_by_id.get(node_id, {})
        symbol_value = node_data.get("symbol")
        file_value = node_data.get("file")
        merged_metadata = dict(metadata or {})
        if isinstance(symbol_value, str):
            merged_metadata.setdefault("symbol", symbol_value)
        if isinstance(file_value, str):
            merged_metadata.setdefault("file", file_value)
        return AnchorCandidate(
            node_id=node.id,
            label=label or (symbol_value if isinstance(symbol_value, str) else None),
            kind=node.kind,
            score=score,
            rank=rank,
            reason=reason,
            metadata=merged_metadata or None,
        )

    def resolve_candidates(self, query: str, *, limit: int = 8) -> list[dict[str, object]]:
        """Return ranked candidates for ambiguous or below-threshold resolve."""
        resolved = self.resolve(query)
        if resolved is not None:
            return []
        candidates = self.collect_anchor_candidates(query, limit=limit)
        out: list[dict[str, object]] = []
        for candidate in candidates:
            payload = anchor_candidate_to_dict(candidate)
            symbol_value = (
                candidate.metadata.get("symbol") if candidate.metadata is not None else None
            )
            if isinstance(symbol_value, str):
                payload["symbol"] = symbol_value
            out.append(payload)
        return out

    def get_neighbors(self, node_id: str, kinds: list[str] | None = None) -> list[str]:
        neighbors: set[str] = set()

        for edge in self.out_edges.get(node_id, []):
            if kinds is None or edge.kind in kinds:
                neighbors.add(edge.target)

        for edge in self.in_edges.get(node_id, []):
            if kinds is None or edge.kind in kinds:
                neighbors.add(edge.source)

        return sorted(neighbors)

    def get_neighborhood(self, node_id: str, radius: int) -> set[str]:
        if radius < 0:
            return set()

        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque()
        queue.append((node_id, 0))
        visited.add(node_id)

        while queue:
            current, dist = queue.popleft()
            if dist >= radius:
                continue

            for neighbor in self.get_neighbors(current):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, dist + 1))

        return visited


def debug_summary(store: GraphStore) -> dict[str, int]:
    return {
        "nodes": len(store.nodes_by_id),
        "edges": sum(len(v) for v in store.out_edges.values()),
    }
