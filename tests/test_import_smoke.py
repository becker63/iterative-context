"""Buck import smoke for the uv-wrapper iterative-context boundary."""

import importlib


def test_import_iterative_context() -> None:
    assert importlib.import_module("hypothesis") is not None
    assert importlib.import_module("iterative_context") is not None
