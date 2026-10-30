#!/bin/sh
set -eu
unset DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER GDK_DISPLAY
export YUE_DESKTOP_RECOVERY=0
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
toolchain=${1:?usage: editor_field_test.sh TOOLCHAIN}
cd "$root"
entity=$(ziran pkg path entity)
kryon=$(ziran pkg path kryon)
apps=$(ziran pkg path apps)
mingcute=$(ziran pkg path mingcute)
work="$root/work/editor-field-test"
mkdir -p "$work"
set -- --root "$root" --module-path "$root/tests" --module-path "$toolchain/std" \
 --module-path "std=$toolchain/std" --module-path "entity=$entity/src" \
 --module-path "kryon=$kryon/src/ui" --module-path "kryon=$kryon/src/backend" \
 --module-path "apps=$apps/src" --module-path "mingcute=$mingcute/src" \
 --bind-host editor_field_host
native_test() {
    module=$1
    shift
    output="$work/$module-c"
"$toolchain/build/bin/ziran" build --target=c --no-main "$@" --entry "$module:Check" -o "$output" "$root/tests/$module.zi"
cat > "$output/main.c" <<C
#include <stdio.h>
#include "$module.h"
int main(void) {
    int result = Check();
    if (result != 42) fprintf(stderr, "Editor field native result: %d\\n", result);
    return result == 42 ? 0 : 1;
}
C
includes=$(find "$output" -type d -printf ' -iquote %p')
# shellcheck disable=SC2046,SC2086
"${CC:-cc}" -std=c11 -O1 -ffunction-sections -fdata-sections -I"$toolchain/include" $includes \
 $(find "$output" -name '*.c') "$root/build/ziran/libziran.a" -Wl,--gc-sections -lm -lpthread -o "$work/$module-native"
"$work/$module-native"
echo "$module: native local tests passed"
}
"$toolchain/build/bin/ziran" bundle "$@" --entry editor_field_legacy_behavior:Check -o "$work/legacy.zx" "$root/tests/editor_field_legacy_behavior.zi"
result=$("$toolchain/build/bin/ziran" run "$work/legacy.zx")
test "$result" = 42 || { echo "Legacy field baseline failed: $result" >&2; exit 1; }
echo 'Editor field: existing widget accepts select-all replacement of malformed legacy bytes'
native_test editor_field_legacy_behavior "$@"
"$toolchain/build/bin/ziran" bundle "$@" --entry editor_field_behavior:Check -o "$work/field.zx" "$root/tests/editor_field_behavior.zi"
result=$("$toolchain/build/bin/ziran" run "$work/field.zx")
test "$result" = 42 || { echo "Editor field portable local test failed: $result" >&2; exit 1; }
echo 'Editor field: portable typing, Unicode selection, capacity, Enter, focus, scroll, paint and persisted collection rename passed'
native_test editor_field_behavior "$@"
