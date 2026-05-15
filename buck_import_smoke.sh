#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"
uv sync --locked
exec uv run python -c "import hypothesis, iterative_context; print('iterative-context: import smoke ok')"
