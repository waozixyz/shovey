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
release_spec = importlib.util.spec_from_file_location('publish_approved', ROOT / 'scripts/publish-approved.py')
release = importlib.util.module_from_spec(release_spec)
release_spec.loader.exec_module(release)


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
    def test_publication_status_identifies_a_gap_in_the_campaign(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            root = Path(directory)
            (root / 'levels').mkdir()
            path = root / 'levels/approved.json'
            with patch.object(release, 'ROOT', root):
                path.write_text(json.dumps(dict(levels=[{}] * 20, pending={'22': {}})))
                self.assertEqual(release.publication_status(), 'Level 22 queued. Approve 21.')
                path.write_text(json.dumps(dict(levels=[{}] * 23, pending={})))
                self.assertEqual(release.publication_status(), 'Published')

    def test_approving_a_gap_promotes_waiting_levels_in_order(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            root = Path(directory)
            drafts = root / 'drafts'
            drafts.mkdir()
            (root / 'levels').mkdir()
            (root / 'backup').mkdir()
            path = root / 'levels/approved.json'
            records = [actions.record(n, board(), '333332') for n in range(1, 4)]
            path.write_text(json.dumps(dict(levels=records[:1], pending={'3': records[2]})))
            (drafts / '002.approval-request').write_text(board() + '\n333332')
            with patch.object(actions, 'ROOT', root), patch.object(actions, 'DRAFTS', drafts):
                actions.approve(2)
            campaign = json.loads(path.read_text())
            self.assertEqual(campaign['levels'], records)
            self.assertEqual(campaign['pending'], {})

    def test_each_moss_wall_button_pair_is_solved_in_the_shipped_engine(self):
        for wall, button in [(14, 13), *zip(range(127, 131), range(131, 135))]:
            with self.subTest(wall=wall, button=button):
                cells, tiles = [0] * 240, [12] * 240
                for position in (13, 14, 15, 16, 17, 25, 26, 27, 28):
                    tiles[position] = 0
                cells[13], cells[14], cells[15], cells[17] = 10, 9, button, 7
                tiles[16] = wall
                encoded = ''.join(f'{kind:02x}' for kind in cells + tiles + [0] * 240)
                self.assertTrue(actions.verify_route(1, encoded, '232212'))
                route = actions.prove_proposal(1, encoded)
                self.assertTrue(actions.verify_route(1, encoded, route))
    def test_approve_replaces_the_snapshot_and_detaches_publication(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            root = Path(directory)
            drafts = root / 'drafts'
            drafts.mkdir()
            (root / 'levels').mkdir()
            (root / 'backup').mkdir()
            (root / 'backup/editor-publish.json').write_text('{}')
            old = actions.record(1, board(), '333332')
            other = actions.record(2, board(), '333332')
            path = root / 'levels/approved.json'
            path.write_text(json.dumps(dict(levels=[old, other])))
            candidate = actions.apply_proposal(board(), variation())
            (drafts / '001.approval-request').write_text(candidate + '\n333332')
            (drafts / '001.approved').write_text(candidate)
            with patch.object(actions, 'ROOT', root), patch.object(actions, 'DRAFTS', drafts), \
                    patch.object(actions.subprocess, 'Popen') as spawn:
                actions.approve(1)
            self.assertEqual(json.loads(path.read_text())['levels'],
                             [actions.record(1, candidate, '333332'), other])
            spawn.assert_called_once()
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])
            self.assertEqual(spawn.call_args.kwargs['stdin'], actions.subprocess.DEVNULL)
            spawn.return_value.wait.assert_not_called()

    def test_update_retries_approved_campaign_without_a_draft_or_approval(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            drafts = Path(directory)
            (drafts / 'publish-status').write_text('The previous update failed')
            with patch.object(actions, 'DRAFTS', drafts), patch.object(actions.subprocess, 'Popen') as spawn:
                actions.update()
            self.assertIn('--force', spawn.call_args.args[0])
            self.assertTrue((drafts / 'publish-status').read_text())
            self.assertEqual(sorted(path.name for path in drafts.iterdir()), ['publish-status'])

    def test_preserves_inventory_and_landscape_coordinates(self):
        candidate = actions.apply_proposal(board(), variation())
        self.assertEqual(candidate[at(3, 3) * 2:at(3, 3) * 2 + 2], '01')
        self.assertTrue(actions.verify_route(1, candidate, '333332'))

    def test_saved_win_remains_valid_with_later_recorded_input(self):
        candidate = actions.apply_proposal(board(), variation())
        self.assertTrue(actions.verify_route(1, candidate, '333332tt01'))
        self.assertFalse(actions.verify_route(1, candidate, '333332x'))
        self.assertFalse(actions.verify_route(1, candidate, '2'))

    def test_variation_choices_are_changes_of_the_source_and_engine_proven(self):
        choices = actions.proven_variations(1, board(), '333332')
        self.assertTrue(choices)
        for choice in choices:
            candidate = actions.apply_proposal(board(), choice)
            self.assertNotEqual(candidate, board())
            self.assertTrue(actions.verify_route(1, candidate, choice['solution']))

    def test_glm_can_select_a_proven_variation_without_inventing_a_route(self):
        response = dict(choices=[dict(message=dict(content=json.dumps(dict(choice=0, explanation='A longer push approach.'))))])
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            drafts = Path(directory)
            (drafts / '001.glm-base').write_text(board())
            with patch.object(actions, 'DRAFTS', drafts), \
                    patch.object(actions, 'existing_route', return_value='333332'), \
                    patch.object(actions, 'glm_settings', return_value=('https://example.invalid', 'test', 'glm-test')), \
                    patch.object(actions.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())):
                actions.modify_once(1, choices=actions.proven_variations(1, board(), '333332'))
            candidate, route = (drafts / '001.glm-proof').read_text().splitlines()
            self.assertEqual((drafts / '001.glm-result').read_text(), candidate)
            self.assertTrue(actions.verify_route(1, candidate, route))

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
        responses = [variation(1, 1), variation(4, 4)]
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

    def test_design_request_is_not_restricted_to_preset_choices(self):
        response = dict(choices=[dict(message=dict(content=json.dumps(variation(4, 4))))])
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            drafts = Path(directory)
            (drafts / '001.glm-base').write_text(board())
            with patch.object(actions, 'DRAFTS', drafts), \
                    patch.object(actions, 'existing_route', return_value='333332'), \
                    patch.object(actions, 'glm_settings', return_value=('https://example.invalid', 'test', 'glm-test')), \
                    patch.object(actions.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as request:
                actions.modify(1)
            payload = json.loads(request.call_args.args[0].data)
            self.assertEqual(json.loads(payload['messages'][1]['content'])['verified_variations'], [])
            candidate, route = (drafts / '001.glm-proof').read_text().splitlines()
            self.assertFalse(actions.verify_route(1, candidate, '333332'))
            self.assertTrue(actions.verify_route(1, candidate, route))
            self.assertEqual((drafts / '001.glm-state').read_text(), 'ready')

    def test_single_nudge_with_unchanged_route_is_rejected(self):
        response = dict(choices=[dict(message=dict(content=json.dumps(variation())))])
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            drafts = Path(directory)
            (drafts / '001.glm-base').write_text(board())
            with patch.object(actions, 'DRAFTS', drafts), \
                    patch.object(actions, 'existing_route', return_value='333332'), \
                    patch.object(actions, 'glm_settings', return_value=('https://example.invalid', 'test', 'glm-test')), \
                    patch.object(actions.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())):
                with self.assertRaisesRegex(ValueError, 'Only one piece was nudged'):
                    actions.modify_once(1)
            self.assertFalse((drafts / '001.glm-result').exists())

    def test_provider_errors_have_specific_short_messages(self):
        for code, word in ((401, 'key'), (429, 'limit'), (503, '503')):
            error = actions.urllib.error.HTTPError('https://example.invalid', code, '', {}, None)
            self.assertIn(word, actions.failure_message(error))


if __name__ == '__main__':
    unittest.main()
