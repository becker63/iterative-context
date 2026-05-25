# pyright: reportUnusedFunction=false

from __future__ import annotations

from pathlib import Path

from iterative_context.graph_models import Graph, GraphNode
from iterative_context.graph_replay import GraphReplayObserver
from iterative_context.graph_session import (
    GraphSession,
    GraphSnapshotDict,
    RepoIdentity,
    _build_graph_from_repo as _session_build_graph_from_repo,  # pyright: ignore[reportPrivateUsage]
    compute_source_signature,
)
from iterative_context.store import GraphStore
from iterative_context.types import SelectionCallable

_default_session = GraphSession()


def _set_active_graph(
    graph: Graph,
    repo_root: Path | None = None,
    signature: str | None = None,
) -> None:
    root = repo_root or Path.cwd().resolve()
    _default_session.set_graph(
        graph,
        repo_root=root,
        source_signature=signature,
        repo_identity=RepoIdentity(repo_root=root, workspace_kind="test"),
    )


def _clear_active_graph() -> None:
    _default_session.reset(clear_repo_root=True)


def get_active_graph() -> Graph | None:
    return _default_session.graph


def get_active_store() -> GraphStore | None:
    return _default_session.store


def _repo_signature(root: Path) -> str:
    return compute_source_signature(root)


def _build_graph_from_repo(root: Path) -> Graph:
    return _session_build_graph_from_repo(root)


def get_default_session() -> GraphSession:
    return _default_session


def ensure_graph_loaded(repo_root: str | Path | None = None) -> None:
    root = Path(repo_root).resolve() if repo_root is not None else Path.cwd().resolve()
    signature = compute_source_signature(root)
    if (
        _default_session.graph is not None
        and _default_session.repo_identity is not None
        and _default_session.repo_identity.repo_root == root
        and _default_session.source_signature == signature
    ):
        return
    graph = _build_graph_from_repo(root)
    _default_session.set_graph(
        graph,
        repo_root=root,
        source_signature=signature,
    )


def get_active_repo_root() -> Path | None:
    if _default_session.repo_identity is None:
        return None
    return _default_session.repo_identity.repo_root


def get_active_repo_metadata() -> dict[str, object]:
    return _default_session.repo_metadata()


def resolve(symbol: str) -> GraphNode | None:
    return _default_session.resolve(symbol)


def expand(
    node_id: str,
    depth: int = 1,
    score_fn: SelectionCallable | None = None,
    observer: GraphReplayObserver | None = None,
) -> GraphSnapshotDict:
    return _default_session.expand(
        node_id=node_id,
        depth=depth,
        score_fn=score_fn,
        observer=observer,
    )


def expand_with_policy(
    node_id: str,
    depth: int,
    score_fn: SelectionCallable,
    observer: GraphReplayObserver | None = None,
) -> GraphSnapshotDict:
    return expand(node_id=node_id, depth=depth, score_fn=score_fn, observer=observer)


def resolve_and_expand(
    symbol: str,
    depth: int = 1,
    score_fn: SelectionCallable | None = None,
    observer: GraphReplayObserver | None = None,
) -> GraphSnapshotDict:
    node = resolve(symbol)
    if node is None:
        return {"nodes": [], "edges": [], "metadata": {}}
    return expand(node.id, depth=depth, score_fn=score_fn, observer=observer)
