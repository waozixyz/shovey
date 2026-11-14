#!/bin/sh
# Fake shop answers only: no account, network, display or Dew spending.
set -eu
unset DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER GDK_DISPLAY
export YUE_DESKTOP_RECOVERY=0
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
python3 - <<'PYTEST'
from pathlib import Path
import re
source = Path('src/island_unlock.zi').read_text()
keys = set(re.findall(r'shovey_(?:island|shop)_[a-z]+(?:_[a-z]+)*', source))
locales = list(Path('src/locales').glob('*.txt'))
assert len(locales) == 12 and len(keys) >= 9
for locale in locales:
    text = locale.read_text()
    for key in keys:
        assert text.count(f'[{key}]') == 1, (locale, key)
        assert re.search(r'\[' + key + r'\]\n[^\n]+\n---', text), (locale, key)
print(f'Island copy: {len(keys)} keys in 12 locales')
PYTEST
flags=--locked
if [ -f ziran.local.toml ]; then flags=; fi
toolchain=$(./scripts/ziran.sh pkg path ziran $flags)
kryon=$(./scripts/ziran.sh pkg path kryon $flags)
entity=$(./scripts/ziran.sh pkg path entity $flags)
work="$root/build/tests/island-unlock-test"
git check-ignore -q "$work"
mkdir -p "$work"
native="$work/native"
rm -rf "$native"
"$toolchain/build/bin/ziran" build --project --target=c --no-main --root "$root/src" \
    --module-path "$root/tests" \
    --bind-host island_unlock_test \
    --bind island_unlock:AppLocaleHost=island_unlock_test:FakeLocale \
    --entry island_unlock_test:Check -o "$native" "$root/tests/island_unlock_test.zi"
cat > "$native/main.c" <<'C'
#include <stdio.h>
#include "island_unlock_test.h"
int main(void) {
    int result = Check();
    if (result != 42) fprintf(stderr, "Island unlock local test failed: %d\n", result);
    return result == 42 ? 0 : 1;
}
C
includes=$(find "$native" -type d -printf ' -iquote %p')
# shellcheck disable=SC2046,SC2086
"${CC:-cc}" -std=c11 -O1 -ffunction-sections -fdata-sections -I"$toolchain/include" $includes \
    $(find "$native" -name '*.c') "$root/build/ziran/libziran.a" -Wl,--gc-sections -lm -lpthread -lz -ldl -o "$work/unlock"
"$work/unlock"
echo 'Island unlock local tests: exact quote, one press at the shown price, refusals, offline restore, remembered unlock and account isolation passed'
