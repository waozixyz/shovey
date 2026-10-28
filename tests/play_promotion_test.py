#!/usr/bin/env python3
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('promotion', ROOT / 'scripts/promote-play-release.py')
promotion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promotion)


def tracks():
    return [{'track': 'production', 'releases': []},
            {'track': 'internal', 'releases': [
                {'name': '0.6.159', 'versionCodes': ['167'], 'status': 'completed',
                 'releaseNotes': [{'language': 'en-US', 'text': 'Small Dew packs and bulk savings.'}]}]}]


class PromotionTest(unittest.TestCase):
    def test_exact_release_preserves_notes_and_source(self):
        source = tracks()
        before = copy.deepcopy(source)
        result = promotion.production_release(source, '0.6.159', '167')
        self.assertEqual(result['releases'], source[1]['releases'])
        self.assertEqual(result['track'], 'production')
        self.assertEqual(source, before)

    def test_rejects_other_versions_and_unfinished_internal_release(self):
        for version, code in [('0.6.160', '167'), ('0.6.159', '168'), ('bad', '167'), ('0.6.159', '0')]:
            with self.subTest(version=version, code=code), self.assertRaises(ValueError):
                promotion.production_release(tracks(), version, code)
        source = tracks()
        source[1]['releases'][0]['status'] = 'draft'
        with self.assertRaises(ValueError):
            promotion.production_release(source, '0.6.159', '167')

    def test_does_not_replace_another_public_release(self):
        source = tracks()
        source[0]['releases'] = [{'name': '0.6.160', 'versionCodes': ['168'], 'status': 'completed'}]
        with self.assertRaises(ValueError):
            promotion.production_release(source, '0.6.159', '167')

    def test_repeated_exact_publication_is_a_readback(self):
        source = tracks()
        source[0]['releases'] = copy.deepcopy(source[1]['releases'])
        self.assertIsNone(promotion.production_release(source, '0.6.159', '167'))

    def test_failed_validation_never_commits_and_discards_edit(self):
        class Play:
            def __init__(self):
                self.calls = []

            def call(self, method, path, body=None):
                self.calls.append((method, path))
                if (method, path) == ('POST', '/edits'):
                    return 200, {'id': 'test'}
                if method == 'GET':
                    return 200, {'tracks': tracks()}
                if path.endswith(':validate'):
                    return 400, 'Launch requirements missing'
                return 200, {}

        play = Play()
        with self.assertRaises(RuntimeError):
            promotion.promote(play, '0.6.159', '167')
        self.assertNotIn(('POST', '/edits/test:commit'), play.calls)
        self.assertIn(('DELETE', '/edits/test'), play.calls)


if __name__ == '__main__':
    unittest.main()
