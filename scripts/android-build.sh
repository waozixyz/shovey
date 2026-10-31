#!/bin/sh
# Build the release APK from this checkout and its own lock. F-Droid and the
# Downloads workflow both run this build, so the signed
# shovey-VERSION-fdroid.apk reproduces byte for byte. With "gplay" it builds
# the Google Play edition's APK instead, the only one with Play Billing.
set -eu
edition=${1:-}
case $edition in '' | gplay) ;; *) echo "usage: android-build.sh [gplay]" >&2; exit 2 ;; esac
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$root/build/fdroid"
# Fetch every package into this build's own cache, never a shared one.
export XDG_CACHE_HOME="$root/build/fdroid/cache"
ziran="$root/scripts/ziran.sh"
"$ziran" fetch --locked
toolchain=$("$ziran" pkg path ziran --locked)
if [ ! -x "$toolchain/build/bin/ziran" ] || [ ! -x "$toolchain/build/bin/zi2c" ]; then
    env -u DISPLAY -u WAYLAND_DISPLAY make -s -j1 -C "$toolchain" all
fi
export PATH="$toolchain/build/bin:$PATH"

sdk=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Android/Sdk}}
export ANDROID_HOME="$sdk" ANDROID_SDK_ROOT="$sdk"
if [ ! -x "$sdk/build-tools/36.0.0/aapt2" ] || [ ! -d "$sdk/platforms/android-36" ] || [ ! -d "$sdk/cmake/3.22.1" ]; then
    # F-Droid's builder has sdkmanager on PATH; an installed SDK keeps it in cmdline-tools.
    sdkmanager=$(command -v sdkmanager || echo "$sdk/cmdline-tools/latest/bin/sdkmanager")
    "$sdkmanager" 'build-tools;36.0.0' 'platforms;android-36' 'cmake;3.22.1'
fi

unset MAKEFLAGS MFLAGS MAKEOVERRIDES
make -j1 -C "$root" levels landscape
python3 "$root/scripts/player.py" collection
if [ "$edition" = gplay ]; then
    env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS \
        python3 "$root/scripts/player.py" android --gplay
    cp "$root/build/player/android/shovey-gplay-unsigned.apk" "$root/build/fdroid/shovey-gplay.apk"
    printf '%s\n' "Google Play edition APK: $root/build/fdroid/shovey-gplay.apk"
    exit 0
fi
env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS \
    python3 "$root/scripts/player.py" android --release
cp "$root/build/player/android/shovey-unsigned.apk" "$root/build/fdroid/shovey.apk"
printf '%s\n' "Android source build: $root/build/fdroid/shovey.apk"
