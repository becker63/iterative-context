# pyright: reportMissingTypeStubs=false
import os
import sys

import pytest
from pytest_snapshot.plugin import Snapshot

# Ensure the directory containing this file is on sys.path so we can import
# the local ``snapshot_graph`` module directly.
sys.path.append(os.path.dirname(__file__))

from snapshot_graph import GraphSnapshot


@pytest.fixture
def snapshot_graph(snapshot: Snapshot) -> GraphSnapshot:
    """Provide a GraphSnapshot instance bound to the pytest‑snapshot fixture."""
    return GraphSnapshot(snapshot)
