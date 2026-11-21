#!/usr/bin/env python3
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("repair", ROOT / "scripts/fetch-android-repair.py")
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)


class RepairFetchTest(unittest.TestCase):
    def run_fetch(self, body, *, data=b"local APK", url="https://git.waozi.xyz/lfs/object", descriptor=None):
        digest = hashlib.sha256(data).hexdigest()
        obj = descriptor or {"oid": digest, "size": len(data),
                             "actions": {"download": {"href": url}}}
        replies = iter([json.dumps({"objects": [obj]}).encode(), body])
        def open_url(request, timeout):
            self.assertEqual(timeout, 60)
            return io.BytesIO(next(replies))
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as directory:
            output = Path(directory) / "repair.apk"
            output.write_bytes(b"previous")
            try:
                repair.fetch(digest, len(data), output, open_url)
            except Exception:
                self.assertEqual(output.read_bytes(), b"previous")
                self.assertFalse(output.with_suffix(".apk.download").exists())
                raise
            self.assertEqual(output.read_bytes(), data)

    def test_exact_bytes(self):
        self.run_fetch(b"local APK")

    def test_truncated_corrupt_and_oversized(self):
        for body in (b"local", b"wrong APK", b"local APK extra"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.run_fetch(body)

    def test_only_canonical_https_download(self):
        for url in ("http://git.waozi.xyz/object", "https://example.com/object",
                    "https://user@git.waozi.xyz/object", "https://git.waozi.xyz:444/object"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.run_fetch(b"local APK", url=url)

    def test_descriptor_must_match(self):
        with self.assertRaises(ValueError):
            self.run_fetch(b"local APK", descriptor={"oid": "0" * 64, "size": 9})

    def test_redirect_cannot_leave_host(self):
        with self.assertRaises(ValueError):
            repair.CanonicalRedirect().redirect_request(
                Request(repair.BATCH), None, 302, "redirect", {}, "https://example.com/object")

    def test_invalid_input(self):
        for digest, size in (("bad", 9), ("0" * 64, 0), ("0" * 64, repair.LIMIT + 1)):
            with self.subTest(size=size), self.assertRaises(ValueError):
                repair.fetch(digest, size, ROOT / "build/invalid.apk")


if __name__ == "__main__":
    (ROOT / "build").mkdir(exist_ok=True)
    unittest.main()
