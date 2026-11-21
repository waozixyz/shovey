#!/usr/bin/env python3
"""Device repair ABI selection must not relax normal release verification."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('release', ROOT / 'scripts/android-release.py')
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class RepairAbiTest(unittest.TestCase):
    def verify(self, abis, device_abi=None):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            root = Path(directory)
            (root / 'src').mkdir()
            (root / 'src/CHANGELOG.md').write_text('## [1.0.0] - 2026-11-21\n')
            apk = root / 'app.apk'
            payload = b'collection'
            with zipfile.ZipFile(apk, 'w') as archive:
                for abi in abis:
                    archive.writestr(f'lib/{abi}/libmain.so', b'native')
                archive.writestr('assets/shovey.zx', payload)
                archive.writestr('assets/shovey.json', json.dumps(dict(
                    id='arcade.shovey-player', version='1.0.0',
                    sha256=hashlib.sha256(payload).hexdigest())))
            def output(command, **kwargs):
                if command[0] == 'openssl':
                    return b'certificate'
                if str(command[0]).endswith('aapt'):
                    return "package: name='xyz.waozi.shovey' versionCode='1' versionName='1.0.0'\n"
                return ('Number of signers: 1\nSigner #1 certificate SHA-256 digest: '
                        + hashlib.sha256(b'certificate').hexdigest() + '\n')
            with patch.object(release, 'ROOT', root), \
                    patch.object(release.subprocess, 'check_output', side_effect=output), \
                    patch.object(release.subprocess, 'run'):
                return release.verify(apk, '1.0.0', root, device_abi=device_abi)

    def test_normal_release_requires_both(self):
        self.verify(['arm64-v8a', 'armeabi-v7a'])
        with self.assertRaises(AssertionError):
            self.verify(['arm64-v8a'])

    def test_device_build_requires_exact_selected_abi(self):
        self.verify(['arm64-v8a'], 'arm64-v8a')
        for abis in (['armeabi-v7a'], ['arm64-v8a', 'armeabi-v7a']):
            with self.subTest(abis=abis), self.assertRaises(AssertionError):
                self.verify(abis, 'arm64-v8a')


if __name__ == '__main__':
    (ROOT / 'build').mkdir(exist_ok=True)
    unittest.main()
