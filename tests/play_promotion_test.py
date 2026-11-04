#!/usr/bin/env python3
"""Exercise the exact Play API code embedded in the reusable workflow."""
import contextlib
import copy
import io
from pathlib import Path
import re
import textwrap
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/play-promote.yml'
source = WORKFLOW.read_text().split("python3 - <<'PY'\n")[-1].rsplit('          PY', 1)[0]
promotion = types.ModuleType('promotion')
exec(compile(textwrap.dedent(source), str(WORKFLOW), 'exec'), promotion.__dict__)
VERSION, CODE = '1.2.3', '42'


def tracks():
    return [{'track': 'production', 'releases': [
                {'name': 'public', 'versionCodes': ['10'], 'status': 'completed'}]},
            {'track': 'alpha', 'releases': []},
            {'track': 'internal', 'releases': [
                {'name': VERSION, 'versionCodes': [CODE], 'status': 'completed',
                 'releaseNotes': [{'language': 'en-US', 'text': 'Release notes.'}]}]}]


class Play:
    package = 'fixture'

    def __init__(self, initial=None, fail_validation=False, stale_readback=False):
        self.tracks = copy.deepcopy(initial if initial is not None else tracks())
        self.initial = copy.deepcopy(self.tracks)
        self.calls = []
        self.pending = None
        self.edits = 0
        self.fail_validation = fail_validation
        self.stale_readback = stale_readback

    def call(self, method, path, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if (method, path) == ('POST', '/edits'):
            self.edits += 1
            return 200, {'id': str(self.edits)}
        if method == 'GET' and path.endswith('/tracks'):
            return 200, {'tracks': copy.deepcopy(self.tracks)}
        if method == 'GET' and '/testers/' in path:
            return 200, {}
        if method == 'PUT':
            if not path.endswith('/tracks/alpha') or body['track'] != 'alpha':
                raise AssertionError('Unexpected write outside closed testing')
            self.pending = copy.deepcopy(body)
        if path.endswith(':validate') and self.fail_validation:
            return 400, 'fixture validation error'
        if path.endswith(':commit') and not self.stale_readback:
            self.tracks = [self.pending if t['track'] == 'alpha' else t for t in self.tracks]
        return 200, {}


class PromotionTest(unittest.TestCase):
    def setUp(self):
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def test_completed_release_preserves_notes_and_source(self):
        source = tracks()
        before = copy.deepcopy(source)
        source[2]['releases'][0]['userFraction'] = 0.5
        result = promotion.closed_release(source, VERSION, CODE)
        self.assertEqual(result['track'], 'alpha')
        self.assertEqual(result['releases'], before[2]['releases'])
        self.assertEqual(source[0], before[0])
        self.assertEqual(source[2]['releases'][0]['userFraction'], 0.5)

    def test_forbids_production_and_every_unconfigured_target(self):
        for target in ('production', 'internal', 'beta', 'other-closed'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                promotion.closed_release(tracks(), VERSION, CODE, target)

    def test_requires_exact_completed_internal_release(self):
        for version, code in [('bad', CODE), (VERSION, '0'), ('1.2.4', CODE), (VERSION, '43')]:
            with self.subTest(version=version, code=code), self.assertRaises(ValueError):
                promotion.closed_release(tracks(), version, code)
        for status in ('draft', 'inProgress', 'halted'):
            source = tracks()
            source[2]['releases'][0]['status'] = status
            with self.subTest(status=status), self.assertRaises(ValueError):
                promotion.closed_release(source, VERSION, CODE)

    def test_requires_configured_track_and_refuses_downgrade(self):
        with self.assertRaises(ValueError):
            promotion.closed_release([tracks()[2]], VERSION, CODE)
        source = tracks()
        source[1]['releases'] = [{'versionCodes': ['43'], 'status': 'completed'}]
        with self.assertRaises(ValueError):
            promotion.closed_release(source, VERSION, CODE)
        source[1]['releases'][0]['versionCodes'] = ['41']
        self.assertIsNotNone(promotion.closed_release(source, VERSION, CODE))

    def test_real_transaction_writes_only_closed_and_reads_fresh_state(self):
        play = Play()
        promotion.promote(play, VERSION, CODE)
        self.assertEqual(play.edits, 2)
        writes = [(m, p) for m, p, _ in play.calls if m == 'PUT']
        self.assertEqual(writes, [('PUT', '/edits/1/tracks/alpha')])
        self.assertIn(('POST', '/edits/1:validate', {}), play.calls)
        self.assertIn(('POST', '/edits/1:commit', {}), play.calls)
        self.assertIn(('GET', '/edits/2/tracks', None), play.calls)
        self.assertEqual(play.tracks[0], play.initial[0])
        self.assertEqual(play.tracks[2], play.initial[2])
        self.assertIsNone(promotion.closed_release(play.tracks, VERSION, CODE))
        play.calls.clear()
        promotion.promote(play, VERSION, CODE)
        self.assertFalse(any(m == 'PUT' or p.endswith(':commit') for m, p, _ in play.calls))

    def test_inspection_never_writes_or_commits(self):
        play = Play()
        promotion.promote(play, '', '', inspect_only=True)
        self.assertEqual(play.tracks, play.initial)
        self.assertFalse(any(m == 'PUT' or p.endswith(':commit') for m, p, _ in play.calls))
        self.assertIn(('DELETE', '/edits/1', None), play.calls)

    def test_failed_validation_discards_edit_and_stale_readback_fails(self):
        play = Play(fail_validation=True)
        with self.assertRaisesRegex(RuntimeError, 'validation error'):
            promotion.promote(play, VERSION, CODE)
        self.assertFalse(any(p.endswith(':commit') for _, p, _ in play.calls))
        self.assertIn(('DELETE', '/edits/1', None), play.calls)
        play = Play(stale_readback=True)
        with self.assertRaisesRegex(RuntimeError, 'Fresh API read'):
            promotion.promote(play, VERSION, CODE)
        self.assertIn(('DELETE', '/edits/2', None), play.calls)

    def test_credential_setup_uses_github_compatible_sealed_ciphertext(self):
        import base64
        import ctypes
        sodium = ctypes.CDLL('libsodium.so.23')
        sodium.sodium_init()
        public, private = ctypes.create_string_buffer(32), ctypes.create_string_buffer(32)
        self.assertEqual(sodium.crypto_box_keypair(public, private), 0)
        credential = 'fixture credential, never a real key'
        sealed = base64.b64decode(promotion.seal_credential(
            base64.b64encode(public.raw).decode(), credential))
        self.assertNotIn(credential.encode(), sealed)
        opened = ctypes.create_string_buffer(len(sealed) - 48)
        self.assertEqual(sodium.crypto_box_seal_open(opened, sealed, len(sealed), public, private), 0)
        self.assertEqual(opened.raw.decode(), credential)
        with self.assertRaises(ValueError):
            promotion.seal_credential('YmFk', credential)

    def test_release_workflows_target_internal_then_closed_and_only_gplay(self):
        bundle = (ROOT / '.github/workflows/play-bundle.yml').read_text()
        downloads = (ROOT / '.github/workflows/downloads.yml').read_text()
        self.assertIn('uses: ./.github/workflows/play-promote.yml', bundle)
        self.assertIn('uses: ./.github/workflows/play-bundle.yml', downloads)
        self.assertIn('secrets: inherit', bundle)
        uploads = re.findall(r'(?ms)^      - .*?upload-google-play@.*?(?=^      - |^  [a-z]|\Z)', bundle)
        self.assertEqual(len(uploads), 1)
        self.assertIn('track: internal', uploads[0])
        self.assertIn('status: completed', uploads[0])
        files = re.findall(r'releaseFiles: (.+)', uploads[0])
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith('-gplay.aab'))
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            text = path.read_text()
            self.assertNotRegex(text, r'track:\s*production|tracks/production')
            self.assertNotIn('scripts/promote-play-release.py', text)


if __name__ == '__main__':
    unittest.main()
