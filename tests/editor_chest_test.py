"""Hidden-room saves preserve the campaign, and ordered maps match their cards."""
import importlib.util
import json
from pathlib import Path
import tempfile

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


saver = module('editor_chest')
preview = module('editor_previews')
source = json.loads((ROOT / 'levels/approved.json').read_text())
hidden = next(level for level in source['hidden_levels'] if level['name'] == '29a')
raw = ''.join(hidden['cells'] + hidden['tiles'] + hidden['decorations'])
fixture_root = ROOT / 'build/editor-chest-unit'
fixture_root.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=fixture_root) as temporary:
    root = Path(temporary)
    (root / 'levels').mkdir()
    drafts = root / 'backup/editor-drafts'
    drafts.mkdir(parents=True)
    path = root / 'levels/approved.json'
    path.write_text(json.dumps(source))
    edited = raw[:960] + '39' + raw[962:]
    (drafts / '178.chest-request').write_text(edited + '\n' + hidden['solution'] + '\n')
    saver.save(root)
    after = json.loads(path.read_text())
    assert after['levels'] == source['levels']
    assert {key: value for key, value in after.items() if key != 'hidden_levels'} == \
        {key: value for key, value in source.items() if key != 'hidden_levels'}
    assert ''.join(after['hidden_levels'][0]['decorations']).startswith('39')
    assert not list(drafts.glob('*.publication')) and not list(drafts.glob('*.approved'))
    before = path.read_bytes()
    (drafts / '178.chest-request').write_text('incomplete\n')
    try:
        saver.save(root)
        raise AssertionError('Incomplete board replaced approved data')
    except ValueError:
        pass
    assert path.read_bytes() == before
    preview.FOLDER = root / 'previews'
    preview.FOLDER.mkdir()
    wanted = []
    for number, level in ((29, source['levels'][28]), (178, hidden), (30, source['levels'][29])):
        wanted.append((number, ''.join(level['cells'] + level['tiles'] + level['decorations'])))
    (preview.FOLDER / 'wanted.txt').write_text(''.join(f'{number} {board}\n' for number, board in wanted))
    assert preview.main() == 0
    expected_name = f"map-{preview.fnv(''.join(preview.fnv(board) for number, board in wanted))}.png"
    with Image.open(preview.FOLDER / expected_name) as combined:
        expected = Image.new('RGB', combined.size, (24, 28, 27))
        for slot, (number, board) in enumerate(wanted):
            with Image.open(preview.FOLDER / f'{number:03}-{preview.fnv(board)}.png') as tile:
                expected.paste(tile.convert('RGB'), (slot * tile.width, 0))
        # Apply the same PNG palette once to the expected composite; compare
        # exact pixels rather than inventing a visual-similarity threshold.
        expected = expected.quantize(colors=192, method=2, dither=1).convert('RGB')
        assert ImageChops.difference(expected, combined.convert('RGB')).getbbox() is None, \
            'Map image moved a board away from its actual selector card'
print('Hidden editor: atomic saves preserve all ordinary maps/metadata; map artwork keeps 29,29a,30 card order')
