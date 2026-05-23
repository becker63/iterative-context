from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import math
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from mcp.server import Server
from mcp.types import TextContent, Tool

from iterative_context import exploration
from iterative_context.anchor_policy import (
    POLICY_INTERFACE_VERSION,
    AnchorCandidate,
    AnchorDecision,
    ResolveCandidateCounts,
    ResolvePolicyState,
    anchor_candidate_to_dict,
    anchor_decision_from_value,
    anchor_decision_to_dict,
)
from iterative_context.graph_models import GraphNode
from iterative_context.serialization import serialize_graph_summary, serialize_node
from iterative_context.types import (
    LookaheadPolicyCallable,
    ResolvePolicyCallable,
)

server = Server("iterative-context")

_DEPTH_FLOAT_TOLERANCE = 1e-9


class ToolPayloadError(Exception):
    def __init__(self, code: str, message: str, **payload: object):
        super().__init__(message)
        self.code = code
        self.message = message
        self.payload = payload

    def as_payload(self) -> dict[str, object]:
        out: dict[str, object] = {"error": self.message, "error_code": self.code}
        out.update(self.payload)
        return out


@dataclass
class InstalledPolicy:
    policy_id: str
    policy_path: Path
    policy_sha: str
    interface_version: str
    resolve_policy_symbol: str | None
    lookahead_policy_symbol: str | None
    resolve_policy: ResolvePolicyCallable | None
    lookahead_policy: LookaheadPolicyCallable | None
    install_mode: str

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "policy_id": self.policy_id,
            "policy_path": str(self.policy_path),
            "policy_sha": self.policy_sha,
            "interface_version": self.interface_version,
            "install_mode": self.install_mode,
            "resolve_policy_symbol": self.resolve_policy_symbol,
            "lookahead_policy_symbol": self.lookahead_policy_symbol,
        }
        payload["has_resolve_policy"] = self.resolve_policy is not None
        payload["has_lookahead_policy"] = self.lookahead_policy is not None
        return payload


def _serialize_resolved_node(node: GraphNode) -> dict[str, Any]:
    graph = exploration.get_active_graph()
    extras: dict[str, Any] = {}
    if graph is not None and node.id in graph.nodes:
        raw = graph.nodes[node.id]
        extras = {k: v for k, v in raw.items() if k != "data"}
    return serialize_node(node, extras)


def _serialize_candidate(candidate: AnchorCandidate) -> dict[str, object]:
    payload = anchor_candidate_to_dict(candidate)
    metadata = candidate.metadata or {}
    symbol_value = metadata.get("symbol")
    if isinstance(symbol_value, str):
        payload["symbol"] = symbol_value
    file_value = metadata.get("file")
    if isinstance(file_value, str):
        payload["file"] = file_value
    return payload


def _serialize_candidates(candidates: list[AnchorCandidate]) -> list[dict[str, object]]:
    return [_serialize_candidate(candidate) for candidate in candidates]


def _empty_expansion_graph() -> dict[str, Any]:
    return {"nodes": [], "edges": [], "metadata": {}}


def _serialize_active_graph() -> dict[str, Any]:
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
            name="install_policy",
            description="Install a behavior policy for this runtime session.",
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
                    "interface_version": {
                        "type": "string",
                        "description": (
                            "Policy contract version. Defaults to "
                            "iterative_context.behavior_policy.v1."
                        ),
                    },
                    "resolve_policy_symbol": {
                        "type": "string",
                        "description": (
                            "Optional behavior symbol for fuzzy anchor decisions. "
                            "Defaults to resolve_policy."
                        ),
                    },
                    "lookahead_policy_symbol": {
                        "type": "string",
                        "description": (
                            "Optional behavior symbol for graph traversal lookahead. "
                            "Defaults to lookahead_policy."
                        ),
                    },
                },
                "required": ["policy_path", "policy_id"],
            },
        ),
        Tool(
            name="verify_policy",
            description="Verify the active session-bound behavior policy identity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "policy_id": {
                        "type": "string",
                        "description": "Expected deterministic policy identity.",
                    },
                    "policy_sha": {
                        "type": "string",
                        "description": (
                            "Expected policy SHA256 when the harness wants stronger "
                            "identity verification."
                        ),
                    },
                    "interface_version": {
                        "type": "string",
                        "description": "Expected policy interface version.",
                    },
                },
                "required": ["policy_id"],
            },
        ),
        Tool(
            name="describe_policy",
            description="Describe the currently active policy metadata.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
    ]


def _as_text_content(payload: dict[str, Any]) -> TextContent:
    return TextContent(type="text", text=json.dumps(payload))


class IterativeContextToolRuntime:
    """In-process MCP-compatible runtime for the IC MCP surface."""

    def __init__(self, repo_root: str | Path | None = None):
        self._repo_root = Path(repo_root).resolve() if repo_root is not None else None
        self._installed_policy: InstalledPolicy | None = None

    async def list_tools(self) -> list[Tool]:
        return _tool_definitions()

    async def list_admin_tools(self) -> list[Tool]:
        return _admin_tool_definitions()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            result = self._dispatch(name, arguments or {})
            return [_as_text_content(result)]
        except ToolPayloadError as exc:
            return [_as_text_content(exc.as_payload())]
        except Exception as exc:  # pragma: no cover - defensive guard
            return [_as_text_content({"error": str(exc)})]

    def _dispatch(  # noqa: PLR0911
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        tool_name = name.strip()
        if tool_name == "install_policy":
            return self._install_policy(arguments)
        if tool_name == "verify_policy":
            return self._verify_policy(arguments)
        if tool_name == "describe_policy":
            return self._describe_policy()

        if tool_name == "resolve":
            self._ensure_policy_ready_for_evaluator()
            return self._resolve_tool(arguments)

        if tool_name == "expand":
            self._ensure_policy_ready_for_evaluator()
            lookahead_policy = self._resolve_effective_lookahead_policy()
            node_id = _require_str(arguments, "node_id")
            depth = _require_int(arguments, "depth")
            self._ensure_graph_ready()
            graph = exploration.expand(node_id=node_id, depth=depth, score_fn=lookahead_policy)
            return {
                "graph": graph,
                "full_graph": _serialize_active_graph(),
                **self._policy_payload_fields(),
            }

        if tool_name == "resolve_and_expand":
            self._ensure_policy_ready_for_evaluator()
            lookahead_policy = self._resolve_effective_lookahead_policy()
            return self._resolve_and_expand(arguments, lookahead_policy)

        return {"error": f"Unknown tool: {name}"}

    def _ensure_graph_ready(self) -> None:
        exploration.ensure_graph_loaded(repo_root=self._repo_root)

    def _ensure_policy_ready_for_evaluator(self) -> None:
        if self._installed_policy is None:
            raise ToolPayloadError(
                "policy_install_required",
                "policy install required before evaluator tools can run",
            )

    def clear_policy_install(self) -> None:
        self._installed_policy = None

    def _policy_payload_fields(self) -> dict[str, object]:
        if self._installed_policy is None:
            return {
                "active_policy_id": None,
                "policy_interface_version": POLICY_INTERFACE_VERSION,
            }
        return {
            "active_policy_id": self._installed_policy.policy_id,
            "policy_interface_version": self._installed_policy.interface_version,
            "policy_path": str(self._installed_policy.policy_path),
            "policy_sha": self._installed_policy.policy_sha,
        }

    def _install_policy(self, arguments: dict[str, Any]) -> dict[str, Any]:
        policy_path = Path(_require_str(arguments, "policy_path")).expanduser().resolve()
        policy_id = _require_non_empty_str(arguments, "policy_id")
        interface_version = (
            _optional_str(arguments, "interface_version") or POLICY_INTERFACE_VERSION
        )
        resolve_policy_symbol = _optional_str(
            arguments, "resolve_policy_symbol", default="resolve_policy"
        )
        lookahead_policy_symbol = _optional_str(
            arguments, "lookahead_policy_symbol", default="lookahead_policy"
        )

        try:
            module = _load_policy_module(policy_path)
            resolve_policy = _load_required_behavior_callable(
                module, policy_path, resolve_policy_symbol
            )
            lookahead_policy = _load_required_selection_callable(
                module, policy_path, lookahead_policy_symbol
            )
        except FileNotFoundError as exc:
            raise ToolPayloadError(
                "policy_load_error",
                str(exc),
                policy_path=str(policy_path),
            ) from exc
        except (ImportError, ValueError) as exc:
            raise ToolPayloadError(
                "policy_load_error",
                str(exc),
                policy_path=str(policy_path),
                policy_id=policy_id,
            ) from exc

        installed = InstalledPolicy(
            policy_id=policy_id,
            policy_path=policy_path,
            policy_sha=_sha256_file(policy_path),
            interface_version=interface_version,
            resolve_policy_symbol=resolve_policy_symbol,
            lookahead_policy_symbol=lookahead_policy_symbol,
            resolve_policy=resolve_policy,
            lookahead_policy=lookahead_policy,
            install_mode="policy",
        )
        self._installed_policy = installed
        return {
            "ok": True,
            **installed.to_payload(),
            "policy_source": "installed",
        }

    def _verify_policy(self, arguments: dict[str, Any]) -> dict[str, Any]:
        expected_policy_id = _require_non_empty_str(arguments, "policy_id")
        expected_policy_sha = _optional_str(arguments, "policy_sha")
        expected_interface_version = _optional_str(arguments, "interface_version")

        if self._installed_policy is None:
            raise ToolPayloadError(
                "no_active_policy",
                "no policy installed for this runtime session",
                expected_policy_id=expected_policy_id,
            )
        if self._installed_policy.policy_id != expected_policy_id:
            raise ToolPayloadError(
                "policy_mismatch",
                (
                    "active policy mismatch: expected "
                    f"{expected_policy_id}, got {self._installed_policy.policy_id}"
                ),
                expected_policy_id=expected_policy_id,
                active_policy_id=self._installed_policy.policy_id,
            )
        if (
            expected_policy_sha is not None
            and self._installed_policy.policy_sha != expected_policy_sha
        ):
            raise ToolPayloadError(
                "policy_mismatch",
                (
                    "active policy sha mismatch: expected "
                    f"{expected_policy_sha}, got {self._installed_policy.policy_sha}"
                ),
                expected_policy_sha=expected_policy_sha,
                active_policy_sha=self._installed_policy.policy_sha,
            )
        if (
            expected_interface_version is not None
            and self._installed_policy.interface_version != expected_interface_version
        ):
            raise ToolPayloadError(
                "policy_mismatch",
                (
                    "active policy interface_version mismatch: expected "
                    f"{expected_interface_version}, got {self._installed_policy.interface_version}"
                ),
                expected_interface_version=expected_interface_version,
                active_interface_version=self._installed_policy.interface_version,
            )
        return {"ok": True, **self._installed_policy.to_payload(), "policy_source": "installed"}

    def _describe_policy(self) -> dict[str, Any]:
        if self._installed_policy is None:
            return {
                "ok": True,
                "active": False,
                "policy_source": None,
                "policy_interface_version": POLICY_INTERFACE_VERSION,
            }
        return {
            "ok": True,
            "active": True,
            "policy_source": "installed",
            **self._installed_policy.to_payload(),
        }

    def admin_install_policy(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._install_policy(arguments)

    def admin_verify_policy(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._verify_policy(arguments)

    def admin_describe_policy(self) -> dict[str, Any]:
        return self._describe_policy()

    def _resolve_effective_lookahead_policy(self) -> LookaheadPolicyCallable:
        if self._installed_policy is None:
            raise ToolPayloadError(
                "policy_install_required",
                "policy install required before evaluator tools can run",
            )
        if self._installed_policy.lookahead_policy is None:
            raise ToolPayloadError(
                "policy_load_error",
                "installed policy does not define a callable lookahead_policy",
                policy_id=self._installed_policy.policy_id,
            )
        return self._installed_policy.lookahead_policy

    def _resolve_tool(self, arguments: dict[str, Any]) -> dict[str, Any]:
        symbol = _take_anchor_symbol(arguments)
        self._ensure_graph_ready()
        decision = self._resolve_anchor_decision(symbol)
        return self._resolve_payload_from_decision(symbol, decision)

    def _resolve_anchor_decision(self, symbol: str) -> AnchorDecision:
        self._ensure_graph_ready()
        store = exploration.get_active_store()
        candidates = (
            [] if store is None else store.collect_anchor_candidates(symbol, limit=8)
        )
        state = self._resolve_policy_state(symbol, candidates)
        if self._installed_policy is None or self._installed_policy.resolve_policy is None:
            raise ToolPayloadError(
                "policy_load_error",
                "installed policy does not define a callable resolve_policy",
                policy_id=self._installed_policy.policy_id if self._installed_policy else None,
            )
        raw_decision = self._installed_policy.resolve_policy(symbol, candidates, state)
        try:
            return anchor_decision_from_value(
                raw_decision,
                query=symbol,
                fallback_candidates=candidates,
            )
        except ValueError as exc:
            raise ToolPayloadError(
                "policy_behavior_error",
                f"resolve_policy returned invalid AnchorDecision: {exc}",
                policy_id=self._installed_policy.policy_id if self._installed_policy else None,
            ) from exc

    def _resolve_policy_state(
        self, query: str, candidates: list[AnchorCandidate]
    ) -> ResolvePolicyState:
        exact = 0
        fuzzy = 0
        file_matches = 0
        for candidate in candidates:
            source = (candidate.metadata or {}).get("match_source")
            if source == "exact_symbol":
                exact += 1
            elif source == "fuzzy_symbol":
                fuzzy += 1
            elif source == "file_substring":
                file_matches += 1
        return ResolvePolicyState(
            query_label=query,
            repo_metadata=exploration.get_active_repo_metadata(),
            candidate_limit=8,
            fuzzy_min_score=70.0,
            fuzzy_gap=5.0,
            candidate_counts=ResolveCandidateCounts(
                total=len(candidates),
                exact_symbol=exact,
                fuzzy_symbol=fuzzy,
                file_substring=file_matches,
            ),
            active_policy_id=(
                self._installed_policy.policy_id if self._installed_policy else None
            ),
            policy_interface_version=(
                self._installed_policy.interface_version
                if self._installed_policy is not None
                else POLICY_INTERFACE_VERSION
            ),
        )

    def _resolve_payload_from_decision(
        self,
        symbol: str,
        decision: AnchorDecision,
        *,
        include_graph: bool = False,
        graph: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        node = self._decision_node(decision)
        payload: dict[str, Any] = {
            "query": symbol,
            "node": node,
            "anchor_decision": anchor_decision_to_dict(decision),
            "full_graph": _serialize_active_graph(),
            **self._policy_payload_fields(),
        }
        if decision.candidates:
            payload["candidates"] = _serialize_candidates(decision.candidates)
        if include_graph:
            payload["graph"] = graph if graph is not None else _empty_expansion_graph()
        return payload

    def _decision_node(self, decision: AnchorDecision) -> dict[str, Any] | None:
        if decision.status != "resolved" or decision.selected_anchor_id is None:
            return None
        store = exploration.get_active_store()
        if store is None:
            return None
        node = store._node_for_id(  # pyright: ignore[reportPrivateUsage]
            decision.selected_anchor_id
        )
        if node is None:
            return None
        return _serialize_resolved_node(node)

    def _resolve_and_expand(
        self,
        arguments: dict[str, Any],
        lookahead_policy: LookaheadPolicyCallable,
    ) -> dict[str, Any]:
        symbol = _take_anchor_symbol(arguments)
        budget = _take_depth(arguments, default=1)
        self._ensure_graph_ready()

        decision = self._resolve_anchor_decision(symbol)
        if (
            decision.status != "resolved"
            or decision.selected_anchor_id is None
            or budget <= 0
        ):
            return self._resolve_payload_from_decision(
                symbol,
                decision,
                include_graph=True,
                graph=_empty_expansion_graph(),
            )

        graph = exploration.expand(
            decision.selected_anchor_id,
            depth=budget,
            score_fn=lookahead_policy,
        )
        return self._resolve_payload_from_decision(
            symbol,
            decision,
            include_graph=True,
            graph=cast(dict[str, Any], graph),
        )


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


def _require_non_empty_str(arguments: dict[str, Any], key: str) -> str:
    value = _require_str(arguments, key).strip()
    if not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_str(
    arguments: dict[str, Any], key: str, *, default: str | None = None
) -> str | None:
    value = arguments.get(key, default)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    stripped = value.strip()
    return stripped or None


def _require_int(arguments: dict[str, Any], key: str) -> int:
    value = arguments.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        hasher.update(fh.read())
    return hasher.hexdigest()


def _load_policy_module(policy_path: str | Path) -> ModuleType:
    path = Path(policy_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"policy module not found: {path}")

    module_name = f"iterative_context_installed_policy_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load policy module from {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_optional_behavior_callable(
    module: ModuleType, policy_path: Path, symbol: str | None
) -> ResolvePolicyCallable | None:
    if symbol is None:
        return None
    candidate = getattr(module, symbol, None)
    if candidate is None:
        return None
    if not callable(candidate):
        raise ValueError(f"policy module {policy_path} defines non-callable {symbol}")
    _validate_callable_signature(
        candidate,
        expected_arity=3,
        policy_path=policy_path,
        symbol=symbol,
    )
    return cast(ResolvePolicyCallable, candidate)


def _load_required_behavior_callable(
    module: ModuleType, policy_path: Path, symbol: str | None
) -> ResolvePolicyCallable:
    candidate = _load_optional_behavior_callable(module, policy_path, symbol)
    if candidate is None:
        raise ValueError(f"policy module {policy_path} does not define callable {symbol}")
    return candidate


def _load_optional_selection_callable(
    module: ModuleType, policy_path: Path, symbol: str | None
) -> LookaheadPolicyCallable | None:
    if symbol is None:
        return None
    candidate = getattr(module, symbol, None)
    if candidate is None:
        return None
    if not callable(candidate):
        raise ValueError(f"policy module {policy_path} defines non-callable {symbol}")
    _validate_callable_signature(
        candidate,
        expected_arity=3,
        policy_path=policy_path,
        symbol=symbol,
    )
    return cast(LookaheadPolicyCallable, candidate)


def _load_required_selection_callable(
    module: ModuleType, policy_path: Path, symbol: str | None
) -> LookaheadPolicyCallable:
    candidate = _load_optional_selection_callable(module, policy_path, symbol)
    if candidate is None:
        raise ValueError(f"policy module {policy_path} does not define callable {symbol}")
    return candidate


def load_policy_callable(
    policy_path: str | Path, symbol: str = "lookahead_policy"
) -> LookaheadPolicyCallable:
    path = Path(policy_path).expanduser().resolve()
    module = _load_policy_module(path)
    return _load_required_selection_callable(module, path, symbol)


def _validate_callable_signature(
    candidate: Any,
    *,
    expected_arity: int,
    policy_path: Path,
    symbol: str,
) -> None:
    try:
        signature = inspect.signature(candidate)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"policy module {policy_path} exposes {symbol} with unreadable signature"
        ) from exc

    positional_params = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    has_varargs = any(
        parameter.kind is inspect.Parameter.VAR_POSITIONAL
        for parameter in signature.parameters.values()
    )
    if has_varargs or len(positional_params) != expected_arity:
        raise ValueError(
            f"policy module {policy_path} callable {symbol} must accept exactly "
            f"{expected_arity} positional parameters"
        )


_default_runtime = IterativeContextToolRuntime()


async def list_tools() -> list[Tool]:
    return await _default_runtime.list_tools()


async def list_admin_tools() -> list[Tool]:
    return await _default_runtime.list_admin_tools()


async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    return await _default_runtime.call_tool(name, arguments)


async def install_policy(
    policy_path: str,
    policy_id: str,
    *,
    resolve_policy_symbol: str = "resolve_policy",
    lookahead_policy_symbol: str = "lookahead_policy",
) -> dict[str, Any]:
    return _default_runtime.admin_install_policy(
        {
            "policy_path": policy_path,
            "policy_id": policy_id,
            "resolve_policy_symbol": resolve_policy_symbol,
            "lookahead_policy_symbol": lookahead_policy_symbol,
        }
    )


async def verify_policy(policy_id: str) -> dict[str, Any]:
    return _default_runtime.admin_verify_policy({"policy_id": policy_id})


async def describe_policy() -> dict[str, Any]:
    return _default_runtime.admin_describe_policy()


@server.list_tools()
async def _server_list_tools() -> list[Tool]:  # pyright: ignore[reportUnusedFunction]
    return await list_tools()


@server.call_tool()
async def _server_call_tool(  # pyright: ignore[reportUnusedFunction]
    name: str, arguments: dict[str, Any]
) -> list[TextContent]:
    return await call_tool(name, arguments)


def main() -> None:
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
    "install_policy",
    "verify_policy",
    "describe_policy",
    "load_policy_callable",
    "main",
]
