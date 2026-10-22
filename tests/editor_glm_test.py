"""GLM variations preserve authored puzzles and win in the real Classic engine."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('editor_actions', ROOT / 'scripts/editor_actions.py')
actions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(actions)


def at(x, y):
    return 11 - y + x * 12


def board():
    cells, tiles = [0] * 240, [0] * 240
    for x in range(20):
        for y in range(12):
            if x in (0, 19) or y in (0, 11):
                tiles[at(x, y)] = 12
    cells[at(2, 3)], cells[at(4, 3)], cells[at(7, 2)] = 10, 1, 7
    tiles[at(6, 3)] = 4
    return ''.join(f'{kind:02x}' for kind in cells + tiles + [0] * 240)


def variation(x=3, y=3):
    return dict(edits=[dict(layer='cells', x=4, y=3, **{'from': 1, 'to': 0}),
                       dict(layer='cells', x=x, y=y, **{'from': 0, 'to': 1})],
                solution='333332', explanation='Move the red ball closer so its first push starts earlier.')


class Variations(unittest.TestCase):
    def test_update_retries_approved_campaign_without_a_draft_or_approval(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            drafts = Path(directory)
            (drafts / 'publish-status').write_text('The previous update failed')
            with patch.object(actions, 'DRAFTS', drafts), patch.object(actions.subprocess, 'Popen') as spawn:
                actions.update()
            self.assertIn('--force', spawn.call_args.args[0])
            self.assertIn('previously approved', (drafts / 'publish-status').read_text())
            self.assertEqual(sorted(path.name for path in drafts.iterdir()), ['publish-status'])

    def test_preserves_inventory_and_landscape_coordinates(self):
        candidate = actions.apply_proposal(board(), variation())
        self.assertEqual(candidate[at(3, 3) * 2:at(3, 3) * 2 + 2], '01')
        self.assertTrue(actions.verify_route(1, candidate, '333332'))

    def test_rejects_removing_or_recoloring_a_goal_piece(self):
        for change in (dict(edits=variation()['edits'][:1]),
                       dict(edits=[dict(layer='tiles', x=6, y=3, **{'from': 4, 'to': 5})])):
            with self.subTest(change=change), self.assertRaises(ValueError):
                actions.apply_proposal(board(), change)

    def test_rejects_moving_start_and_editing_border(self):
        for edits in ([dict(layer='cells', x=2, y=3, **{'from': 10, 'to': 0}),
                       dict(layer='cells', x=3, y=3, **{'from': 0, 'to': 10})],
                      [dict(layer='tiles', x=0, y=3, **{'from': 12, 'to': 0})]):
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                actions.apply_proposal(board(), dict(edits=edits))

    def test_rejects_invented_grids_and_decorative_changes(self):
        for proposal in (dict(cells=[], tiles=[], decorations=[]),
                         dict(edits=[dict(layer='decorations', x=3, y=3, **{'from': 0, 'to': 57})])):
            with self.subTest(proposal=proposal), self.assertRaises(ValueError):
                actions.apply_proposal(board(), proposal)

    def test_solver_checks_model_claim_and_finds_a_real_route(self):
        candidate = actions.apply_proposal(board(), variation())
        self.assertFalse(actions.verify_route(1, candidate, '2'))
        route = actions.prove_proposal(1, candidate, '2')
        self.assertTrue(actions.verify_route(1, candidate, route))

    def test_unsolvable_corner_is_not_published_as_a_result(self):
        candidate = actions.apply_proposal(board(), variation(1, 1))
        with self.assertRaises(ValueError):
            actions.prove_proposal(1, candidate, '333332')

    def test_retry_uses_original_and_feedback_before_exposing_a_result(self):
        responses = [variation(1, 1), variation()]
        requests = []

        def reply(request, **kwargs):
            requests.append(json.loads(request.data))
            self.assertFalse((actions.DRAFTS / '001.glm-result').exists())
            return io.BytesIO(json.dumps(dict(choices=[dict(message=dict(content=json.dumps(responses.pop(0))))])).encode())

        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            drafts = Path(directory)
            (drafts / '001.glm-base').write_text(board())
            with patch.object(actions, 'DRAFTS', drafts), \
                    patch.object(actions, 'existing_route', return_value='333332'), \
                    patch.object(actions, 'glm_settings', return_value=('https://example.invalid', 'test', 'glm-test')), \
                    patch.object(actions.urllib.request, 'urlopen', side_effect=reply):
                actions.modify(1)
            candidate, route = (drafts / '001.glm-proof').read_text().splitlines()
            self.assertEqual((drafts / '001.glm-result').read_text(), candidate)
            self.assertTrue(actions.verify_route(1, candidate, route))
            self.assertEqual((drafts / '001.glm-base').read_text(), board())
        self.assertEqual(len(requests), 2)
        self.assertIn('rejected_proposal', requests[1]['messages'][-1]['content'])
        self.assertEqual(json.loads(requests[0]['messages'][1]['content'])['existing_solution'], '333332')


if __name__ == '__main__':
    unittest.main()
