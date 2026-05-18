"""Serialization helpers for graph tool payloads."""
from __future__ import annotations

import json
from typing import cast

from iterative_context.serialization import serialize_graph, serialize_graph_summary
from iterative_context.test_helpers.graph_dsl import EdgeSpec, GraphSpec, NodeSpec, build_graph


def test_serialize_graph_summary_is_much_smaller_than_full_graph() -> None:
    node_specs: list[NodeSpec] = [
        {
            "id": f"sym_{index}",
            "kind": "symbol",
            "state": "pending",
        }
        for index in range(200)
    ]
    edge_specs: list[EdgeSpec] = [
        {"source": f"sym_{index}", "target": f"sym_{index + 1}", "kind": "calls"}
        for index in range(199)
    ]
    graph = build_graph(cast(GraphSpec, {"nodes": node_specs, "edges": edge_specs}))
    for index in range(200):
        node_id = f"sym_{index}"
        graph.nodes[node_id]["symbol"] = f"symbol_{index}"
        graph.nodes[node_id]["file"] = f"src/pkg/module_{index % 5}.py"

    full = serialize_graph(graph, metadata={"repo_root": "/repo"})
    summary = serialize_graph_summary(graph, metadata={"repo_root": "/repo"})

    full_bytes = len(json.dumps(full))
    summary_bytes = len(json.dumps(summary))

    assert summary["format"] == "summary_v1"
    assert summary["node_count"] == 200
    assert summary["edge_count"] == 199
    assert summary["files_total"] == 5
    assert len(summary["files_sample"]) == 5
    assert summary_bytes < full_bytes // 10
