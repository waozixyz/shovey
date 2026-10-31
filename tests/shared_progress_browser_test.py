#!/usr/bin/env python3
"""Exercise Shovey's production record adapter against real browser IDBFS."""
import os
from pathlib import Path
import shutil
import subprocess
ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
env = dict(os.environ, EMCC_CORES='1')
scratch = ROOT / 'work/t'
scratch.mkdir(parents=True, exist_ok=True)
env['TMPDIR'] = str(scratch)
for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER'):
    env.pop(key, None)
package = lambda name: Path(subprocess.check_output(['./scripts/ziran.sh', 'pkg', 'path', name], text=True).strip())
ziran = package('ziran')
out = ROOT / 'build/shared-progress-browser-test'
out.mkdir(parents=True, exist_ok=True)
shutil.rmtree(out / 'generated', ignore_errors=True)
bindings = ['--bind', 'controls:AppServiceHost=shared_progress_browser:Service',
            '--bind', 'controls:AppRecordHost=shared_progress_browser:Record',
            '--bind', 'controls:SaveAppRecordHost=shared_progress_browser:Save']
subprocess.run(['./scripts/ziran.sh', 'build', '--project', '--root', str(ROOT), '--target=c', '--define', 'PLATFORM_WEB',
                '--entry', 'shared_progress_browser:main', *bindings,
                '-o', str(out / 'generated'), 'tests/shared_progress_browser.zi'], check=True, env=env)
runtime = ROOT / 'build/profile-web/runtime/libziran.a'
if not runtime.is_file():
    raise SystemExit('Existing browser test runtime required: ' + str(runtime))
emcc = os.environ.get('EMCC') or shutil.which('emcc') or str(Path.home() / 'emsdk/upstream/emscripten/emcc')
env['EM_CACHE'] = str(ROOT / 'build/profile-web/emscripten-cache')
generated = out / 'generated'
subprocess.run([emcc, '-O1', '-I' + str(ziran / 'include'),
                *[arg for path in sorted({p.parent for p in generated.rglob('*.c')}) for arg in ('-iquote', str(path))],
                *map(str, sorted(generated.rglob('*.c'))), str(runtime),
                '--js-library', str(ziran / 'web/ziran_web.js'), '-lidbfs.js', '-sASYNCIFY',
                '-sALLOW_MEMORY_GROWTH=1', '-sEXPORTED_RUNTIME_METHODS=FS', '-sEXIT_RUNTIME=0', '-sSTACK_SIZE=16777216',
                '-sASYNCIFY_STACK_SIZE=1048576', '-o', str(out / 'test.js')], check=True, env=env)
(out / 'index.html').write_text('''<!doctype html><title>Shovey progress storage</title><script>
var Module={preRun:[function(){
 const sync=FS.syncfs;let fail=false;
 globalThis.progressFlushFailure=value=>{fail=value};
 FS.syncfs=(populate,callback)=>fail&&!populate?setTimeout(()=>callback(Error('injected flush failure')),0):sync(populate,callback);
}]};</script><script src="test.js"></script>''')
subprocess.run(['node', 'tests/shared_progress_browser_test.mjs'], check=True, env=env)
