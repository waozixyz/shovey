#!/bin/sh
set -eu
unset DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER GDK_DISPLAY
export YUE_DESKTOP_RECOVERY=0
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
# UI copy and real sprite references are part of this screen's contract.
python3 - <<'PYTEST'
from pathlib import Path
import re
source = Path('src/shop_view.zi').read_text()
keys = set(re.findall(r'shovey_shop_[a-z_]+', source))
locales = list(Path('src/locales').glob('*.txt'))
assert len(locales) == 12
for locale in locales:
    text = locale.read_text()
    for key in keys:
        assert text.count(f'[{key}]') == 1, (locale, key)
        assert re.search(r'\[' + key + r'\]\n[^\n]+\n---', text), (locale, key)
for path in re.findall(r'"(assets/[^\"]+\.png)"', source):
    assert Path(path).is_file(), path
for skin in range(1, 8):
    for kind in ('player', 'charged'):
        for direction in ('left', 'up', 'right', 'down'):
            for folder in ('assets/shovey/sprites', 'assets/shovey-landscape/sprites'):
                path = Path(folder) / f'skin-{skin}-{kind}-{direction}.png'
                assert path.is_file(), path
print(f'Shop copy/assets: {len(keys)} keys in 12 locales and all portrait/landscape skin facings passed')
PYTEST
fixture=${1:-}
flags=--locked
if [ -f ziran.local.toml ]; then flags=; fi
toolchain=$(./scripts/ziran.sh pkg path ziran $flags)
kryon=$(./scripts/ziran.sh pkg path kryon $flags)
entity=$(./scripts/ziran.sh pkg path entity $flags)
work="$root/build/tests/shop-view-test"
git check-ignore -q "$work"
mkdir -p "$work"
if [ "$fixture" != --fixture-only ]; then
"$toolchain/build/bin/ziran" bundle --project --root "$root/src" \
    --module-path "$root/tests" \
    --bind-host shop_view_test \
    --entry shop_view_test:Check -o "$work/view.zx" "$root/tests/shop_view_test.zi"
result=$("$toolchain/build/bin/ziran" run "$work/view.zx")
test "$result" = 42 || { echo "Shop view local test failed: $result" >&2; exit 1; }
echo 'Shop view local tests: narrow/wide widget bounds, routes, Back, confirmation/cancel, coin purchase, Dew/profile/leaderboard links and daily claim passed'

fi

# Optional native fixture uses Kryon's existing software rasterizer only.
# It has no display, input, network or player process.
if [ "$fixture" = --fixture ] || [ "$fixture" = --fixture-only ]; then
    native="$work/native"
    "$toolchain/build/bin/ziran" build --target=c --no-main --root "$root" \
        --module-path "$root/tests" \
        --module-path "$toolchain/std" --module-path "std=$toolchain/std" \
        --module-path "entity=$entity/src" \
        --module-path "kryon=$kryon/src/ui" --module-path "kryon=$kryon/src/backend" \
        --bind-host shop_view_test --define SHOVEY_SHOP_FIXTURE \
        --entry shop_view_test:Fixture -o "$native" "$root/tests/shop_view_test.zi"
    cat > "$native/main.c" <<'C'
#include <stdio.h>
#include "shop_view_test.h"
int main(void) {
    int result = Fixture();
    if (result != 42) fprintf(stderr, "Shop raster fixture failed: %d\n", result);
    return result == 42 ? 0 : 1;
}
C
    includes=$(find "$native" -type d -printf ' -iquote %p')
    # shellcheck disable=SC2046,SC2086
    "${CC:-cc}" -std=c11 -O1 -ffunction-sections -fdata-sections -I"$toolchain/include" $includes \
        $(find "$native" -name '*.c') "$root/build/ziran/libziran.a" \
        -Wl,--gc-sections -lm -lpthread -lz -ldl -o "$work/fixture"
    "$work/fixture"
    echo 'Shop/chest native raster fixtures: work/shop-view-test/shop.png and chest.png'
fi
