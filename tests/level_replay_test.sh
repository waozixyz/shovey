#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
toolchain=${1:?usage: level_replay_test.sh TOOLCHAIN}
entity=$(cd "$root" && "$toolchain/build/bin/ziran" pkg path entity)
daochi=$(cd "$root" && "$toolchain/build/bin/ziran" pkg path DaochiClient)
crypto=$(cd "$root" && "$toolchain/build/bin/ziran" pkg path crypto)
work="$root/build/level-replay-test"
mkdir -p "$work"
"$toolchain/build/bin/ziran" bundle --root "$root" --module-path "$toolchain/std" \
    --module-path "std=$toolchain/std" --module-path "entity=$entity/src" \
    --module-path "daochi_client=$daochi" --module-path "crypto=$crypto/src" \
    --bind controls:AppServiceHost=completion_path_behavior:FakeService \
    --bind controls:AppRecordHost=completion_path_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=completion_path_behavior:FakeSave \
    --entry level_replay_behavior:Check -o "$work/path.zx" "$root/tests/level_replay_behavior.zi"
result=$("$toolchain/build/bin/ziran" run "$work/path.zx")
test "$result" = 42 || { echo "Level replay local test failed: $result" >&2; exit 1; }
echo 'Level replay: portable local tests passed'
mkdir -p "$work/c"
"$toolchain/build/bin/ziran" build --target=c --no-main --root "$root" \
    --module-path "$toolchain/std" --module-path "std=$toolchain/std" \
    --module-path "entity=$entity/src" --module-path "daochi_client=$daochi" --module-path "crypto=$crypto/src" \
    --bind controls:AppServiceHost=completion_path_behavior:FakeService \
    --bind controls:AppRecordHost=completion_path_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=completion_path_behavior:FakeSave \
    --entry level_replay_behavior:Check -o "$work/c" "$root/tests/level_replay_behavior.zi"
cat > "$work/c/main.c" <<'C'
#include <stdio.h>
#include "level_replay_behavior.h"
int main(int argc, char **argv) {
    if (argc == 2) {
        String text = UiFixture();
        if (!text.length) return 1;
        fwrite(text.data, 1, text.length, stdout);
        return 0;
    }
    int result = Check();
    if (result != 42) { fprintf(stderr, "Level replay native result: %d\n", result); return 1; }
    return 0;
}
C
includes=$(find "$work/c" -type d -printf ' -iquote %p')
# shellcheck disable=SC2046,SC2086
"${CC:-cc}" -std=c11 -O1 -ffunction-sections -fdata-sections -I"$toolchain/include" $includes \
    $(find "$work/c" -name '*.c') "$root/build/ziran/libziran.a" -Wl,--gc-sections -lm -lpthread -o "$work/native"
"$work/native"
echo 'Level replay: native local tests passed; changed-route dot, opening acknowledgement, cosmetic edits, account isolation, portals, slides and bounded replay'
