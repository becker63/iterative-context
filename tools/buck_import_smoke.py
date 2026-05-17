"""Buck import smoke entrypoint (#92). Not a public CLI — invoked by //src/iterative-context:import_smoke."""

import hypothesis  # noqa: F401
import iterative_context  # noqa: F401

print("iterative-context: import smoke ok")
