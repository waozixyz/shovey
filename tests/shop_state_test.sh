#!/bin/sh
# Fake account, ledger and storage only: no network or actual Dew spending.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
unset DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER GDK_DISPLAY
export YUE_DESKTOP_RECOVERY=0
lock_flags=--locked
if [ -f ziran.local.toml ]; then lock_flags=; fi
toolchain=$(./scripts/ziran.sh pkg path ziran $lock_flags)
entity=$(./scripts/ziran.sh pkg path entity $lock_flags)
kryon=$(./scripts/ziran.sh pkg path kryon $lock_flags)
work="$root/build/tests/shop-state-test"
git check-ignore -q "$work"
mkdir -p "$work"
"$toolchain/build/bin/ziran" bundle --project --root "$root/src" \
    --module-path "$root/tests" \
    --bind-host shop_state_behavior \
    --bind controls:AppServiceHost=shop_state_behavior:FakeService \
    --bind controls:AppRecordHost=shop_state_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=shop_state_behavior:FakeSave \
    --entry shop_state_behavior:Check -o "$work/shop.zx" "$root/tests/shop_state_behavior.zi"
result=$("$toolchain/build/bin/ziran" run "$work/shop.zx")
test "$result" = 42 || { echo "Shop local test failed: $result" >&2; exit 1; }
echo 'Shop local tests: verified ownership, owner isolation, atomic coin spend, ledger replacement, skin selection and completion coin firstclears/replays/reload/rebind/failure recovery passed'
# Run the same production state transitions through native C as well as VM.
"$toolchain/build/bin/ziran" build --project --target=c --no-main --root "$root/src" \
    --module-path "$root/tests" \
    --bind controls:AppServiceHost=shop_state_behavior:FakeService \
    --bind controls:AppRecordHost=shop_state_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=shop_state_behavior:FakeSave \
    --entry shop_state_behavior:Check -o "$work/c" "$root/tests/shop_state_behavior.zi"
cat > "$work/c/main.c" <<'C'
#include <stdio.h>
#include "shop_state_behavior.h"
int main(void) {
    int result = Check();
    if (result != 42) fprintf(stderr, "Shop native local test failed: %d\n", result);
    return result != 42;
}
C
includes=$(find "$work/c" -type d -printf ' -iquote %p')
# shellcheck disable=SC2046,SC2086
"${CC:-cc}" -std=c11 -O1 -ffunction-sections -fdata-sections -I"$toolchain/include" $includes \
    $(find "$work/c" -name '*.c') "$toolchain/build/libziran.a" -Wl,--gc-sections -lm -lpthread -o "$work/native"
env -u DISPLAY -u WAYLAND_DISPLAY "$work/native"
echo 'Shop wallet and completion rewards: native C local tests passed'
