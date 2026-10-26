#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
toolchain=${1:?usage: guide_test.sh TOOLCHAIN}
work="$root/build/guide-test"
mkdir -p "$work"
"$toolchain/build/bin/ziran" bundle --root "$root" --module-path "$toolchain/std" \
    --module-path "std=$toolchain/std" --entry guide_behavior:Check \
    -o "$work/guide.zx" "$root/tests/guide_behavior.zi"
result=$("$toolchain/build/bin/ziran" run "$work/guide.zx")
test "$result" = 42 || { echo "Friend guide local test failed: $result" >&2; exit 1; }
mkdir -p "$work/c"
"$toolchain/build/bin/ziran" build --target=c --no-main --root "$root" \
    --module-path "$toolchain/std" --module-path "std=$toolchain/std" \
    --entry guide_behavior:Check -o "$work/c" "$root/tests/guide_behavior.zi"
cat > "$work/c/main.c" <<'C'
#include <stdio.h>
#include <stdlib.h>
#include "guide_behavior.h"
int main(int argc, char **argv) {
    if (argc == 2) {
        String saved = Fixture(atoi(argv[1]));
        if (!saved.length) return 1;
        fwrite(saved.data, 1, saved.length, stdout);
        return 0;
    }
    int result = Check();
    if (result != 42) { fprintf(stderr, "Friend guide native result: %d\n", result); return 1; }
    return 0;
}
C
includes=$(find "$work/c" -type d -printf ' -iquote %p')
# shellcheck disable=SC2046,SC2086
"${CC:-cc}" -std=c11 -O1 -ffunction-sections -fdata-sections -I"$toolchain/include" $includes \
    $(find "$work/c" -name '*.c') "$root/build/ziran/libziran.a" -Wl,--gc-sections -lm -lpthread -o "$work/native"
"$work/native"
echo 'Friend guide: first encounters, local seen records, manual replay, saved-attempt preservation, compound mechanics and secret-room exclusion'
