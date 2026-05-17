load("//build_defs:py_ops.bzl", "python_module_test")
load("@elk//:elk.bzl", "elk_packages", "uv_packages")
load(":elk_ic_deps.bzl", "IC_RUNTIME_DEPS")
load("@prelude//:rules.bzl", "genrule", "python_binary", "python_library", "python_test", "test_suite")
load(":linux-aarch64.tags.json", linux_aarch64_tags = "value")
load(":linux-x86_64.tags.json", linux_x86_64_tags = "value")
load(":uv.lock.toml", lock = "value")

elk_packages(
    packages = uv_packages(lock),
    platform_tags = {
        "linux-aarch64": linux_aarch64_tags,
        "linux-x86_64": linux_x86_64_tags,
    },
)

genrule(
    name = "optimizable_backend",
    out = "optimizable_backend.json",
    srcs = ["optimizable_backend.json"],
    cmd = "cp $SRCS $OUT",
)

python_library(
    name = "iterative-context",
    srcs = glob(["src/**/*.py"]),
    deps = IC_RUNTIME_DEPS,
    visibility = ["PUBLIC"],
)

python_binary(
    name = "pytest_runner",
    main = "tools/buck_pytest_main.py",
    deps = [":iterative-context"] + IC_RUNTIME_DEPS,
)

python_binary(
    name = "basedpyright_runner",
    main = "tools/buck_basedpyright_main.py",
    deps = [":iterative-context"] + IC_RUNTIME_DEPS,
)

python_module_test(
    name = "import_smoke",
    binary = ":pytest_runner",
    args = [
        "src/iterative-context/tests/test_import_smoke.py",
        "-q",
    ],
)

python_module_test(
    name = "pytest_all",
    binary = ":pytest_runner",
    args = [
        "src/iterative-context/tests",
        "-q",
        "--ignore=src/iterative-context/tests/test_graph_store.py",
        "--ignore=src/iterative-context/tests/test_ingest_llm_tldr.py",
        "--ignore=src/iterative-context/tests/test_llm_tldr_normalization.py",
    ],
)

python_module_test(
    name = "basedpyright_check",
    work_dir = "src/iterative-context",
    binary = ":basedpyright_runner",
    args = [],
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
