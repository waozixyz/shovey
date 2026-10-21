#!/usr/bin/env python3
"""Build both Shovey editions and the editor into portable app bundles
(build/games/*.zib).

Each catalog.json names its entry, source, assets and locales. Hosts such as
Arcade build the same bundles from this package's sources.

    python3 scripts/build-bundles.py --toolchain DIR --kryon DIR --apps DIR
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EDITIONS = ['src/catalog.json', 'src/island/catalog.json', 'src/editor/catalog.json']
# A bundle may hold only its own assets/<name>/ folder. A game that draws
# another's pictures lists copies in shared_assets.json beside its catalog.


def translations(descriptor):
    """Every translated string of one edition, as staged locale files and
    as Ziran code: older hosts only know their own locale files."""
    blocks_by_language, values_by_language = {}, {}
    for locale in sorted((ROOT / descriptor['locales']).glob('*.txt')):
        blocks, values = [], {}
        for block in locale.read_text().split('---\n'):
            lines = block.splitlines()
            if lines and lines[0].startswith('[' + descriptor['locale_prefix']):
                blocks.append(block.rstrip() + '\n---\n')
                values[lines[0][1:-1]] = '\n'.join(lines[1:]).rstrip()
        blocks_by_language[locale.name] = ''.join(blocks)
        values_by_language[locale.stem] = values
    code = 'GameLocaleText :: (language: string, key: string) -> string {\n'
    for language, values in sorted(values_by_language.items(), key=lambda item: item[0] == 'en'):
        indent = '    ' if language == 'en' else '        '
        if language != 'en':
            code += '    if language == ' + json.dumps(language) + ' {\n'
        for key, value in values.items():
            code += indent + 'if key == ' + json.dumps(key) + ' { return ' + json.dumps(value, ensure_ascii=False) + ' }\n'
        if language != 'en':
            code += '    }\n'
    code += '    return ""\n}\n'
    return blocks_by_language, code


def build(toolchain, kryon, apps):
    for manifest in EDITIONS:
        descriptor = json.loads((ROOT / manifest).read_text())
        name = descriptor['name']
        staged = ROOT / 'build/game-assets' / name
        resources = staged / 'assets' / name
        if staged.exists():
            shutil.rmtree(staged)
        shutil.copytree(ROOT / descriptor['assets'], resources)
        shared = (ROOT / manifest).with_name('shared_assets.json')
        for copy in json.loads(shared.read_text())['copies'] if shared.exists() else []:
            source, target = ROOT / copy['from'], resources / copy['to']
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copyfile(source, target)
        shutil.copyfile(ROOT / manifest, resources / 'catalog.json')
        blocks, code = translations(descriptor)
        (resources / 'locales').mkdir()
        for file_name, text in blocks.items():
            (resources / 'locales' / file_name).write_text(text)
        generated = ROOT / 'build/game-generated' / name
        generated.mkdir(parents=True, exist_ok=True)
        (generated / 'translations.zi').write_text(code)
        bundle = ROOT / 'build/games' / f'{name}.zib'
        bundle.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            str(toolchain / 'build/bin/zi2zib'), 'bundle', '--root', str(ROOT),
            '--module-path', str(generated),
            '--module-path', str(kryon / 'src/ui'),
            '--module-path', 'kryon=' + str(kryon / 'src/ui'),
            '--module-path', 'kryon=' + str(kryon / 'src/backend'),
            '--module-path', 'std=' + str(toolchain / 'std'),
            '--module-path', str(toolchain / 'std'),
            '--module-path', 'apps=' + str(apps / 'src'),
            '--define', 'KRYON_HOSTED_UI', '--asset-dir', 'assets=' + str(staged / 'assets'),
            '--entry', descriptor['entry'], '-o', str(bundle), str(ROOT / descriptor['source'])],
            cwd=ROOT, check=True)
        shutil.copyfile(ROOT / descriptor['preview'], bundle.with_name(f'{name}-preview.png'))
        print(f'built {bundle.relative_to(ROOT)} ({bundle.stat().st_size // 1024} KiB)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--toolchain', type=Path, required=True)
    parser.add_argument('--kryon', type=Path, required=True)
    parser.add_argument('--apps', type=Path, required=True)
    args = parser.parse_args()
    build(args.toolchain.resolve(), args.kryon.resolve(), args.apps.resolve())
