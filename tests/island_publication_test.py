#!/usr/bin/env python3
"""Exercise Island publication with the real canonical Apps importer."""
from hashlib import sha256
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("publish_island", ROOT / "scripts/publish-island.py")
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)
CANONICAL = Path(os.environ.get("APPS_NODE_RELEASE",
    str(ROOT.parents[1] / "modules/apps/scripts/node_release.py")))
release = publish.load_release(CANONICAL)


class IslandPublicationTest(unittest.TestCase):
    def setUp(self):
        work = ROOT / "work/island-publication-tests"
        work.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = self.root / "packages"
        self.store.mkdir()
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(serialization.Encoding.Raw,
                                               serialization.PublicFormat.Raw).hex()
        self.pins = [dict(key_id=publish.KEY_ID, public_key=public,
                          app_ids=[], node_app_ids=[publish.APP])]
        self.data = b"ZX\0\0Island compiled fixture"
        self.digest = sha256(self.data).hexdigest()
        self.value = dict(app_id=publish.APP, sequence=1, version="0.4.8",
            runtime="kryon-app-v1", host_api=41, module_api=2, data_schema=0,
            key_id=publish.KEY_ID, artifacts=[dict(variant="module", sha256=self.digest,
            size=len(self.data))], dependencies=[])
        self.value["signature"] = key.sign(release.signing_message(self.value)).hex()
        self.entries = self.packet(self.value)

    def packet(self, value):
        encoded = json.dumps(value).encode()
        base = publish.APP + "/"
        payload = self.digest + ".zx"
        return {base + "latest-v2.json": encoded, base + payload: self.data,
                base + payload + ".release-v2.json": encoded, base + "release-1.json": encoded}

    def run_import(self, register=lambda value: None):
        return publish.protected_import(release, self.entries, self.pins,
                                        self.store, self.root / "scratch", register)

    def test_gate_precedes_registration_and_every_public_write(self):
        gate = self.store / publish.APP / (self.digest + ".zx.product")
        events = []
        original = release.atomic_write

        def observed(path, data):
            if path.parent == self.store / publish.APP and path != gate:
                self.assertEqual(gate.read_text(), publish.PRODUCT + "\n")
                self.assertEqual(events[0], "registered")
                events.append(path.name)
            original(path, data)

        def register(value):
            self.assertEqual(gate.read_text(), publish.PRODUCT + "\n")
            self.assertFalse((gate.parent / (self.digest + ".zx")).exists())
            events.append("registered")

        with patch.object(release, "atomic_write", observed):
            self.assertEqual(self.run_import(register), self.value)
        self.assertIn("latest-v2.json", events)
        self.assertEqual((gate.parent / (self.digest + ".zx")).read_bytes(), self.data)
        self.run_import()

    def test_bad_signature_namespace_size_and_digest_never_reach_registration(self):
        original = self.entries.copy()
        variants = []
        forged = dict(self.value, signature="00" * 64)
        variants.append(self.packet(forged))
        variants.append(dict(original, **{"xyz.waozi.arcade/latest-v2.json": b"{}"}))
        corrupted = dict(original)
        corrupted[publish.APP + "/" + self.digest + ".zx"] = self.data + b"extra"
        variants.append(corrupted)
        for entries in variants:
            with self.subTest(entries=list(entries)):
                self.entries = entries
                with self.assertRaises(ValueError):
                    self.run_import(lambda value: self.fail("invalid package was registered"))
                self.assertFalse((self.store / publish.APP).exists())

    def test_foreign_pin_is_rejected(self):
        self.pins[0]["node_app_ids"] = ["xyz.waozi.arcade"]
        with self.assertRaises(ValueError):
            self.run_import()

    def test_failed_registration_leaves_only_the_gate(self):
        def failed(value):
            raise RuntimeError("registration failed")
        with self.assertRaises(RuntimeError):
            self.run_import(failed)
        directory = self.store / publish.APP
        self.assertEqual([path.name for path in directory.iterdir()], [self.digest + ".zx.product"])

    def test_existing_ungated_or_conflicting_payload_is_refused(self):
        directory = self.store / publish.APP
        directory.mkdir()
        (directory / (self.digest + ".zx")).write_bytes(self.data)
        with self.assertRaises(ValueError):
            self.run_import()
        (directory / (self.digest + ".zx.product")).write_text("other.product\n")
        with self.assertRaises(ValueError):
            self.run_import()

    def test_archive_rejects_duplicate_traversal_symlink_and_source(self):
        for kind in ("duplicate", "traversal", "symlink", "source"):
            with self.subTest(kind=kind):
                packet = self.root / "bad.tar"
                with tarfile.open(packet, "w:") as archive:
                    names = [publish.APP + "/latest-v2.json"]
                    names += {"duplicate": names, "traversal": [publish.APP + "/../secret"],
                              "symlink": [publish.APP + "/link"],
                              "source": [publish.APP + "/private.zi"]}[kind]
                    for name in names:
                        item = tarfile.TarInfo(name)
                        if kind == "symlink":
                            item.type = tarfile.SYMTYPE
                            item.linkname = "/outside"
                        archive.addfile(item, BytesIO(b""))
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    entries = publish.read_packet(packet)
                    publish.validate_entries(release, entries, self.pins, self.root / "scratch")


if __name__ == "__main__":
    unittest.main()
