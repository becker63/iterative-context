"""Buck import smoke for the uv-wrapper iterative-context boundary."""


def test_import_iterative_context() -> None:
    import importlib

    assert importlib.import_module("hypothesis") is not None
    assert importlib.import_module("iterative_context") is not None
