"""Campaign generation, editor approval and publication reject touching stars."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from editor_actions import record
from editor_server import live_campaign_snapshot

spec = importlib.util.spec_from_file_location('levels_tool', ROOT / 'tools/levels/levels.py')
levels_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(levels_tool)


class StarStarts(unittest.TestCase):
    def setUp(self):
        self.campaign = json.loads((ROOT / 'levels/approved.json').read_text())
        self.config = json.loads((ROOT / 'levels/publication.json').read_text())

    def test_all_authored_starting_boards_keep_stars_apart(self):
        documents = [self.campaign]
        for name in ('classic', 'secret'):
            path = ROOT / f'levels/{name}.json'
            if path.exists():
                documents.append(json.loads(path.read_text()))
        for document in documents:
            for level in document['levels'] + document.get('hidden_levels', []):
                board = levels_tool.cells(level['cells'])
                stars = [at for at, kind in enumerate(board) if kind == 19]
                for first in stars:
                    for second in stars:
                        if first < second:
                            self.assertNotEqual(abs(first % 12 - second % 12) + abs(first // 12 - second // 12), 1,
                                                f'Level {level.get("number", level.get("name"))}: stars start touching')

    def test_bad_start_cannot_be_generated_approved_or_published(self):
        for second in (69, 80):
            with self.subTest(second=second):
                level = copy.deepcopy(self.campaign['levels'][74])
                board = levels_tool.cells(level['cells'])
                board = [0 if kind == 19 else kind for kind in board]
                board[68] = board[second] = 19
                level['cells'] = [''.join(f'{kind:02x}' for kind in board[at:at + 12]) for at in range(0, 240, 12)]
                with self.assertRaisesRegex(ValueError, 'touching star blocks'):
                    levels_tool.classic_functions([level])
                data = ''.join(level['cells'] + level['tiles'] + level['decorations'])
                with self.assertRaisesRegex(ValueError, 'touching star blocks'):
                    record(75, data, level['solution'])
                document = copy.deepcopy(self.campaign)
                document['levels'][74] = level
                answer = dict(publication=dict(id=self.config['id'], format=self.config['format'], visibility='public',
                                               author=dict(public_id=self.config['author']), levels=len(document['levels'])),
                              document=document)
                with self.assertRaisesRegex(ValueError, 'touching star blocks'):
                    live_campaign_snapshot(self.config, answer, lambda *args: True)

    def test_board_edges_do_not_wrap_into_touching_stars(self):
        level = copy.deepcopy(self.campaign['levels'][74])
        board = [0 if kind == 19 else kind for kind in levels_tool.cells(level['cells'])]
        board[59] = board[60] = 19
        level['cells'] = [''.join(f'{kind:02x}' for kind in board[at:at + 12]) for at in range(0, 240, 12)]
        levels_tool.classic_functions([level])


if __name__ == '__main__':
    unittest.main()
