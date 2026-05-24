# Iterative Context

Iterative Context is the MCP-backed challenger used by SearchBench for code-localization rounds.

## Tool surface

Evaluator-visible tools:

- `resolve`
- `expand`
- `resolve_and_expand`

Admin / hidden tools:

- `install_policy`
- `verify_policy`
- `describe_policy`
- `collect_graph_trace`

## Policy contract

Behavior policy modules must define:

```python
def resolve_policy(query, candidates, state):
    ...

def lookahead_policy(node, graph, step):
    ...
```

`resolve_policy` is the installable fuzzy-anchor decision surface. Candidate generation stays in IC mechanism; the policy decides whether the result is `resolved`, `ambiguous`, or `not_found`.

`lookahead_policy` is the installable traversal policy surface. It receives the current node, graph, and step index, and returns a float score used to rank frontier expansion.

Installed policy identity is behavior-policy-wide, not traversal-only. `install_policy`, `verify_policy`, and `describe_policy` carry policy metadata including:

- `policy_id`
- `policy_sha`
- `interface_version`
- `resolve_policy_symbol`
- `lookahead_policy_symbol`

## AnchorDecision

`resolve` and `resolve_and_expand` now emit structured anchor decisions. The important semantics are:

- `resolved`: exactly one selected anchor
- `ambiguous`: multiple plausible anchors, no fake winner
- `not_found`: structured miss, not a fatal tool/schema failure

The decision object is also the future seam for replay work in issue `#144`, so callers should treat it as the canonical source of anchor causality.

## Graph replay

IC now records a session-scoped graph replay trace while evaluator tools run.

The only replay admin tool is:

- `collect_graph_trace`

Normal evaluator-visible tool responses stay compact. Full replay events are returned only from `collect_graph_trace`.

Replay payloads use:

- `kind = "searchbench.graph_replay.v1"`
- `source = "iterative-context"`

The replay stream is SAT-compatible and stays within:

- `iteration`
- `addNodes`
- `addEdges`
- `updateNode`
- `setContext`
- `tokenAdd`

The replay shows a bounded visible frontier rather than the full internal frontier. The current default is `maxVisiblePending = 4`.

See `notes/graph_replay.md` for the recorder contract, pending vs pruned semantics, trace isolation, and portability constraints.
