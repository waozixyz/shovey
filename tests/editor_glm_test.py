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


def blocked_board():
    cells = [int(board()[i:i + 2], 16) for i in range(0, 1440, 2)]
    for x, y in ((1, 3), (2, 2), (2, 4), (3, 3)):
        cells[240 + at(x, y)] = 12
    return ''.join(f'{kind:02x}' for kind in cells)


def repair():
    return dict(edits=[dict(layer='tiles', x=3, y=3, **{'from': 12, 'to': 0})],
                solution='333332', explanation='Open one wall so the player can reach the ball.')


PLAN = dict(win_route_analysis='The red ball needs two pushes into the reusable red pit.',
            complexity_changes=['Stage a second ball before clearing the exit.'],
            theme='Slate workshop with bluebells along the edges.',
            previous_level_difference='Use a compact workshop instead of the previous courtyard.')


class Variations(unittest.TestCase):
    def test_glm53_uses_supported_reasoning_and_rejects_truncated_json(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory, \
                patch.object(actions, 'DRAFTS', Path(directory)), \
                patch.object(actions, 'glm_settings', return_value=('https://example.invalid', 'test', 'glm-5.3')):
            response = dict(choices=[dict(finish_reason='stop', message=dict(content='{"ok":true}'))])
            with patch.object(actions.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as provider:
                self.assertEqual(actions.glm_json('JSON only', {}, 100)[0], dict(ok=True))
            payload = json.loads(provider.call_args.args[0].data)
            self.assertEqual(payload['thinking'], dict(type='enabled'))
            self.assertEqual(payload['reasoning_effort'], 'low')
            self.assertGreater(payload['max_tokens'], 100)
            response['choices'][0].update(finish_reason='length', message=dict(content=''))
            with patch.object(actions.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())):
                with self.assertRaisesRegex(ValueError, 'response budget'):
                    actions.glm_json('JSON only', {}, 100)

    def test_guided_redesign_builds_proves_shapes_then_decorates(self):
        strategic = dict(edits=[dict(layer='cells', x=5, y=4, **{'from': 0, 'to': 1})],
                         explanation='A second ball shares the pit and working lane.')
        structure = dict(edits=[dict(layer='tiles', x=x, y=y, **{'from': 0, 'to': 12})
                               for x, y in [(x, 7) for x in range(2, 11)] + [(x, 8) for x in range(2, 5)]],
                         explanation='Close unused space into a compact workshop.')
        scenery = dict(edits=[dict(layer='decorations', x=x, y=9, **{'from': 0, 'to': 137}) for x in (3, 5, 7)],
                       explanation='Bluebells along the garden edge.')
        design = dict(target=dict(goals=1, pushes=2, mechanics=0, moves=6, tier=0, solution='333332'),
                      plan=PLAN, previous_board=None)
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory, \
                patch.object(actions, 'DRAFTS', Path(directory)), \
                patch.object(actions, 'glm_json', side_effect=[(p, 'glm-test') for p in (strategic, structure, scenery)]) as provider:
            proposal, _ = actions.guided_redesign(1, board(), design, 'Design a completely NEW puzzle.', {})
            candidate = actions.apply_proposal(board(), proposal, mode='redesign')
            self.assertTrue(actions.verify_route(1, candidate, proposal['solution']))
            self.assertEqual([call.args[1]['step'] for call in provider.call_args_list],
                             ['strategy', 'structure', 'decoration'])
            self.assertEqual(provider.call_args_list[1].args[1]['current_route_analysis']['goals'], 2)
            self.assertIn('repeats the source', provider.call_args_list[1].args[1]['remaining_quality_issue'])
            self.assertEqual(len(design['work']['steps']), 3)
            self.assertFalse((Path(directory) / '001.glm-result').exists())

    def test_guided_decoration_preserves_trail_floor_rules(self):
        import time
        values = [int(board()[i:i + 2], 16) for i in range(0, 1440, 2)]
        values[at(2, 4)] = 11
        source = ''.join(f'{kind:02x}' for kind in values)
        design = dict(work=dict(board=source, route='333332', deadline=time.monotonic() + 60,
                               steps=[dict(stage='strategy'), dict(stage='structure')]))
        proposal = dict(edits=[dict(layer='tiles', x=3, y=4, **{'from': 0, 'to': 99})])
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory, \
                patch.object(actions, 'DRAFTS', Path(directory)), \
                patch.object(actions, 'glm_json', return_value=(proposal, 'glm-test')):
            with self.assertRaisesRegex(ValueError, 'trail puzzle'):
                actions.guided_redesign(1, source, design, '', {})
            self.assertEqual(design['work']['board'], source)

    def test_redesign_plan_uses_verified_source_and_previous_level(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            root = Path(directory)
            drafts = root / 'drafts'
            drafts.mkdir()
            (root / 'levels').mkdir()
            (root / 'levels/classic.json').write_text(json.dumps(dict(levels=[
                actions.record(1, board(), '333332'), actions.record(2, board(), '333332')])))
            with patch.object(actions, 'ROOT', root), patch.object(actions, 'DRAFTS', drafts):
                target = dict(goals=1, pushes=2, moves=6, mechanics=0, solution='333332', tier=0)
                context = actions.redesign_context(2, board(), target)
                self.assertEqual(context['previous_level']['level'], 1)
                self.assertEqual(context['previous_level']['metrics']['pushes'], 2)
                self.assertEqual(context['source']['events'][0]['destination'], [5, 3])
                with patch.object(actions, 'glm_json', return_value=(PLAN, 'glm-test')) as request:
                    plan = actions.plan_redesign(2, context)
                self.assertEqual(plan, PLAN)
                self.assertEqual(request.call_args.args[1]['source_route_analysis'], context['source'])
                self.assertEqual(request.call_args.args[1]['previous_level']['level'], 1)
                self.assertEqual(json.loads((drafts / '002.glm-plan.json').read_text()), PLAN)
                self.assertFalse((drafts / '002.glm-result').exists())
                with patch.object(actions, 'glm_json', return_value=({}, 'glm-test')):
                    with self.assertRaisesRegex(ValueError, 'complete redesign plan'):
                        actions.plan_redesign(2, context)

    def test_route_analysis_records_real_pushes_in_landscape_coordinates(self):
        replay = actions.analyze_route(1, board(), '333332')
        self.assertEqual((replay['goals'], replay['pushes']), (1, 2))
        pushes = [event for event in replay['events'] if event['piece']]
        self.assertEqual([event['destination'] for event in pushes], [[5, 3], [6, 3]])
        self.assertEqual(pushes[0]['piece_id'], pushes[1]['piece_id'])
        self.assertEqual(pushes[-1]['target'], 4)
        self.assertEqual(pushes[-1]['piece_name'], 'red ball')
        self.assertEqual(pushes[-1]['target_name'], 'red pit')
        self.assertEqual(pushes[-1]['remaining'], 0)
        with self.assertRaises(ValueError):
            actions.analyze_route(1, board(), '3')

    def test_push_loops_do_not_inflate_redesign_difficulty(self):
        route = '33' + '2330' + '1' + '0112' + '33332'
        observed = actions.analyze_route(1, board(), route)
        self.assertEqual(observed['pushes'], 4)
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory, \
                patch.object(actions, 'DRAFTS', Path(directory)):
            measured = actions.difficulty(1, board(), route)
        self.assertEqual(measured['pushes'], 2)

    def test_redesign_checks_structure_complexity_and_scenery(self):
        values = [int(board()[i:i + 2], 16) for i in range(0, 1440, 2)]
        for x in range(2, 11): values[240 + at(x, 7)] = 95
        for x in (3, 5, 7): values[480 + at(x, 8)] = 137
        changed = ''.join(f'{kind:02x}' for kind in values)
        metrics = dict(goals=1, pushes=2, mechanics=0)
        context = dict(target=metrics, previous_board=None)
        with self.assertRaisesRegex(ValueError, 'Too easy'):
            actions.check_redesign(board(), changed, context, metrics)
        with self.assertRaisesRegex(ValueError, 'repeats the source'):
            actions.check_redesign(board(), board(), context, dict(metrics, goals=2))
        # Material and decoration edits do not disguise a repeated puzzle.
        self.assertEqual(actions.redesign_difference(board(), changed), 9)
        for x in range(2, 11): values[240 + at(x, 8)] = 12; values[480 + at(x, 8)] = 0
        structured = ''.join(f'{kind:02x}' for kind in values)
        with self.assertRaisesRegex(ValueError, 'scenery'):
            actions.check_redesign(board(), structured, context, dict(metrics, goals=2))
        for x in (3, 5, 7): values[480 + at(x, 9)] = 137
        unique = ''.join(f'{kind:02x}' for kind in values)
        actions.check_redesign(board(), unique, context, dict(metrics, goals=2))
        with self.assertRaisesRegex(ValueError, 'previous level'):
            actions.check_redesign(board(), unique, dict(context, previous_board=unique), dict(metrics, goals=2))

    def test_long_walks_and_slow_search_do_not_replace_pushes(self):
        target = dict(tier=1, moves=50, pushes=12, goals=4)
        self.assertIn('pushes', actions.too_easy(target, dict(tier=2, moves=200, pushes=2, goals=4)))
        self.assertIn('goals', actions.too_easy(target, dict(tier=2, moves=200, pushes=12, goals=1)))
        self.assertEqual(actions.too_easy(target, dict(tier=1, moves=55, pushes=14, goals=4)), '')
        self.assertEqual(actions.too_easy(target, dict(tier=0, moves=40, pushes=14, goals=4)), '')
        self.assertIn('mechanics', actions.too_easy(dict(target, mechanics=4), dict(tier=2, moves=100, pushes=14, goals=4, mechanics=1)))

    def test_deadlock_rules_preserve_existing_winning_routes(self):
        generated = ROOT / 'build/solver/classic/c'
        output = ROOT / 'build/solver-state-test'
        output.mkdir(exist_ok=True)
        toolchain = Path(actions.subprocess.check_output(['ziran', 'pkg', 'path', 'ziran'], cwd=ROOT, text=True).strip())
        binary = output / 'state-test'
        command = ['cc', '-std=c11', '-O2', '-I' + str(toolchain / 'include'), '-iquote', str(generated),
                   str(ROOT / 'tests/solver_state_test.c')]
        command += [str(path) for path in generated.glob('*.c')]
        command += [str(ROOT / 'build/ziran/libziran.a'), '-lm', '-lpthread', '-o', str(binary)]
        actions.subprocess.run(command, check=True, capture_output=True)
        actions.subprocess.run([str(binary)], check=True, capture_output=True)
        checked = 0
        for level in json.loads((ROOT / 'levels/classic.json').read_text())['levels']:
            route = level.get('solution', '')
            candidate = actions.board_hex(level)
            if not actions.verify_route(level['number'], candidate, route): continue
            run = actions.subprocess.run([str(binary), candidate, route], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, f'Level {level["number"]}: {run.stderr}')
            checked += 1
        self.assertGreater(checked, 100)

    def test_spare_crates_do_not_distract_from_the_solution(self):
        generated = ROOT / 'build/solver/classic/c'
        output = ROOT / 'build/solver-focus-test'
        output.mkdir(exist_ok=True)
        toolchain = Path(actions.subprocess.check_output(['ziran', 'pkg', 'path', 'ziran'], cwd=ROOT, text=True).strip())
        binary = output / 'focus-test'
        command = ['cc', '-std=c11', '-O2', '-I' + str(toolchain / 'include'), '-iquote', str(generated),
                   str(ROOT / 'tests/solver_focus_test.c')]
        command += [str(path) for path in generated.glob('*.c')]
        command += [str(ROOT / 'build/ziran/libziran.a'), '-lm', '-lpthread', '-o', str(binary)]
        actions.subprocess.run(command, check=True, capture_output=True)
        actions.subprocess.run([str(binary)], check=True, capture_output=True)
        candidate = json.loads((ROOT / 'tests/fixtures/spare-crates.json').read_text())['board']
        result = actions.subprocess.run([str(actions.SOLVER), 'solve', '--seconds', '15',
            '--only', 'greedy', '--max-mb', '128', candidate], capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(actions.verify_route(1, candidate, result.stdout.strip()))

    def test_prettify_preserves_buttons_moss_and_blocking_decoration(self):
        def edit(layer, x, y, before, after):
            return dict(layer=layer, x=x, y=y, **{'from': before, 'to': after})
        proposal = dict(edits=[edit('decorations', 3, 4, 0, 57), edit('tiles', 3, 4, 0, 103)])
        candidate = actions.apply_proposal(board(), proposal, mode='prettify')
        self.assertTrue(actions.verify_route(1, candidate, '333332'))
        for layer, before, after in (('cells', 0, 13), ('tiles', 0, 14), ('tiles', 0, 127),
                                    ('tiles', 0, 65), ('decorations', 0, 84), ('decorations', 0, 106)):
            with self.subTest(layer=layer, after=after), self.assertRaises(ValueError):
                actions.apply_proposal(board(), dict(edits=[edit(layer, 3, 4, before, after)]), mode='prettify')
        for wall in (14, 127, 128, 129, 130):
            values = [int(board()[i:i + 2], 16) for i in range(0, 1440, 2)]
            values[240 + at(3, 4)] = wall
            original = ''.join(f'{kind:02x}' for kind in values)
            with self.subTest(wall=wall), self.assertRaises(ValueError):
                actions.apply_proposal(original, dict(edits=[edit('tiles', 3, 4, wall, 12)]), mode='prettify')

    def test_prettify_does_not_search_an_unfinished_puzzle(self):
        proposal = dict(edits=[dict(layer='decorations', x=3, y=4, **{'from': 0, 'to': 57})],
                        explanation='Flowers away from the blocked route.')
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            drafts = Path(directory)
            (drafts / '001.glm-base').write_text(blocked_board())
            response = dict(choices=[dict(message=dict(content=json.dumps(proposal)))])
            with patch.object(actions, 'DRAFTS', drafts), patch.object(actions, 'existing_route', return_value=''), \
                    patch.object(actions, 'prove_proposal', side_effect=AssertionError('Scenery needs no new solution')), \
                    patch.object(actions, 'glm_settings', return_value=('https://example.invalid', 'test', 'glm-test')), \
                    patch.object(actions.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())):
                actions.modify(1, mode='prettify')
            self.assertTrue((drafts / '001.glm-result').exists())
            self.assertFalse((drafts / '001.glm-proof').exists())

    def test_glm_modes_use_distinct_prompts_and_engine_checked_results(self):
        prettify = dict(edits=[dict(layer='decorations', x=3, y=4, **{'from': 0, 'to': 57})],
                        solution='333332', explanation='Flowers by the path.')
        values = [int(board()[i:i + 2], 16) for i in range(0, 1440, 2)]
        values[at(2, 3)], values[at(2, 4)] = 0, 10
        values[at(7, 2)], values[at(8, 2)] = 0, 7
        values[at(5, 4)] = 1
        for x in range(2, 11):
            values[240 + at(x, 7)] = 12
            values[240 + at(x, 8)] = 12
        for x in (3, 5, 7): values[480 + at(x, 9)] = 137
        new_board = ''.join(f'{kind:02x}' for kind in values)
        route = actions.prove_proposal(1, new_board)
        redesign = {name: [[values[layer * 240 + at(x, y)] for x in range(20)] for y in range(12)]
                    for layer, name in enumerate(actions.LAYERS)}
        redesign.update(solution=route, explanation='A new room and approach.')
        for mode, proposal, phrase in (('prettify', prettify, 'NEVER add, remove, recolor or move any mossy'),
                                       ('redesign', redesign, 'completely NEW')):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
                drafts = Path(directory)
                (drafts / '001.glm-base').write_text(board())
                response = dict(choices=[dict(message=dict(content=json.dumps(proposal)))])
                with patch.object(actions, 'DRAFTS', drafts), patch.object(actions, 'existing_route', return_value='333332'), \
                        patch.object(actions, 'plan_redesign', return_value=PLAN), \
                        patch.object(actions, 'glm_settings', return_value=('https://example.invalid', 'test', 'glm-test')), \
                        patch.object(actions.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as request:
                    actions.modify(1, mode=mode)
                result, proof = (drafts / '001.glm-proof').read_text().splitlines()
                self.assertTrue(actions.verify_route(1, result, proof))
                if mode == 'prettify': self.assertEqual(proof, '333332')
                else: self.assertEqual(result, new_board)
                self.assertEqual(json.loads((drafts / '001.glm-details.json').read_text())['mode'], mode)
                self.assertIn(phrase, json.loads(request.call_args.args[0].data)['messages'][0]['content'])
                if mode == 'redesign':
                    context = json.loads(json.loads(request.call_args.args[0].data)['messages'][1]['content'])
                    self.assertEqual(context['redesign_plan'], PLAN)
                    self.assertEqual(context['source_route_analysis']['pushes'], 2)

    def test_redesigns_easier_than_the_source_are_rejected(self):
        values = [int(board()[i:i + 2], 16) for i in range(0, 1440, 2)]
        values[at(2, 3)], values[at(4, 3)], values[at(5, 3)] = 0, 10, 1
        values[at(7, 2)], values[at(6, 2)] = 0, 7
        for x in range(2, 11): values[240 + at(x, 7)] = 12
        easy = ''.join(f'{kind:02x}' for kind in values)
        proposal = {name: [[values[layer * 240 + at(x, y)] for x in range(20)] for y in range(12)]
                    for layer, name in enumerate(actions.LAYERS)}
        proposal.update(solution=actions.prove_proposal(1, easy), explanation='One push and home.')
        response = dict(choices=[dict(message=dict(content=json.dumps(proposal)))])
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            drafts = Path(directory)
            (drafts / '001.glm-base').write_text(board())
            with patch.object(actions, 'DRAFTS', drafts), patch.object(actions, 'existing_route', return_value='333332'), \
                    patch.object(actions, 'plan_redesign', return_value=PLAN), \
                    patch.object(actions, 'glm_settings', return_value=('https://example.invalid', 'test', 'glm-test')), \
                    patch.object(actions.urllib.request, 'urlopen',
                                 side_effect=lambda *_, **__: io.BytesIO(json.dumps(response).encode())) as request:
                with self.assertRaisesRegex(ValueError, 'as hard as the original'):
                    actions.modify(1, mode='redesign')
            self.assertFalse((drafts / '001.glm-result').exists())
            self.assertIn('difficulty_target', json.loads(request.call_args.args[0].data)['messages'][1]['content'])

    def test_every_door_and_search_can_open_then_push_a_crate_through(self):
        for door in (104, 105, *range(116, 122)):
            cells, tiles = [0] * 240, [12] * 240
            for y in (2, 3):
                for x in range(2, 7): tiles[at(x, y)] = 0
            cells[at(2, 3)], cells[at(3, 3)], cells[at(4, 3)], cells[at(5, 3)], cells[at(6, 3)] = 10, 9, door, 18, 7
            tiles[at(4, 3)] = 12
            candidate = ''.join(f'{kind:02x}' for kind in cells + tiles + [0] * 240)
            for method in ('bfs', 'greedy', 'macro-bfs', 'chain'):
                with self.subTest(door=door, method=method):
                    result = actions.subprocess.run([str(actions.SOLVER), 'solve', '--seconds', '2',
                        '--only', method, '--max-mb', '64', candidate], capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(actions.verify_route(1, candidate, result.stdout.strip()))

    def test_continues_a_learned_route_after_moving_home(self):
        values = [int(board()[i:i + 2], 16) for i in range(0, 1440, 2)]
        values[at(7, 2)], values[at(7, 1)] = 0, 7
        candidate = ''.join(f'{kind:02x}' for kind in values)
        self.assertFalse(actions.verify_route(1, candidate, '333332'))
        route = actions.prove_proposal(1, candidate, prefixes=['333332'])
        self.assertTrue(route.startswith('333332'))
        self.assertTrue(actions.verify_route(1, candidate, route))

    def test_a_losing_old_route_falls_back_to_a_fresh_search(self):
        values = [int(board()[i:i + 2], 16) for i in range(0, 1440, 2)]
        values[240 + at(2, 4)] = 65
        candidate = ''.join(f'{kind:02x}' for kind in values)
        self.assertFalse(actions.verify_route(1, candidate, '0'))
        route = actions.prove_proposal(1, candidate, prefixes=['0'])
        self.assertTrue(actions.verify_route(1, candidate, route))
        self.assertFalse(route.startswith('0'))

    def test_route_history_keeps_completed_examples_and_ranks_the_closest(self):
        candidate = actions.apply_proposal(board(), variation(4, 4))
        route = actions.prove_proposal(1, candidate)
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            drafts = Path(directory)
            (drafts / '001.proof').write_text(board() + '\n333332')
            with patch.object(actions, 'DRAFTS', drafts):
                actions.remember_route(1, candidate, route)
                self.assertEqual(actions.learned_routes(1, board())[0], '333332')
                self.assertEqual(actions.learned_routes(1, candidate)[0], route)
                for index in range(10): actions.remember_route(1, board(), '333332' + '0' * index)
                self.assertEqual(len(actions.route_examples(1)), 8)

    def test_fix_uses_glm_and_proves_a_minimal_repair(self):
        source = blocked_board()
        self.assertFalse(actions.verify_route(1, source, '333332'))
        response = dict(choices=[dict(message=dict(content=json.dumps(repair())))])
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            drafts = Path(directory)
            (drafts / '001.glm-base').write_text(source)
            with patch.object(actions, 'DRAFTS', drafts), \
                    patch.object(actions, 'existing_route', return_value=''), \
                    patch.object(actions, 'glm_settings', return_value=('https://example.invalid', 'test', 'glm-test')), \
                    patch.object(actions.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as request:
                actions.modify(1, repair=True)
            candidate, route = (drafts / '001.glm-proof').read_text().splitlines()
            self.assertTrue(actions.verify_route(1, candidate, route))
            self.assertEqual((drafts / '001.glm-result').read_text(), candidate)
            self.assertEqual((drafts / '001.glm-base').read_text(), source)
            self.assertEqual(json.loads((drafts / '001.glm-details.json').read_text())['changed_coordinates'], 1)
            instruction = json.loads(request.call_args.args[0].data)['messages'][0]['content']
            self.assertIn('repair', instruction)
            self.assertIn('smallest necessary', instruction)
            request.assert_called_once()

    def test_repairs_keep_objectives_and_modify_keeps_its_stricter_rules(self):
        with self.assertRaises(ValueError):
            actions.apply_proposal(blocked_board(), repair())
        for edit in (dict(layer='cells', x=4, y=3, **{'from': 1, 'to': 0}),
                     dict(layer='tiles', x=6, y=3, **{'from': 4, 'to': 0})):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                actions.apply_proposal(blocked_board(), dict(edits=[edit]), repair=True)

    def test_failed_glm_repair_keeps_the_source_and_exposes_no_result(self):
        proposal = dict(edits=[dict(layer='cells', x=4, y=3, **{'from': 1, 'to': 0})], solution='2')
        def reply(*args, **kwargs):
            return io.BytesIO(json.dumps(dict(choices=[dict(message=dict(content=json.dumps(proposal)))])).encode())
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            drafts = Path(directory)
            (drafts / '001.glm-base').write_text(blocked_board())
            with patch.object(actions, 'DRAFTS', drafts), \
                    patch.object(actions, 'existing_route', return_value=''), \
                    patch.object(actions, 'glm_settings', return_value=('https://example.invalid', 'test', 'glm-test')), \
                    patch.object(actions.urllib.request, 'urlopen', side_effect=reply):
                with self.assertRaisesRegex(ValueError, 'No winnable repair'):
                    actions.modify(1, repair=True)
            self.assertEqual((drafts / '001.glm-base').read_text(), blocked_board())
            self.assertFalse((drafts / '001.glm-result').exists())
            self.assertFalse((drafts / '001.glm-proof').exists())

    def test_update_all_force_publishes_approved_snapshots_without_rechecking(self):
        candidate = actions.apply_proposal(board(), variation(4, 4))
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            root = Path(directory)
            drafts = root / 'backup/editor-drafts'
            drafts.mkdir(parents=True)
            (root / 'levels').mkdir()
            (root / 'backup/editor-publish.json').write_text('{}')
            approved = dict(levels=[actions.record(1, board(), '333332'),
                                    actions.record(2, board(), '333332')],
                            pending={'4': actions.record(4, board(), '333332')})
            path = root / 'levels/approved.json'
            path.write_text(json.dumps(approved))
            (drafts / '001.hex').write_text(board())
            (drafts / '002.hex').write_text(candidate)
            # Even a winning draft is not a new approval.
            (drafts / '002.proof').write_text(candidate + '\n333332')
            before = {p.name: p.read_bytes() for p in drafts.iterdir()}
            with patch.object(actions, 'ROOT', root), patch.object(actions, 'DRAFTS', drafts), \
                    patch.object(actions, 'verify_route', side_effect=AssertionError('Already approved')), \
                    patch.object(actions, 'prove_proposal', side_effect=AssertionError('No draft search')), \
                    patch.object(actions.subprocess, 'run', side_effect=AssertionError('No server check')), \
                    patch.object(actions, 'update') as publish:
                actions.update_all()
            publish.assert_called_once_with(force=True)
            self.assertEqual(json.loads(path.read_text()), approved)
            self.assertEqual({name: (drafts / name).read_bytes() for name in before}, before)
            summary = json.loads((drafts / 'update-all-summary.json').read_text())
            self.assertEqual(summary['updated'], [1, 2])
            self.assertEqual(summary['checked'], [])
            self.assertEqual(summary['kept_unproven_drafts'], [2])

    def test_publication_reports_drafts_that_were_not_proven(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            root = Path(directory)
            drafts = root / 'backup/editor-drafts'
            drafts.mkdir(parents=True)
            (root / 'levels').mkdir()
            (root / 'levels/approved.json').write_text(json.dumps(dict(levels=[{}])))
            (drafts / '001.hex').write_text(blocked_board())
            (drafts / '001.published').write_text(board())
            (drafts / 'update-all-summary.json').write_text(json.dumps(dict(
                unproven_boards={'1': actions.hashlib.sha256(blocked_board().encode()).hexdigest()})))
            with patch.object(release, 'ROOT', root):
                self.assertEqual(release.publication_status(), 'Published · 1 not updated')
                (drafts / '001.published').write_text(blocked_board())
                self.assertEqual(release.publication_status(), 'Published')

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
