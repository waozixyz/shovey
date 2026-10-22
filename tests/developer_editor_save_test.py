"""Run the save regression against disposable levels and editor records."""
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
output = ROOT / 'build/developer-editor-save-test'
profile = output / 'profile'
(profile / 'levels').mkdir(parents=True, exist_ok=True)
(profile / 'backup/editor-drafts').mkdir(parents=True, exist_ok=True)
(profile / 'backup/redesign').mkdir(parents=True, exist_ok=True)
for record in (profile / 'backup/editor-drafts').iterdir():
    record.unlink()
board = [12] * 240
board[13], board[14], board[15] = 10, 7, 0
rows = [''.join(f'{kind:02x}' for kind in board[start:start + 12]) for start in range(0, 240, 12)]
levels = {'edition': 'classic', 'width': 12, 'height': 20,
          'levels': [{'number': 1, 'cells': rows, 'solution': '2'},
                     {'number': 2, 'cells': rows}]}
(profile / 'levels/classic.json').write_text(json.dumps(levels, indent=1) + '\n')
tiles = [12 if kind == 12 else 77 if kind == 7 else 0 for kind in board]
def rows_of(values):
    return [''.join(f'{kind:02x}' for kind in values[start:start + 12]) for start in range(0, 240, 12)]
(profile / 'levels/approved.json').write_text(json.dumps(dict(levels=[
    dict(number=n, cells=rows, tiles=rows_of(tiles), decorations=rows_of([0] * 240))
    for n in (21, 22, 23)])))
(profile / 'backup/redesign/stuck.txt').write_text(''.join(f'classic {n}\n' for n in range(2, 175)))
environment = {k: v for k, v in os.environ.items()
               if k not in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS')}
generated = ROOT / 'build/private-editor/c'
toolchain = Path(subprocess.check_output(['ziran', 'pkg', 'path', 'ziran'], cwd=ROOT, text=True).strip())
command = [os.environ.get('CC', 'cc'), '-std=c11', '-O2', '-ffunction-sections', '-fdata-sections',
           '-Dmain=shovey_editor_main', '-I' + str(toolchain / 'include'), '-I' + str(generated)]
for folder in sorted({p.parent for p in generated.rglob('*.h')}):
    command += ['-iquote', str(folder)]
command += [str(p) for p in generated.rglob('*.c')]
command += [str(ROOT / 'tests/developer_editor_save_test.c'), str(ROOT / 'build/ziran/libziran.a'),
            '-Wl,--gc-sections']
command += shlex.split(subprocess.check_output(['pkg-config', '--libs', 'sdl2', 'cairo', 'freetype2', 'fontconfig', 'pangocairo'], text=True))
command += ['-lm', '-lpthread', '-o', str(output / 'save-test')]
subprocess.run(command, cwd=ROOT, env=environment, check=True)
subprocess.run([str(output / 'save-test')], cwd=profile, env=environment, check=True)
solver = profile / 'build/solver/shovey-solve-classic'
solver.parent.mkdir(parents=True, exist_ok=True)
if not solver.exists():
    solver.symlink_to(ROOT / 'build/solver/shovey-solve-classic')
for mode in ('update', 'status'):
    for record in (profile / 'backup/editor-drafts').iterdir():
        record.unlink()
    (profile / 'levels/classic.json').write_text(json.dumps(levels, indent=1) + '\n')
    subprocess.run([str(output / 'save-test'), mode], cwd=profile, env=environment, check=True)
