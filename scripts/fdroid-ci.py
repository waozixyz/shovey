#!/usr/bin/env python3
"""Run F-Droid's real build of this commit with the submitted recipe.

Actions checks this commit out at WORKSPACE/build/xyz.waozi.shovey inside
F-Droid's builder image. F-Droid resets and cleans that checkout, so this
refuses to run anywhere else. The unsigned APK lands in WORKSPACE/tmp.
"""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
APP_ID = 'xyz.waozi.shovey'


def main():
    workspace = Path.cwd().resolve()
    if os.environ.get('GITHUB_ACTIONS') != 'true' or ROOT != workspace / 'build' / APP_ID:
        raise SystemExit('Refusing to reset an ordinary checkout; run the F-Droid workflow')
    if (ROOT / 'ziran.local.toml').exists() or (ROOT / 'build').exists():
        raise SystemExit('F-Droid must build the committed sources without overrides or caches')
    for name in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS',
                 'ZIRAN', 'ZIRAN_PROJECT_ROOT', 'XDG_CACHE_HOME'):
        os.environ.pop(name, None)
    run = lambda *args, **kwargs: subprocess.run(args, check=True, text=True, **kwargs)
    run('git', 'config', '--global', '--add', 'safe.directory', str(ROOT))
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    version = subprocess.check_output(['python3', '-c', 'import re; print(re.search(r"^## \\[([0-9.]+)\\]", '
                                       'open("src/CHANGELOG.md").read(), re.M)[1])'], cwd=ROOT, text=True).strip()
    # version.json holds the Android version code (update_version.sh).
    release = json.loads((ROOT / 'version.json').read_text())
    if release['version'] != version:
        raise SystemExit(f'version.json names Shovey {release["version"]}, not {version}: run update_version.sh')
    release['sequence'] = release['version_code']
    from fdroidserver import metadata
    # Build exactly the recipe submitted to fdroiddata, at this commit. The
    # signed release is compared separately, as it may not be published yet.
    app = metadata.parse_metadata(ROOT / 'packaging/fdroid/metadata' / (APP_ID + '.yml'))
    build = app['Builds'][-1]
    build.update(versionName=version, versionCode=release['sequence'], commit=commit)
    app.update(Builds=[build], CurrentVersion=version, CurrentVersionCode=release['sequence'])
    for field in ('Binaries', 'AllowedAPKSigningKeys'):
        app.pop(field, None)
    # F-Droid's builder runs the recipe's sudo commands as root; so does this job.
    run('bash', '-e', '-u', '-o', 'pipefail', '-x', '-c', '; '.join(build['sudo']),
        env=dict(os.environ, DEBIAN_FRONTEND='noninteractive'))
    (workspace / 'metadata').mkdir(exist_ok=True)
    metadata.write_metadata(workspace / 'metadata' / (APP_ID + '.yml'), app)
    (workspace / 'build' / ('.fdroidvcs-' + APP_ID)).write_text('git https://github.com/waozixyz/shovey.git\n')
    (workspace / 'config.yml').write_text('sdk_path: /opt/android-sdk\n')
    run('fdroid', 'build', '--verbose', '--test', '--no-refresh', '--no-tarball', '--scan-binary',
        f'{APP_ID}:{release["sequence"]}', cwd=workspace)
    apk = workspace / 'tmp' / f'{APP_ID}_{release["sequence"]}.apk'
    if not apk.is_file():
        raise SystemExit('F-Droid did not produce the expected unsigned APK')
    print('F-Droid built', apk, 'from', commit, flush=True)


if __name__ == '__main__':
    main()
