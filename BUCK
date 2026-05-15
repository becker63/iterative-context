load("@prelude//:rules.bzl", "sh_test", "test_suite")

sh_test(
    name = "import_smoke",
    test = "buck_import_smoke.sh",
)

sh_test(
    name = "pytest_all",
    test = "buck_pytest.sh",
)

sh_test(
    name = "basedpyright_check",
    test = "buck_basedpyright.sh",
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
