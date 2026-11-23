#!/usr/bin/env bash
# Prepare one job on Gitea's own build host: no installs and no root. The
# locked compiler and packages live in the lane's cache (XDG_CACHE_HOME),
# which the Downloads workflow empties whenever ziran.lock changes.
set -euo pipefail
mode=${1:-}
case $mode in android | desktop) ;; *) echo 'usage: native-ci.sh android|desktop' >&2; exit 2 ;; esac
cd -- "$(dirname -- "$0")/.."
: "${GITHUB_ENV:?Run inside the Downloads workflow}" "${GITHUB_PATH:?}" "${XDG_CACHE_HOME:?}"

handoff="$HOME/handoff/$GITHUB_RUN_ID"
test "$(cat "$handoff/revision")" = "$GITHUB_SHA"
echo "HANDOFF=$handoff" >> "$GITHUB_ENV"

scripts/ziran.sh fetch --locked
toolchain=$(scripts/ziran.sh pkg path ziran --locked)
if [ ! -x "$toolchain/build/bin/ziran" ] || [ ! -x "$toolchain/build/bin/zi2c" ]; then
    env -u DISPLAY -u WAYLAND_DISPLAY make -s -j2 -C "$toolchain" all
fi

if [ "$mode" = android ]; then
    sdk=${ANDROID_SDK_ROOT:?}
    for tool in aapt aapt2 apksigner zipalign; do
        test -x "$sdk/build-tools/36.0.0/$tool"
    done
    test -s "$sdk/platforms/android-36/android.jar"
    test -x "$sdk/cmake/3.22.1/bin/cmake"
    test -x "$sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/linux-x86_64/bin/clang"
    test -x "${JAVA_HOME:?}/bin/jarsigner"
    printf '%s\n' "$JAVA_HOME/bin" "$sdk/build-tools/36.0.0" >> "$GITHUB_PATH"
    # The release build keeps its packages in the lane's cache between runs;
    # F-Droid's rebuild of the same commit starts without one.
    echo "SHOVEY_ANDROID_CACHE=$XDG_CACHE_HOME" >> "$GITHUB_ENV"
    echo "KRYON=$(scripts/ziran.sh pkg path kryon --locked)" >> "$GITHUB_ENV"
fi
