from iterative_context.expansion import expand_node
from iterative_context.graph_models import Graph
from iterative_context.store import GraphStore
from iterative_context.test_helpers.graph_dsl import apply_events


def resolve(query: str, store: GraphStore) -> list[str]:
    """Resolve a query string to node ids via exact match then substring fallback."""
    exact = store.find_symbol(query)
    if exact:
        return sorted(exact)

    matches: list[str] = []
    lowered = query.lower()
    for node_id, data in sorted(store.nodes_by_id.items(), key=lambda item: item[0]):
        symbol = data.get("symbol")
        if isinstance(symbol, str) and lowered in symbol.lower():
            matches.append(node_id)
            continue

        file_value = data.get("file")
        if isinstance(file_value, str) and lowered in file_value.lower():
            matches.append(node_id)

    # Deduplicate while preserving deterministic order from sorted iteration.
    seen: set[str] = set()
    ordered: list[str] = []
    for node_id in matches:
        if node_id in seen:
            continue
        seen.add(node_id)
        ordered.append(node_id)

    return ordered


def expand(
    node_ids: list[str],
    graph: Graph,
    depth: int,
) -> set[str]:
    """
    ORCHESTRATION LAYER.

    Compose mutation + query to perform bounded expansion from multiple anchors.
    """
    store = GraphStore(graph)
    anchors = list(dict.fromkeys(node_ids))  # deterministic dedupe
    frontier = anchors.copy()

    for _ in range(depth):
        next_frontier: list[str] = []

        for nid in frontier:
            node_data = store.nodes_by_id.get(nid)
            if node_data is None:
                continue

            events = expand_node({"id": nid, "state": node_data.get("state", "pending")}, graph)
            apply_events(graph, events)

            store = GraphStore(graph)  # rebuild after mutation
            neighbors = store.get_neighbors(nid)
            next_frontier.extend(neighbors)

        frontier = list(dict.fromkeys(next_frontier))

    neighborhoods: set[str] = set()
    for nid in anchors:
        neighborhoods.update(store.get_neighborhood(nid, radius=depth))

    return neighborhoods


def resolve_and_expand(
    query: str,
    graph: Graph,
    depth: int,
) -> set[str]:
    """Resolve a query string to nodes, then perform bounded expansion."""
    store = GraphStore(graph)
    node_ids = resolve(query, store)
    return expand(node_ids, graph, depth)
