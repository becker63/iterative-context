from collections.abc import Iterable

from iterative_context.graph_models import Graph
from iterative_context.path_ids import file_for_node_id, node_kind_for_id, node_label_for_id
from iterative_context.raw_tree import RawTree


def raw_tree_to_graph(tree: RawTree) -> Graph:
    """Create a minimal graph from a RawTree."""
    graph = Graph()

    def ensure_node(node_id: str, *, node_type: str, symbol: str, file: str | None) -> None:
        inferred_kind = node_kind_for_id(node_id)
        inferred_symbol = node_label_for_id(node_id)
        inferred_file = file_for_node_id(node_id)
        if node_id not in graph.nodes:
            graph.add_node(
                node_id,
                type=node_type if node_type != "unknown" else inferred_kind,
                symbol=symbol or inferred_symbol,
                file=file if file is not None else inferred_file,
            )
        else:
            # Preserve existing attributes but backfill symbol/type/file if missing.
            data = graph.nodes[node_id]
            data.setdefault("type", node_type if node_type != "unknown" else inferred_kind)
            data.setdefault("symbol", symbol or inferred_symbol)
            if file is not None:
                data.setdefault("file", file)
            elif inferred_file is not None:
                data.setdefault("file", inferred_file)

    for raw_file in sorted(tree.files, key=lambda f: f.path):
        for fn in raw_file.functions:
            ensure_node(fn.id, node_type="function", symbol=fn.name, file=fn.file)

    def iter_edges() -> Iterable[tuple[str, str, str, str]]:
        for raw_file in sorted(tree.files, key=lambda f: f.path):
            for edge in sorted(raw_file.edges, key=lambda e: (e.kind, e.source, e.target)):
                yield edge.kind, edge.source, edge.target, raw_file.path

    for kind, source, target, file_path in iter_edges():
        if kind == "import":
            ensure_node(source, node_type="file", symbol=file_path, file=file_path)
            ensure_node(target, node_type="type", symbol=node_label_for_id(target), file=None)
            graph.add_edge(source, target, kind="imports")
        elif kind == "call":
            ensure_node(source, node_type="function", symbol=node_label_for_id(source), file=file_path)
            ensure_node(target, node_type="symbol", symbol=node_label_for_id(target), file=None)
            graph.add_edge(source, target, kind="calls")

    return graph
