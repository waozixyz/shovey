#!/bin/sh
# Builds build/solver/shovey-solve-classic and build/solver/shovey-solve-island:
# each edition's engine and wrapper compiled to C, linked with solver.c.
#
#   tools/solver/build.sh
#
# ZIRAN_TOOLCHAIN overrides the locked Ziran checkout; CC and CFLAGS apply.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
toolchain=${ZIRAN_TOOLCHAIN:-"$HOME/.cache/ziran/sources/p86cd37cbd504a4ae"}
out=${SOLVER_OUT:-"$root/build/solver"}
lib="$root/build/ziran/libziran.a"

# The engines import their boards from the generated level code.
for file in levels.zi island_levels.zi; do
    [ -f "$root/apps/shovey/$file" ] || { echo "missing apps/shovey/$file; run make levels" >&2; exit 1; }
done

[ -f "$lib" ] || make -s -C "$toolchain" BUILD_DIR="$root/build/ziran" "$lib"

for edition in classic island; do
    work="$out/$edition"
    rm -rf "$work"
    mkdir -p "$work/c"
    "$toolchain/build/bin/ziran" build --target=c --no-main --root "$root/tools/solver" \
        --module-path "$toolchain/std" -o "$work/c" "$root/tools/solver/${edition}_api.zi"
    define=$(echo "SHOVEY_$edition" | tr '[:lower:]' '[:upper:]')
    includes=$(find "$work/c" -type d -printf ' -iquote %p')
    # shellcheck disable=SC2046,SC2086
    "${CC:-cc}" -std=c11 ${CFLAGS:--O2} -D"$define" -I"$toolchain/include" $includes \
        "$root/tools/solver/solver.c" $(find "$work/c" -name '*.c') "$lib" \
        -Wl,--gc-sections -lm -lpthread -o "$out/shovey-solve-$edition"
done
echo "built $out/shovey-solve-classic and $out/shovey-solve-island"
