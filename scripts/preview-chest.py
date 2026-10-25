#!/usr/bin/env python3
"""Build an unsigned offline game preview in a new isolated output directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(output):
    if output.exists():
        raise ValueError('Use a new preview directory; existing app outputs are preserved')
    output.mkdir(parents=True)
    ziran = shutil.which('ziran')
    if not ziran:
        raise ValueError('ziran is not on PATH')
    def package(name, cwd=ROOT):
        return Path(subprocess.check_output([ziran, 'pkg', 'path', name], cwd=cwd, text=True).strip())
    toolchain, kryon, apps, mingcute, entity = [package(name) for name in ('ziran', 'kryon', 'apps', 'mingcute', 'entity')]
    daochi = package('daochi_client', entity)
    crypto = package('crypto', daochi)
    ziran = toolchain / 'build/bin/ziran'
    subprocess.run(['python3', 'tools/levels/levels.py', 'generate'], cwd=ROOT, check=True)
    room = next(level for level in json.loads((ROOT / 'levels/approved.json').read_text())['hidden_levels'] if level['name'] == '29a')
    raw = ''.join(room['cells'] + room['tiles'] + room['decorations'])
    identity = dict(level=1003, name='29a', map_hash=hashlib.sha256(('shovey.classic.map.v1\n1003\n' + raw).encode()).hexdigest(),
                    unsigned=True, account_service='offline-signin')
    (output / 'room-snapshot.json').write_text(json.dumps(room, indent=2) + '\n')
    (output / 'preview_map.zi').write_text('PreviewMap :: ' + json.dumps(raw) + '\nPreviewIdentity :: ' + json.dumps(json.dumps(identity)) + '\n')
    sys.path.insert(0, str(ROOT / 'scripts'))
    code = runpy.run_path(str(ROOT / 'scripts/build-bundles.py'))['translations'](json.loads((ROOT / 'src/catalog.json').read_text()))[1]
    (output / 'translations.zi').write_text(code + '\nEditorLocaleText :: (language:string,key:string)->string { unused language; unused key; return "" }\n')
    command = [str(ziran), 'bundle', '--root', str(ROOT)]
    paths = [str(output), str(kryon / 'src/ui'), f'kryon={kryon}/src/ui', f'kryon={kryon}/src/backend',
             f'std={toolchain}/std', str(toolchain / 'std'), f'apps={apps}/src', f'mingcute={mingcute}/src',
             f'entity={entity}/src', f'daochi_client={daochi}', f'crypto={crypto}/src']
    for path in paths:
        command += ['--module-path', path]
    for flag in ('KRYON_HOSTED_UI', 'SHOVEY_RELEASE'):
        command += ['--define', flag]
    bindings = {'controls:AppServiceHost': 'treasure:OfflineService',
                'controls:AppRecordHost': 'treasure:RecordHost', 'controls:SaveAppRecordHost': 'treasure:SaveHost',
                'shovey_view:ReadAppUiHost': 'host:ReadAppUiHost', 'shovey_view:AppLocaleHost': 'treasure:LocaleHost',
                'shovey_view:AppRecordHost': 'treasure:RecordHost', 'shovey_view:SaveAppRecordHost': 'treasure:SaveHost',
                'shovey_view:AppKeyHost': 'treasure:KeyHost', 'shovey_view:AppSoundHost': 'treasure:SoundHost'}
    for source, target in bindings.items():
        command += ['--bind', source + '=' + target]
    with (output / 'build.log').open('w') as log:
        for entry, name in (('CheckOffline', 'offline-check.zx'), ('Main', 'app.zx')):
            subprocess.run(command + ['--asset-dir', 'assets=' + str(ROOT / 'build/game-assets/shovey/assets'),
                           '--entry', 'treasure:' + entry, '-o', str(output / name), str(ROOT / 'tools/preview/treasure.zi')],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    checked = subprocess.check_output([str(ziran), 'run', str(output / 'offline-check.zx')], text=True).strip()
    if checked != '42':
        raise ValueError('Offline services or current map snapshot did not match: ' + checked)
    shutil.copy2(kryon / 'build/zx-raylib/zx', output / 'player')
    shutil.copy2(kryon / 'build/zx-raylib/kryon-font.ttf', output / 'kryon-font.ttf')
    subprocess.run([str(output / 'player'), '--check', str(output / 'app.zx')], cwd=output, check=True)
    (output / 'app.title').write_text('Shovey 29a — Offline treasure preview\n')
    profile = output / 'profile'
    profile.mkdir()
    runtime_hash, bundle_hash = digest(output / 'player'), digest(output / 'app.zx')
    # This launcher supervises only its own game process. Its provenance comes
    # from /proc for that actual child, not from an argv-name search.
    c = r'''
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <time.h>
int main(void) {
    const char *root = ROOT_PATH, *profile = PROFILE_PATH;
    if (chdir(root)) return 2;
    pid_t child = fork(); if (child < 0) return 3;
    if (!child) {
        setenv("KRYON_APP_DATA", profile, 1); setenv("YUE_DESKTOP_RECOVERY", "0", 1);
        unsetenv("KRYON_TEST_DRIVER");
        int log = open("game.log", O_WRONLY|O_CREAT|O_APPEND, 0600);
        if (log >= 0) { dup2(log, 1); dup2(log, 2); close(log); }
        char *args[] = {"./player", NULL}; execv(args[0], args); _exit(127);
    }
    struct timespec pause = {1, 0}; nanosleep(&pause, NULL);
    char proc[128], exe[4096], cwd[4096]; struct stat actual, selected;
    snprintf(proc, sizeof(proc), "/proc/%ld/exe", (long)child);
    ssize_t n = readlink(proc, exe, sizeof(exe)-1); if (n < 0) { waitpid(child, NULL, 0); return 4; } exe[n] = 0;
    int matches = !stat(proc, &actual) && !stat("player", &selected) && actual.st_dev == selected.st_dev && actual.st_ino == selected.st_ino;
    snprintf(proc, sizeof(proc), "/proc/%ld/cwd", (long)child);
    n = readlink(proc, cwd, sizeof(cwd)-1); if (n < 0) cwd[0] = 0; else cwd[n] = 0;
    FILE *out = fopen("running-game.json", "w");
    if (out) { fprintf(out, "{\"game_pid\":%ld,\"exe\":\"%s\",\"cwd\":\"%s\",\"runtime_inode_matches\":%s,\"runtime_sha256\":\"%s\",\"bundle_sha256\":\"%s\",\"profile\":\"%s\"}\n", (long)child, exe, cwd, matches?"true":"false", RUNTIME_HASH, BUNDLE_HASH, profile); fclose(out); }
    int status = 0; if (waitpid(child, &status, 0) < 0) return 5;
    return WIFEXITED(status) ? WEXITSTATUS(status) : 6;
}
'''
    defines = {'ROOT_PATH': str(output), 'PROFILE_PATH': str(profile), 'RUNTIME_HASH': runtime_hash, 'BUNDLE_HASH': bundle_hash}
    c = '\n'.join('#define ' + key + ' ' + json.dumps(value) for key, value in defines.items()) + '\n' + c
    (output / 'launch.c').write_text(c)
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-O2', str(output / 'launch.c'), '-o', str(output / 'shovey-29a-preview')], check=True)
    receipt = dict(room=identity, bindings=bindings, profile=str(profile), account_files_copied=False,
                   runtime_sha256=runtime_hash, bundle_sha256=bundle_hash, launcher_sha256=digest(output / 'shovey-29a-preview'),
                   offline_binding_vm_result=42, native_runtime_bundle_check=0, published=False, launched=False)
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Built offline actual-game preview:', output.relative_to(ROOT))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(ROOT / 'build'):
        parser.error('Preview output must be a new folder under build/')
    build(output)
