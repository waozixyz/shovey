#!/bin/sh
set -eu
unset DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER GDK_DISPLAY
export YUE_DESKTOP_RECOVERY=0
cd "$(dirname "$0")/.."
python3 tests/shop_host_test.py
