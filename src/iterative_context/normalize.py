from iterative_context.graph_models import Graph
from iterative_context.raw_tree import RawTree


def raw_tree_to_graph(tree: RawTree) -> Graph:
    """Create a minimal graph from a RawTree."""
    graph = Graph()

    for raw_file in tree.files:
        for fn in raw_file.functions:
            graph.add_node(fn.id, type="function", file=fn.file)

    for raw_file in tree.files:
        for edge in raw_file.edges:
            if edge.kind == "import":
                graph.add_node(edge.target, type="module")
                graph.add_edge(edge.source, edge.target, kind="imports")
            elif edge.kind == "call":
                if edge.target in graph.nodes:
                    graph.add_edge(edge.source, edge.target, kind="calls")

    return graph
