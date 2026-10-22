"""Stage the existing game and editor resources for their shared browser host."""
import json
from pathlib import Path
import runpy
import shutil

root = Path(__file__).resolve().parents[1]
assets = root / 'build/web-assets/assets'
if assets.exists():
    shutil.rmtree(assets)
assets.mkdir(parents=True)
for name in ('shovey', 'shovey-editor'):
    shutil.copytree(root / 'build/game-assets' / name / 'assets' / name, assets / name)

translations = runpy.run_path(str(root / 'scripts/build-bundles.py'))['translations']
code = []
for manifest, function in (('src/catalog.json', 'GameLocaleText'),
                           ('src/editor/catalog.json', 'EditorLocaleText')):
    descriptor = json.loads((root / manifest).read_text())
    code.append(translations(descriptor)[1].replace('GameLocaleText', function))
generated = root / 'build/web-generated'
generated.mkdir(exist_ok=True)
(generated / 'translations.zi').write_text('\n'.join(code))
