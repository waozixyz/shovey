#!/bin/sh
set -eu
unset DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER GDK_DISPLAY
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
toolchain=${1:?usage: editor_sharing_test.sh TOOLCHAIN}
cd "$root"
work="$root/build/editor-sharing-test"
mkdir -p "$work"
"$toolchain/build/bin/ziran" bundle --project --root "$root/src" --module-path "$root/tests" \
 --bind editor_view:AppServiceHost=editor_sharing_behavior:FakeService \
 --bind editor_view:SaveAppRecordHost=editor_sharing_behavior:FakeSave \
 --bind editor_view:AppRecordHost=editor_sharing_behavior:FakeRecord \
 --bind editor_view:AppLocaleHost=editor_sharing_behavior:FakeLocale \
 --bind editor_view:SmoothFramesHost=editor_sharing_behavior:FakeSmooth \
 --entry editor_sharing_behavior:Check -o "$work/sharing.zx" "$root/tests/editor_sharing_behavior.zi"
result=$("$toolchain/build/bin/ziran" run "$work/sharing.zx")
test "$result" = 42 || { echo "Editor sharing local test failed: $result" >&2; exit 1; }
echo 'Editor sharing: real client lifecycle, owner cancellation, errors and accepted/rejected route proofs passed'

"$toolchain/build/bin/ziran" build --project --target=c --no-main --root "$root/src" --module-path "$root/tests" \
 --bind editor_view:AppServiceHost=editor_sharing_behavior:FakeService \
 --bind editor_view:SaveAppRecordHost=editor_sharing_behavior:FakeSave \
 --bind editor_view:AppRecordHost=editor_sharing_behavior:FakeRecord \
 --bind editor_view:AppLocaleHost=editor_sharing_behavior:FakeLocale \
 --bind editor_view:SmoothFramesHost=editor_sharing_behavior:FakeSmooth \
 --entry editor_sharing_behavior:Check -o "$work/c" "$root/tests/editor_sharing_behavior.zi"
cat > "$work/c/main.c" <<'C'
#include <stdio.h>
#include "editor_sharing_behavior.h"
int main(void) {
    int result = Check();
    if (result != 42) fprintf(stderr, "Editor sharing native result: %d\n", result);
    return result == 42 ? 0 : 1;
}
C
includes=$(find "$work/c" -type d -printf ' -iquote %p')
# shellcheck disable=SC2046,SC2086
"${CC:-cc}" -std=c11 -O1 -ffunction-sections -fdata-sections -I"$toolchain/include" $includes \
 $(find "$work/c" -name '*.c') "$root/build/ziran/libziran.a" -Wl,--gc-sections -lm -lpthread -o "$work/native"
"$work/native"
echo 'Editor sharing: native consumer local tests passed'
