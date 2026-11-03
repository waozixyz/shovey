"""Build and exercise the real public editor on a private display, offline."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work/public-editor-create-only'
subprocess.run(['git', 'check-ignore', '-q', str(WORK)], cwd=ROOT, check=True)
WORK.mkdir(parents=True, exist_ok=True)
for name in ('tmp', 'native'):
    (WORK / name).mkdir(exist_ok=True)
os.environ['TMPDIR'] = str(WORK / 'tmp')
os.environ['ZIRAN_NATIVE_DIR'] = str(WORK / 'native')

def package(name):
    return Path(subprocess.check_output([ROOT / 'scripts/ziran.sh', 'pkg', 'path', name], cwd=ROOT, text=True).strip())

def build():
    toolchain = package('ziran')
    modules = ['--module-path', str(ROOT / 'src'), '--module-path', str(WORK / 'generated'),
               '--module-path', str(toolchain / 'std'), '--module-path', 'std=' + str(toolchain / 'std')]
    for name, folders in [('kryon', ['src/ui', 'src/backend']), ('apps', ['src']), ('entity', ['src']), ('mingcute', ['src'])]:
        for folder in folders:
            modules += ['--module-path', name + '=' + str(package(name) / folder)]
            if name == 'kryon':
                modules += ['--module-path', str(package(name) / folder)]
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('bundler', ROOT / 'scripts/build-bundles.py')
    bundler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundler)
    generated = WORK / 'generated'
    generated.mkdir(exist_ok=True)
    descriptor = json.loads((ROOT / 'src/editor/catalog.json').read_text())
    _, translations = bundler.translations(descriptor)
    (generated / 'translations.zi').write_text(translations)
    assets = WORK / 'package-assets'
    assets.mkdir(exist_ok=True)
    (generated / 'levels.zi').unlink(missing_ok=True)
    subprocess.run([sys.executable, ROOT / 'scripts/prepare_editor_assets.py', assets, WORK / 'package-generated'], check=True)
    assert not list(assets.rglob('*.png')), 'Public editor preparation generated campaign previews'
    shared = json.loads((ROOT / 'src/editor/shared_assets.json').read_text())
    assert not shared.get('release_copies'), 'Public editor includes a campaign preview inventory'
    assert all('/levels' not in copy['from'] for copy in shared['copies'])
    binds = []
    for name, fake in [('ReadAppUiHost', 'Frame'), ('AppLocaleHost', 'Locale'), ('AppRecordHost', 'Record'),
                       ('SaveAppRecordHost', 'Save'), ('AppKeyHost', 'Key'), ('AppFieldInputHost', 'Input'),
                       ('AppSoundHost', 'Sound'), ('SmoothFramesHost', 'Smooth'),
                       ('AppSupportsHost', 'Supports'), ('AppServiceHost', 'Service')]:
        binds += ['--bind', f'editor_view:{name}=public_editor_ui_host:Fake{fake}']
    binds += ['--bind', 'text_input_platform:SetPlatformTextKeyboardVisible=public_editor_ui_host:FakeKeyboard']
    output = WORK / 'c'
    shutil.rmtree(output, ignore_errors=True)
    subprocess.run([toolchain / 'build/bin/ziran', 'build', '--target=c', '--no-main', '--root', ROOT,
                    *modules, *binds, '--bind-host', 'cairo_raster', '--entry', 'public_editor_ui_host:RunPublicEditor',
                    '-o', output, ROOT / 'tests/public_editor_ui_host.zi'], cwd=ROOT, check=True)
    (output / 'main.c').write_text('#include \"public_editor_ui_host.h\"\nint main(void) { return RunPublicEditor(); }\n')
    command = [os.environ.get('CC', 'cc'), '-std=c11', '-O1', '-ffunction-sections', '-fdata-sections',
               '-I' + str(toolchain / 'include')]
    for folder in sorted({p.parent for p in output.rglob('*.h')}):
        command += ['-iquote', str(folder)]
    command += [str(p) for p in output.rglob('*.c')] + [str(ROOT / 'build/ziran/libziran.a'), '-Wl,--gc-sections']
    command += shlex.split(subprocess.check_output(['pkg-config', '--libs', 'sdl2', 'cairo', 'freetype2', 'fontconfig', 'pangocairo'], text=True))
    command += ['-lm', '-lpthread', '-o', str(WORK / 'public-editor-ui-test')]
    subprocess.run(command, cwd=ROOT, check=True)

if __name__ == '__main__':
    if '--ui' in sys.argv:
        from public_editor_ui_test import run
        run()
    else:
        try:
            build()
        except subprocess.CalledProcessError as error:
            raise SystemExit(error.returncode)
        environment = {k: v for k, v in os.environ.items() if k not in
                       ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY')}
        environment |= {'YUE_DESKTOP_RECOVERY': '0', 'SDL_AUDIODRIVER': 'dummy'}
        subprocess.run(['xvfb-run', '-a', '-n', '400', '-s', '-screen 0 1600x1200x24',
                        sys.executable, __file__, '--ui'], cwd=ROOT, env=environment, check=True)
        # The public editor suite also exercises its existing Unicode fields
        # and real collection client with synthetic services on both targets.
        for script in ('editor_field_test.sh', 'editor_sharing_test.sh'):
            subprocess.run(['sh', str(ROOT / 'tests' / script), str(package('ziran'))],
                           cwd=ROOT, env=environment, check=True)
