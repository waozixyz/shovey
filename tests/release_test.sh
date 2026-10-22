#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
toolchain=${1:?usage: release_test.sh TOOLCHAIN}
unset DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS
work="$root/build/release-test"
mkdir -p "$work/c"
"$toolchain/build/bin/ziran" build --target=c --no-main --define SHOVEY_RELEASE \
    --entry release_behavior:Check --root "$root/tests" --module-path "$toolchain/std" \
    --module-path "std=$toolchain/std" -o "$work/c" "$root/tests/release_behavior.zi"
cat > "$work/main.c" <<'C'
#include <stdio.h>
#include "release_behavior.h"
int main(void) { int result = Check(); if (result) fprintf(stderr, "release check %d failed\n", result); return result; }
C
includes=$(find "$work/c" -type d -printf ' -iquote %p')
${CC:-cc} -std=c11 -O2 -I"$toolchain/include" $includes "$work/main.c" $(find "$work/c" -name '*.c') \
    "$root/build/ziran/libziran.a" -Wl,--gc-sections -lm -lpthread -o "$work/test"
"$work/test"
echo 'Release: approved campaign playable, later levels and Island absent, last win and older campaign progress preserved'
