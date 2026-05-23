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

## AnchorDecision

`resolve` and `resolve_and_expand` now emit structured anchor decisions. The important semantics are:

- `resolved`: exactly one selected anchor
- `ambiguous`: multiple plausible anchors, no fake winner
- `not_found`: structured miss, not a fatal tool/schema failure

The decision object is also the future seam for replay work in issue `#144`, so callers should treat it as the canonical source of anchor causality.
