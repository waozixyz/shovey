#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
toolchain=${1:?usage: secret_travel_test.sh TOOLCHAIN}
work="$root/build/secret-travel-test"
mkdir -p "$work"
"$toolchain/build/bin/ziran" bundle --root "$root" --module-path "$toolchain/std" \
    --module-path "std=$toolchain/std" --entry secret_behavior:Check \
    -o "$work/secret.zx" "$root/tests/secret_behavior.zi"
result=$("$toolchain/build/bin/ziran" run "$work/secret.zx")
test "$result" = 0 || { echo "Secret beach local test failed: $result" >&2; exit 1; }
echo 'Hidden 29a: genuine beach approach, all nine entrances, chest and engine win, exact parent-state return, no campaign unlock, invalid edges rejected, existing secret beaches preserved'
