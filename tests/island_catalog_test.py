#!/usr/bin/env python3
"""Exercise the public collection packer without a compiler or private source."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('player', ROOT / 'scripts/player.py')
player = importlib.util.module_from_spec(spec)
spec.loader.exec_module(player)
work = ROOT / 'work/island-catalog-test'
subprocess.run(['git', 'check-ignore', '-q', str(work)], cwd=ROOT, check=True)
shutil.rmtree(work, ignore_errors=True)
work.mkdir(parents=True)
declaration, apps = player.declared_apps()
assert [app['descriptor']['id'] for app in apps] == ['arcade.shovey', 'arcade.shovey-island', 'arcade.shovey-editor']
island = apps[1]
assert island['external'] and not island['private']
assert 'source' not in island['descriptor'] and 'assets' not in island['descriptor']
with patch.object(player, 'package', return_value=work):
    player.build_games([island])

def games(items):
    folder = player.OUT / 'games'
    folder.mkdir(parents=True, exist_ok=True)
    for app in items:
        if app['external']:
            continue
        name = app['descriptor']['name']
        (folder / (name + '.zx')).write_bytes(b'ZX\0\0public-fixture-' + name.encode())
        if app['requires']:
            (folder / (name + '-resources.json')).write_text(json.dumps(dict(dependencies=app['requires'], resources=[])))

def compiler(command, **kwargs):
    Path(command[command.index('-o') + 1]).write_bytes(b'ZX\0\0collection-fixture')

controller = work / 'controller.zx'
controller.write_bytes(b'ZX\0\0controller')
with patch.object(player, 'OUT', work / 'out'), patch.object(player, 'PRIVATE_APP', work / 'missing-private-source'), \
        patch.object(player, 'build_games', side_effect=games), \
        patch.object(player, 'build_controller', return_value=(controller, player.digest(controller))), \
        patch.object(player, 'build_entity'), patch.object(player, 'ziran', return_value='fixture'), \
        patch.object(player, 'run', side_effect=compiler):
    player.collection()
    assets = player.OUT / 'collection/assets'
    catalog = json.loads((assets / 'apps/catalog.json').read_text())
    child = catalog['children'][1]
    for key in ('sha256', 'bytes', 'version', 'package_id'):
        assert child[key] == island['descriptor'][key]
    assert not (assets / child['bundle'].removeprefix('assets/')).exists()
    for key in ('portrait', 'landscape', 'logo'):
        assert (assets / child['cover'][key].removeprefix('assets/')).is_file()
    assert 'src/island' not in json.dumps(catalog)
print('Public catalog local test: Classic → Island → Editor, pinned external package, public covers and no private bytecode/source passed')
