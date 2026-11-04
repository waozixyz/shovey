"""The publication prefix excludes draft boards and leaves its source intact."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from island_campaign import generate, stage_assets


class CampaignTest(unittest.TestCase):
    def test_only_configured_prefix_is_generated(self):
        config = json.loads((ROOT / 'packaging/island-campaign.json').read_text())
        self.assertEqual(config, dict(shipped_levels=30, planned_levels=175))
        scratch = ROOT / 'build/island-campaign-config-test'
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            for name in ('packaging', 'levels', 'src'):
                (root / name).mkdir()
            (root / 'packaging/island-campaign.json').write_text(json.dumps(config))
            levels = [dict(number=i, name=f'Island {i}', solution='123',
                           ground=['00' * 12] * 20, features=['00' * 12] * 20,
                           objects=['00' * 12] * 20) for i in range(1, 176)]
            source = root / 'levels/island.json'
            source.write_text(json.dumps(dict(levels=levels)))
            before = source.read_bytes()
            self.assertEqual(generate(root), 30)
            code = (root / 'src/island_levels.zi').read_text()
            self.assertIn('ISLAND_LEVEL_COUNT :: 30', code)
            self.assertIn('if number == 30 ', code)
            self.assertNotIn('if number == 31 ', code)
            self.assertEqual(source.read_bytes(), before)
            resources = root / 'staged'
            entries = []
            for folder in ('levels', 'levels-landscape'):
                (resources / folder).mkdir(parents=True)
                for number in (1, 30, 31, 150):
                    name = f'{folder}/{number}.png'
                    (resources / name).write_bytes(b'preview fixture')
                    entries.append(dict(path=name))
            (resources / 'art.json').write_text(json.dumps(dict(files=entries)))
            stage_assets(resources, root)
            self.assertEqual([e['path'] for e in json.loads((resources / 'art.json').read_text())['files']],
                             ['levels/1.png', 'levels/30.png', 'levels-landscape/1.png', 'levels-landscape/30.png'])
            self.assertFalse((resources / 'levels/31.png').exists())
            self.assertEqual(source.read_bytes(), before)
            config['shipped_levels'] = 175
            (root / 'packaging/island-campaign.json').write_text(json.dumps(config))
            self.assertEqual(generate(root), 175)
            self.assertIn('if number == 175 ', (root / 'src/island_levels.zi').read_text())


if __name__ == '__main__':
    unittest.main()
