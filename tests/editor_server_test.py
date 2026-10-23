"""A local publication marker must never stand in for a different server release."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

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


if __name__ == '__main__':
    unittest.main()
