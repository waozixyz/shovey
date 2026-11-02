#!/usr/bin/env python3
"""Production package client with fake account/HTTP boundaries and private files."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import player

parser = argparse.ArgumentParser(description=__doc__)
for name in ('ziran', 'kryon', 'apps', 'crypto'):
    parser.add_argument('--' + name, type=Path)
args = parser.parse_args()
tools = {name: getattr(args, name) or player.package(name) for name in ('ziran', 'kryon', 'apps', 'crypto')}
work = ROOT / 'work/island-package-test'
subprocess.run(['git', 'check-ignore', '-q', str(work)], cwd=ROOT, check=True)
work.mkdir(parents=True, exist_ok=True)
native = work / 'native'
shutil.rmtree(native, ignore_errors=True)
shutil.rmtree(work / 'files', ignore_errors=True)
environment = os.environ.copy()
for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY'):
    environment.pop(key, None)
environment['YUE_DESKTOP_RECOVERY'] = '0'
subprocess.run([str(tools['ziran'] / 'build/bin/ziran'), 'build', '--target=c', '--no-main',
    '--root', str(ROOT / 'src'), '--module-path', str(ROOT / 'tests'),
    '--module-path', 'std=' + str(tools['ziran'] / 'std'), '--module-path', str(tools['ziran'] / 'std'),
    '--module-path', 'apps=' + str(tools['apps'] / 'src'),
    '--module-path', 'kryon=' + str(tools['kryon'] / 'src/ui'),
    '--module-path', 'kryon=' + str(tools['kryon'] / 'src/backend'),
    '--module-path', 'crypto=' + str(tools['crypto'] / 'src'),
    '--entry', 'island_package_test:Check', '-o', str(native), str(ROOT / 'tests/island_package_test.zi')],
    cwd=ROOT, env=environment, check=True)
(native / 'main.c').write_text('''#include <stdio.h>
#include <string.h>
#include "island_package_test.h"
int main(void) {
    const char *path = ''' + json.dumps(str(work / 'files')) + ''';
    String text = {(unsigned char *)path, (int64_t)strlen(path)};
    int result = island_package_test_Check(text);
    if (result != 42) fprintf(stderr, "Island package test failed: %d\\n", result);
    return result == 42 ? 0 : 1;
}
''')
includes = [flag for path in sorted(native.rglob('*')) if path.is_dir() for flag in ('-iquote', str(path))]
subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-O1', '-ffunction-sections', '-fdata-sections',
    '-I' + str(tools['ziran'] / 'include'), '-iquote', str(native), *includes,
    *map(str, native.rglob('*.c')), str(ROOT / 'build/ziran/libziran.a'), '-Wl,--gc-sections',
    '-lm', '-lpthread', '-lz', '-ldl', '-o', str(work / 'test')], env=environment, check=True)
subprocess.run([str(work / 'test')], env=environment, check=True)
print('Island package local tests: guest/unowned, grant binding/expiry, protected route, HTTP refusal, digest, retry, offline cache, account isolation and cancellation passed')
