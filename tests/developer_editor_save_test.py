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
