"""Replay star joins through the current generated engine and board."""
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
generated = Path(os.environ.get('EDITOR_GENERATED', ROOT / 'build/private-editor/c')).resolve()
output = ROOT / 'build/star-merge-behavior-test'
output.mkdir(parents=True, exist_ok=True)
toolchain = Path(os.environ.get('ZIRAN_TOOLCHAIN') or subprocess.check_output(
    ['ziran', 'pkg', 'path', 'ziran'], cwd=ROOT, text=True).strip())
command = [os.environ.get('CC', 'cc'), '-std=c11', '-O2', '-ffunction-sections', '-fdata-sections',
           '-Dmain=shovey_editor_main', '-I' + str(toolchain / 'include'), '-I' + str(generated)]
for folder in sorted({p.parent for p in generated.rglob('*.h')}):
    command += ['-iquote', str(folder)]
command += [str(p) for p in generated.rglob('*.c')]
command += [str(ROOT / 'tests/star_merge_behavior_test.c'), str(ROOT / 'build/ziran/libziran.a'), '-Wl,--gc-sections']
command += shlex.split(subprocess.check_output(['pkg-config', '--libs', 'sdl2', 'cairo', 'freetype2', 'fontconfig', 'pangocairo'], text=True))
command += ['-lm', '-lpthread', '-o', str(output / 'test')]
environment = {k: v for k, v in os.environ.items() if k not in
               ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY')}
subprocess.run(command, cwd=ROOT, env=environment, check=True)
subprocess.run([str(output / 'test')], cwd=ROOT, env=environment, check=True)
