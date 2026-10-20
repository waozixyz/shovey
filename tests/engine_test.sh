#!/bin/sh
# Compiles each edition's engine with its behavior checks, and the editor's
# rules with the Ziran solver, and runs them.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
toolchain=${1:?usage: engine_test.sh TOOLCHAIN}
lib="$root/build/ziran/libziran.a"
unset DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS
[ -f "$lib" ] || make -s -C "$toolchain" BUILD_DIR="$root/build/ziran" "$lib"
for edition in classic island editor import; do
    work="$root/build/engine-test/$edition"
    rm -rf "$work"
    mkdir -p "$work/c"
    "$toolchain/build/bin/ziran" build --target=c --no-main --entry "${edition}_behavior:Check" --root "$root/tests" \
        --module-path "$toolchain/std" --module-path "std=$toolchain/std" -o "$work/c" "$root/tests/${edition}_behavior.zi"
    cat > "$work/c/main.c" <<C
#include <stdio.h>
#include "${edition}_behavior.h"
int main(void) {
    int result = Check();
    if (result) fprintf(stderr, "$edition check %d failed\n", result);
    return result ? 1 : 0;
}
C
    includes=$(find "$work/c" -type d -printf ' -iquote %p')
    # shellcheck disable=SC2046,SC2086
    "${CC:-cc}" -std=c11 -O2 -I"$toolchain/include" $includes $(find "$work/c" -name '*.c') \
        "$lib" -Wl,--gc-sections -lm -lpthread -o "$work/test"
    (cd "$root" && "$work/test")
done
echo 'Engines: opening the newest level, progress, saves and every board load passed for both editions'
echo 'Editor: painting, coast, undo, records, play proofs, export, shared collections and the Ziran solver passed'
echo 'Import: level files rewritten byte for byte, proven levels merged, unproven ones refused'
