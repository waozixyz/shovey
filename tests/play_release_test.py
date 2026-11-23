#!/usr/bin/env python3
"""Play upload gates: a rehearsal never commits and no version is uploaded twice."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('play_release', ROOT / 'scripts/play-release.py')
play_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(play_release)
VERSION, CODE = '1.2.3', '42'


class Play:
    package, token = 'fixture', 'fixture-token'

    def __init__(self, internal=()):
        self.tracks = [{'track': 'internal', 'releases': list(internal)}, {'track': 'alpha', 'releases': []}]
        self.calls = []

    def call(self, method, path, body=None):
        self.calls.append((method, path))
        if (method, path) == ('POST', '/edits'):
            return 200, {'id': 'e1'}
        if method == 'GET' and path.endswith('/tracks'):
            return 200, {'tracks': self.tracks}
        if method == 'PUT' and path.endswith('/tracks/internal'):
            self.pending = body
        return 200, {}

    def did(self, method, suffix):
        return any(m == method and p.endswith(suffix) for m, p in self.calls)


RELEASED = {'name': VERSION, 'versionCodes': [CODE], 'status': 'completed'}


class PlayReleaseTests(unittest.TestCase):
    def publish(self, play, answer, rehearse):
        sent = []
        def send(play, edit, bundle):
            sent.append(edit)
            return answer
        result = play_release.publish(play, Path('bundle.aab'), VERSION, CODE, 'Notes.', rehearse, send=send)
        return result, sent

    def test_rehearsal_of_a_new_version_validates_and_sends_nothing(self):
        play = Play()
        result, sent = self.publish(play, (200, {'versionCode': 42}), rehearse=True)
        self.assertFalse(result)
        self.assertEqual(sent, ['e1'])
        self.assertEqual(play.pending, play_release.internal_release(VERSION, CODE, 'Notes.'))
        self.assertTrue(play.did('POST', ':validate') and play.did('DELETE', '/edits/e1'))
        self.assertFalse(play.did('POST', ':commit'))

    def test_rehearsal_of_a_released_version_accepts_plays_refusal(self):
        play = Play([RELEASED])
        result, sent = self.publish(play, (403, 'Version code 42 has already been used.'), rehearse=True)
        self.assertTrue(result)
        self.assertEqual(sent, ['e1'])
        self.assertTrue(play.did('DELETE', '/edits/e1'))
        self.assertFalse(play.did('PUT', '/tracks/internal') or play.did('POST', ':commit'))

    def test_release_commits_internal_testing_once(self):
        play = Play()
        result, _ = self.publish(play, (200, {'versionCode': 42}), rehearse=False)
        self.assertTrue(result)
        self.assertEqual(play.pending['releases'][0]['status'], 'completed')
        self.assertTrue(play.did('POST', ':validate') and play.did('POST', ':commit'))
        self.assertFalse(play.did('DELETE', '/edits/e1'))

    def test_released_version_is_never_uploaded_again(self):
        play = Play([RELEASED])
        result, sent = self.publish(play, (200, {'versionCode': 42}), rehearse=False)
        self.assertTrue(result)
        self.assertEqual(sent, [])
        self.assertTrue(play.did('DELETE', '/edits/e1'))
        self.assertFalse(play.did('POST', ':commit'))

    def test_refused_or_mismatched_bundle_never_commits(self):
        for answer in ((403, 'Version code 42 has already been used.'), (400, 'Invalid bundle'),
                       (200, {'versionCode': 41})):
            play = Play()
            with self.assertRaises(RuntimeError):
                self.publish(play, answer, rehearse=False)
            self.assertTrue(play.did('DELETE', '/edits/e1'))
            self.assertFalse(play.did('POST', ':commit'))
        play = Play()
        with self.assertRaises(RuntimeError):
            self.publish(play, (400, 'Invalid bundle'), rehearse=True)

    def test_notes_keep_plays_500_characters(self):
        changelog = '## [1.2.3] - 2026-11-23\n\n' + 'é' * 501 + '\n\n## [1.2.2] - 2026-11-01\n\n- Older.\n'
        self.assertEqual(play_release.notes('1.2.3', changelog), 'é' * 499 + '…')
        self.assertEqual(play_release.notes('1.2.2', changelog), '- Older.')

    def test_session_cannot_reach_play(self):
        with patch.dict(os.environ, {'GITEA_ACTIONS': 'false'}), \
                patch('sys.argv', ['play-release.py', 'account.json', 'bundle.aab', '--entity', '.']), \
                patch.object(play_release, 'load') as load:
            with self.assertRaises(SystemExit):
                play_release.main()
            load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
