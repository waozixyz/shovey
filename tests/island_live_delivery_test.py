#!/usr/bin/env python3
"""Keep catalog parity and missing/ungated paid-byte failures observable."""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('island_delivery', ROOT / 'scripts/verify-island-delivery.py')
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)


class LiveIslandTest(unittest.TestCase):
    def setUp(self):
        self.descriptor = json.loads((ROOT / 'packaging/island.json').read_bytes())
        self.value = dict(app_id=self.descriptor['package_id'], version=self.descriptor['version'],
                          artifacts=[dict(variant='module', sha256=self.descriptor['sha256'],
                                          size=self.descriptor['bytes'])])
        self.status = b'403'

    def request(self, command, **kwargs):
        body = json.dumps(self.value).encode() if '/latest?' in command[-1] else self.status
        return subprocess.CompletedProcess(command, 0, body, b'')

    def test_matching_catalog_and_gate(self):
        self.assertEqual(delivery.verify(self.descriptor, self.request), self.value)

    def test_wrong_package_version_digest_or_size(self):
        for field, wrong in [('app_id', 'other'), ('version', '0.0.0'), ('artifacts', [])]:
            with self.subTest(field=field):
                original = self.value[field]
                self.value[field] = wrong
                with self.assertRaisesRegex(ValueError, 'catalog differs'):
                    delivery.verify(self.descriptor, self.request)
                self.value[field] = original
        for field, wrong in [('sha256', '0' * 64), ('size', 1)]:
            original = self.value['artifacts'][0][field]
            self.value['artifacts'][0][field] = wrong
            with self.assertRaises(ValueError):
                delivery.verify(self.descriptor, self.request)
            self.value['artifacts'][0][field] = original

    def test_missing_or_ungated_payload(self):
        for status in (b'404', b'200', b'500'):
            with self.subTest(status=status):
                self.status = status
                with self.assertRaisesRegex(ValueError, 'product gate'):
                    delivery.verify(self.descriptor, self.request)


if __name__ == '__main__':
    unittest.main()
