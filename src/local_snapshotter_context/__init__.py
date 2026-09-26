"""Public API for local_snapshotter_context.

Re-exports the names intended for external consumption so callers can do::

    from local_snapshotter_context import ContextSnapshotter, SnapshotError

rather than reaching into the internal module layout.
"""

from .core import ContextSnapshotter, SnapshotError

__all__ = ["ContextSnapshotter", "SnapshotError"]
