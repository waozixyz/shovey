#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
toolchain=${1:?usage: completion_path_test.sh TOOLCHAIN}
entity=$(cd "$root" && "$toolchain/build/bin/ziran" pkg path entity)
daochi=$(cd "$root" && "$toolchain/build/bin/ziran" pkg path DaochiClient)
crypto=$(cd "$root" && "$toolchain/build/bin/ziran" pkg path crypto)
work="$root/build/completion-path-test"
mkdir -p "$work"
"$toolchain/build/bin/ziran" bundle --root "$root" --module-path "$toolchain/std" \
    --module-path "std=$toolchain/std" --module-path "entity=$entity/src" \
    --module-path "daochi_client=$daochi" --module-path "crypto=$crypto/src" \
    --bind controls:AppServiceHost=completion_path_behavior:FakeService \
    --bind controls:AppRecordHost=completion_path_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=completion_path_behavior:FakeSave \
    --entry completion_path_behavior:Check -o "$work/path.zx" "$root/tests/completion_path_behavior.zi"
result=$("$toolchain/build/bin/ziran" run "$work/path.zx")
test "$result" = 42 || { echo "Completion path local test failed: $result" >&2; exit 1; }
echo 'Classic paths: zero service calls during moves, checkpoint resume, exact slide/portal trace, actual move counts, owner/map bests, qualifying replay, one completion submission and bounded local chunks'
mkdir -p "$work/c"
"$toolchain/build/bin/ziran" build --target=c --no-main --root "$root" \
    --module-path "$toolchain/std" --module-path "std=$toolchain/std" \
    --module-path "entity=$entity/src" --module-path "daochi_client=$daochi" --module-path "crypto=$crypto/src" \
    --bind controls:AppServiceHost=completion_path_behavior:FakeService \
    --bind controls:AppRecordHost=completion_path_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=completion_path_behavior:FakeSave \
    --entry completion_path_behavior:Check -o "$work/c" "$root/tests/completion_path_behavior.zi"
cat > "$work/c/main.c" <<'C'
#include <stdio.h>
#include "completion_path_behavior.h"
int main(int argc, char **argv) {
    int result = Check();
    if (result != 42) { fprintf(stderr, "Classic path native result: %d\n", result); return 1; }
    if (argc == 2) {
        FILE *out = fopen(argv[1], "wb"); if (!out) return 1;
        for (int at = 0; at < fixture_count; ++at) {
            String fixture = fixtures[at];
            fwrite(fixture.data, 1, fixture.length, out); fputc('\n', out);
        }
        if (fclose(out)) return 1;
    }
    return 0;
}
C
includes=$(find "$work/c" -type d -printf ' -iquote %p')
# shellcheck disable=SC2046,SC2086
"${CC:-cc}" -std=c11 -O1 -ffunction-sections -fdata-sections -I"$toolchain/include" $includes \
    $(find "$work/c" -name '*.c') "$root/build/ziran/libziran.a" -Wl,--gc-sections -lm -lpthread -o "$work/native"
"$work/native" "$work/evidence.jsonl"
echo 'Classic paths: portable VM and native C local tests passed, including all 175 stored routes with contiguous slide/portal traces'
