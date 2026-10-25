"""Source snapshots and route evidence share stable, versioned map identities."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/game_maps.py'
spec = importlib.util.spec_from_file_location('game_maps', SCRIPT)
game_maps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(game_maps)


def campaign():
    cells = '00' * 13 + '0a' + '00' * (240 - 14)
    level = dict(number=1, solution='0123')
    for name, layer in zip(game_maps.LAYERS, (cells, '00' * 240, '00' * 240)):
        level[name] = [layer[at:at + 24] for at in range(0, 480, 24)]
    return dict(levels=[level], pending={'2': 'unapproved draft'})


class GameMaps(unittest.TestCase):
    def test_wire_payload_and_cross_language_hash_vector(self):
        payload = game_maps.registration(campaign(), 'v1')
        self.assertEqual(set(payload), {'game', 'source_version', 'maps'})
        self.assertEqual(payload['game'], 'shovey.classic')
        self.assertEqual(payload['source_version'], 'v1')
        self.assertEqual(len(payload['maps']), 1)
        item = payload['maps'][0]
        self.assertEqual(set(item), {'level', 'map_hash', 'map'})
        self.assertEqual(item['level'], 1)
        self.assertEqual(len(item['map']), 1440)
        # Independently verified with OpenSSL on the LF-delimited preimage.
        self.assertEqual(item['map_hash'],
                         '24d2379cda5857ca231fcce8e05ad74bdf39389ed07e29f21ae8a356ea0e3eee')
        self.assertEqual(item['map'][26:28], '0a')
        self.assertNotIn('solution', json.dumps(payload))
        self.assertNotIn('unapproved draft', json.dumps(payload))

    def test_solution_and_source_version_do_not_change_map_identity(self):
        original = campaign()
        first = game_maps.registration(original, 'v1')
        original['levels'][0]['solution'] = '3333'
        second = game_maps.registration(original, 'v2')
        self.assertEqual(first['maps'], second['maps'])
        self.assertNotEqual(first['source_version'], second['source_version'])

    def test_each_changed_layer_gets_a_new_identity_without_changing_old_snapshot(self):
        original = campaign()
        before = copy.deepcopy(original)
        first = game_maps.registration(original, 'v1')
        saved = copy.deepcopy(first)
        for name in game_maps.LAYERS:
            changed = copy.deepcopy(original)
            changed['levels'][0][name][0] = '01' + changed['levels'][0][name][0][2:]
            second = game_maps.registration(changed, 'v2')
            self.assertNotEqual(first['maps'][0]['map_hash'], second['maps'][0]['map_hash'])
        self.assertEqual(original, before)
        self.assertEqual(first, saved)

    def test_level_number_is_part_of_map_identity(self):
        first = game_maps.registration(campaign(), 'v1')['maps'][0]
        self.assertNotEqual(first['map_hash'], game_maps.map_hash(28, first['map']))

    def test_preserves_original_layer_bytes_before_engine_interpretation(self):
        source = campaign()
        level = source['levels'][0]
        level['cells'][0] = '3e' + level['cells'][0][2:]
        level['tiles'][0] = '47' + level['tiles'][0][2:]
        level['decorations'][0] = '4f' + level['decorations'][0][2:]
        board = game_maps.registration(source, 'v1')['maps'][0]['map']
        self.assertEqual(board[:2], '3e')
        self.assertEqual(board[480:482], '47')
        self.assertEqual(board[960:962], '4f')

    def test_rejects_malformed_or_ambiguous_snapshots(self):
        for number in (None, True, 0, 4097, '1'):
            source = campaign()
            source['levels'][0]['number'] = number
            with self.subTest(number=number), self.assertRaises(ValueError):
                game_maps.registration(source, 'v1')
        for replacement in (None, '00' * 240, ['00' * 12] * 19,
                            ['0A' * 12] * 20, ['00' * 11] * 20):
            source = campaign()
            source['levels'][0]['tiles'] = replacement
            with self.subTest(layer=replacement), self.assertRaises(ValueError):
                game_maps.registration(source, 'v1')
        source = campaign()
        source['levels'].append(copy.deepcopy(source['levels'][0]))
        with self.assertRaises(ValueError):
            game_maps.registration(source, 'v1')
        with self.assertRaises(ValueError):
            game_maps.registration(campaign(), '')
        for source in ({}, {'levels': None}, {'levels': [None]}):
            with self.subTest(source=source), self.assertRaises(ValueError):
                game_maps.registration(source, 'v1')

    def test_command_uses_only_explicit_snapshot_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / 'approved-v1.json'
            snapshot.write_text(json.dumps(campaign()))
            command = [sys.executable, str(SCRIPT), '--approved', str(snapshot),
                       '--source-version', 'v1']
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), game_maps.registration(campaign(), 'v1'))
            rejected = subprocess.run(command[:-2], capture_output=True, text=True)
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual(rejected.stdout, '')


if __name__ == '__main__':
    unittest.main()
