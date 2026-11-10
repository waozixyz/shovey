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


class ReleasedIslandTest(unittest.TestCase):
    def setUp(self):
        self.revision = 'a' * 40
        self.release = dict(tag_name='v0.6.169', draft=False, prerelease=False)
        self.descriptor = json.loads((ROOT / 'packaging/island.json').read_bytes())
        # A published player's bytes differ from the unreleased checkout.
        self.descriptor.update(sha256='b' * 64, bytes=6502780)
        self.live = dict(app_id=self.descriptor['package_id'], version=self.descriptor['version'],
                         artifacts=[dict(variant='module', sha256=self.descriptor['sha256'],
                                         size=self.descriptor['bytes'])])
        self.paths = []

    def request(self, command, **kwargs):
        path = command[-1]
        if command[0] == 'gh':
            self.paths.append(path)
            if path.endswith('/releases/latest'):
                value = self.release
            elif '/commits/' in path:
                value = dict(sha=self.revision)
            else:
                self.assertEqual(path, 'repos/waozixyz/shovey/contents/packaging/island.json?ref=' + self.revision)
                self.assertIn('Accept: application/vnd.github.raw+json', command)
                value = self.descriptor
            body = json.dumps(value).encode()
        else:
            body = json.dumps(self.live).encode() if '/latest?' in path else b'403'
        return subprocess.CompletedProcess(command, 0, body, b'')

    def test_unreleased_rebuild_uses_published_commit_and_passes_live_gate(self):
        descriptor, tag, revision = delivery.released_descriptor(self.request)
        self.assertNotEqual(descriptor['sha256'], json.loads((ROOT / 'packaging/island.json').read_bytes())['sha256'])
        self.assertEqual((tag, revision), ('v0.6.169', self.revision))
        self.assertEqual(self.paths, ['repos/waozixyz/shovey/releases/latest',
                                     'repos/waozixyz/shovey/commits/v0.6.169',
                                     'repos/waozixyz/shovey/contents/packaging/island.json?ref=' + self.revision])
        self.assertEqual(delivery.verify(descriptor, self.request), self.live)

    def test_new_published_descriptor_still_requires_matching_live_bytes(self):
        self.descriptor['sha256'] = 'c' * 64
        descriptor, _, _ = delivery.released_descriptor(self.request)
        with self.assertRaisesRegex(ValueError, 'catalog differs'):
            delivery.verify(descriptor, self.request)

    def test_unpublished_or_unresolved_source_is_rejected(self):
        for invalid in (dict(draft=True), dict(prerelease=True), dict(tag_name='master')):
            with self.subTest(invalid=invalid):
                previous = self.release.copy()
                self.release.update(invalid)
                with self.assertRaisesRegex(ValueError, 'published stable'):
                    delivery.released_descriptor(self.request)
                self.release = previous
        self.revision = 'master'
        with self.assertRaisesRegex(ValueError, 'full commit'):
            delivery.released_descriptor(self.request)

    def test_github_failure_does_not_fall_back_to_checkout(self):
        def failed(command, **kwargs):
            raise subprocess.CalledProcessError(1, command)
        with self.assertRaises(subprocess.CalledProcessError):
            delivery.released_descriptor(failed)


if __name__ == '__main__':
    unittest.main()
