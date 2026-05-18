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
        "pytest",
        "tests/test_import_smoke.py",
        "-q",
    ],
)

uv_project_test(
    name = "pytest_all",
    work_dir = "src/iterative-context",
    argv = [
        "run",
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
        "basedpyright",
        "src",
        "tests",
    ],
)

test_suite(
    name = "check",
    tests = [
        ":import_smoke",
        ":pytest_all",
    ],
)

test_suite(
    name = "check_full",
    tests = [
        ":check",
        ":basedpyright_check",
    ],
)
