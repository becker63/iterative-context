"""MCP surface integration tests."""
# pyright: reportPrivateUsage=false
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from iterative_context import exploration, server
from iterative_context.exploration import _repo_signature, _set_active_graph
from iterative_context.graph_models import Graph
from iterative_context.server import (
    IterativeContextToolRuntime,
    call_tool,
    list_admin_tools,
    list_tools,
)
from iterative_context.test_helpers.graph_dsl import build_graph


@pytest.fixture(autouse=True)
def _reset_active_graph() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    exploration._clear_active_graph()
    server._default_runtime.clear_policy_install()
    yield
    exploration._clear_active_graph()
    server._default_runtime.clear_policy_install()


def _make_graph_with_symbols() -> Graph:
    graph = build_graph(
        {
            "nodes": [
                {"id": "A", "kind": "symbol", "state": "pending"},
                {"id": "B", "kind": "symbol", "state": "pending"},
            ],
            "edges": [
                {"source": "A", "target": "B", "kind": "calls"},
            ],
        }
    )
    graph.nodes["A"]["symbol"] = "expand_node"
    graph.nodes["A"]["file"] = "src/iterative_context/expansion.py"
    graph.nodes["B"]["symbol"] = "other_symbol"
    graph.nodes["B"]["file"] = "src/iterative_context/other.py"
    return graph


def _activate_graph_with_symbols() -> None:
    graph = _make_graph_with_symbols()
    signature = _repo_signature(Path.cwd())
    _set_active_graph(graph, repo_root=Path.cwd().resolve(), signature=signature)


def _write_policy(root: Path, *, score_value: float = 7.0) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "policy.py"
    path.write_text(
        (
            "def lookahead_policy(node, graph, step):\n"
            f"    return {score_value}\n"
            "\n"
            "def resolve_policy(query, candidates, state):\n"
            "    exact = [\n"
            "        candidate\n"
            "        for candidate in candidates\n"
            "        if (candidate.metadata or {}).get('match_source') == 'exact_symbol'\n"
            "    ]\n"
            "    if len(exact) == 1:\n"
            "        chosen = exact[0]\n"
            "        return {\n"
            "            'status': 'resolved',\n"
            "            'query_label': query,\n"
            "            'candidates': [chosen],\n"
            "            'selected_anchor_id': chosen.node_id,\n"
            "            'reason': 'exact_symbol_match',\n"
            "        }\n"
            "    if not candidates:\n"
            "        return {\n"
            "            'status': 'not_found',\n"
            "            'query_label': query,\n"
            "            'candidates': [],\n"
            "            'selected_anchor_id': None,\n"
            "            'reason': 'no_candidates',\n"
            "        }\n"
            "    top = candidates[0]\n"
            "    if top.score is None or top.score < 70.0:\n"
            "        return {\n"
            "            'status': 'not_found',\n"
            "            'query_label': query,\n"
            "            'candidates': candidates[:3],\n"
            "            'selected_anchor_id': None,\n"
            "            'reason': 'below_threshold',\n"
            "        }\n"
            "    if len(candidates) > 1:\n"
            "        second = candidates[1]\n"
            "        if (\n"
            "            top.score is not None\n"
            "            and second.score is not None\n"
            "            and abs(top.score - second.score) <= 5.0\n"
            "        ):\n"
            "            return {\n"
            "                'status': 'ambiguous',\n"
            "                'query_label': query,\n"
            "                'candidates': candidates[:2],\n"
            "                'selected_anchor_id': None,\n"
            "                'reason': 'ambiguous_top_candidates',\n"
            "            }\n"
            "    return {\n"
            "        'status': 'resolved',\n"
            "        'query_label': query,\n"
            "        'candidates': candidates[:3],\n"
            "        'selected_anchor_id': top.node_id,\n"
            "        'reason': 'top_candidate',\n"
            "        'shallow_expand': False,\n"
            "    }\n"
        ),
        encoding="utf-8",
    )
    return path


async def _install_test_policy(
    tmp_path: Path,
    *,
    runtime: IterativeContextToolRuntime | None = None,
    score_value: float = 7.0,
    policy_id: str = "policy-v1",
) -> None:
    policy_path = _write_policy(tmp_path, score_value=score_value)
    tool_runtime = runtime or server._default_runtime
    payload = tool_runtime.admin_install_policy(
        {"policy_path": str(policy_path), "policy_id": policy_id}
    )
    assert payload["ok"] is True


@pytest.mark.anyio
async def test_list_tools_definitions() -> None:
    tools = await list_tools()
    names = {tool.name for tool in tools}
    assert names == {"resolve", "expand", "resolve_and_expand"}

    resolve_tool = next(tool for tool in tools if tool.name == "resolve")
    assert resolve_tool.inputSchema["required"] == []
    assert resolve_tool.inputSchema["properties"]["symbol"]["type"] == "string"

    rex = next(tool for tool in tools if tool.name == "resolve_and_expand")
    assert rex.inputSchema["required"] == []

    expand_tool = next(tool for tool in tools if tool.name == "expand")
    assert expand_tool.inputSchema["properties"]["depth"]["type"] == "integer"
    assert "node_id" in expand_tool.inputSchema["required"]


@pytest.mark.anyio
async def test_list_admin_tools_definitions() -> None:
    tools = await list_admin_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "install_policy",
        "verify_policy",
        "describe_policy",
        "collect_graph_trace",
    }
    assert "start_graph_trace" not in names
    assert "clear_graph_trace" not in names
    assert "describe_graph_trace" not in names

    install_tool = next(tool for tool in tools if tool.name == "install_policy")
    assert install_tool.inputSchema["required"] == ["policy_path", "policy_id"]

    verify_tool = next(tool for tool in tools if tool.name == "verify_policy")
    assert verify_tool.inputSchema["required"] == ["policy_id"]

    collect_tool = next(tool for tool in tools if tool.name == "collect_graph_trace")
    assert collect_tool.inputSchema["required"] == ["trace_id"]


@pytest.mark.anyio
async def test_call_tool_resolve_serializes_node(tmp_path: Path) -> None:
    _activate_graph_with_symbols()
    await _install_test_policy(tmp_path)

    response = await call_tool("resolve", {"symbol": "expand_node"})
    payload = json.loads(response[0].text)

    assert payload["node"]["id"] == "A"
    assert payload["node"]["symbol"] == "expand_node"
    assert payload["anchor_decision"]["status"] == "resolved"
    assert payload["anchor_decision"]["selected_anchor_id"] == "A"
    assert "file" in payload["node"]
    assert payload["full_graph"]["format"] == "summary_v1"
    assert payload["full_graph"]["node_count"] >= 1


def test_default_graph_session_uses_env_repo_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SEARCHBENCH_ITERATIVE_CONTEXT_REPO_ROOT", str(tmp_path))
    session = server._default_graph_session()
    assert session.repo_root == tmp_path.resolve()


@pytest.mark.anyio
async def test_call_tool_expand_returns_graph(tmp_path: Path) -> None:
    _activate_graph_with_symbols()
    await _install_test_policy(tmp_path)

    response = await call_tool("expand", {"node_id": "A", "depth": 1})
    payload = json.loads(response[0].text)
    graph = payload["graph"]

    assert graph["metadata"]["expanded_from"] == "A"
    assert graph["metadata"]["depth"] == 1
    assert graph["nodes"]
    assert payload["full_graph"]["format"] == "summary_v1"
    assert payload["full_graph"]["node_count"] >= 1


@pytest.mark.anyio
async def test_call_tool_resolve_accepts_query_alias(tmp_path: Path) -> None:
    _activate_graph_with_symbols()
    await _install_test_policy(tmp_path)

    response = await call_tool("resolve", {"query": "expand_node"})
    payload = json.loads(response[0].text)

    assert payload["node"]["id"] == "A"
    assert payload["node"]["symbol"] == "expand_node"


@pytest.mark.anyio
async def test_call_tool_resolve_and_expand_accepts_query_and_default_depth(
    tmp_path: Path,
) -> None:
    _activate_graph_with_symbols()
    await _install_test_policy(tmp_path)

    response = await call_tool("resolve_and_expand", {"query": "expand_node"})
    payload = json.loads(response[0].text)

    assert payload["graph"]["metadata"]["expanded_from"] == "A"
    assert payload["graph"]["metadata"]["depth"] == 1
    assert payload["graph"]["nodes"]
    assert payload["anchor_decision"]["status"] == "resolved"


@pytest.mark.anyio
async def test_call_tool_resolve_and_expand(tmp_path: Path) -> None:
    _activate_graph_with_symbols()
    await _install_test_policy(tmp_path)

    response = await call_tool("resolve_and_expand", {"symbol": "expand_node", "depth": 1})
    payload = json.loads(response[0].text)

    assert payload["graph"]["metadata"]["expanded_from"] == "A"
    assert payload["graph"]["nodes"]
    assert payload["anchor_decision"]["status"] == "resolved"
    assert payload["full_graph"]["format"] == "summary_v1"
    assert payload["full_graph"]["node_count"] >= 1


@pytest.mark.anyio
async def test_call_tool_resolve_ambiguous_returns_null_node_and_candidates(
    tmp_path: Path,
) -> None:
    graph = build_graph(
        {
            "nodes": [
                {"id": "A", "kind": "symbol", "state": "pending"},
                {"id": "B", "kind": "symbol", "state": "pending"},
            ],
            "edges": [],
        }
    )
    graph.nodes["A"]["symbol"] = "fetch_user_data"
    graph.nodes["B"]["symbol"] = "fetch_user_info"
    signature = _repo_signature(Path.cwd())
    _set_active_graph(graph, repo_root=Path.cwd().resolve(), signature=signature)
    await _install_test_policy(tmp_path)

    response = await call_tool("resolve", {"query": "fetch_user"})
    payload = json.loads(response[0].text)

    assert payload["node"] is None
    assert payload["anchor_decision"]["status"] == "ambiguous"
    assert len(payload["candidates"]) == 2
    assert payload["query"] == "fetch_user"
    assert "candidates" not in (payload["node"] or {})


@pytest.mark.anyio
async def test_call_tool_resolve_and_expand_ambiguous_returns_candidates(
    tmp_path: Path,
) -> None:
    graph = build_graph(
        {
            "nodes": [
                {"id": "A", "kind": "symbol", "state": "pending"},
                {"id": "B", "kind": "symbol", "state": "pending"},
            ],
            "edges": [],
        }
    )
    graph.nodes["A"]["symbol"] = "fetch_user_data"
    graph.nodes["B"]["symbol"] = "fetch_user_info"
    signature = _repo_signature(Path.cwd())
    _set_active_graph(graph, repo_root=Path.cwd().resolve(), signature=signature)
    await _install_test_policy(tmp_path)

    response = await call_tool("resolve_and_expand", {"query": "fetch_user", "depth": 1})
    payload = json.loads(response[0].text)

    assert payload["node"] is None
    assert payload["anchor_decision"]["status"] == "ambiguous"
    assert len(payload["candidates"]) == 2
    assert payload["query"] == "fetch_user"
    assert payload["graph"]["nodes"] == []
    assert payload["graph"]["edges"] == []


@pytest.mark.anyio
async def test_call_tool_resolve_below_threshold_returns_top_candidates(tmp_path: Path) -> None:
    graph = build_graph(
        {
            "nodes": [
                {"id": "A", "kind": "symbol", "state": "pending"},
                {"id": "B", "kind": "symbol", "state": "pending"},
            ],
            "edges": [],
        }
    )
    graph.nodes["A"]["symbol"] = "expand_node"
    graph.nodes["B"]["symbol"] = "other_symbol"
    signature = _repo_signature(Path.cwd())
    _set_active_graph(graph, repo_root=Path.cwd().resolve(), signature=signature)
    await _install_test_policy(tmp_path)

    response = await call_tool("resolve", {"query": "zzz_no_match"})
    payload = json.loads(response[0].text)

    assert payload["node"] is None
    assert payload["anchor_decision"]["status"] == "not_found"
    assert len(payload["candidates"]) >= 1
    assert payload["query"] == "zzz_no_match"


@pytest.mark.anyio
async def test_call_tool_unknown_returns_error() -> None:
    _activate_graph_with_symbols()

    response = await call_tool("unknown_tool", {})
    payload = json.loads(response[0].text)

    assert "error" in payload
    assert "unknown" in payload["error"].lower()


@pytest.mark.anyio
async def test_runtime_requires_install_before_evaluator_tools(tmp_path: Path) -> None:
    _activate_graph_with_symbols()
    runtime = IterativeContextToolRuntime()

    for tool_name, arguments in (
        ("resolve", {"symbol": "expand_node"}),
        ("expand", {"node_id": "A", "depth": 1}),
        ("resolve_and_expand", {"symbol": "expand_node", "depth": 1}),
    ):
        blocked = await runtime.call_tool(tool_name, arguments)
        blocked_payload = json.loads(blocked[0].text)
        assert "error" in blocked_payload
        assert blocked_payload["error_code"] == "policy_install_required"
        assert "policy install required" in blocked_payload["error"]

    await _install_test_policy(tmp_path, runtime=runtime, score_value=11.0)

    expanded = await runtime.call_tool("expand", {"node_id": "A", "depth": 1})
    expanded_payload = json.loads(expanded[0].text)
    assert expanded_payload["active_policy_id"] == "policy-v1"
    assert expanded_payload["active_behavior_policy_id"] == "policy-v1"
    assert expanded_payload["graph"]["metadata"]["expanded_from"] == "A"


@pytest.mark.anyio
async def test_runtime_verify_policy_reports_missing_and_mismatch(tmp_path: Path) -> None:
    runtime = IterativeContextToolRuntime()

    missing = await runtime.call_tool("verify_policy", {"policy_id": "policy-v1"})
    missing_payload = json.loads(missing[0].text)
    assert "error" in missing_payload
    assert missing_payload["error_code"] == "no_active_policy"
    assert "no policy installed" in missing_payload["error"]

    policy_path = _write_policy(tmp_path, score_value=5.0)
    policy_source = policy_path.read_text(encoding="utf-8")
    policy_sha = hashlib.sha256(policy_source.encode("utf-8")).hexdigest()
    await runtime.call_tool(
        "install_policy",
        {
            "policy_path": str(policy_path),
            "policy_id": "policy-v1",
            "interface_version": "iterative_context.behavior_policy.v1",
        },
    )

    mismatch = await runtime.call_tool("verify_policy", {"policy_id": "policy-v2"})
    mismatch_payload = json.loads(mismatch[0].text)
    assert "error" in mismatch_payload
    assert mismatch_payload["error_code"] == "policy_mismatch"
    assert "expected policy-v2, got policy-v1" in mismatch_payload["error"]

    verified = await runtime.call_tool(
        "verify_policy",
        {
            "policy_id": "policy-v1",
            "policy_sha": policy_sha,
            "interface_version": "iterative_context.behavior_policy.v1",
        },
    )
    verified_payload = json.loads(verified[0].text)
    assert verified_payload["ok"] is True
    assert verified_payload["policy_id"] == "policy-v1"
    assert verified_payload["policy_source"] == "installed"
    assert verified_payload["resolve_policy_symbol"] == "resolve_policy"
    assert verified_payload["lookahead_policy_symbol"] == "lookahead_policy"


@pytest.mark.anyio
async def test_runtime_describe_policy_returns_active_metadata(tmp_path: Path) -> None:
    runtime = IterativeContextToolRuntime()
    policy_path = _write_policy(tmp_path, score_value=4.0)
    await runtime.call_tool(
        "install_policy",
        {
            "policy_path": str(policy_path),
            "policy_id": "policy-v1",
            "resolve_policy_symbol": "resolve_policy",
            "lookahead_policy_symbol": "lookahead_policy",
        },
    )

    described = await runtime.call_tool("describe_policy", {})
    payload = json.loads(described[0].text)

    assert payload["ok"] is True
    assert payload["active"] is True
    assert payload["policy_id"] == "policy-v1"
    assert payload["resolve_policy_symbol"] == "resolve_policy"
    assert payload["lookahead_policy_symbol"] == "lookahead_policy"
    assert payload["has_lookahead_policy"] is True
    assert payload["has_resolve_policy"] is True


@pytest.mark.anyio
async def test_install_policy_typed_failure_for_bad_symbol(tmp_path: Path) -> None:
    path = tmp_path / "bad_policy.py"
    path.write_text(
        (
            "resolve_policy = 123\n"
            "def lookahead_policy(node, graph, step):\n"
            "    return 0.0\n"
        ),
        encoding="utf-8",
    )
    runtime = IterativeContextToolRuntime()

    result = await runtime.call_tool(
        "install_policy",
        {
            "policy_path": str(path),
            "policy_id": "policy-v1",
            "resolve_policy_symbol": "resolve_policy",
        },
    )
    payload = json.loads(result[0].text)

    assert payload["error_code"] == "policy_load_error"
    assert "non-callable resolve_policy" in payload["error"]


@pytest.mark.anyio
async def test_resolve_and_expand_uses_installed_resolve_and_traversal_policy(
    tmp_path: Path,
) -> None:
    _activate_graph_with_symbols()
    policy_path = tmp_path / "policy.py"
    policy_path.write_text(
        (
            "SEEN = []\n"
            "def resolve_policy(query, candidates, state):\n"
            "    total = state.candidate_counts.total\n"
            "    SEEN.append((query, [c.node_id for c in candidates], total))\n"
            "    chosen = candidates[0]\n"
            "    return {\n"
            "        'status': 'resolved',\n"
            "        'query_label': query,\n"
            "        'candidates': candidates,\n"
            "        'selected_anchor_id': chosen.node_id,\n"
            "        'reason': 'custom_resolve',\n"
            "        'shallow_expand': False,\n"
            "    }\n"
            "def lookahead_policy(node, graph, step):\n"
            "    assert isinstance(step, int)\n"
            "    if node.id == 'B':\n"
            "        return 9.0\n"
            "    return 1.0\n"
        ),
        encoding="utf-8",
    )
    runtime = IterativeContextToolRuntime()
    await runtime.call_tool(
        "install_policy",
        {"policy_path": str(policy_path), "policy_id": "policy-v1"},
    )

    response = await runtime.call_tool(
        "resolve_and_expand",
        {"symbol": "expand_node", "depth": 2},
    )
    payload = json.loads(response[0].text)

    assert payload["anchor_decision"]["reason"] == "custom_resolve"
    assert payload["graph"]["metadata"]["expanded_from"] == "A"
    assert payload["graph"]["nodes"]


@pytest.mark.anyio
async def test_install_policy_requires_resolve_and_lookahead_callables(
    tmp_path: Path,
) -> None:
    runtime = IterativeContextToolRuntime()
    policy_path = tmp_path / "resolve_only_policy.py"
    policy_path.write_text(
        (
            "def resolve_policy(query, candidates, state):\n"
            "    return {\n"
            "        'status': 'not_found',\n"
            "        'query_label': query,\n"
            "        'candidates': [],\n"
            "        'selected_anchor_id': None,\n"
            "        'reason': 'stub',\n"
            "    }\n"
        ),
        encoding="utf-8",
    )

    installed = await runtime.call_tool(
        "install_policy",
        {"policy_path": str(policy_path), "policy_id": "policy-v1"},
    )
    install_payload = json.loads(installed[0].text)
    assert install_payload["error_code"] == "policy_load_error"
    assert "does not define callable lookahead_policy" in install_payload["error"]

    resolved = await runtime.call_tool("resolve", {"symbol": "expand_node"})
    resolved_payload = json.loads(resolved[0].text)
    assert resolved_payload["error_code"] == "policy_install_required"


def _write_repo(root: Path, symbol: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "module.py").write_text(
        f"def {symbol}() -> str:\n    return '{symbol}'\n", encoding="utf-8"
    )
    return root


@pytest.fixture
def two_repos(tmp_path: Path) -> tuple[Path, Path]:
    repo_a = _write_repo(tmp_path / "repo_a", "alpha_symbol")
    repo_b = _write_repo(tmp_path / "repo_b", "beta_symbol")
    return repo_a, repo_b


def test_explicit_repo_load_without_chdir(two_repos: tuple[Path, Path]) -> None:
    repo_a, _ = two_repos
    start_cwd = Path.cwd()

    exploration.ensure_graph_loaded(repo_root=repo_a)
    node = exploration.resolve("alpha_symbol")

    assert node is not None
    assert exploration.resolve("beta_symbol") is None
    assert Path.cwd() == start_cwd
    assert str(node.id).endswith("alpha_symbol")


@pytest.mark.anyio
async def test_runtime_binds_to_repo_root(two_repos: tuple[Path, Path], tmp_path: Path) -> None:
    repo_a, _ = two_repos
    runtime = IterativeContextToolRuntime(repo_root=repo_a)
    await _install_test_policy(tmp_path, runtime=runtime)

    response = await runtime.call_tool("resolve", {"symbol": "alpha_symbol"})
    payload = json.loads(response[0].text)

    assert payload["node"]["symbol"] == "alpha_symbol"

    missing = await runtime.call_tool("resolve", {"symbol": "beta_symbol"})
    missing_payload = json.loads(missing[0].text)
    assert missing_payload["node"] is None


@pytest.mark.anyio
async def test_runtimes_isolate_repos(two_repos: tuple[Path, Path], tmp_path: Path) -> None:
    repo_a, repo_b = two_repos
    runtime_a = IterativeContextToolRuntime(repo_root=repo_a)
    runtime_b = IterativeContextToolRuntime(repo_root=repo_b)
    await _install_test_policy(tmp_path / "policy_a", runtime=runtime_a, policy_id="policy-a")
    await _install_test_policy(tmp_path / "policy_b", runtime=runtime_b, policy_id="policy-b")

    first = await runtime_a.call_tool("resolve", {"symbol": "alpha_symbol"})
    first_payload = json.loads(first[0].text)
    second = await runtime_b.call_tool("resolve", {"symbol": "beta_symbol"})
    second_payload = json.loads(second[0].text)

    expand_a = await runtime_a.call_tool(
        "expand", {"node_id": first_payload["node"]["id"], "depth": 0}
    )
    expand_b = await runtime_b.call_tool(
        "expand", {"node_id": second_payload["node"]["id"], "depth": 0}
    )

    graph_a = json.loads(expand_a[0].text)["graph"]
    graph_b = json.loads(expand_b[0].text)["graph"]
    full_a = json.loads(expand_a[0].text)["full_graph"]
    full_b = json.loads(expand_b[0].text)["full_graph"]

    symbols_a = {n["symbol"] for n in graph_a["nodes"]}
    symbols_b = {n["symbol"] for n in graph_b["nodes"]}

    assert symbols_a == {"alpha_symbol"}
    assert symbols_b == {"beta_symbol"}
    assert full_a["metadata"]["graphSignature"] != full_b["metadata"]["graphSignature"]
    assert "repoRoot" not in full_a["metadata"]["repoIdentity"]
    assert "repoRoot" not in full_b["metadata"]["repoIdentity"]
    assert full_a["metadata"]["repoIdentity"]["workspaceKind"] in {"git", "filesystem"}
    assert full_b["metadata"]["repoIdentity"]["workspaceKind"] in {"git", "filesystem"}


@pytest.mark.anyio
async def test_runtime_defaults_to_cwd(
    two_repos: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_a, _ = two_repos
    monkeypatch.chdir(repo_a)

    runtime = IterativeContextToolRuntime()
    await _install_test_policy(tmp_path, runtime=runtime)
    response = await runtime.call_tool("resolve", {"symbol": "alpha_symbol"})
    payload = json.loads(response[0].text)

    assert payload["node"]["symbol"] == "alpha_symbol"


def test_ensure_graph_loaded_idempotent(
    two_repos: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_a, _ = two_repos
    calls: list[Path] = []

    original = exploration._build_graph_from_repo

    def _tracked(root: Path) -> Graph:
        calls.append(root)
        return original(root)

    monkeypatch.setattr(exploration, "_build_graph_from_repo", _tracked)

    exploration.ensure_graph_loaded(repo_root=repo_a)
    exploration.ensure_graph_loaded(repo_root=repo_a)

    assert calls == [Path(repo_a).resolve()]
