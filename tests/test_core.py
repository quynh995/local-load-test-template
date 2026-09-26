import threading
import unittest

from local_snapshotter_context import ContextSnapshotter, SnapshotError


class TestBasic(unittest.TestCase):
    def test_set_get_roundtrip(self):
        snap = ContextSnapshotter()
        snap.set("request_id", "abc-123")
        self.assertEqual(snap.get("request_id"), "abc-123")
        self.assertIsNone(snap.get("missing"))
        self.assertEqual(snap.get("missing", "fallback"), "fallback")

    def test_clear(self):
        snap = ContextSnapshotter()
        snap.set("a", 1)
        snap.set("b", 2)
        snap.clear()
        self.assertIsNone(snap.get("a"))
        self.assertIsNone(snap.get("b"))

    def test_overwrite(self):
        snap = ContextSnapshotter()
        snap.set("k", "first")
        snap.set("k", "second")
        self.assertEqual(snap.get("k"), "second")


class TestSerialization(unittest.TestCase):
    def test_snapshot_restore_roundtrip(self):
        snap = ContextSnapshotter()
        data = {"request_id": "abc-123", "user_id": 42, "admin": True, "tags": ["x", "y"], "meta": {"nested": None}}
        for k, v in data.items():
            snap.set(k, v)
        token = snap.snapshot()
        self.assertIsInstance(token, str)

        snap2 = ContextSnapshotter()
        snap2.restore(token)
        self.assertEqual(snap2.get("request_id"), "abc-123")
        self.assertEqual(snap2.get("user_id"), 42)
        self.assertEqual(snap2.get("admin"), True)
        self.assertEqual(snap2.get("tags"), ["x", "y"])
        self.assertEqual(snap2.get("meta"), {"nested": None})

    def test_token_is_base64url_text(self):
        snap = ContextSnapshotter()
        snap.set("k", "v")
        token = snap.snapshot()
        self.assertTrue(token.startswith("LSC1"))
        body = token[4:]
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=")
        for ch in body:
            self.assertIn(ch, allowed)

    def test_deterministic_token_for_equal_contexts(self):
        a = ContextSnapshotter()
        b = ContextSnapshotter()
        # Insert in different orders — sort_keys should normalize this.
        a.set("z", 1)
        a.set("a", 2)
        b.set("a", 2)
        b.set("z", 1)
        self.assertEqual(a.snapshot(), b.snapshot())

    def test_restore_replaces_not_merges(self):
        snap = ContextSnapshotter()
        snap.set("before", 1)
        snap.set("kept", 2)
        token = ContextSnapshotter().snapshot()  # empty context token
        snap.restore(token)
        self.assertIsNone(snap.get("before"))
        self.assertIsNone(snap.get("kept"))


class TestErrors(unittest.TestCase):
    def test_restore_bad_prefix(self):
        snap = ContextSnapshotter()
        with self.assertRaises(SnapshotError):
            snap.restore("XXXXnot-a-real-token")

    def test_restore_garbage_body(self):
        snap = ContextSnapshotter()
        with self.assertRaises(SnapshotError):
            snap.restore("LSC1!!!garbage!!!")

    def test_restore_non_string_token(self):
        snap = ContextSnapshotter()
        with self.assertRaises(SnapshotError):
            snap.restore(b"LSC1whatever")

    def test_restore_non_object_payload(self):
        snap = ContextSnapshotter()
        # Encode a JSON list instead of an object.
        import json, zlib, base64
        raw = json.dumps([1, 2, 3]).encode("utf-8")
        body = base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii")
        with self.assertRaises(SnapshotError):
            snap.restore("LSC1" + body)

    def test_set_non_string_key(self):
        snap = ContextSnapshotter()
        with self.assertRaises(TypeError):
            snap.set(123, "x")

    def test_set_bytes_value_rejected(self):
        snap = ContextSnapshotter()
        with self.assertRaises(TypeError):
            snap.set("k", b"raw")

    def test_set_unsupported_type_rejected(self):
        class Custom:
            pass
        snap = ContextSnapshotter()
        with self.assertRaises(TypeError):
            snap.set("k", Custom())


class TestThreadIsolation(unittest.TestCase):
    def test_threads_do_not_share_context(self):
        snap = ContextSnapshotter()
        snap.set("main", "yes")
        results = {}

        def worker():
            # A fresh thread should see an empty context.
            results["before"] = snap.get("main")
            snap.set("worker", 1)
            results["token"] = snap.snapshot()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        self.assertIsNone(results["before"])
        self.assertEqual(snap.get("main"), "yes")
        # Main thread never saw the worker's key.
        self.assertIsNone(snap.get("worker"))

        # The worker's snapshot can be restored in the main thread.
        snap.restore(results["token"])
        self.assertEqual(snap.get("worker"), 1)


class TestNestedAndNumeric(unittest.TestCase):
    def test_nested_structures_roundtrip(self):
        snap = ContextSnapshotter()
        snap.set("a", {"b": [{"c": 1}, {"d": [True, False, None]}]})
        token = snap.snapshot()
        ContextSnapshotter().restore(token)
        self.assertEqual(snap.get("a"), {"b": [{"c": 1}, {"d": [True, False, None]}]})

    def test_float_values_roundtrip(self):
        snap = ContextSnapshotter()
        snap.set("pi", 3.14159)
        token = snap.snapshot()
        snap2 = ContextSnapshotter()
        snap2.restore(token)
        self.assertEqual(snap2.get("pi"), 3.14159)


if __name__ == "__main__":
    unittest.main()
