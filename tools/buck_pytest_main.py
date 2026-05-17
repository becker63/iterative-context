"""Pytest entrypoint for Buck (no uv run)."""

from __future__ import annotations

import sys

import pytest


def main() -> None:
    raise SystemExit(pytest.main(sys.argv[1:]))


if __name__ == "__main__":
    main()
