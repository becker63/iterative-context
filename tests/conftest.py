# pyright: reportMissingTypeStubs=false
import pytest
from pytest_snapshot.plugin import Snapshot

from iterative_context.test_helpers import GraphSnapshot


@pytest.fixture
def snapshot_graph(snapshot: Snapshot) -> GraphSnapshot:
    """Provide a GraphSnapshot instance bound to the pytest‑snapshot fixture."""
    return GraphSnapshot(snapshot)
