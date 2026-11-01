#!/usr/bin/env python3
"""Generate Shovey shop icons and character skins from committed source art."""
import argparse
import hashlib
import io
import json
import subprocess
import sys
from collections import deque
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ICON_SOURCE = ROOT / "design/shop-icons-source.png"
ICON_NAMES = (
    "chest-closed",
    "chest-open",
    "coins",
    "dew",
    "stall",
    "trophy",
    "profile",
    "settings",
)
ICON_DEPICTS = {
    "chest-closed": "closed shop treasure chest with Shovey's wooden and gold theme",
    "chest-open": "opened shop treasure chest revealing coins and a Dew drop",
    "coins": "stack of Shovey coins with the character's green face",
    "dew": "large blue Dew drop with highlights and a small splash",
    "stall": "Shovey's shop stall with a striped awning and wooden counter",
    "trophy": "golden leaderboard trophy on a green emblem",
    "profile": "profile icon showing Shovey beside a card and progress line",
    "settings": "settings icon with a gear and Shovey-themed controls",
}
SKIN_NAMES = {
    1: "ember",
    2: "frost",
    3: "berry",
    4: "night",
    5: "crystal",
    6: "stone",
    7: "gold",
}
SKIN_RAMPS = {
    1: ((116, 26, 12), (236, 83, 42), (255, 168, 91)),
    2: ((99, 151, 186), (188, 229, 244), (242, 251, 255)),
    3: ((100, 22, 92), (201, 55, 175), (255, 143, 221)),
    4: ((20, 13, 75), (53, 42, 162), (176, 197, 255)),
    5: ((14, 95, 118), (36, 188, 216), (248, 110, 194)),
    6: ((61, 64, 68), (132, 136, 141), (205, 209, 213)),
    7: ((122, 74, 10), (232, 166, 32), (255, 227, 136)),
}
FACINGS = ("up", "down", "left", "right")


def is_near_white(color):
    return min(color) >= 225 and max(color) - min(color) <= 25


def icon_spans(image):
    width, height = image.size
    pixels = image.load()
    spans = []
    start = None
    for x in range(width + 1):
        active = x < width and any(not is_near_white(pixels[x, y]) for y in range(height))
        if active and start is None:
            start = x
        if not active and start is not None:
            spans.append((start, x - 1))
            start = None
    if len(spans) != len(ICON_NAMES):
        raise ValueError(f"expected {len(ICON_NAMES)} icon columns, found {len(spans)}")
    return spans


def largest_icon_component(image, span):
    width, height = image.size
    pixels = image.load()
    left, right = span
    visited = set()
    largest = []
    for x in range(left, right + 1):
        for y in range(height):
            if is_near_white(pixels[x, y]) or (x, y) in visited:
                continue
            queue = [(x, y)]
            component = []
            while queue:
                point = queue.pop()
                if point in visited:
                    continue
                visited.add(point)
                component.append(point)
                point_x, point_y = point
                for delta_x in (-1, 0, 1):
                    for delta_y in (-1, 0, 1):
                        neighbor = (point_x + delta_x, point_y + delta_y)
                        if (
                            left <= neighbor[0] <= right
                            and 0 <= neighbor[1] < height
                            and neighbor not in visited
                            and not is_near_white(pixels[neighbor])
                        ):
                            queue.append(neighbor)
            if len(component) > len(largest):
                largest = component
    if not largest:
        raise ValueError(f"no connected icon found in columns {span}")
    xs = [point[0] for point in largest]
    ys = [point[1] for point in largest]
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def nearest_strong_color(pixels, point, crop_size):
    x, y = point
    width, height = crop_size
    nearest = None
    nearest_distance = None
    for radius in range(1, 4):
        for candidate_x in range(max(0, x - radius), min(width, x + radius + 1)):
            for candidate_y in range(max(0, y - radius), min(height, y + radius + 1)):
                color = pixels[candidate_x, candidate_y]
                if is_near_white(color):
                    continue
                distance = (candidate_x - x) ** 2 + (candidate_y - y) ** 2
                if nearest_distance is None or distance < nearest_distance:
                    nearest = color
                    nearest_distance = distance
        if nearest is not None:
            return nearest
    return pixels[x, y]


def remove_resize_halo(image):
    pixels = image.load()
    opaque_colors = [
        (x, y)
        for y in range(image.height)
        for x in range(image.width)
        if pixels[x, y][3] == 255 and not is_near_white(pixels[x, y])
    ]
    if not opaque_colors:
        return image
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0 or alpha == 255 or not is_near_white((red, green, blue)):
                continue
            distance = min(
                (candidate_x - x) ** 2 + (candidate_y - y) ** 2
                for candidate_x, candidate_y in opaque_colors
            )
            if distance > 8 ** 2:
                continue
            nearest = min(
                opaque_colors,
                key=lambda point: (point[0] - x) ** 2 + (point[1] - y) ** 2,
            )
            pixels[x, y] = (*nearest[:3], alpha)
    return image


def soften_final_edge(image):
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            if pixels[x, y][3] == 0:
                continue
            touches_transparent = any(
                (not 0 <= neighbor_x < image.width)
                or (not 0 <= neighbor_y < image.height)
                or pixels[neighbor_x, neighbor_y][3] == 0
                for neighbor_x, neighbor_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
            )
            if touches_transparent:
                red, green, blue, _ = pixels[x, y]
                pixels[x, y] = (red, green, blue, 192)
    return image


def soften_outside_edge(crop):
    rgba = crop.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    background = [[False] * height for _ in range(width)]
    queue = deque()
    for x in range(width):
        for y in (0, height - 1):
            if is_near_white(pixels[x, y]):
                background[x][y] = True
                queue.append((x, y))
    for y in range(height):
        for x in (0, width - 1):
            if not background[x][y] and is_near_white(pixels[x, y]):
                background[x][y] = True
                queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        for delta_x, delta_y in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            neighbor_x, neighbor_y = x + delta_x, y + delta_y
            if (
                0 <= neighbor_x < width
                and 0 <= neighbor_y < height
                and not background[neighbor_x][neighbor_y]
                and is_near_white(pixels[neighbor_x, neighbor_y])
            ):
                background[neighbor_x][neighbor_y] = True
                queue.append((neighbor_x, neighbor_y))

    for x in range(width):
        for y in range(height):
            if background[x][y]:
                pixels[x, y] = (*pixels[x, y][:3], 0)
                continue
            if not is_near_white(pixels[x, y]):
                continue
            touches_background = any(
                0 <= x + delta_x < width
                and 0 <= y + delta_y < height
                and background[x + delta_x][y + delta_y]
                for delta_x, delta_y in ((-1, 0), (1, 0), (0, -1), (0, 1))
            )
            if not touches_background:
                continue
            observed = pixels[x, y][:3]
            strong = nearest_strong_color(pixels, (x, y), rgba.size)
            coverage = 1
            for observed_channel, strong_channel in zip(observed, strong):
                if strong_channel < 255:
                    coverage = max(
                        coverage,
                        (255 - observed_channel) / (255 - strong_channel),
                    )
            alpha = max(1, min(255, round(coverage * 255)))
            pixels[x, y] = (*strong, alpha)
    alpha_bbox = rgba.getchannel("A").getbbox()
    return rgba.crop(alpha_bbox)


def cut_icons(source):
    """Cut the eight generated shop icons from an unsegmented source image."""
    if isinstance(source, (str, Path)):
        with Image.open(source) as image:
            source_image = image.convert("RGB")
    else:
        source_image = source.convert("RGB")
    icons = {}
    for name, span in zip(ICON_NAMES, icon_spans(source_image)):
        crop_box = largest_icon_component(source_image, span)
        crop = source_image.crop(crop_box)
        icon = soften_outside_edge(crop)
        icon.thumbnail((240, 240), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        offset = ((256 - icon.width) // 2, (256 - icon.height) // 2)
        canvas.paste(icon, offset, icon)
        canvas = soften_final_edge(canvas)
        icons[name] = remove_resize_halo(canvas)
    return icons


def interpolate_ramp(ramp, position):
    scaled = position * (len(ramp) - 1)
    lower = min(int(scaled), len(ramp) - 2)
    amount = scaled - lower
    return tuple(
        round(lower_color + (upper_color - lower_color) * amount)
        for lower_color, upper_color in zip(ramp[lower], ramp[lower + 1])
    )


def recolor_skin(sprite, ramp):
    """Map Shovey's green body ramp to another colour without touching effects."""
    if isinstance(sprite, (str, Path)):
        with Image.open(sprite) as image:
            result = image.convert("RGBA").copy()
    else:
        result = sprite.convert("RGBA").copy()
    pixels = result.load()
    for x in range(result.width):
        for y in range(result.height):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0 or green <= red + 40 or green <= blue + 30 or green < 80:
                continue
            luminance = 0.299 * red + 0.587 * green + 0.114 * blue
            position = min(1.0, max(0.0, (luminance - 72.0) / 108.0))
            pixels[x, y] = (*interpolate_ramp(ramp, position), alpha)
    return result


def optimized_png(image):
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True, compress_level=9)
    return output.getvalue()


def expected_outputs():
    outputs = {}
    for name, icon in cut_icons(ICON_SOURCE).items():
        path = ROOT / f"assets/shovey/shop/{name}.png"
        outputs[path] = optimized_png(icon)
    for number, ramp in SKIN_RAMPS.items():
        for charged in (False, True):
            kind = "charged" if charged else "player"
            for facing in FACINGS:
                source = ROOT / f"assets/shovey/sprites/{kind}-{facing}.png"
                skin = recolor_skin(source, ramp)
                path = ROOT / f"assets/shovey/sprites/skin-{number}-{kind}-{facing}.png"
                outputs[path] = optimized_png(skin)
    return outputs


def manifest_with_new_art(outputs):
    path = ROOT / "assets/shovey/art.json"
    manifest = json.loads(path.read_text())
    entries = {item["path"]: item for item in manifest["files"]}
    for output in sorted(outputs):
        relative = output.relative_to(ROOT / "assets/shovey").as_posix()
        if relative.startswith("shop/"):
            depicts = ICON_DEPICTS[relative.removeprefix("shop/").removesuffix(".png")]
        else:
            number, kind, facing = relative.removeprefix("sprites/skin-").removesuffix(".png").split("-")
            skin_name = SKIN_NAMES[int(number)]
            state = "charged Shovey" if kind == "charged" else "Shovey"
            facing_name = {"up": "looking up", "down": "looking down", "left": "looking left", "right": "looking right"}[facing]
            depicts = f"{skin_name}-skinned {state} {facing_name}"
        entries[relative] = {
            "path": relative,
            "depicts": depicts,
            "sha256": hashlib.sha256(outputs[output]).hexdigest(),
        }
    manifest["files"] = [entries[path] for path in sorted(entries)]
    return path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated art is missing or different")
    arguments = parser.parse_args()
    outputs = expected_outputs()
    changed = []
    for path, data in outputs.items():
        if not path.is_file() or path.read_bytes() != data:
            changed.append(path.relative_to(ROOT).as_posix())
    manifest_path, manifest = manifest_with_new_art(outputs)
    if not manifest_path.is_file() or manifest_path.read_text() != manifest:
        changed.append(manifest_path.relative_to(ROOT).as_posix())
    if changed:
        if arguments.check:
            print("out of date: " + ", ".join(changed[:5]))
            return 1
        for path, data in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        manifest_path.write_text(manifest)
    landscape = subprocess.run(
        [sys.executable, str(ROOT / "tools/levels/landscape.py"), *(["--check"] if arguments.check else [])],
        cwd=ROOT,
        check=False,
    )
    if landscape.returncode:
        return landscape.returncode
    action = "checked" if arguments.check else "generated"
    print(f"Shop art: {action} ({len(outputs)} portrait files plus landscape skins)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
