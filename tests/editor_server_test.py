"""A local publication marker must never stand in for a different server release."""
import importlib.util
from pathlib import Path
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
