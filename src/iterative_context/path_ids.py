from __future__ import annotations

from pathlib import Path
from typing import Literal

NodeKind = Literal["symbol", "function", "file", "type"]

FILE_PREFIX = "file:"
FUNCTION_PREFIX = "function:"
MODULE_PREFIX = "module:"
SYMBOL_PREFIX = "symbol:"
TYPE_PREFIX = "type:"


def repo_relative_path(path: str | Path, repo_root: str | Path) -> str:
    root = Path(repo_root).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    normalized = candidate.relative_to(root).as_posix()
    return normalized


def file_node_id(path: str | Path, repo_root: str | Path) -> str:
    return f"{FILE_PREFIX}{repo_relative_path(path, repo_root)}"


def function_node_id(path: str | Path, function_name: str, repo_root: str | Path) -> str:
    rel = repo_relative_path(path, repo_root)
    return f"{FUNCTION_PREFIX}{rel}::{function_name.strip()}"


def module_node_id(module: str) -> str:
    return f"{MODULE_PREFIX}{module.strip()}"


def symbol_node_id(symbol: str) -> str:
    return f"{SYMBOL_PREFIX}{symbol.strip()}"


def type_node_id(name: str) -> str:
    return f"{TYPE_PREFIX}{name.strip()}"


def node_kind_for_id(node_id: str) -> NodeKind:
    if node_id.startswith(FUNCTION_PREFIX):
        return "function"
    if node_id.startswith(FILE_PREFIX):
        return "file"
    if node_id.startswith(TYPE_PREFIX) or node_id.startswith(MODULE_PREFIX):
        return "type"
    return "symbol"


def node_label_for_id(node_id: str) -> str:
    if node_id.startswith(FUNCTION_PREFIX):
        _, _, function_name = node_id[len(FUNCTION_PREFIX) :].partition("::")
        return function_name or node_id
    for prefix in (FILE_PREFIX, MODULE_PREFIX, SYMBOL_PREFIX, TYPE_PREFIX):
        if node_id.startswith(prefix):
            return node_id[len(prefix) :]
    return node_id


def file_for_node_id(node_id: str) -> str | None:
    if node_id.startswith(FILE_PREFIX):
        return node_id[len(FILE_PREFIX) :]
    if node_id.startswith(FUNCTION_PREFIX):
        rel_path, _, _ = node_id[len(FUNCTION_PREFIX) :].partition("::")
        return rel_path or None
    return None


__all__ = [
    "FILE_PREFIX",
    "FUNCTION_PREFIX",
    "MODULE_PREFIX",
    "SYMBOL_PREFIX",
    "TYPE_PREFIX",
    "NodeKind",
    "repo_relative_path",
    "file_node_id",
    "function_node_id",
    "module_node_id",
    "symbol_node_id",
    "type_node_id",
    "node_kind_for_id",
    "node_label_for_id",
    "file_for_node_id",
]
