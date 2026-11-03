#!/bin/sh
# Run the map selection UI test on an isolated display and private profile.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
scratch="$root/work/world-map-selection-test/tmp"
git check-ignore -q "$scratch"
mkdir -p "$scratch"

exec env -u DISPLAY -u XAUTHORITY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
    -u SESSION_MANAGER -u GDK_DISPLAY \
    TMPDIR="$scratch" YUE_DESKTOP_RECOVERY=0 SDL_AUDIODRIVER=dummy APP_NO_TRAY=1 \
    timeout 240s xvfb-run -a -n 400 -s '-screen 0 1280x1000x24' \
    python3 tests/world_map_selection_ui_test.py \
    --binary "$root/build/player/linux/shovey" \
    --driver-source "${UI_DRIVER_SOURCE:-$root/../../apps/breeze}" "$@"
