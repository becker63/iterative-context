"""Tests for iterative_context.validate_policy CLI helpers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from iterative_context.validate_policy import main as validate_main, validate_policy


def _write_policy(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_missing_policy_path_fails() -> None:
    out = validate_policy(Path("/no/such/policy_candidate.py"), "pid", "score_fn")
    assert out["ok"] is False
    assert out["stage"] == "policy_path"


def test_empty_policy_fails(tmp_path: Path) -> None:
    p = tmp_path / "p.py"
    _write_policy(p, "   \n")
    out = validate_policy(p, "pid", "score_fn")
    assert out["ok"] is False
    assert out["stage"] == "empty_policy"


def test_markdown_fence_fails(tmp_path: Path) -> None:
    p = tmp_path / "p.py"
    _write_policy(p, "```python\ndef score_fn():\n  pass\n```")
    out = validate_policy(p, "pid", "score_fn")
    assert out["ok"] is False
    assert out["stage"] == "markdown_fence"


def test_missing_symbol_fails(tmp_path: Path) -> None:
    p = tmp_path / "p.py"
    _write_policy(p, "x = 1\n")
    out = validate_policy(p, "pid", "score_fn")
    assert out["ok"] is False
    assert out["stage"] == "symbol"


def test_non_callable_symbol_fails(tmp_path: Path) -> None:
    p = tmp_path / "p.py"
    _write_policy(p, "score_fn = 123\n")
    out = validate_policy(p, "pid", "score_fn")
    assert out["ok"] is False


def test_valid_policy_passes(tmp_path: Path) -> None:
    p = tmp_path / "p.py"
    _write_policy(
        p,
        """
def score_fn(node, graph, depth):
    return 0.0
""".strip(),
    )
    out = validate_policy(p, "next-challenger-test", "score_fn")
    assert out["ok"] is True
    assert out["policy_id"] == "next-challenger-test"
    assert out["symbol"] == "score_fn"
    assert any(s.get("name") == "install_score" and s.get("ok") for s in out["stages"])
    assert any(s.get("name") == "verify_score" and s.get("ok") for s in out["stages"])
    assert "sha256" in out


def test_cli_json_success(tmp_path: Path) -> None:
    p = tmp_path / "p.py"
    _write_policy(
        p,
        """
def score_fn(node, graph, depth):
    return 0.0
""".strip(),
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "iterative_context.validate_policy",
            "--policy-path",
            str(p),
            "--policy-id",
            "cli-policy",
            "--symbol",
            "score_fn",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True


def test_cli_json_failure_exit_code(tmp_path: Path) -> None:
    p = tmp_path / "bad.py"
    _write_policy(p, "")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "iterative_context.validate_policy",
            "--policy-path",
            str(p),
            "--policy-id",
            "cli-policy",
            "--symbol",
            "score_fn",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False


def test_main_wrapper_json(tmp_path: Path) -> None:
    p = tmp_path / "p.py"
    _write_policy(
        p,
        """
def score_fn(node, graph, depth):
    return 0.0
""".strip(),
    )
    rc = validate_main(
        [
            "--policy-path",
            str(p),
            "--policy-id",
            "wrap",
            "--symbol",
            "score_fn",
            "--json",
        ]
    )
    assert rc == 0
