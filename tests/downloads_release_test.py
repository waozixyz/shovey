#!/usr/bin/env python3
"""Release gates: another commit's build, wrong tags and bad uploads cannot publish."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release', ROOT / 'scripts/downloads-release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def run_gate(self, other_commit=False, rehearse=False, wrong_tag=False, bad_readback=False):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as scratch:
            folder = Path(scratch)
            revision = '1' * 40
            (folder / 'version.json').write_text(json.dumps({'version': '1.2.3', 'version_code': 9}))
            (folder / 'src').mkdir()
            (folder / 'src/CHANGELOG.md').write_text('## [1.2.3] - 2026-11-22\n\n- Release notes.\n')
            downloads = folder / 'native/downloads'
            downloads.mkdir(parents=True)
            for name in release.names('1.2.3'):
                (downloads / name).write_bytes(name.encode())
            (folder / 'native/revision').write_text(('2' * 40 if other_commit else revision) + '\n')
            mutations = []
            def api(base, path, token, method='GET', data=None, missing=False):
                if method != 'GET':
                    mutations.append((base, path, method, data))
                if path.startswith('/releases/tags/'):
                    return None
                if path == '/releases?per_page=30':
                    return []
                if path == '/commits/master':
                    return {'sha': revision}
                if path == '/releases':
                    if base == release.GITHUB:
                        return {'id': 9, 'assets': [], 'draft': True,
                                'upload_url': 'https://uploads.github.com/repos/waozixyz/shovey/releases/9/assets{?name,label}'}
                    return {'id': 3, 'assets': [], 'target_commitish': revision}
                if path.startswith('/tags/'):
                    return {'commit': {'sha': '2' * 40 if wrong_tag else revision}}
                if 'play-bundle.yml/runs?' in path:
                    return {'workflow_runs': [{'head_sha': revision}]}
                if path == '/releases/3':
                    self.assertEqual(len(uploads), 5)
                    self.assertEqual(len(readbacks), 5)
                    return {}
                if path == '/releases/9':
                    self.assertEqual(len(github_uploads), 5)
                    return {}
                self.fail('Unexpected API operation: ' + path)
            uploads, github_uploads, readbacks = [], [], []
            def upload(identifier, path, token):
                uploads.append(path.name)
                return {'browser_download_url': path.name}
            def upload_github(upload_url, path, token):
                github_uploads.append(path.name)
                return {'name': path.name}
            def download(url, destination, token):
                readbacks.append(url)
                destination.write_bytes(b'corrupt' if bad_readback else url.encode())
            env = {'GITEA_ACTIONS': 'true', 'GITHUB_SERVER_URL': release.GITEA,
                   'RELEASE_REVISION': revision, 'SHOVEY_BUILD_TOKEN': 'build-test-token',
                   'SHOVEY_RELEASE_TOKEN': 'release-test-token',
                   'SHOVEY_NATIVE_BUILD': str(folder / 'native'), 'SHOVEY_REHEARSE': str(rehearse).lower()}
            with patch.object(release, 'ROOT', folder), patch.dict(os.environ, env), \
                    patch.object(release.subprocess, 'check_output', return_value=revision), \
                    patch.object(release, 'request', side_effect=api), \
                    patch.object(release, 'verify') as verification, \
                    patch.object(release, 'upload', side_effect=upload), \
                    patch.object(release, 'upload_github', side_effect=upload_github), \
                    patch.object(release, 'download', side_effect=download):
                if other_commit or wrong_tag or bad_readback:
                    with self.assertRaises((SystemExit, ValueError)):
                        release.main()
                    self.assertFalse(any(method == 'PATCH' for _, _, method, _ in mutations))
                    if other_commit:
                        self.assertEqual(mutations, [])
                        verification.assert_not_called()
                elif rehearse:
                    release.main()
                    verification.assert_called_once()
                    self.assertEqual(mutations, [])
                    self.assertEqual(uploads + github_uploads, [])
                else:
                    release.main()
                    verification.assert_called_once()
                    self.assertIn((release.GITEA + '/api/v1/repos/' + release.REPO, '/releases/3', 'PATCH', {'draft': False}), mutations)
                    self.assertEqual(mutations[-1][0:3], (release.GITHUB, '/releases/9', 'PATCH'))
                    self.assertFalse(mutations[-1][3]['draft'])

    def test_another_commits_build_never_creates_release(self):
        self.run_gate(other_commit=True)

    def test_rehearsal_verifies_and_publishes_nothing(self):
        self.run_gate(rehearse=True)

    def test_unexpected_download_never_publishes(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as scratch:
            build = Path(scratch)
            (build / 'downloads').mkdir()
            (build / 'revision').write_text('1' * 40)
            for name in [*release.names('1.2.3'), 'extra.apk']:
                (build / 'downloads' / name).write_bytes(b'apk')
            with self.assertRaises(ValueError):
                release.collect(build, '1' * 40, '1.2.3')
            (build / 'downloads/extra.apk').unlink()
            self.assertEqual(release.collect(build, '1' * 40, '1.2.3'), build / 'downloads')

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
