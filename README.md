# local_snapshotter_context

Captures a context-local dict of key-value pairs and returns a serialized token string suitable for propagation across process boundaries.

## Usage

```python
from local_snapshotter_context import ContextSnapshotter, SnapshotError

snap = ContextSnapshotter()
snap.set("request_id", "abc-123")
snap.set("user_id", 42)

token = snap.snapshot()      # str, safe to pass through pipes/queues/env vars

other = ContextSnapshotter()
other.restore(token)         # raises SnapshotError on malformed input
print(other.get("request_id"))  # -> "abc-123"
```

## Why this exists

When work is handed off across a process boundary (a subprocess, a task queue worker, a fresh handler in another language runtime) the in-memory context that travelled with the request is lost. This library serializes whatever the caller has stashed in a thread-local dict into a self-contained text token and restores it on the other side, so the downstream code sees the same key-value pairs without a shared dependency on a tracing server or an external propagation format.

The trade-off is explicit: the token is opaque and carries its own bytes. It is not a standard like W3C Baggage or B3. Use this when you control both ends and want zero dependencies and no schema negotiations; reach for a real propagation header format when you need interop with systems you do not control.

## Edge cases you will hit

- **`bytes` are rejected.** Python's `json` module handles `bytes` inconsistently across versions, so `_validate_value` raises `TypeError` eagerly. Convert bytes to `str` before storing them.
- **Keys must be `str`.** Non-string keys raise `TypeError` on `set` and `SnapshotError` on `restore` if they appear in a decoded payload.
- **Two `ContextSnapshotter` instances are isolated.** Context is stored in a per-instance `threading.local`, so there is no process-global context. If you want a shared scope, hold one instance in a module-level variable.
- **Restore replaces, it does not merge.** Calling `restore` overwrites the current context entirely.
- **Tokens are deterministic for equal contexts.** JSON keys are sorted before serialization, so the same dict produces the same token regardless of insertion order. Do not rely on this across library versions; the format prefix (`LSC1`) names the current scheme but is not a versioned commitment.

## Exported names

- `ContextSnapshotter` — the class. Methods: `set(key, value)`, `get(key, default=None)`, `clear()`, `snapshot() -> str`, `restore(token: str) -> None`.
- `SnapshotError` — subclass of `ValueError`, raised by `restore` on any malformed token.
