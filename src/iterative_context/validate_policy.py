"""Candidate policy validation for SearchBench-Go optimizer pipelines."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from iterative_context.server import IterativeContextToolRuntime, load_policy_callable


def _policy_has_markdown_fence(src: str) -> bool:
    return "```" in src


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _install_verify_smoke(
    rt: IterativeContextToolRuntime, policy_path: Path, policy_id: str, symbol: str
) -> None:
    payload = rt.admin_install_policy(
        {
            "policy_path": str(policy_path),
            "policy_id": policy_id,
            "lookahead_policy_symbol": symbol,
        }
    )
    if not payload.get("ok"):
        raise RuntimeError(f"install_policy failed: {payload}")
    verify = rt.admin_verify_policy({"policy_id": policy_id})
    if not verify.get("ok"):
        raise RuntimeError(f"verify_policy failed: {verify}")


async def _strict_requires_install_before_tools(rt: IterativeContextToolRuntime) -> dict[str, Any]:
    """Evaluator tools must fail before install_policy succeeds."""
    resp = await rt.call_tool("resolve", {"symbol": "dummy-symbol"})
    payload = json.loads(resp[0].text)
    err = payload.get("error")
    if err is None:
        return {
            "name": "strict_tool_smoke",
            "ok": False,
            "message": "expected evaluator tool to fail before install_policy",
            "hint": "Evaluator tools should reject calls until install_policy succeeds.",
        }
    return {"name": "strict_tool_smoke", "ok": True}


async def validate_policy_async(  # noqa: PLR0911
    policy_path: Path, policy_id: str, symbol: str
) -> dict[str, Any]:
    """Run staged validation and return a structured result dict."""
    stages: list[dict[str, Any]] = []

    path = policy_path.expanduser().resolve()
    if not path.is_file():
        return {
            "ok": False,
            "stage": "policy_path",
            "message": f"policy path does not exist or is not a file: {path}",
            "policy_id": policy_id,
            "symbol": symbol,
        }

    raw = _read_text(path)
    if not raw.strip():
        return {
            "ok": False,
            "stage": "empty_policy",
            "message": "policy file is empty",
            "policy_id": policy_id,
            "symbol": symbol,
        }

    if _policy_has_markdown_fence(raw):
        return {
            "ok": False,
            "stage": "markdown_fence",
            "message": "policy file contains markdown code fences (```)",
            "hint": "Emit raw Python only without fenced blocks.",
            "policy_id": policy_id,
            "symbol": symbol,
        }

    stages.append({"name": "load_policy", "ok": True})

    try:
        load_policy_callable(path, symbol)
    except Exception as exc:  # noqa: BLE001 - surfaced to harness
        return {
            "ok": False,
            "stage": "symbol",
            "message": str(exc),
            "hint": (
                f"Export def {symbol}(node, graph, step): "
                "... returning a float traversal score."
            ),
            "policy_id": policy_id,
            "symbol": symbol,
            "stages": stages,
        }

    stages.append({"name": "callable_symbol", "ok": True})

    rt = IterativeContextToolRuntime()

    strict = await _strict_requires_install_before_tools(rt)
    stages.append(strict)
    if not strict.get("ok"):
        return {
            "ok": False,
            "stage": "strict_tool_smoke",
            "message": strict.get("message", "strict smoke failed"),
            "hint": strict.get("hint"),
            "policy_id": policy_id,
            "symbol": symbol,
            "stages": stages,
        }

    try:
        _install_verify_smoke(rt, path, policy_id, symbol)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "stage": "install_verify",
            "message": str(exc),
            "policy_id": policy_id,
            "symbol": symbol,
            "stages": stages,
        }

    stages.append({"name": "install_policy", "ok": True})
    stages.append({"name": "verify_policy", "ok": True})

    resp = await rt.call_tool("resolve", {"symbol": "dummy-symbol"})
    after_payload = json.loads(resp[0].text)
    stages.append(
        {
            "name": "evaluator_identity_smoke",
            "ok": True,
            "active_policy_id": after_payload.get("active_policy_id"),
        }
    )

    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return {
        "ok": True,
        "policy_id": policy_id,
        "symbol": symbol,
        "policy_path": str(path),
        "sha256": digest,
        "stages": stages,
    }


def validate_policy(policy_path: Path, policy_id: str, symbol: str) -> dict[str, Any]:
    return asyncio.run(validate_policy_async(policy_path, policy_id, symbol))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a candidate Iterative Context policy module."
    )
    parser.add_argument(
        "--policy-path", required=True, help="Filesystem path to the policy .py file"
    )
    parser.add_argument("--policy-id", required=True, help="Stable policy identifier")
    parser.add_argument("--symbol", required=True, help="Callable symbol to load from the module")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout")
    ns = parser.parse_args(argv)

    result = validate_policy(Path(ns.policy_path), ns.policy_id.strip(), ns.symbol.strip())
    if ns.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif not result.get("ok"):
        print(result.get("message", "validation failed"), file=sys.stderr)
        if hint := result.get("hint"):
            print(hint, file=sys.stderr)
        return 1

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
