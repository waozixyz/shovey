#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
set --
if [ ! -f ziran.local.toml ]; then set -- --locked; fi
toolchain=${SHARED_PROGRESS_TEST_TOOLCHAIN:-$(./scripts/ziran.sh pkg path ziran "$@")}
work="$root/build/shared-progress-test"
mkdir -p "$work"
env -u DISPLAY -u WAYLAND_DISPLAY "$toolchain/build/bin/ziran" bundle --project "$@" --root "$root" \
    --bind controls:AppServiceHost=shared_progress_behavior:FakeService \
    --bind controls:AppRecordHost=shared_progress_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=shared_progress_behavior:FakeSave \
    --entry shared_progress_behavior:Check -o "$work/progress.zx" "$root/tests/shared_progress_behavior.zi"
result=$(env -u DISPLAY -u WAYLAND_DISPLAY "$toolchain/build/bin/ziran" run "$work/progress.zx")
test "$result" = 42 || { echo "Shared progress portable local test failed: $result" >&2; exit 1; }
echo 'Shared game progress: completion-only account writes, zero account calls during moves and active play, active boards preserved, account changes and offline fallback'
# Exercise the same state machine through generated native C without rebuilding
# a compiler or the player's runtime archive.
env -u DISPLAY -u WAYLAND_DISPLAY "$toolchain/build/bin/ziran" build --project "$@" --target=c --no-main --root "$root" \
    --bind controls:AppServiceHost=shared_progress_behavior:FakeService \
    --bind controls:AppRecordHost=shared_progress_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=shared_progress_behavior:FakeSave \
    --entry shared_progress_behavior:Check -o "$work/c" "$root/tests/shared_progress_behavior.zi"
cat > "$work/c/main.c" <<'C'
#include <stdio.h>
#include "shared_progress_behavior.h"
int main(void) {
    int result = Check();
    if (result != 42) fprintf(stderr, "Shared progress native local test failed: %d\n", result);
    return result != 42;
}
C
includes=$(find "$work/c" -type d -printf ' -iquote %p')
# shellcheck disable=SC2046,SC2086
"${CC:-cc}" -std=c11 -O1 -ffunction-sections -fdata-sections -I"$toolchain/include" $includes \
    $(find "$work/c" -name '*.c') "$root/build/ziran/libziran.a" -Wl,--gc-sections -lm -lpthread -o "$work/native"
"$work/native"
echo 'Shared progress local tests passed in portable VM and native C: durable owner saves, failed flush/rebind, hydrate-before-put, dirty during pending put, guest/A/B isolation, active boards and same-owner reset'
