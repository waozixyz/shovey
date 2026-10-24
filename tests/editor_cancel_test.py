"""Cancelling an approval: a live level goes back to its published record, a
level never published leaves the campaign and later approvals wait again."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('editor_actions', ROOT / 'scripts/editor_actions.py')
actions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(actions)


def level(number, fill):
    board = f'{fill:02x}' * 720
    return actions.record(number, board, '0'), board


class CancelApproval(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        actions.ROOT, actions.DRAFTS = root, root / 'backup/editor-drafts'
        actions.DRAFTS.mkdir(parents=True)
        (root / 'levels').mkdir()
        self.live2, self.live2_board = level(2, 0x20)
        published = dict(edition='classic', levels=[level(1, 0x10)[0], self.live2], pending={})
        self.approved_path = root / 'levels/approved.json'
        self.approved_path.write_text(json.dumps(published))
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        subprocess.run(['git', '-C', str(root), 'add', 'levels/approved.json'], check=True)
        subprocess.run(['git', '-C', str(root), '-c', 'user.name=test', '-c', 'user.email=test@example.com',
                        'commit', '-qm', 'published'], check=True)
        # A new version of level 2 and two new levels wait for publishing.
        new2, self.new2_board = level(2, 0x22)
        levels = [level(1, 0x10)[0], new2, level(3, 0x30)[0], level(4, 0x40)[0]]
        self.approved_path.write_text(json.dumps(dict(edition='classic', levels=levels, pending={})))
        for number, board in ((1, '10' * 720), (2, self.live2_board)):
            (actions.DRAFTS / f'{number:03}.published').write_text(board)
        for number, fill in ((1, 0x10), (2, 0x22), (3, 0x30), (4, 0x40)):
            (actions.DRAFTS / f'{number:03}.approved').write_text(f'{fill:02x}' * 720)

    def tearDown(self):
        self.temporary.cleanup()

    def campaign(self):
        data = json.loads(self.approved_path.read_text())
        return [item['number'] for item in data['levels']], {int(n): v for n, v in data['pending'].items()}, data

    def test_a_live_level_goes_back_to_its_published_record(self):
        actions.cancel(2)
        numbers, pending, data = self.campaign()
        self.assertEqual(numbers, [1, 2, 3, 4])
        self.assertEqual(data['levels'][1], self.live2)
        self.assertEqual((actions.DRAFTS / '002.approved').read_text(), self.live2_board)

    def test_a_new_level_leaves_and_later_approvals_wait(self):
        actions.cancel(3)
        numbers, pending, data = self.campaign()
        self.assertEqual(numbers, [1, 2])
        self.assertEqual(sorted(pending), [4])
        self.assertFalse((actions.DRAFTS / '003.approved').exists())
        self.assertTrue((actions.DRAFTS / '004.approved').exists())


if __name__ == '__main__':
    unittest.main()
