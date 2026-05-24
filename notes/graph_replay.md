# Graph replay

Iterative Context records a bounded, SAT-compatible replay trace while normal evaluator tools run.

## Admin surface

The only replay admin tool is:

- `collect_graph_trace`

Do not add:

- `start_graph_trace`
- `clear_graph_trace`
- `describe_graph_trace`

Replay collection is hidden from evaluator-visible tool lists. Normal `resolve`, `expand`, and `resolve_and_expand` responses stay compact and do not inline full replay events.

## Envelope

Replay payloads use:

- `kind = "searchbench.graph_replay.v1"`
- `source = "iterative-context"`

The collector accepts an opaque `trace_id`, optional opaque metadata labels, and `clear_after_collect`.

IC may echo:

- `match_id`
- `role`
- `attempt_id`

It must treat those values as labels only, not filesystem paths.

## Event grammar

The replay stream stays within the current SAT-compatible event union:

- `iteration`
- `addNodes`
- `addEdges`
- `updateNode`
- `setContext`
- `tokenAdd`

The implementation should prefer the narrow event surface and encode richer IC semantics through stable reason strings and compact iteration descriptions.

## Anchor and frontier semantics

`AnchorDecision` is the canonical source of anchor causality.

- `resolved` emits visible candidates and marks the selected anchor explicitly.
- `ambiguous` emits visible candidates without fabricating a winner.
- `not_found` emits no fake anchor node or expansion.

Pending nodes represent the bounded visible frontier, not the full internal frontier.

The current default is:

- `maxVisiblePending = 4`

Visible frontier selection is deliberate:

- always include the selected lookahead candidate when one exists
- include explicitly pruned candidates when the replay budget allows
- prefer sticky already-visible pending candidates before introducing new ones
- fill remaining slots by rank
- if a hidden candidate is later selected, emit it as `pending` before it becomes `resolved`

Visible non-selected anchor candidates may be explicitly pruned after a resolved `AnchorDecision`.
Lookahead candidates stay pending unless the traversal explicitly prunes them.
Hidden candidates stay out of the emitted graph until they become visible.

Compact score/rank evidence is attached through `updateNode` patches with replay reasons such as `candidate_scored`.
Expansion causality is preserved through emitted `addEdges` records from the selected or discovered parent node to newly visible or discovered children.

## Trace isolation

Replay state is scoped to the in-process IC runtime session.

- sequential attempts must not leak stale events
- collect-and-clear must reset the recorder
- one session must not return another session's events

## Portability

Replay payloads should avoid:

- host-absolute paths
- bundle-local artifact paths
- projection paths
- secrets

Prefer stable node IDs, repo-relative labels when available, and compact metadata.
