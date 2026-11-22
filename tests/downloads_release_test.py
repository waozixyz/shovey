#!/usr/bin/env python3
"""Release gates: failed builds, unsafe artifacts and wrong tags cannot publish."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release', ROOT / 'scripts/downloads-release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_artifact_paths_and_duplicates(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as scratch:
            folder = Path(scratch)
            archive = folder / 'artifact.zip'
            for name in ['../escape.apk', '/escape.apk', 'unexpected.apk']:
                with zipfile.ZipFile(archive, 'w') as zipped:
                    zipped.writestr(name, b'apk')
                with self.assertRaises(ValueError):
                    release.extract(archive, folder / 'out', {'game.apk'})
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('game.apk', b'apk')
            release.extract(archive, folder / 'out', {'game.apk'})
            with self.assertRaises(ValueError):
                release.extract(archive, folder / 'out', {'game.apk'})

    def run_gate(self, conclusion='success', wrong_tag=False, bad_readback=False):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as scratch:
            folder = Path(scratch)
            revision = '1' * 40
            (folder / 'version.json').write_text(json.dumps({'version': '1.2.3', 'version_code': 9}))
            (folder / 'src').mkdir()
            (folder / 'src/CHANGELOG.md').write_text('## [1.2.3] - 2026-11-22\n\n- Release notes.\n')
            run = {'id': 17, 'head_sha': revision, 'display_title': 'Shovey build ' + revision,
                   'status': 'completed', 'conclusion': conclusion, 'html_url': 'https://github.com/build/17'}
            mutations = []
            def api(base, path, token, method='GET', data=None, missing=False):
                if method != 'GET':
                    mutations.append((path, method, data))
                if path.startswith('/releases/tags/'):
                    return None
                if path == '/commits/master':
                    return {'sha': revision}
                if 'downloads.yml/runs?' in path:
                    return {'workflow_runs': [run]}
                if path == '/releases':
                    return {'id': 3, 'assets': [], 'target_commitish': revision}
                if path.startswith('/tags/'):
                    return {'commit': {'sha': '2' * 40 if wrong_tag else revision}}
                if 'play-bundle.yml/runs?' in path:
                    return {'workflow_runs': [{'head_sha': revision}]}
                if path == '/releases/3':
                    self.assertEqual(len(uploads), 5)
                    self.assertEqual(len(readbacks), 5)
                    return {}
                self.fail('Unexpected API operation: ' + path)
            uploads, readbacks = [], []
            def collect(*args):
                downloads = folder / 'downloads'
                downloads.mkdir()
                for name in release.names('1.2.3'):
                    (downloads / name).write_bytes(name.encode())
                return downloads
            def upload(identifier, path, token):
                uploads.append(path.name)
                return {'browser_download_url': path.name}
            def download(url, destination, token):
                readbacks.append(url)
                destination.write_bytes(b'corrupt' if bad_readback else url.encode())
            env = {'GITEA_ACTIONS': 'true', 'GITHUB_SERVER_URL': release.GITEA,
                   'RELEASE_REVISION': revision, 'SHOVEY_BUILD_TOKEN': 'build-test-token',
                   'SHOVEY_RELEASE_TOKEN': 'release-test-token'}
            with patch.object(release, 'ROOT', folder), patch.dict(os.environ, env), \
                    patch.object(release.subprocess, 'check_output', return_value=revision), \
                    patch.object(release, 'request', side_effect=api), \
                    patch.object(release, 'collect', side_effect=collect), \
                    patch.object(release, 'verify') as verification, \
                    patch.object(release, 'upload', side_effect=upload), \
                    patch.object(release, 'download', side_effect=download):
                if conclusion != 'success' or wrong_tag or bad_readback:
                    with self.assertRaises(SystemExit):
                        release.main()
                    self.assertFalse(any(method == 'PATCH' for _, method, _ in mutations))
                    if conclusion != 'success':
                        self.assertEqual(mutations, [])
                        verification.assert_not_called()
                else:
                    release.main()
                    verification.assert_called_once()
                    self.assertEqual(mutations[-1], ('/releases/3', 'PATCH', {'draft': False}))

    def test_failed_build_never_creates_release(self):
        self.run_gate(conclusion='failure')

    def test_wrong_source_tag_never_publishes(self):
        self.run_gate(wrong_tag=True)

    def test_bad_upload_never_publishes(self):
        self.run_gate(bad_readback=True)

    def test_success_requires_five_verified_readbacks(self):
        self.run_gate()

    def test_session_cannot_publish(self):
        with patch.dict(os.environ, {'GITEA_ACTIONS': 'false'}), \
                patch.object(release, 'request') as api:
            with self.assertRaises(SystemExit):
                release.main()
            api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
