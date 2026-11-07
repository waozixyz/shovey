#!/usr/bin/env python3
"""Exercise local bundle staging alongside external catalog entries."""
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('build_bundles', ROOT / 'scripts/build-bundles.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
import player


class PlayerPayloadTest(unittest.TestCase):
    def test_native_payload_receipt_staging_and_corruption(self):
        work = ROOT / 'work'
        subprocess.run(['git', 'check-ignore', '-q', str(work)], cwd=ROOT, check=True)
        with tempfile.TemporaryDirectory(prefix='player-payload-', dir=work) as folder:
            root = Path(folder)
            payload = root / 'games/shovey.zx'
            payload.parent.mkdir()
            payload.write_bytes(b'ZX\0\0verified game')
            (root / 'shovey.zx').write_bytes(b'ZX\0\0small collection')
            (root / 'entity.zx').write_bytes(b'ZX\0\0profile')
            receipt = dict(version='test', island_bundled=True,
                sha256=player.digest(root / 'shovey.zx'),
                local_bundles={'arcade.shovey': 'games/shovey.zx'},
                children=[dict(id='arcade.shovey', expected_id='shovey',
                    bytes=payload.stat().st_size, sha256=hashlib.sha256(payload.read_bytes()).hexdigest())])
            (root / 'shovey.json').write_text(json.dumps(receipt))
            with patch.object(player, 'OUT', root), patch.object(player, 'release', return_value={'version': 'test'}):
                self.assertEqual(player.checked_collection(), receipt)
                target = root / 'native'
                player.stage_collection_data(target, receipt)
                self.assertEqual((target / 'games/shovey.zx').read_bytes(), payload.read_bytes())
                self.assertEqual((target / 'shovey.zx').read_bytes(), (root / 'shovey.zx').read_bytes())
                preload, linked = player.web_preload(target, root / 'web', receipt)
                self.assertEqual((preload / 'games/shovey.zx').read_bytes(), payload.read_bytes())
                self.assertEqual((preload / 'shovey.zx').read_bytes(), (root / 'shovey.zx').read_bytes())
                self.assertEqual(linked, [target / 'games/shovey.zx'])
                payload.write_bytes(b'corrupt payload')
                with self.assertRaisesRegex(SystemExit, 'A local game changed'):
                    player.checked_collection()


class BundleCatalogTest(unittest.TestCase):
    def setUp(self):
        work = ROOT / 'work'
        work.mkdir(exist_ok=True)
        subprocess.run(['git', 'check-ignore', '-q', str(work)], cwd=ROOT, check=True)
        self.temp = tempfile.TemporaryDirectory(prefix='bundle-catalog-', dir=work)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(builder, 'ROOT', self.root).start()
        self.commands = []
        patch.object(builder.subprocess, 'check_output', return_value=str(self.root / 'dependency')).start()
        patch.object(builder.subprocess, 'run', side_effect=self.compile).start()

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def compile(self, command, **kwargs):
        self.commands.append(command)
        Path(command[command.index('-o') + 1]).write_bytes(b'ZX\0\0fixture')

    def build(self):
        builder.build(*[self.root / name for name in ('toolchain', 'kryon', 'apps', 'mingcute')])

    def test_external_descriptor_is_not_read_or_embedded(self):
        # Format 62 and the reminder capability must reject older hosts before entry.
        minimum_host = json.loads((ROOT / 'src/catalog.json').read_text())['host_api']
        self.assertEqual(minimum_host, 43)
        descriptor = dict(name='public', assets='art', locales='locales', locale_prefix='game.',
                          entry='game:Entry', source='game.zi', preview='preview.png', host_api=minimum_host)
        self.write('public/catalog.json', json.dumps(descriptor))
        self.write('art/marker.txt', 'public art')
        self.write('locales/en.txt', '[game.title]\nPublic game\n---\n')
        self.write('game.zi', 'fixture source')
        preview = self.root / 'preview.png'
        preview.write_bytes(b'\x89PNG\r\n\x1a\nfixture preview')
        # A public external entry need not even have a local descriptor/source.
        # Existing private build outputs belong to their separate build path.
        private = self.write('build/games/private.zx', 'preserved private output')
        self.write('apps.json', json.dumps(dict(apps=[
            dict(manifest='public/catalog.json', library_entries=['game:Retain']),
            dict(manifest='private/missing.json', external=True),
        ])))
        self.build()
        self.assertEqual(len(self.commands), 1)
        command = self.commands[0]
        self.assertIn(str(self.root / 'game.zi'), command)
        self.assertIn('game:Retain', command)
        self.assertEqual((self.root / 'build/game-assets/public/assets/public/marker.txt').read_text(), 'public art')
        packed = json.loads((self.root / 'build/game-assets/public/assets/public/catalog.json').read_text())
        self.assertEqual(packed['host_api'], minimum_host)
        self.assertIn('Public game', (self.root / 'build/game-generated/public/translations.zi').read_text())
        self.assertEqual((self.root / 'build/games/public-preview.png').read_bytes(), preview.read_bytes())
        self.assertEqual(private.read_text(), 'preserved private output')
        self.assertFalse((self.root / 'build/game-assets/private').exists())
        self.assertFalse((self.root / 'build/game-generated/private').exists())

    def test_portable_title_art_is_kept_and_editor_covers_stay_out(self):
        rules = json.loads((ROOT / 'src/bundle.json').read_text())
        self.write('src/bundle.json', json.dumps(rules))
        staged = self.root / 'staged'
        names = ('title-portrait.png', 'title-landscape.png', 'logo.png',
                 'editor-portrait.png', 'editor-landscape.png')
        for name in names:
            self.write('staged/assets/shovey/' + name, 'fixture picture')
        self.write('staged/assets/shovey/title/shovey-editor-portrait.jpg', 'shared title cover')
        packed = builder.bundle_assets('src/catalog.json', 'shovey', staged, True) / 'shovey'
        self.assertEqual({p.name for p in packed.iterdir()},
                         {'title-portrait.png', 'title-landscape.png', 'logo.png', 'title'})
        self.assertEqual((packed / 'title/shovey-editor-portrait.jpg').read_text(), 'shared title cover')

    def test_locale_entries_after_blank_lines_are_kept(self):
        self.write('locales/en.txt', '[game.one]\nOne\n---\n\n[game.two]\nLevel % complete\n---\n\n\n[game.three]\nThree\n---\n')
        blocks, code = builder.translations(dict(locales='locales', locale_prefix='game.'))
        self.assertEqual(blocks['en.txt'], '[game.one]\nOne\n---\n[game.two]\nLevel % complete\n---\n[game.three]\nThree\n---\n')
        for text in ('One', 'Level % complete', 'Three'):
            self.assertIn(text, code)

    def test_invalid_local_descriptor_still_fails(self):
        self.write('apps.json', json.dumps(dict(apps=[dict(manifest='broken.json')])))
        self.write('broken.json', json.dumps(dict(name='broken')))
        with self.assertRaisesRegex(KeyError, 'assets'):
            self.build()
        self.assertEqual(self.commands, [])


if __name__ == '__main__':
    unittest.main()
