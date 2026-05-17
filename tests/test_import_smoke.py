"""Buck import smoke (Elk + python_library graph)."""


def test_import_iterative_context() -> None:
    import hypothesis  # noqa: F401
    import iterative_context  # noqa: F401
