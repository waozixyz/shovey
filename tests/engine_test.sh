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
    if [ "$edition" = import ]; then
        # Import fixtures must leave room for additions and exist in public builds.
        mkdir -p "$work/levels" "$work/build"
        python3 - "$root" "$work" <<'PYTEST'
import importlib.util, json, sys
from pathlib import Path
root, work = map(Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location('levels_tool', root / 'tools/levels/levels.py')
levels = importlib.util.module_from_spec(spec)
spec.loader.exec_module(levels)
classic = json.loads((root / 'levels/approved.json').read_text())['levels'][:2]
classic.append(levels.finale(3))
def rows(values):
    return [''.join(f'{v:02x}' for v in values[at:at+12]) for at in range(0, 240, 12)]
terrain = [int(3 <= at % 12 <= 8 and 5 <= at // 12 <= 14) for at in range(240)]
objects = [0] * 240
objects[7 * 12 + 5], objects[12 * 12 + 7] = 56, 75
island = [dict(number=n, name=name, terrain=rows(terrain), objects=rows(objects), solution='3333322')
          for n, name in enumerate(('First Landing', 'Test Shore', 'Test Lagoon'), 1)]
for edition, boards in (('classic', classic), ('island', island)):
    (work / 'levels' / (edition + '.json')).write_text(json.dumps(
        dict(edition=edition, width=12, height=20, levels=boards), indent=1, ensure_ascii=False) + '\n')
PYTEST
        (cd "$work" && ./test)
    else
        (cd "$root" && "$work/test")
    fi
done
echo 'Engines: opening the newest level, progress, saves and every board load passed for both editions'
echo 'Editor: painting, coast, undo, records, play proofs, export, shared collections and the Ziran solver passed'
echo 'Import: level files rewritten byte for byte, proven levels merged, unproven ones refused'
