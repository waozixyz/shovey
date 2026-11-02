#!/bin/sh
set -eu
unset DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER GDK_DISPLAY
export YUE_DESKTOP_RECOVERY=0
cd "$(dirname "$0")/.."
flags=--locked
if [ -f ziran.local.toml ]; then flags=; fi
toolchain=$(./scripts/ziran.sh pkg path ziran $flags)
work="$PWD/work/collectibles-test"
git check-ignore -q "$work"
mkdir -p "$work"
"$toolchain/build/bin/ziran" bundle --root "$PWD" --module-path "$toolchain/std" --module-path "std=$toolchain/std" \
    --bind controls:AppServiceHost=collectibles_behavior:FakeService \
    --bind controls:AppRecordHost=collectibles_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=collectibles_behavior:FakeSave \
    --entry collectibles_behavior:Check -o "$work/collectibles.zx" tests/collectibles_behavior.zi
result=$("$toolchain/build/bin/ziran" run "$work/collectibles.zx")
test "$result" = 42 || { echo "Collectibles local test failed: $result" >&2; exit 1; }
"$toolchain/build/bin/ziran" build --target=c --no-main --root "$PWD" --module-path "$toolchain/std" --module-path "std=$toolchain/std" \
    --bind controls:AppServiceHost=collectibles_behavior:FakeService \
    --bind controls:AppRecordHost=collectibles_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=collectibles_behavior:FakeSave \
    --entry collectibles_behavior:Check -o "$work/c" tests/collectibles_behavior.zi
cat > "$work/c/main.c" <<'C'
#include <stdio.h>
#include "collectibles_behavior.h"
int main(void) {
    int result = Check();
    if (result != 42) fprintf(stderr, "Collectibles native local test failed: %d\n", result);
    return result != 42;
}
C
includes=$(find "$work/c" -type d -printf ' -iquote %p')
# shellcheck disable=SC2046,SC2086
"${CC:-cc}" -std=c11 -O1 -ffunction-sections -fdata-sections -I"$toolchain/include" $includes \
    $(find "$work/c" -name '*.c') "$PWD/build/ziran/libziran.a" -Wl,--gc-sections -lm -lpthread -o "$work/native"
"$work/native"
python3 - <<'PY'
from pathlib import Path
import re
src=Path('src/collectibles.zi').read_text()+Path('src/collectible_book.zi').read_text()
keys=set(re.findall(r'"(shovey_(?:book\w*|item_\w+))"',src))
for path in Path('src/locales').glob('*.txt'):
    text=path.read_text()
    for key in keys: assert text.count('['+key+']')==1,(path,key)
for icon in re.findall(r'"(assets/shovey/collectibles/[^\"]+)"',src): assert Path(icon).is_file(),icon
print('Collectibles local tests passed: record once, durable reload, guest/A/B isolation, deferred owner, failed storage retries, invalid records, all 16 book entries and 12 locales')
PY
