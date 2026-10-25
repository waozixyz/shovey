"""A local publication marker must never stand in for a different server release."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('editor_server', ROOT / 'scripts/editor_server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ServerCampaignTest(unittest.TestCase):
    def setUp(self):
        self.release = dict(version='0.6.30', sequence=34, artifacts=[dict(sha256='a' * 64)])
        self.boards = ['00' * 720, '0c' * 720]
        self.receipt = dict(phase='verified', release=self.release, approved_boards=self.boards)

    def test_exact_server_release_uses_its_published_boards(self):
        self.assertEqual(server.campaign_boards(self.release, self.receipt, {}), self.boards)

    def test_same_version_with_different_artifact_is_not_a_match(self):
        other = self.release | dict(artifacts=[dict(sha256='b' * 64)])
        with self.assertRaises(ValueError):
            server.campaign_boards(other, self.receipt, {})

    def test_changed_release_identity_is_not_a_match(self):
        with self.assertRaises(ValueError):
            server.campaign_boards(self.release | dict(sequence=35), self.receipt, {})

    def test_prior_server_snapshot_survives_new_local_publication(self):
        cached = dict(release=self.release, boards=self.boards)
        pending = dict(phase='building', approved_boards=['01' * 720])
        self.assertEqual(server.campaign_boards(self.release, pending, cached), self.boards)

    def test_verified_history_survives_a_new_build_and_an_older_editor_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            server.remember_verified(root, self.receipt)
            history = json.loads(server.history_path(root, self.release).read_text())
            pending = dict(phase='building', approved_boards=['01' * 720])
            older_cache = dict(release=self.release | dict(sequence=33), boards=['02' * 720])
            self.assertEqual(server.campaign_boards(self.release, pending, older_cache, history), self.boards)
            cached = json.loads((root / 'backup/editor-drafts/server-campaign.json').read_text())
            self.assertEqual(cached['boards'], self.boards)

    def test_history_requires_the_exact_public_release(self):
        history = dict(release=self.release, boards=self.boards)
        with self.assertRaises(ValueError):
            server.campaign_boards(self.release | dict(sequence=35), {}, {}, history)

    def test_same_verified_artifact_cannot_be_assigned_different_boards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            server.remember_verified(root, self.receipt)
            with self.assertRaises(ValueError):
                server.remember_verified(root, self.receipt | dict(approved_boards=['01' * 720]))

    def test_unverified_local_build_cannot_claim_server_match(self):
        with self.assertRaises(ValueError):
            server.campaign_boards(self.release, self.receipt | dict(phase='building'), {})

    def test_incomplete_campaign_is_not_accepted(self):
        for boards in ([], ['00' * 240], ['z' * 1440], ['00' * 720] * 176):
            with self.subTest(boards=len(boards)):
                with self.assertRaises(ValueError):
                    server.campaign_boards(self.release, self.receipt | dict(approved_boards=boards), {})


class LiveCampaignTest(unittest.TestCase):
    def setUp(self):
        self.config = dict(id='a' * 32, author='b' * 64, format='shovey-campaign-1')
        level = dict(number=1, cells=['00' * 12] * 20, tiles=['0c' * 12] * 20,
                     decorations=['00' * 12] * 20, solution='203')
        self.answer = dict(publication=dict(id=self.config['id'], author=dict(public_id=self.config['author']),
                           format=self.config['format'], visibility='public', levels=1),
                           document=dict(edition='classic', levels=[level]))
        self.calls = []

    def verify(self, number, board, route):
        self.calls.append((number, board, route))
        return True

    def test_live_boards_replace_the_older_package_comparison(self):
        result = server.live_campaign_snapshot(self.config, self.answer, self.verify,
                    dict(release=dict(sequence=147), boards=['01' * 720]))
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['source'], 'live-campaign')
        self.assertEqual(result['boards'], ['00' * 240 + '0c' * 240 + '00' * 240])
        self.assertEqual(len(self.calls), 1)

    def test_wrong_identity_cannot_mark_levels_synced(self):
        for key, value in (('id', 'c' * 32), ('author', dict(public_id='c' * 64)),
                           ('format', 'other'), ('visibility', 'private'), ('levels', 2)):
            with self.subTest(key=key):
                answer = self.answer | dict(publication=self.answer['publication'] | {key: value})
                with self.assertRaises(ValueError):
                    server.live_campaign_snapshot(self.config, answer, self.verify)
        self.assertEqual(self.calls, [])

    def test_route_must_win_before_a_board_is_synced(self):
        with self.assertRaisesRegex(ValueError, 'does not win'):
            server.live_campaign_snapshot(self.config, self.answer, lambda *args: False)

    def test_unchanged_verified_document_reuses_its_route_proof(self):
        result = server.live_campaign_snapshot(self.config, self.answer, self.verify)
        self.calls.clear()
        again = server.live_campaign_snapshot(self.config, self.answer, self.verify, result)
        self.assertEqual(again['boards'], result['boards'])
        self.assertEqual(self.calls, [])
        result['boards'] = ['01' * 720]
        server.live_campaign_snapshot(self.config, self.answer, self.verify, result)
        self.assertEqual(len(self.calls), 1, 'A changed cache reused an unrelated route proof')

    def test_changed_route_requires_new_proof(self):
        result = server.live_campaign_snapshot(self.config, self.answer, self.verify)
        self.answer['document']['levels'][0]['solution'] = '0'
        with self.assertRaises(ValueError):
            server.live_campaign_snapshot(self.config, self.answer, lambda *args: False, result)

    def test_unavailable_live_campaign_keeps_cache_but_does_not_claim_synced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / 'backup/editor-drafts'
            state.mkdir(parents=True)
            (root / 'backup/editor-publish.json').write_text('{}')
            config = root / 'backup/campaign-publisher/publication.json'
            config.parent.mkdir()
            config.write_text(json.dumps(self.config))
            previous = server.live_campaign_snapshot(self.config, self.answer, self.verify)
            cache = state / 'server-campaign.json'
            cache.write_text(json.dumps(previous))
            with patch.object(server, 'Queue'), patch.object(server, 'read_live_campaign', side_effect=OSError('offline')):
                server.check(root)
            result = json.loads(cache.read_text())
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['boards'], previous['boards'])


if __name__ == '__main__':
    unittest.main()
