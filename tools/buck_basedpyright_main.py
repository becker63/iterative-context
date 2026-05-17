"""Basedpyright entrypoint for Buck (no uv run)."""

from __future__ import annotations

import sys

from basedpyright.pyright import main as basedpyright_main


def main() -> None:
    raise SystemExit(basedpyright_main())


if __name__ == "__main__":
    main()
