#!/usr/bin/env python3
"""The shipped Island chapter uses its approved upward first-30 map."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MAP_SOURCE = ROOT / "src/island/island_map.zi"
VIEW_SOURCE = ROOT / "src/island/island_view.zi"
APPROVED = ROOT / "work/island-map-v3/island-map-v3-portrait-first-30-upward-proposal.png"
RECEIPT = ROOT / "work/island-map-v3/first-30-upward-proposal-receipt.json"
INSTALLED = ROOT / "assets/shovey-island/world-map/island-map-portrait.png"
PACKAGE = ROOT / "packaging/compiled/shovey-island.zx"
PACKAGE_DESCRIPTOR = ROOT / "packaging/island.json"
VERSION = ROOT / "version.json"
RUNNABLE = ROOT / "build/player/linux/shovey"
RUNNABLE_COLLECTION = ROOT / "build/player/linux/shovey.zx"
RUNNABLE_RECEIPT = ROOT / "build/player/linux/shovey.json"
ZIRAN = ROOT / "scripts/ziran.sh"
EXPECTED_SHA256 = "8030c8eab981178d229c3b0710783577e33e1d0e4d69251b830fc499669a5ab5"


if not MAP_SOURCE.is_file():
    print("Private Island source unavailable; upward first-30 map test skipped")
    raise SystemExit(0)

for path in (VIEW_SOURCE, APPROVED, RECEIPT, INSTALLED):
    assert path.is_file(), path

receipt = json.loads(RECEIPT.read_text())
assert receipt["sha256"] == EXPECTED_SHA256
assert receipt["native_dimensions"] == "724x2172"
prompt = receipt["exact_prompt"]
assert "Bottom first landing: a small OPEN weathered WOODEN PORT" in prompt
assert "Do NOT include the wooden houseboat" in prompt
assert "The 30th landing near the top should feel like the route continues upward" in prompt
assert hashlib.file_digest(APPROVED.open("rb"), "sha256").hexdigest() == EXPECTED_SHA256
assert APPROVED.read_bytes() == INSTALLED.read_bytes(), "Installed map changed the approved source bytes"
with Image.open(INSTALLED) as image:
    assert image.size == (724, 2172) and image.format == "PNG" and image.mode == "RGB"

art = json.loads((ROOT / "assets/shovey-island/art.json").read_text())
maps = [item for item in art["files"] if item["path"].startswith("world-map/island-map-")]
assert maps == [{
    "path": "world-map/island-map-portrait.png",
    "depicts": "first 30 Island landings climbing upward from the wooden port",
    "sha256": EXPECTED_SHA256,
}]
assert not (INSTALLED.parent / "island-map-portrait.webp").exists()
assert not (INSTALLED.parent / "island-map-landscape.webp").exists()

source = MAP_SOURCE.read_text()
matches = re.findall(
    r"if level == (\d+) \{ return Vector2\.\{([0-9.]+), ([0-9.]+)\} \}",
    source,
)
assert [int(level) for level, _, _ in matches] == list(range(1, 31))
points = [(float(x), float(y)) for _, x, y in matches]
xs = [point[0] for point in points]
ys = [point[1] for point in points]
assert all(later < earlier for earlier, later in zip(ys, ys[1:])), "Every level must climb upward"
assert ys[0] > 0.90 and ys[-1] < 0.05, "The chapter must travel from the bottom port to the map top"
assert all(0.25 <= x <= 0.70 for x in xs), "The route left its central vertical corridor"
assert max(xs) - min(xs) < 0.40, "The route became a full-width horizontal sweep"
assert max(abs(later - earlier) for earlier, later in zip(xs, xs[1:])) < 0.30
marker_x = 29 / 724
marker_y = 29 / 2172
assert all(marker_x < x < 1 - marker_x and marker_y < y < 1 - marker_y for x, y in points)

view = VIEW_SOURCE.read_text()
levels = view[view.index("IslandLevels ::"):view.index("\nIslandInventory ::")]
assert 'asset_path="assets/shovey-island/world-map/island-map-portrait.png"' in levels
assert "island-map-landscape" not in levels and "IslandMapLandscapePoint" not in view
assert levels.count("point := IslandMapPoint(") == 2
assert ".horizontal=false" in levels
assert ".content_height=cast(s32)art_height" in levels
assert "point.y * art_height - viewport.height * 0.5" in levels
assert "ifx landscape" not in levels

# Startup and Back use the same state machine as Classic, rather than the old
# Island board landing screen or a one-off approximation.
classic = (ROOT / "src/shovey_view.zi").read_text()
classic_node = (ROOT / "src/shovey.zi").read_text()
island_node = (ROOT / "src/island/island.zi").read_text()
start = view[view.index("IslandStart ::"):view.index("\n// Opens or closes the sticker book")]
assert "IslandOpenLevels()" in start and "island_selector_from_cover = true" in start
assert "IslandOpenLevels ::" in view
assert "island_map_focus = island_game.level" in view
assert "island_selector_from_cover = false" in view
assert "IslandBack :: () -> bool" in view and "IslandBackToMap :: () -> bool" in view
assert "playing := IslandPlaying()" in island_node
assert "IslandBack() || (playing && IslandBackToMap())" in island_node
assert "playing := ShoveyPlaying()" in classic_node
assert "ShoveyBack() || (playing && ShoveyBackToMap())" in classic_node
assert "selector_from_cover = !mini" in classic

# Prove both package layers used by the stable runnable. The private bundle
# must contain the exact approved PNG, and the collection receipt plus Ziran's
# own inspector must identify that exact reviewed bundle in shovey.zx.
for path in (PACKAGE, PACKAGE_DESCRIPTOR, VERSION, RUNNABLE, RUNNABLE_COLLECTION, RUNNABLE_RECEIPT, ZIRAN):
    assert path.is_file(), f"Build the stable Linux player before this test: missing {path}"
descriptor = json.loads(PACKAGE_DESCRIPTOR.read_text())
release = json.loads(VERSION.read_text())
assert PACKAGE.stat().st_size == descriptor["bytes"]
assert hashlib.file_digest(PACKAGE.open("rb"), "sha256").hexdigest() == descriptor["sha256"]
assert PACKAGE.read_bytes().count(INSTALLED.read_bytes()) == 1, "Compiled Island does not carry the approved map bytes"
collection_receipt = json.loads(RUNNABLE_RECEIPT.read_text())
assert collection_receipt["version"] == release["version"], "Stable player is from an older Shovey release"
assert hashlib.file_digest(RUNNABLE_COLLECTION.open("rb"), "sha256").hexdigest() == collection_receipt["sha256"]
island_child = next(item for item in collection_receipt["children"] if item["id"] == descriptor["id"])
assert island_child["sha256"] == descriptor["sha256"] and island_child["bytes"] == descriptor["bytes"]
inspection = subprocess.run(
    [str(ZIRAN), "inspect", str(RUNNABLE_COLLECTION)],
    check=True, text=True, stdout=subprocess.PIPE,
).stdout
assert f"asset assets/paid/shovey-island.zx bytes={descriptor['bytes']}" in inspection
assert RUNNABLE.stat().st_mode & 0o111
latest_player_source = max((ROOT / path).stat().st_mtime_ns for path in (
    "scripts/player.py", "src/player_desktop.zi", "src/player_entity.zi", "src/player_host.zi", "ziran.lock",
))
assert RUNNABLE.stat().st_mtime_ns >= latest_player_source, "Stable executable predates its player sources"

print(
    "Island map local test passed: map-first Classic startup/back flow; approved "
    "first-30 bytes in the reviewed Island package and stable Linux player; "
    "portrait and wide consumers scroll vertically"
)
