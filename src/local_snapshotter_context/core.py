import json
import zlib
import base64
import threading
from typing import Any, Dict, Optional, Tuple


class SnapshotError(ValueError):
    """Raised when a snapshot token cannot be decoded or is structurally invalid.

    Subclassing ValueError keeps the exception familiar to callers who already
    catch ValueError for malformed input, while still allowing SnapshotError to
    be caught specifically.
    """


class ContextSnapshotter:
    """Captures a context-local dict of key-value pairs and round-trips it as a token.

    Context isolation is provided by a per-instance threading.local container.
    Each instance therefore behaves as an independent context scope: two
    instances do not share context even within the same thread. This matches
    the common pattern of one snapshotter per subsystem rather than a single
    process-global singleton.

    Serialization format (stable across versions within this library):
        base64url(json_with_sorted_keys + zlib_compression)

    JSON key ordering is forced to be deterministic so that equal dicts produce
    byte-identical tokens, which makes token comparison and caching safe.

    Value restrictions:
        Keys must be ``str``. Values must be JSON-serializable and, after
        serialization, consist only of strings, integers, floats, booleans,
        None, lists, or dicts. We reject ``bytes`` eagerly because Python's
        json module silently accepts bytes by treating them as integers in
        some implementations and erroring in others — a portability trap.

    Token integrity:
        Tokens carry a fixed prefix ``LSC1`` so a wrong blob is rejected early
        with a clear error rather than a confusing zlib or json failure.
    """

    _PREFIX = "LSC1"

    def __init__(self) -> None:
        self._local = threading.local()

    def _context(self) -> Dict[str, Any]:
        container = getattr(self._local, "context", None)
        if container is None:
            container = {}
            self._local.context = container
        return container

    def set(self, key: str, value: Any) -> None:
        """Set a single key in the current context."""
        if not isinstance(key, str):
            raise TypeError("key must be a string, got %r" % type(key).__name__)
        self._validate_value(value)
        self._context()[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Return a key from the current context, or ``default`` if absent."""
        return self._context().get(key, default)

    def clear(self) -> None:
        """Drop all keys held in the current context."""
        self._local.context = {}

    def snapshot(self) -> str:
        """Serialize the current context into a self-contained token string.

        The token is safe to pass across process boundaries (pipes, queues,
        environment variables, network payloads) because it is base64url text
        containing only ``[A-Za-z0-9_-]``.
        """
        return self._encode(self._context())

    def restore(self, token: str) -> None:
        """Replace the current context with the one carried by ``token``.

        Raises SnapshotError on any malformed input. On success the previous
        context is fully replaced, not merged.
        """
        data = self._decode(token)
        self._local.context = dict(data)

    @classmethod
    def _encode(cls, data: Dict[str, Any]) -> str:
        for k in data:
            if not isinstance(k, str):
                raise TypeError("context keys must be strings, got %r" % type(k).__name__)
            cls._validate_value(data[k])
        raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        compressed = zlib.compress(raw, 9)
        body = base64.urlsafe_b64encode(compressed).decode("ascii")
        return cls._PREFIX + body

    @classmethod
    def _decode(cls, token: str) -> Dict[str, Any]:
        if not isinstance(token, str):
            raise SnapshotError("token must be a string, got %r" % type(token).__name__)
        if not token.startswith(cls._PREFIX):
            raise SnapshotError("token is missing the expected prefix")
        body = token[len(cls._PREFIX):]
        # base64.urlsafe_b64decode is permissive about missing padding, but we
        # add it defensively so we never raise on a structurally fine token.
        pad = (-len(body)) % 4
        try:
            compressed = base64.urlsafe_b64decode(body + ("=" * pad))
            raw = zlib.decompress(compressed)
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, zlib.error) as exc:
            raise SnapshotError("failed to decode token: %s" % exc) from exc
        if not isinstance(data, dict):
            raise SnapshotError("decoded payload is not a JSON object")
        for k in data:
            if not isinstance(k, str):
                raise SnapshotError("decoded payload has non-string keys")
        return data

    @staticmethod
    def _validate_value(value: Any, depth: int = 0) -> None:
        """Recursively reject values json can't safely and portably encode.

        We intentionally constrain the accepted set rather than relying on
        json.dumps to complain, because the failure mode for bytes in
        particular is implementation-dependent. Depth guards against
        pathological recursion from self-referential structures that json
        would catch but only after consuming a large stack.
        """
        if depth > 64:
            raise TypeError("nesting depth exceeded maximum of 64")
        if value is None or isinstance(value, (bool, int, float, str)):
            return
        if isinstance(value, bytes):
            raise TypeError("bytes are not supported in context values")
        if isinstance(value, list):
            for item in value:
                ContextSnapshotter._validate_value(item, depth + 1)
            return
        if isinstance(value, dict):
            for k, v in value.items():
                if not isinstance(k, str):
                    raise TypeError("nested dict keys must be strings")
                ContextSnapshotter._validate_value(v, depth + 1)
            return
        raise TypeError("unsupported value type: %s" % type(value).__name__)
