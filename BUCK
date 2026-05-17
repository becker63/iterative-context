load("//build_defs:tool_ops.bzl", "uv_project_test")
load("@prelude//:rules.bzl", "genrule", "test_suite")

genrule(
    name = "optimizable_backend",
    out = "optimizable_backend.json",
    srcs = ["optimizable_backend.json"],
    cmd = "cp $SRCS $OUT",
)

uv_project_test(
    name = "import_smoke",
    work_dir = "src/iterative-context",
    argv = [
        "run",
        "python",
        "tools/buck_import_smoke.py",
    ],
)

uv_project_test(
    name = "pytest_all",
    work_dir = "src/iterative-context",
    argv = [
        "run",
        "python",
        "-m",
        "pytest",
        "-q",
        "--ignore=tests/test_graph_store.py",
        "--ignore=tests/test_ingest_llm_tldr.py",
        "--ignore=tests/test_llm_tldr_normalization.py",
    ],
)

uv_project_test(
    name = "basedpyright_check",
    work_dir = "src/iterative-context",
    argv = [
        "run",
        "python",
        "-m",
        "basedpyright",
        "src",
        "tests",
    ],
)

# Fast gate (pre-commit aggregate): locked env sync, import smoke, pytest (excludes TEST_REPO_* fixtures).
test_suite(
    name = "check",
    tests = [
        ":import_smoke",
        ":pytest_all",
    ],
)

# Full gate: `check` plus static typing (pre-push aggregate includes this under `//:check_full`).
test_suite(
    name = "check_full",
    tests = [
        ":check",
        ":basedpyright_check",
    ],
)
