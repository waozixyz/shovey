#!/usr/bin/env python3
"""Package the standalone authoring tool with its own art and a fresh puzzle."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'build/admin-editor'


def main():
    spec = importlib.util.spec_from_file_location('levels', ROOT / 'tools/levels/levels.py')
    levels = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(levels)
    version = re.search(r'^## \[([0-9.]+)\]', (ROOT / 'src/editor/CHANGELOG.md').read_text(), re.M)[1]
    payload = OUTPUT / 'package/shovey-level-editor'
    if payload.exists():
        shutil.rmtree(payload)
    for folder in ('bin', 'build/solver', 'scripts', 'levels', 'backup/redesign', 'backup/editor-drafts'):
        (payload / folder).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUTPUT / 'shovey-level-editor', payload / 'bin/shovey-level-editor')
    shutil.copyfile(OUTPUT / 'solver/shovey-solve-classic', payload / 'build/solver/shovey-solve-classic')
    shutil.copyfile(OUTPUT / 'solver/fingerprint', payload / 'build/solver/fingerprint')
    for binary in (payload / 'bin/shovey-level-editor', payload / 'build/solver/shovey-solve-classic'):
        binary.chmod(0o755)
        data = binary.read_bytes()
        for item in levels.load('classic'):
            assert ''.join(item['cells']).encode() not in data, 'Story data was compiled into the authoring package'
        assert b'backup/original/' not in data, 'Reference loader was compiled into the authoring package'
    shutil.copyfile(ROOT / 'scripts/editor_actions.py', payload / 'scripts/editor_actions.py')
    for edition in ('shovey', 'shovey-landscape'):
        target = payload / 'assets' / edition
        shutil.copytree(ROOT / 'assets' / edition / 'sprites', target / 'sprites')
        art = json.loads((ROOT / 'assets' / edition / 'art.json').read_text())
        art['files'] = [item for item in art['files'] if item['path'].startswith('sprites/')]
        (target / 'art.json').write_text(json.dumps(art, indent=2) + '\n')
    starter = dict(edition='classic', width=12, height=20, levels=levels.editor_starter_levels())
    (payload / 'levels/classic.json').write_text(json.dumps(starter, indent=1) + '\n')
    (payload / 'levels/approved.json').write_text(json.dumps(dict(levels=[]), indent=1) + '\n')
    (payload / 'backup/redesign/stuck.txt').write_text(''.join(f'classic {n}\n' for n in range(2, 175)))
    (payload / 'run.sh').write_text('#!/bin/sh\ncd -- "$(dirname -- "$0")" || exit 1\nexec ./bin/shovey-level-editor "$@"\n')
    (payload / 'run.sh').chmod(0o755)
    shutil.copyfile(ROOT / 'LICENSE', payload / 'LICENSE')
    (payload / 'README.txt').write_text(
        f'Shovey Level Editor {version}\n\n'
        'Linux x86_64. Run ./run.sh from the extracted folder.\n'
        'Requires Python 3, SDL2, Cairo, Pango, Fontconfig and FreeType.\n'
        'The starter puzzle and included artwork are created for this tool.\n'
        'Story campaigns, comparison material, accounts and publishing credentials are omitted.\n\n'
        'Tiles paints floors and walls. Objects contains pieces, animals and solid decoration.\n'
        'Play with arrows; Tab returns to editing. Right-click erases the active layer.\n'
        'Undo, Redo and Reset are available. Solve the level to save its winning route.\n'
        'Approve marks the saved level locally. Saved edits to approved levels stay approved.\n'
        'Server publishing requires the separately configured developer checkout.\n\n'
        'GLM Modify uses GLM_API_KEY or ZAI_API_KEY from your environment.\n'
        'GLM_BASE_URL and GLM_MODEL are optional. Every variation must win in the real engine.\n'
        'Levels are stored in levels/classic.json; working drafts are under backup/editor-drafts.\n')
    board = starter['levels'][0]
    encoded = ''.join(board['cells'] + board['tiles'] + board['decorations'])
    subprocess.run([str(payload / 'build/solver/shovey-solve-classic'), 'verify', '--level', '1', encoded, board['solution']],
                   check=True, capture_output=True)
    subprocess.run([str(payload / 'bin/shovey-level-editor'), '--check-file', str(payload / 'levels/classic.json')], check=True)
    files = {str(p.relative_to(payload)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(payload.rglob('*')) if p.is_file()}
    (payload / 'manifest.json').write_text(json.dumps(dict(version=version, files=files), indent=2) + '\n')
    archive = OUTPUT / 'shovey-level-editor-linux-x86_64.tar.gz'
    with tarfile.open(archive, 'w:gz') as output:
        output.add(payload, arcname=payload.name)
    print(f'Editor download: {archive}')


if __name__ == '__main__':
    main()
