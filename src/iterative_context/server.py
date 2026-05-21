from __future__ import annotations

import importlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any, cast

from mcp.server import Server
from mcp.types import TextContent, Tool

from iterative_context import exploration
from iterative_context.scoring import default_score_fn
from iterative_context.serialization import serialize_graph_summary, serialize_node
from iterative_context.graph_models import GraphNode
from iterative_context.types import SelectionCallable

server = Server("iterative-context")

_DEPTH_FLOAT_TOLERANCE = 1e-9


def _serialize_resolved_node(node: GraphNode) -> dict[str, Any]:
    """Serialize a resolved graph node with any graph extras."""
    graph = exploration.get_active_graph()
    extras: dict[str, Any] = {}
    if graph is not None and node.id in graph.nodes:
        raw = graph.nodes[node.id]
        extras = {k: v for k, v in raw.items() if k != "data"}
    return serialize_node(node, extras)


def _resolve_lookup(symbol: str) -> tuple[dict[str, Any] | None, list[dict[str, object]] | None]:
    """
    Resolve a symbol to a node and/or ranked candidates.

    Returns (node, candidates). On unique match, node is set and candidates is None.
    On ambiguity or below-threshold miss, node is None and candidates lists top matches.
    """
    node = exploration.resolve(symbol)
    if node is not None:
        return _serialize_resolved_node(node), None

    store = exploration.get_active_store()
    if store is None:
        return None, None

    candidates = store.resolve_candidates(symbol)
    if candidates:
        return None, candidates
    return None, None


def _empty_expansion_graph() -> dict[str, Any]:
    return {"nodes": [], "edges": [], "metadata": {}}


def _resolve_tool_payload(
    symbol: str,
    *,
    score_source: str,
    active_score_id: str | None,
    include_graph: bool = False,
) -> dict[str, Any]:
    node, candidates = _resolve_lookup(symbol)
    payload: dict[str, Any] = {
        "node": node,
        "full_graph": _serialize_active_graph(),
        "score_source": score_source,
        "active_score_id": active_score_id,
    }
    if include_graph:
        payload["graph"] = _empty_expansion_graph()
    if candidates is not None:
        payload["candidates"] = candidates
        payload["query"] = symbol
    return payload


def _serialize_active_graph() -> dict[str, Any]:
    """Return a compact digest of the active graph (not full node/edge lists)."""
    graph = exploration.get_active_graph()
    metadata: dict[str, Any] = {"source": "active_graph"}
    metadata.update(exploration.get_active_repo_metadata())
    return serialize_graph_summary(graph, metadata=metadata)


def _tool_definitions() -> list[Tool]:
    return [
        Tool(
            name="resolve",
            description=(
                "Resolve a symbol to a graph node if present. Provide symbol (preferred), "
                "or query — an alias carrying the same string when models emit generic search text."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Anchor string to resolve (identifier or searchable text).",
                    },
                    "query": {
                        "type": "string",
                        "description": "Alias of symbol for tool-call ergonomics.",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="expand",
            description="Expand a node outward to a bounded depth.",
            inputSchema={
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "ID of the node to expand"},
                    "depth": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Expansion depth to explore",
                    },
                },
                "required": ["node_id", "depth"],
            },
        ),
        Tool(
            name="resolve_and_expand",
            description=(
                "Resolve a symbol and expand its neighborhood. Provide symbol or query "
                "(alias). Depth defaults to 1 when omitted."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Anchor passed to resolve (identifier or searchable text).",
                    },
                    "query": {
                        "type": "string",
                        "description": "Alias of symbol for models that omit symbol.",
                    },
                    "depth": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Expansion depth to explore (defaults to 1).",
                    },
                },
                "required": [],
            },
        ),
    ]


def _admin_tool_definitions() -> list[Tool]:
    return [
        Tool(
            name="install_score",
            description="Install a score or selection policy for this runtime session.",
            inputSchema={
                "type": "object",
                "properties": {
                    "policy_path": {
                        "type": "string",
                        "description": "Filesystem path to the Python policy module.",
                    },
                    "policy_id": {
                        "type": "string",
                        "description": "Deterministic policy identity chosen by the harness.",
                    },
                    "symbol": {
                        "type": "string",
                        "description": (
                            "Callable symbol to load from the module. "
                            "Defaults to score_fn."
                        ),
                    },
                },
                "required": ["policy_path", "policy_id"],
            },
        ),
        Tool(
            name="verify_score",
            description="Verify the active session-bound score or selection policy identity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "policy_id": {
                        "type": "string",
                        "description": "Expected deterministic policy identity.",
                    }
                },
                "required": ["policy_id"],
            },
        ),
    ]


def _as_text_content(payload: dict[str, Any]) -> TextContent:
    return TextContent(type="text", text=json.dumps(payload))


class IterativeContextToolRuntime:
    """In-process MCP-compatible runtime with optional scoring injection."""

    def __init__(
        self,
        score_fn: SelectionCallable | None = None,
        repo_root: str | Path | None = None,
        require_score_install: bool = False,
    ):
        self._score_fn = score_fn
        self._repo_root = Path(repo_root).resolve() if repo_root is not None else None
        self._require_score_install = require_score_install
        self._installed_score_fn: SelectionCallable | None = None
        self._active_score_id: str | None = None
        self._active_score_path: Path | None = None

    async def list_tools(self) -> list[Tool]:
        return _tool_definitions()

    async def list_admin_tools(self) -> list[Tool]:
        return _admin_tool_definitions()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            result = self._dispatch(name, arguments or {})
            return [_as_text_content(result)]
        except Exception as exc:  # pragma: no cover - defensive guard
            return [_as_text_content({"error": str(exc)})]

    def _dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_name = name.strip()
        if tool_name == "install_score":
            return self._install_score(arguments)
        if tool_name == "verify_score":
            return self._verify_score(arguments)

        score_fn, score_source, active_score_id = self._resolve_effective_score_fn()
        if tool_name == "resolve":
            symbol = _take_anchor_symbol(arguments)
            self._ensure_graph_ready()
            return _resolve_tool_payload(
                symbol,
                score_source=score_source,
                active_score_id=active_score_id,
            )

        if tool_name == "expand":
            node_id = _require_str(arguments, "node_id")
            depth = _require_int(arguments, "depth")
            self._ensure_graph_ready()
            graph = exploration.expand(node_id=node_id, depth=depth, score_fn=score_fn)
            return {
                "graph": graph,
                "full_graph": _serialize_active_graph(),
                "score_source": score_source,
                "active_score_id": active_score_id,
            }

        if tool_name == "resolve_and_expand":
            return self._resolve_and_expand(arguments, score_fn, score_source, active_score_id)

        return {"error": f"Unknown tool: {name}", "score_source": score_source}

    def _ensure_graph_ready(self) -> None:
        exploration.ensure_graph_loaded(repo_root=self._repo_root)

    def clear_score_install(self) -> None:
        self._installed_score_fn = None
        self._active_score_id = None
        self._active_score_path = None

    def _install_score(self, arguments: dict[str, Any]) -> dict[str, Any]:
        policy_path = Path(_require_str(arguments, "policy_path")).expanduser().resolve()
        policy_id = _require_str(arguments, "policy_id").strip()
        if not policy_id:
            raise ValueError("policy_id must be a non-empty string")

        raw_symbol = arguments.get("symbol", "score_fn")
        if not isinstance(raw_symbol, str) or not raw_symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        symbol = raw_symbol.strip()

        score_fn = load_policy_callable(policy_path, symbol)
        self._installed_score_fn = score_fn
        self._active_score_id = policy_id
        self._active_score_path = policy_path
        return {
            "ok": True,
            "policy_id": policy_id,
            "policy_path": str(policy_path),
            "symbol": symbol,
            "score_source": "installed",
        }

    def _verify_score(self, arguments: dict[str, Any]) -> dict[str, Any]:
        expected_policy_id = _require_str(arguments, "policy_id").strip()
        if not expected_policy_id:
            raise ValueError("policy_id must be a non-empty string")

        if self._active_score_id is None:
            raise RuntimeError("no score installed for this runtime session")
        if self._active_score_id != expected_policy_id:
            raise RuntimeError(
                f"active score mismatch: expected {expected_policy_id}, got {self._active_score_id}"
            )

        payload: dict[str, Any] = {
            "ok": True,
            "policy_id": self._active_score_id,
            "score_source": "installed",
        }
        if self._active_score_path is not None:
            payload["policy_path"] = str(self._active_score_path)
        return payload

    def admin_install_score(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Synchronous admin helper for harness-side validation (non-global runtime)."""

        return self._install_score(arguments)

    def admin_verify_score(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Synchronous admin helper for harness-side validation (non-global runtime)."""

        return self._verify_score(arguments)

    def _resolve_effective_score_fn(self) -> tuple[SelectionCallable, str, str | None]:
        if self._installed_score_fn is not None:
            return self._installed_score_fn, "installed", self._active_score_id
        if self._require_score_install:
            raise RuntimeError("score install required before evaluator tools can run")

        score_fn, score_source = _resolve_fallback_score_fn(self._score_fn)
        return score_fn, score_source, None

    def _resolve_and_expand(
        self,
        arguments: dict[str, Any],
        score_fn: SelectionCallable,
        score_source: str,
        active_score_id: str | None,
    ) -> dict[str, Any]:
        symbol = _take_anchor_symbol(arguments)
        depth = _take_depth(arguments, default=1)
        self._ensure_graph_ready()

        node, candidates = _resolve_lookup(symbol)
        if candidates is not None:
            return _resolve_tool_payload(
                symbol,
                score_source=score_source,
                active_score_id=active_score_id,
                include_graph=True,
            )

        if node is None:
            return {
                "node": None,
                "graph": _empty_expansion_graph(),
                "full_graph": _serialize_active_graph(),
                "score_source": score_source,
                "active_score_id": active_score_id,
            }

        return {
            "node": node,
            "graph": exploration.expand(node["id"], depth=depth, score_fn=score_fn),
            "full_graph": _serialize_active_graph(),
            "score_source": score_source,
            "active_score_id": active_score_id,
        }


def _take_anchor_symbol(arguments: dict[str, Any]) -> str:
    sym = arguments.get("symbol")
    q = arguments.get("query")
    if isinstance(sym, str) and sym.strip():
        return sym.strip()
    if isinstance(q, str) and q.strip():
        return q.strip()
    raise ValueError("provide symbol or query (non-empty string)")


def _take_depth(arguments: dict[str, Any], default: int) -> int:
    if "depth" not in arguments or arguments["depth"] is None:
        return default
    v = arguments["depth"]
    if isinstance(v, bool):
        raise ValueError("depth must be an integer")
    if isinstance(v, int):
        if v < 0:
            raise ValueError("depth must be >= 0")
        return v
    if isinstance(v, float) and math.isfinite(v):
        rounded = round(v)
        if abs(v - rounded) > _DEPTH_FLOAT_TOLERANCE:
            raise ValueError("depth must be an integer")
        if rounded < 0:
            raise ValueError("depth must be >= 0")
        return int(rounded)
    raise ValueError("depth must be an integer")


def _require_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _require_int(arguments: dict[str, Any], key: str) -> int:
    value = arguments.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def load_policy_callable(policy_path: str | Path, symbol: str = "score_fn") -> SelectionCallable:
    path = Path(policy_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"policy module not found: {path}")

    module_name = f"iterative_context_installed_policy_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load policy module from {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    candidate = getattr(module, symbol, None)
    if candidate is None and symbol == "score_fn":
        candidate = getattr(module, "score", None)
    if not callable(candidate):
        raise ValueError(f"policy module {path} does not define callable {symbol}")
    return cast(SelectionCallable, candidate)


def load_local_policy() -> SelectionCallable | None:
    """Dynamically load a local policy module if present."""
    try:
        policy_module = importlib.import_module("iterative_context.policy")
    except Exception:
        return None

    candidate = getattr(policy_module, "score_fn", None) or getattr(policy_module, "score", None)
    if callable(candidate):
        return cast(SelectionCallable, candidate)
    return None


def _resolve_fallback_score_fn(
    injected_score_fn: SelectionCallable | None,
) -> tuple[SelectionCallable, str]:
    """Resolve the scoring function with explicit precedence."""
    if injected_score_fn is not None:
        return injected_score_fn, "injected"

    local_policy = load_local_policy()
    if local_policy is not None:
        return local_policy, "local_policy"

    return default_score_fn, "default"


_default_runtime = IterativeContextToolRuntime()


async def list_tools() -> list[Tool]:
    return await _default_runtime.list_tools()


async def list_admin_tools() -> list[Tool]:
    return await _default_runtime.list_admin_tools()


async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    return await _default_runtime.call_tool(name, arguments)


async def install_score(
    policy_path: str, policy_id: str, symbol: str = "score_fn"
) -> dict[str, Any]:
    return _default_runtime.admin_install_score(
        {"policy_path": policy_path, "policy_id": policy_id, "symbol": symbol}
    )


async def verify_score(policy_id: str) -> dict[str, Any]:
    return _default_runtime.admin_verify_score({"policy_id": policy_id})


@server.list_tools()
async def _server_list_tools() -> list[Tool]:  # pyright: ignore[reportUnusedFunction]
    return await list_tools()


@server.call_tool()
async def _server_call_tool(  # pyright: ignore[reportUnusedFunction]
    name: str, arguments: dict[str, Any]
) -> list[TextContent]:
    return await call_tool(name, arguments)


def main() -> None:
    """Run the MCP server over stdio (for SearchBench and other MCP clients)."""
    import anyio  # noqa: PLC0415
    from mcp.server.stdio import stdio_server  # noqa: PLC0415

    async def run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    anyio.run(run)


if __name__ == "__main__":
    main()


__all__ = [
    "server",
    "IterativeContextToolRuntime",
    "list_tools",
    "list_admin_tools",
    "call_tool",
    "install_score",
    "verify_score",
    "load_policy_callable",
    "main",
]
