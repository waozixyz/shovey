"""Requests survive worker failures without blocking unrelated levels."""
import fcntl
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('queue_module', ROOT / 'scripts/publication_queue.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublicationQueue(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.queue = module.Queue(self.temporary.name)
        self.first = dict(number=1, board='01' * 720)
        self.second = dict(number=2, board='02' * 720)

    def tearDown(self):
        self.temporary.cleanup()

    def data(self):
        return json.loads(self.queue.path.read_text())

    def latest(self, number):
        return json.loads((self.queue.state / f'{number:03}.publication').read_text())

    def test_duplicate_clicks_coalesce_and_a_failed_level_retries(self):
        self.queue.enqueue([self.first])
        self.queue.enqueue([self.first])
        self.assertEqual(len(self.data()['jobs']), 1)
        ids = self.queue.claim([self.first['board']])
        self.queue.advance(ids, 'checking', 'Screen check')
        self.queue.fail(ids, 'Play button was not opened')
        self.assertEqual(self.latest(1)['step'], 'Screen check')
        self.assertEqual(self.latest(1)['state'], 'failed')
        self.queue.enqueue([self.first])
        self.queue.claim([self.first['board']])
        self.assertEqual(self.latest(1)['attempt'], 2)
        self.assertEqual(self.latest(1)['error'], '')

    def test_another_level_can_queue_and_failure_does_not_erase_it(self):
        self.queue.enqueue([self.first])
        ids = self.queue.claim([self.first['board']])
        self.queue.enqueue([self.second])
        self.queue.fail(ids, 'Failed first campaign')
        self.assertEqual(self.latest(1)['state'], 'failed')
        self.assertEqual(self.latest(2)['state'], 'queued')
        self.queue.claim([self.first['board'], self.second['board']])
        self.assertEqual(self.latest(2)['state'], 'building')

    def test_campaign_change_carries_existing_requests_into_next_build(self):
        self.queue.enqueue([self.first])
        self.queue.claim([self.first['board']])
        self.queue.enqueue([self.second])
        ids = self.queue.claim([self.first['board'], self.second['board']])
        self.assertEqual(len(ids), 2)
        self.assertEqual(self.latest(1)['attempt'], 1)
        self.queue.published([self.first['board'], self.second['board']])
        self.assertEqual(self.latest(1)['state'], 'published')
        self.assertEqual(self.latest(2)['state'], 'published')

    def test_new_board_waits_while_old_exact_board_is_published(self):
        self.queue.enqueue([self.first])
        self.queue.claim([self.first['board']])
        newer = dict(number=1, board='03' * 720)
        self.queue.enqueue([newer])
        self.queue.published([self.first['board']])
        self.assertEqual(self.latest(1)['state'], 'queued')
        self.assertEqual(self.latest(1)['board'], newer['board'])

    def test_verified_campaign_resolves_an_earlier_failure_for_the_same_board(self):
        self.queue.enqueue([self.first])
        ids = self.queue.claim([self.first['board']])
        self.queue.fail(ids, 'First screen check failed')
        self.queue.enqueue([self.second])
        self.queue.claim([self.first['board'], self.second['board']])
        self.queue.published([self.first['board'], self.second['board']])
        self.assertEqual(self.latest(1)['state'], 'published')

    def test_out_of_order_approval_waits_for_a_contiguous_campaign(self):
        self.queue.enqueue([self.second], available=1)
        self.assertEqual(self.latest(2)['state'], 'waiting')
        self.assertEqual(self.queue.claim([self.first['board']]), [])
        self.assertEqual(len(self.queue.claim([self.first['board'], self.second['board']])), 1)

    def test_reconciliation_uses_worker_lock_and_clears_only_orphaned_work(self):
        self.queue.enqueue([self.first])
        self.queue.claim([self.first['board']])
        with (self.queue.state / 'publish.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.queue.reconcile()
            self.assertEqual(self.latest(1)['state'], 'building')
        self.queue.enqueue([self.second])
        self.queue.reconcile()
        self.assertEqual(self.latest(1)['state'], 'failed')
        self.assertEqual(self.latest(2)['state'], 'queued')
        self.assertNotIn('Updating', (self.queue.state / 'publish-status').read_text())


if __name__ == '__main__':
    unittest.main()
