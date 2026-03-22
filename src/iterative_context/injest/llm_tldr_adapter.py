from collections.abc import Mapping
from pathlib import Path
from typing import cast

from tldr import extract_file  # type: ignore[reportMissingTypeStubs]
from tldr.api import get_imports  # type: ignore[reportMissingTypeStubs]
from tldr.ast_extractor import (  # type: ignore[reportMissingTypeStubs]
    FunctionInfo,
    ImportInfo,
    ModuleInfo,
)

from iterative_context.raw_tree import RawEdge, RawFile, RawFunction, RawTree

Extracted = ModuleInfo | Mapping[str, object]
FunctionLike = FunctionInfo | Mapping[str, object]
ImportLike = ImportInfo | Mapping[str, object]


def _iter_functions(extracted: Extracted) -> list[FunctionLike]:
    """Handle both dict and object outputs from llm-tldr."""
    if isinstance(extracted, ModuleInfo):
        return list(extracted.functions or [])

    functions_value = extracted.get("functions", [])
    if isinstance(functions_value, list):
        return list(cast(list[FunctionLike], functions_value))

    return []


def _iter_imports(source: ModuleInfo | Mapping[str, object] | list[ImportLike]) -> list[ImportLike]:
    """Handle both dict, object, and list outputs from llm-tldr."""
    if isinstance(source, ModuleInfo):
        return list(source.imports or [])

    if isinstance(source, list):
        return list(source)

    imports_value = source.get("imports", [])
    if isinstance(imports_value, list):
        return list(cast(list[ImportLike], imports_value))

    return []


def _iter_calls(fn: FunctionLike) -> list[str]:
    """Extract called function names when present."""
    calls: list[str] = []

    if isinstance(fn, FunctionInfo):
        maybe_calls = getattr(fn, "calls", None)
        if isinstance(maybe_calls, list):
            for call_name in cast(list[object], maybe_calls):
                if isinstance(call_name, str):
                    calls.append(call_name)

        maybe_called_functions = getattr(fn, "called_functions", None)
        if isinstance(maybe_called_functions, list):
            for call_name in cast(list[object], maybe_called_functions):
                if isinstance(call_name, str):
                    calls.append(call_name)

    else:
        fn_mapping = fn
        for key in ("calls", "called_functions"):
            maybe_values = fn_mapping.get(key)
            if isinstance(maybe_values, list):
                for call_name in cast(list[object], maybe_values):
                    if isinstance(call_name, str):
                        calls.append(call_name)

    return calls


def ingest_repo(root: Path) -> RawTree:  # noqa: PLR0912
    files: list[RawFile] = []

    for py_file in root.rglob("*.py"):
        if ".venv" in str(py_file) or "__pycache__" in str(py_file):
            continue

        try:
            extracted: Extracted = extract_file(str(py_file))  # type: ignore[assignment]
        except Exception:
            continue

        functions: list[RawFunction] = []
        edges: list[RawEdge] = []
        for fn in _iter_functions(extracted):
            name: str | None = fn.name if isinstance(fn, FunctionInfo) else None
            if name is None and isinstance(fn, Mapping):
                potential_name = fn.get("name")
                if isinstance(potential_name, str):
                    name = potential_name

            if not isinstance(name, str) or not name:
                continue

            qualified_name = f"{py_file}:{name}"

            functions.append(
                RawFunction(
                    id=qualified_name,
                    name=name,
                    file=str(py_file),
                )
            )

            for called in _iter_calls(fn):
                edges.append(
                    RawEdge(
                        source=qualified_name,
                        target=called,
                        kind="call",
                    )
                )

        try:
            imports_raw = cast(
                list[ImportLike], get_imports(str(py_file), language="python")
            )
        except Exception:
            imports_raw = []
        else:
            imports_raw = list(imports_raw)

        imports: list[str] = []
        for imp in _iter_imports(imports_raw):
            module: str | None = imp.module if isinstance(imp, ImportInfo) else None
            if module is None and isinstance(imp, Mapping):
                potential_module = imp.get("module")
                if isinstance(potential_module, str):
                    module = potential_module
            if isinstance(module, str) and module:
                imports.append(module)
                edges.append(
                    RawEdge(
                        source=str(py_file),
                        target=module,
                        kind="import",
                    )
                )

        files.append(
            RawFile(
                path=str(py_file),
                functions=functions,
                imports=imports,
                edges=edges,
            )
        )

    return RawTree(files=files)
