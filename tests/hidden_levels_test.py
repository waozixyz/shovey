"""A public source build includes 29a without any ignored private level files."""
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('levels_tool', ROOT / 'tools/levels/levels.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
approved = json.loads((ROOT / 'levels/approved.json').read_text())
chest = next(level for level in approved['hidden_levels'] if level['name'] == '29a')
raw = ''.join(chest['cells'] + chest['tiles'] + chest['decorations'])
assert len(raw) == 1440
with tempfile.TemporaryDirectory() as temporary:
    tool.ROOT = Path(temporary)
    (tool.ROOT / 'levels').mkdir()
    (tool.ROOT / 'levels/approved.json').write_text(json.dumps(approved))
    generated = tool.secret_functions()
    assert f'if side == 3 {{ return "{raw}" }}' in generated
    assert f'if side == 3 {{ return "{chest["solution"]}" }}' in generated
    assert 'if side == 1' not in generated and 'if side == 2' not in generated
print('Public source: approved 29a board and route remain available without private campaign/secret files')
