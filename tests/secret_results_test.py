"""Real secret-result view regression; run through build-queue."""
import os
import shlex
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parents[1]
os.chdir(root)
for name in ('DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','SESSION_MANAGER','GDK_DISPLAY'):
    os.environ.pop(name,None)
os.environ['YUE_DESKTOP_RECOVERY']='0'
output=root/'build/tests/secret-level-ratings'
subprocess.run(['git','check-ignore','-q',str(output)],check=True)
output.mkdir(parents=True,exist_ok=True)
lock=[] if (root/'ziran.local.toml').exists() else ['--locked']
def pkg(name):
    return Path(subprocess.check_output(['./scripts/ziran.sh','pkg','path',name,*lock],text=True).strip())
tool=pkg('ziran'); kryon=pkg('kryon')
cmd=[str(tool/'build/bin/ziran'),'bundle','--project','--root',str(root),
    '--define','SHOVEY_RELEASE','--define','KRYON_HOSTED_UI',
    '--module-path',str(root/'tests'),'--module-path',str(root/'src/editor'),
    '--module-path',str(root/'src/solver'),
    '--entry','secret_results_behavior:Check','-o',str(output/'exclusion.zx'),'tests/secret_results_behavior.zi']
subprocess.run(cmd,check=True)
# Bind every imported host capability to a rejecting callback: a secret must
# use none, even though the full view also contains ordinary UI/storage paths.
subprocess.run([*shlex.split(os.environ.get('CC','cc')), '-std=c11', '-O1',
    '-I'+str(tool/'include'), 'tests/secret_results_host.c',
    str(tool/'build/libziran-vm.a'), '-lm', '-lpthread',
    '-o', str(output/'test')],check=True)
subprocess.run([str(output/'test'),str(output/'exclusion.zx')],check=True)
print('Secret results local test passed: real view functions, real engine wins for every shipped secret room, no rating screen/storage, legacy cache ignored/preserved, timed exact parent return, story cache/dismissal retained',flush=True)
