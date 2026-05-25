from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict, cast

from pydantic import BaseModel

from iterative_context.graph_models import Graph, GraphEdge, GraphNode, PendingNode
from iterative_context.graph_replay import GraphReplayObserver
from iterative_context.injest.llm_tldr_adapter import ingest_repo
from iterative_context.normalize import raw_tree_to_graph
from iterative_context.path_ids import node_kind_for_id
from iterative_context.scoring import default_score_fn
from iterative_context.serialization import serialize_graph, serialize_graph_summary
from iterative_context.store import GraphStore
from iterative_context.traversal import DefaultExpansionPolicy, run_traversal
from iterative_context.types import SelectionCallable


class GraphSnapshotDict(TypedDict):
    nodes: list[dict[str, object]]
    edges: list[dict[str, object]]
    metadata: dict[str, object]


@dataclass(frozen=True)
class RepoIdentity:
    repo_root: Path
    repo_url: str | None = None
    commit: str | None = None
    workspace_kind: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "repoRoot": self.repo_root.as_posix(),
            "workspaceKind": self.workspace_kind or "filesystem",
        }
        if self.repo_url:
            payload["repoUrl"] = self.repo_url
        if self.commit:
            payload["commit"] = self.commit
        return payload


def _normalize_kind(raw: str | None, node_id: str) -> str:
    if raw == "function":
        return "function"
    if raw == "file":
        return "file"
    if raw in {"type", "module"}:
        return "type"
    return node_kind_for_id(node_id)


def _normalize_edge_kind(raw: str | None) -> str:
    if raw == "imports":
        return "imports"
    if raw == "calls":
        return "calls"
    return "references"


def _normalize_repo_root(repo_root: str | Path | None) -> Path:
    if repo_root is None:
        return Path.cwd().resolve()
    return Path(repo_root).resolve()


def _iter_python_sources(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        files.append(path)
    return files


def compute_source_signature(root: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(b"iterative-context.source-signature.v1")
    for path in _iter_python_sources(root):
        rel = path.relative_to(root).as_posix()
        hasher.update(rel.encode("utf-8"))
        try:
            contents = path.read_bytes()
        except FileNotFoundError:
            continue
        hasher.update(hashlib.sha256(contents).digest())
    return f"sha256:{hasher.hexdigest()}"


def compute_graph_signature(
    graph: Graph,
    *,
    graph_builder_id: str,
    normalization_version: str,
) -> str:
    payload: dict[str, object] = {
        "graphBuilderId": graph_builder_id,
        "normalizationVersion": normalization_version,
        "nodes": [],
        "edges": [],
    }
    nodes: list[dict[str, object]] = []
    for node_id, raw_data in sorted(graph.nodes(data=True), key=lambda item: item[0]):
        symbol_value: str | None = None
        file_value: str | None = None
        state_value = "pending"
        kind_value = "symbol"
        typed_data = cast(dict[str, object], raw_data)
        embedded = typed_data.get("data")
        if isinstance(embedded, BaseModel):
            state_value = cast(Any, embedded).state
            kind_value = cast(Any, embedded).kind
        symbol_raw = typed_data.get("symbol")
        if isinstance(symbol_raw, str):
            symbol_value = symbol_raw
        file_raw = typed_data.get("file")
        if isinstance(file_raw, str):
            file_value = file_raw
        nodes.append(
            {
                "id": str(node_id),
                "kind": kind_value,
                "symbol": symbol_value,
                "file": file_value,
                "state": state_value,
            }
        )
    edges: list[dict[str, object]] = []
    for src, dst, raw_data in sorted(
        graph.edges(data=True), key=lambda item: (item[0], item[1])
    ):
        edge_kind_value: str | None = None
        typed_edge = cast(dict[str, object], raw_data)
        embedded = typed_edge.get("data")
        if isinstance(embedded, GraphEdge):
            edge_kind_value = embedded.kind
        else:
            raw_kind = typed_edge.get("kind")
            edge_kind_value = raw_kind if isinstance(raw_kind, str) else None
        edges.append(
            {
                "source": str(src),
                "target": str(dst),
                "kind": _normalize_edge_kind(edge_kind_value),
            }
        )
    payload["nodes"] = nodes
    payload["edges"] = edges
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(blob).hexdigest()}"


def _build_graph_from_repo(root: Path) -> Graph:
    raw_tree = ingest_repo(root)
    base_graph = raw_tree_to_graph(raw_tree)

    graph = Graph()
    for node_id, raw_data in base_graph.nodes(data=True):
        symbol_value: str | None = None
        file_value: str | None = None
        kind_value: str | None = None
        if isinstance(raw_data, dict):
            typed_data = cast(dict[str, object], raw_data)
            symbol_raw = typed_data.get("symbol")
            if isinstance(symbol_raw, str):
                symbol_value = symbol_raw
            file_raw = typed_data.get("file")
            if isinstance(file_raw, str):
                file_value = file_raw
            kind_raw = typed_data.get("type")
            kind_value = kind_raw if isinstance(kind_raw, str) else None

        normalized_id = str(node_id)
        node = PendingNode(
            id=normalized_id,
            kind=cast(Any, _normalize_kind(kind_value, normalized_id)),
        )
        attrs: dict[str, object] = {"data": node}
        if isinstance(symbol_value, str):
            attrs["symbol"] = symbol_value
        if isinstance(file_value, str):
            attrs["file"] = file_value
        graph.add_node(node.id, **attrs)

    for src, dst, raw_data in base_graph.edges(data=True):
        typed_edge = cast(dict[str, object], raw_data)
        embedded = typed_edge.get("data")
        if isinstance(embedded, GraphEdge):
            edge_kind = embedded.kind
        else:
            raw_kind = typed_edge.get("kind")
            edge_kind = raw_kind if isinstance(raw_kind, str) else None
        kind = _normalize_edge_kind(edge_kind)
        edge = GraphEdge(source=str(src), target=str(dst), kind=cast(Any, kind))
        graph.add_edge(edge.source, edge.target, data=edge)

    return graph


def _git_output(root: Path, *args: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def _derive_repo_identity(root: Path) -> RepoIdentity:
    commit = _git_output(root, "rev-parse", "HEAD")
    repo_url = _git_output(root, "config", "--get", "remote.origin.url")
    workspace_kind = "git" if commit or repo_url else "filesystem"
    return RepoIdentity(
        repo_root=root,
        repo_url=repo_url,
        commit=commit,
        workspace_kind=workspace_kind,
    )


@dataclass
class GraphSession:
    repo_root: Path | None = None
    repo_identity: RepoIdentity | None = None
    graph: Graph | None = None
    store: GraphStore | None = None
    source_signature: str | None = None
    graph_signature: str | None = None
    graph_builder_id: str = "iterative-context.graph-builder.v1"
    normalization_version: str = "iterative-context.normalize.v1"
    session_id: str = field(default_factory=lambda: f"ic-session:{uuid.uuid4().hex}")

    def ensure_loaded(self, repo_root: str | Path | None = None) -> None:
        root = _normalize_repo_root(repo_root or self.repo_root)
        source_sig = compute_source_signature(root)
        if (
            self.graph is not None
            and self.store is not None
            and self.repo_identity is not None
            and self.repo_identity.repo_root == root
            and self.source_signature == source_sig
        ):
            return

        graph = _build_graph_from_repo(root)
        graph_sig = compute_graph_signature(
            graph,
            graph_builder_id=self.graph_builder_id,
            normalization_version=self.normalization_version,
        )
        self.set_graph(
            graph,
            repo_root=root,
            source_signature=source_sig,
            graph_signature=graph_sig,
            repo_identity=_derive_repo_identity(root),
        )

    def set_graph(
        self,
        graph: Graph,
        *,
        repo_root: str | Path | None = None,
        source_signature: str | None = None,
        graph_signature: str | None = None,
        repo_identity: RepoIdentity | None = None,
    ) -> None:
        root = _normalize_repo_root(repo_root or self.repo_root)
        identity = repo_identity or _derive_repo_identity(root)
        source_sig = source_signature or self.source_signature
        graph_sig = graph_signature or compute_graph_signature(
            graph,
            graph_builder_id=self.graph_builder_id,
            normalization_version=self.normalization_version,
        )
        graph.graph["repo_root"] = identity.repo_root.as_posix()
        graph.graph["source_signature"] = source_sig
        graph.graph["graph_signature"] = graph_sig
        self.repo_root = root
        self.repo_identity = identity
        self.source_signature = source_sig
        self.graph_signature = graph_sig
        self.graph = graph
        self.store = GraphStore(graph)

    def copy_loaded_state_from(self, other: GraphSession) -> None:
        if other.graph is None:
            return
        self.set_graph(
            other.graph,
            repo_root=other.repo_root,
            source_signature=other.source_signature,
            graph_signature=other.graph_signature,
            repo_identity=other.repo_identity,
        )

    def resolve(self, symbol: str) -> GraphNode | None:
        if self.store is None:
            return None
        return self.store.resolve(symbol)

    def collect_anchor_candidates(self, symbol: str, *, limit: int = 8) -> list[Any]:
        if self.store is None:
            return []
        return self.store.collect_anchor_candidates(symbol, limit=limit)

    def node_for_id(self, node_id: str) -> GraphNode | None:
        if self.store is None:
            return None
        return self.store._node_for_id(node_id)  # pyright: ignore[reportPrivateUsage]

    def node_extras(self, node_id: str) -> dict[str, object]:
        if self.graph is None or node_id not in self.graph.nodes:
            return {}
        raw = self.graph.nodes[node_id]
        typed_raw = cast(dict[str, object], raw)
        return {key: value for key, value in typed_raw.items() if key != "data"}

    def expand(
        self,
        node_id: str,
        depth: int = 1,
        score_fn: SelectionCallable | None = None,
        observer: GraphReplayObserver | None = None,
    ) -> GraphSnapshotDict:
        if self.graph is None:
            return cast(
                GraphSnapshotDict,
                {"nodes": [], "edges": [], "metadata": {"depth": depth, "expanded_from": node_id}},
            )

        base_reachable: set[str] = set()
        queue: list[tuple[str, int]] = [(node_id, 0)]
        while queue:
            current, dist = queue.pop(0)
            if current in base_reachable:
                continue
            base_reachable.add(current)
            if dist >= depth:
                continue
            for succ in self.graph.successors(current):
                queue.append((cast(str, succ), dist + 1))
            for pred in self.graph.predecessors(current):
                queue.append((cast(str, pred), dist + 1))

        working = cast(Graph, deepcopy(self.graph.subgraph(base_reachable).copy()))
        steps = max(depth, 0)
        run_traversal(
            working,
            steps=steps,
            expansion_policy=DefaultExpansionPolicy(),
            score_fn=score_fn or default_score_fn,
            observer=observer,
        )

        visited: set[str] = set()
        frontier: list[tuple[str, int]] = [(node_id, 0)]
        while frontier:
            current, dist = frontier.pop(0)
            if current in visited:
                continue
            visited.add(current)
            if dist >= steps:
                continue
            for succ in working.successors(current):
                frontier.append((cast(str, succ), dist + 1))
            for pred in working.predecessors(current):
                frontier.append((cast(str, pred), dist + 1))

        subgraph = cast(Graph, working.subgraph(visited).copy())
        return cast(
            GraphSnapshotDict,
            serialize_graph(subgraph, metadata={"depth": depth, "expanded_from": node_id}),
        )

    def graph_summary(self) -> dict[str, object]:
        return serialize_graph_summary(self.graph, metadata=self.repo_metadata())

    def graph_identity_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "graphBuilder": {
                "name": "iterative-context",
                "version": self.graph_builder_id,
                "normalizationVersion": self.normalization_version,
            },
            "sessionId": self.session_id,
        }
        if self.source_signature:
            payload["sourceSignature"] = self.source_signature
        if self.graph_signature:
            payload["graphSignature"] = self.graph_signature
        return payload

    def repo_metadata(self) -> dict[str, object]:
        payload = self.graph_identity_payload()
        if self.repo_identity is not None:
            payload["repoIdentity"] = self.repo_identity.to_payload()
            payload["repo_root"] = self.repo_identity.repo_root.as_posix()
        if self.graph_signature:
            payload["repo_signature"] = self.graph_signature
        return payload

    def reset(self, *, clear_repo_root: bool = False) -> None:
        self.repo_identity = None
        self.graph = None
        self.store = None
        self.source_signature = None
        self.graph_signature = None
        if clear_repo_root:
            self.repo_root = None


__all__ = [
    "GraphSession",
    "GraphSnapshotDict",
    "RepoIdentity",
    "compute_graph_signature",
    "compute_source_signature",
]
