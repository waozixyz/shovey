#!/bin/sh
# Build the standalone Android host and game from their committed source locks.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
project="$root/packaging/android"
export ZIRAN_PROJECT_ROOT="$project"
ziran="$root/scripts/ziran.sh"
"$ziran" fetch --locked
host=$("$ziran" pkg path host --locked)
toolchain=$("$ziran" pkg path ziran --locked)
compiler="$toolchain/build/bin/ziran"
if [ ! -x "$compiler" ]; then
    compiler="$project/build/ziran-bootstrap/build/bin/ziran"
fi

# The host ledger fixes the Android version code paired with this game release.
python3 - "$root" "$host" <<'PY'
import json, re, sys
from pathlib import Path
root, host = map(Path, sys.argv[1:])
version = re.search(r'^## \[([\d.]+)\]', (root / 'src/CHANGELOG.md').read_text(), re.M)[1]
release = json.loads((host / 'apps/versions.json').read_text())['node_apps']['shovey']
if release['version'] != version:
    raise SystemExit('Update the locked Android host for Shovey ' + version)
PY

sdk=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Android/Sdk}}
export ANDROID_HOME="$sdk" ANDROID_SDK_ROOT="$sdk"
if [ ! -x "$sdk/build-tools/36.0.0/aapt2" ] || [ ! -d "$sdk/platforms/android-36" ]; then
    "$sdk/cmdline-tools/latest/bin/sdkmanager" 'build-tools;36.0.0' 'platforms;android-36'
fi

export PATH="$(dirname "$compiler"):$PATH"
unset ZIRAN_PROJECT_ROOT MAKEFLAGS MFLAGS MAKEOVERRIDES
# Build the approved campaign in the host's locked game package, rather than
# rewriting any dependency paths or host sources in the F-Droid recipe.
game=$(cd "$host" && "$compiler" pkg path shovey --locked)
game_commit=$(git -C "$game" rev-parse HEAD)
git -C "$root" diff --quiet "$game_commit" -- src assets levels/approved.json tools/levels locales || {
    echo 'Update the Android host lock for the changed Shovey game sources' >&2
    exit 1
}
make -j1 -C "$game" levels landscape
env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS \
    make -j1 -C "$host" android-shovey-release ZIRAN="$compiler"
mkdir -p "$root/build/fdroid"
cp "$host/build/shovey-unsigned.apk" "$root/build/fdroid/shovey.apk"
printf '%s\n' "Android source build: $root/build/fdroid/shovey.apk"
