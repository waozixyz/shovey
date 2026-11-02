#!/usr/bin/env python3
"""Exercise local bundle staging alongside external catalog entries."""
import importlib.util
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
        descriptor = dict(name='public', assets='art', locales='locales', locale_prefix='game.',
                          entry='game:Entry', source='game.zi', preview='preview.png')
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
        self.assertIn('Public game', (self.root / 'build/game-generated/public/translations.zi').read_text())
        self.assertEqual((self.root / 'build/games/public-preview.png').read_bytes(), preview.read_bytes())
        self.assertEqual(private.read_text(), 'preserved private output')
        self.assertFalse((self.root / 'build/game-assets/private').exists())
        self.assertFalse((self.root / 'build/game-generated/private').exists())

    def test_invalid_local_descriptor_still_fails(self):
        self.write('apps.json', json.dumps(dict(apps=[dict(manifest='broken.json')])))
        self.write('broken.json', json.dumps(dict(name='broken')))
        with self.assertRaisesRegex(KeyError, 'assets'):
            self.build()
        self.assertEqual(self.commands, [])


if __name__ == '__main__':
    unittest.main()
