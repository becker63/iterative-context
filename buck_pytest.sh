#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"
uv sync --locked
# Use `python -m pytest` so the project venv (with Hypothesis, etc.) is used; `uv run pytest` can resolve a tool-only pytest.
exec uv run python -m pytest -q \
  --ignore=tests/test_graph_store.py \
  --ignore=tests/test_ingest_llm_tldr.py \
  --ignore=tests/test_llm_tldr_normalization.py
