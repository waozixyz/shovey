#!/bin/sh
# Build the standalone Android APK from this checkout and the Arcade host
# pinned in packaging/android. F-Droid and the release workflow both run this
# build, so the signed shovey-VERSION-fdroid.apk reproduces byte for byte.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$root/build/fdroid"
# Fetch every package into this build's own cache, never a shared one.
export XDG_CACHE_HOME="$root/build/fdroid/cache"
project="$root/packaging/android"
ziran="$root/scripts/ziran.sh"
ZIRAN_PROJECT_ROOT="$project" "$ziran" fetch --locked
host=$(ZIRAN_PROJECT_ROOT="$project" "$ziran" pkg path host --locked)
toolchain=$(ZIRAN_PROJECT_ROOT="$project" "$ziran" pkg path ziran --locked)
compiler="$toolchain/build/bin/ziran"
if [ ! -x "$compiler" ]; then
    compiler="$project/build/ziran-bootstrap/build/bin/ziran"
fi

# The host's ledger names this release and its Android version code.
python3 - "$root" "$host" <<'PY'
import json, re, sys
from pathlib import Path
root, host = map(Path, sys.argv[1:])
version = re.search(r'^## \[([\d.]+)\]', (root / 'src/CHANGELOG.md').read_text(), re.M)[1]
release = json.loads((host / 'apps/versions.json').read_text())['node_apps']['shovey']
if release['version'] != version:
    raise SystemExit('Pin the Arcade host that records Shovey ' + version + ': scripts/pin-android-host.py')
PY

sdk=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Android/Sdk}}
export ANDROID_HOME="$sdk" ANDROID_SDK_ROOT="$sdk"
if [ ! -x "$sdk/build-tools/36.0.0/aapt2" ] || [ ! -d "$sdk/platforms/android-36" ] || [ ! -d "$sdk/cmake/3.22.1" ]; then
    # F-Droid's builder has sdkmanager on PATH; an installed SDK keeps it in cmdline-tools.
    sdkmanager=$(command -v sdkmanager || echo "$sdk/cmdline-tools/latest/bin/sdkmanager")
    "$sdkmanager" 'build-tools;36.0.0' 'platforms;android-36' 'cmake;3.22.1'
fi

export PATH="$(dirname "$compiler"):$PATH"
unset MAKEFLAGS MFLAGS MAKEOVERRIDES
# The host builds this checkout's game; every other package stays at the
# commit the host locks, as in the Linux and Windows downloads.
printf '[overrides]\nshovey = "%s"\n' "$root" > "$host/ziran.local.toml"
make -j1 -C "$root" levels landscape
env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS \
    make -j1 -C "$host" android-shovey-release
cp "$host/build/shovey-unsigned.apk" "$root/build/fdroid/shovey.apk"
printf '%s\n' "Android source build: $root/build/fdroid/shovey.apk"
