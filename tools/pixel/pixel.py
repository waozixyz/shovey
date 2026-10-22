#!/usr/bin/env python3
"""Classic Shovey's pixel sprites: 32 by 32 pictures shown four times larger.

    python3 tools/pixel/pixel.py generate [NAME ...]   # draw missing sprites
    python3 tools/pixel/pixel.py fit [NAME ...]        # fit kept pictures again
    python3 tools/pixel/pixel.py build                 # write assets/shovey/sprites

Ground tiles, walls, pits and markings are drawn here. Characters and objects
come from an image model asked for pixel art on magenta: preferably Google Flow
(free; save its downloads as backup/pixel-raw/NAME-N.jpg and run `fit`), or
OpenRouter through `generate` (paid; key OPENROUTER_API_KEY). `fit` finds the
model's grid, sizes the object and keeps the result in tools/pixel/native.
"""
import argparse
import base64
import colorsys
import hashlib
import io
import json
import math
import os
import random
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / 'tools/pixel'
NATIVE = HERE / 'native'
RAW = ROOT / 'backup/pixel-raw'
SPRITES = ROOT / 'assets/shovey/sprites'
SIZE, SCALE = 32, 4
MODEL = 'google/gemini-3.1-flash-image'
SPEC = json.loads((HERE / 'sprites.json').read_text())

# ---------------------------------------------------------------- generation


def magenta(pixels):
    r, g, b = (pixels[..., i].astype(int) for i in range(3))
    return (r > 170) & (b > 170) & (g < 110)


def extract(data):
    """The 32 by 32 sprite in a model's picture, and how well a grid fits it."""
    picture = np.asarray(Image.open(io.BytesIO(data)).convert('RGB'))
    mask = magenta(picture)
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return None, 999.0
    panel = picture[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    background = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    if background.all():
        return None, 999.0
    cell = panel.shape[1] / SIZE
    best = None
    for phase_x in np.linspace(0, cell, 8, endpoint=False):
        for phase_y in np.linspace(0, cell, 8, endpoint=False):
            cx = np.arange(phase_x + cell / 2, panel.shape[1], cell).astype(int)
            cy = np.arange(phase_y + cell / 2, panel.shape[0], cell).astype(int)
            blocks = int(math.ceil(cell))
            back = np.repeat(np.repeat(panel[np.ix_(cy, cx)], blocks, 0), blocks, 1)
            sy, sx = int(phase_y), int(phase_x)
            h, w = min(back.shape[0], panel.shape[0] - sy), min(back.shape[1], panel.shape[1] - sx)
            error = np.abs(back[:h, :w].astype(int) - panel[sy:sy + h, sx:sx + w].astype(int)).mean()
            if best is None or error < best[0]:
                best = (error, phase_x, phase_y)
    error, phase_x, phase_y = best
    half = max(1, int(cell * 0.25))
    centres_x = np.arange(phase_x + cell / 2, panel.shape[1], cell).astype(int)
    centres_y = np.arange(phase_y + cell / 2, panel.shape[0], cell).astype(int)
    rgba = np.zeros((len(centres_y), len(centres_x), 4), np.uint8)
    for j, y in enumerate(centres_y):
        for i, x in enumerate(centres_x):
            block = panel[max(0, y - half):y + half + 1, max(0, x - half):x + half + 1].reshape(-1, 3)
            colour = np.median(block, 0).astype(np.uint8)
            if not magenta(colour[None, None, :])[0, 0]:
                rgba[j, i, :3], rgba[j, i, 3] = colour, 255
    ys, xs = np.nonzero(rgba[..., 3])
    if len(ys) == 0:
        return None, 999.0
    sprite = Image.fromarray(rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1], 'RGBA')
    if max(sprite.size) > SIZE:
        scale = SIZE / max(sprite.size)
        sprite = sprite.resize((max(1, round(sprite.width * scale)), max(1, round(sprite.height * scale))), Image.NEAREST)
    out = Image.new('RGBA', (SIZE, SIZE))
    out.paste(sprite, ((SIZE - sprite.width) // 2, (SIZE - sprite.height) // 2))
    return out, float(error)


def pixelate(data, target):
    """The object in a model's picture fitted to `target` pixels across and
    snapped to the colours the model drew, so every sprite has its size."""
    grid, error = extract(data)
    if grid is None:
        return None, error
    palette = np.unique(np.asarray(grid)[np.asarray(grid)[..., 3] > 0][:, :3], axis=0).astype(int)
    picture = np.asarray(Image.open(io.BytesIO(data)).convert('RGB'))
    mask = magenta(picture)
    ys, xs = np.nonzero(mask)
    panel = picture[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    solid = ~mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    # Ignore stray specks: rows and columns need a little of the object.
    rows = np.nonzero(solid.sum(1) > solid.shape[1] * 0.01)[0]
    cols = np.nonzero(solid.sum(0) > solid.shape[0] * 0.01)[0]
    panel = panel[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1].astype(float)
    solid = solid[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1].astype(float)
    scale = target / max(panel.shape[:2])
    size = (max(1, round(panel.shape[1] * scale)), max(1, round(panel.shape[0] * scale)))
    weight = np.asarray(Image.fromarray(solid.astype(np.float32), 'F').resize(size, Image.BOX))
    colour = np.stack([np.asarray(Image.fromarray((panel[..., i] * solid).astype(np.float32), 'F').resize(size, Image.BOX))
                       for i in range(3)], -1)
    colour = colour / np.maximum(weight, 1e-6)[..., None]
    nearest = palette[np.argmin(((colour[..., None, :] - palette[None, None]) ** 2).sum(-1), -1)]
    rgba = np.zeros((size[1], size[0], 4), np.uint8)
    rgba[..., :3] = nearest
    rgba[..., 3] = np.where(weight > 0.5, 255, 0)
    out = Image.new('RGBA', (SIZE, SIZE))
    out.paste(Image.fromarray(rgba, 'RGBA'), ((SIZE - size[0]) // 2, (SIZE - size[1]) // 2))
    return out, error


def ask(prompt, image=None):
    content = [{'type': 'text', 'text': prompt}]
    if image is not None:
        buffer = io.BytesIO()
        image.save(buffer, 'PNG')
        content.append({'type': 'image_url', 'image_url': {
            'url': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()}})
    body = json.dumps({'model': MODEL, 'modalities': ['image', 'text'],
                       'messages': [{'role': 'user', 'content': content}]}).encode()
    request = urllib.request.Request('https://openrouter.ai/api/v1/chat/completions', data=body, headers={
        'Authorization': 'Bearer ' + os.environ['OPENROUTER_API_KEY'], 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=240) as response:
        message = json.load(response)['choices'][0]['message']
    url = message['images'][0]['image_url']['url']
    return base64.b64decode(url.split(';base64,', 1)[1])


def on_magenta(sprite):
    """A native sprite shown large on magenta, as input for a redraw."""
    canvas = Image.new('RGBA', sprite.size, (255, 0, 255, 255))
    canvas.alpha_composite(sprite)
    return canvas.convert('RGB').resize((SIZE * 24, SIZE * 24), Image.NEAREST)


def draw(name, prompt, source=None, attempts=3):
    for attempt in range(attempts):
        try:
            data = ask(prompt, source)
        except Exception as error:  # a failed call is retried, never fatal
            print(f'{name}: request failed ({error.__class__.__name__})', file=sys.stderr)
            continue
        RAW.mkdir(parents=True, exist_ok=True)
        (RAW / f'{name}-{len(list(RAW.glob(f"{name}-*.png"))) + 1}.png').write_bytes(data)
        if extract(data)[1] < 9:
            break
    fit(name)


def fit(name):
    """Keep the raw picture whose grid fits best, at the sprite's size."""
    best = None
    for raw in sorted([*RAW.glob(f'{name}-[0-9]*.png'), *RAW.glob(f'{name}-[0-9]*.jpg')]):
        sprite, error = pixelate(raw.read_bytes(), SPEC['sizes'].get(name, 26))
        if sprite is not None and (best is None or error < best[1]):
            best = (sprite, error, raw.name)
    if best is None:
        print(f'{name}: no usable picture', file=sys.stderr)
        return
    NATIVE.mkdir(parents=True, exist_ok=True)
    best[0].save(NATIVE / f'{name}.png')
    print(f'{name}: {best[2]}, grid fit {best[1]:.1f}')


def generate(names, again):
    style = SPEC['style']
    todo = [(n, p) for n, p in SPEC['generated'].items()
            if (not names or n in names) and (again or not (NATIVE / f'{n}.png').exists())]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda item: draw(item[0], style + item[1]), todo))
    edits = [(n, s, p) for n, (s, p) in SPEC['edited'].items()
             if (not names or n in names) and (again or not (NATIVE / f'{n}.png').exists())]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda item: draw(item[0], item[2], on_magenta(native(item[1]))), edits))


def native(name):
    return Image.open(NATIVE / f'{name}.png').convert('RGBA')


# ---------------------------------------------------------------- drawn tiles


def shade(colour, factor):
    return tuple(max(0, min(255, round(c * factor))) for c in colour[:3]) + (255,)


FLOOR = (208, 211, 210, 255)
GRASS = (104, 172, 92, 255)


def grain(image, seed, dark=0.88, light=1.08, share=0.22):
    """Speckle every pixel a little, like the original's grainy stone."""
    rng = random.Random(seed)
    px = image.load()
    for y in range(SIZE):
        for x in range(SIZE):
            colour = px[x, y]
            if not colour[3]:
                continue
            roll = rng.random()
            factor = dark if roll < share * 0.6 else light if roll < share else 1 + (rng.random() - 0.5) * 0.04
            px[x, y] = shade(colour, factor)
    return image


def floor():
    image = Image.new('RGBA', (SIZE, SIZE), FLOOR)
    grain(image, 7)
    px = image.load()
    for i in range(SIZE):
        px[i, 0] = px[0, i] = shade(FLOOR, 1.11)
        px[i, SIZE - 1] = px[SIZE - 1, i] = shade(FLOOR, 0.82)
    return image


def grass():
    image = Image.new('RGBA', (SIZE, SIZE), GRASS)
    return grain(image, 11, dark=0.82, light=1.12, share=0.34)


def grass_edge(mask):
    """Connected grass cells stay solid; exposed edges blend into paving."""
    image, stone = grass(), floor()
    px, paving = image.load(), stone.load()
    for y in range(SIZE):
        for x in range(SIZE):
            distances = [distance for bit, distance in enumerate((x, y, SIZE - 1 - x, SIZE - 1 - y))
                         if mask & (1 << bit)]
            distance = min(distances, default=SIZE)
            if distance < 4:
                mix = (distance + 0.25) / 4
                px[x, y] = tuple(round(paving[x, y][channel] * (1 - mix) + px[x, y][channel] * mix)
                                 for channel in range(3)) + (255,)
    return image


def bevel(image, box, face, depth, raised=True, light=1.28, dark=0.58):
    """A square face with lit and shaded edges, raised or sunken."""
    left, top, right, bottom = box
    px = image.load()
    light, dark = shade(face, light), shade(face, dark)
    if not raised:
        light, dark = dark, light
    for y in range(top, bottom + 1):
        for x in range(left, right + 1):
            edge = min(x - left, y - top, right - x, bottom - y)
            if edge >= depth:
                px[x, y] = face
            elif (x - left) + (y - top) < (right - x) + (bottom - y) and min(x - left, y - top) < depth:
                px[x, y] = light
            else:
                px[x, y] = dark


STONE = (157, 171, 171, 255)
MATERIALS = ((104, 126, 137, 255), (166, 102, 78, 255),
             (198, 177, 128, 255), (145, 110, 76, 255))


def wall(face=STONE):
    image = Image.new('RGBA', (SIZE, SIZE))
    bevel(image, (0, 0, SIZE - 1, SIZE - 1), face, 4, light=1.27, dark=0.58)
    grain(image, 21, dark=0.94, light=1.04, share=0.18)
    draw = ImageDraw.Draw(image)
    draw.line((4, 5, 27, 5), fill=shade(face, 1.10))
    draw.line((5, 5, 5, 27), fill=shade(face, 1.10))
    draw.line((6, 27, 27, 27, 27, 6), fill=shade(face, 0.78))
    bevel(image, (10, 10, 21, 21), face, 2, raised=False, light=1.3, dark=0.55)
    return image


def wall_variant(style):
    face = MATERIALS[style]
    image = wall(face)
    draw = ImageDraw.Draw(image)
    seam = shade(face, 0.55)
    if style == 0:
        draw.line((16, 3, 16, 28), fill=seam)
        draw.line((3, 16, 15, 16), fill=seam)
        draw.line((17, 12, 28, 12), fill=seam)
        draw.line((17, 13, 28, 13), fill=shade(face, 1.15))
    elif style == 1:
        for y in (11, 21):
            draw.line((3, y, 28, y), fill=(204, 182, 157, 255), width=2)
        for x, y in ((16, 3), (9, 13), (24, 13), (16, 23)):
            draw.line((x, y, x, min(28, y + 7)), fill=(204, 182, 157, 255))
    elif style == 2:
        draw.line((3, 14, 28, 14), fill=seam)
        draw.line((3, 15, 28, 15), fill=shade(face, 1.18))
        draw.line((12, 3, 12, 13), fill=seam)
        draw.line((22, 16, 22, 28), fill=seam)
    else:
        for x in (9, 17, 25):
            draw.line((x, 3, x, 28), fill=seam)
            draw.line((x + 1, 4, x + 1, 27), fill=shade(face, 1.16))
        for y in (8, 23):
            draw.rectangle((3, y, 28, y + 2), fill=(53, 65, 68, 255))
            for x in (5, 26):draw.point((x, y + 1), fill=(178, 194, 191, 255))
    # Every material keeps the original wall's recessed square and bevel.
    bevel(image, (10, 10, 21, 21), face, 2, raised=False, light=1.3, dark=0.55)
    return image


def material_floor(style):
    """Flat paving in the corresponding wall material, without a wall recess."""
    if style == 4:
        return moss(floor(), 43, 8)
    face = shade(MATERIALS[style], 1.12)
    image = Image.new('RGBA', (SIZE, SIZE), face)
    grain(image, 91 + style, dark=0.94, light=1.05, share=0.2)
    draw = ImageDraw.Draw(image)
    joint, lip = shade(face, 0.73), shade(face, 1.09)
    draw.line((0, 0, 31, 0), fill=lip)
    draw.line((0, 0, 0, 31), fill=lip)
    draw.line((0, 31, 31, 31, 31, 0), fill=joint)
    if style == 0:
        draw.line((16, 1, 16, 30), fill=joint)
        draw.line((1, 16, 15, 16), fill=joint)
        draw.line((17, 10, 30, 10), fill=joint)
    elif style == 1:
        mortar = (181, 158, 135, 255)
        for y in (10, 21):
            draw.line((1, y, 30, y), fill=mortar)
        for x, y in ((16, 1), (8, 11), (24, 11), (16, 22)):
            draw.line((x, y, x, min(30, y + 8)), fill=mortar)
    elif style == 2:
        draw.line((1, 16, 30, 16), fill=joint)
        draw.line((1, 17, 30, 17), fill=lip)
        draw.line((12, 1, 12, 15), fill=joint)
        draw.line((22, 18, 22, 30), fill=joint)
    else:
        for x in (8, 16, 24):
            draw.line((x, 1, x, 30), fill=joint)
            draw.line((x + 1, 1, x + 1, 30), fill=lip)
        for x, y in ((3, 13), (12, 24), (20, 8), (28, 19)):
            draw.line((x, y, x, y + 3), fill=shade(face, 0.88))
    return image


MOSS = ((52, 118, 58, 255), (78, 150, 66, 255), (112, 178, 80, 255), (150, 204, 100, 255))


def moss(image, seed, amount):
    """Green moss and creepers grown over stone, darker where they are thick."""
    rng = random.Random(seed)
    px = image.load()
    for _ in range(amount):
        # Creepers start anywhere on the stone, so no edge gets all the moss.
        x, y = rng.randrange(1, SIZE - 1), rng.randrange(0, SIZE - 8)
        for _ in range(rng.randrange(5, 12)):
            colour = MOSS[rng.randrange(0, 3)] if rng.random() < 0.7 else MOSS[3]
            px[x, y] = colour
            if rng.random() < 0.3 and x + 1 < SIZE:
                px[x + 1, y] = MOSS[0]
            x = max(1, min(SIZE - 2, x + rng.choice((-1, 0, 0, 1))))
            y += 1
            if y >= SIZE - 1:
                break
    for _ in range(amount):
        x, y = rng.randrange(1, SIZE - 1), rng.randrange(1, SIZE - 1)
        px[x, y] = MOSS[rng.randrange(0, 4)]
    return image


def mossy_wall():
    """The gate a button opens: the wall image with moss on top."""
    image = moss(wall(), 31, 11)
    draw = ImageDraw.Draw(image)
    for points in ([(3, 4), (12, 4), (14, 7), (14, 12)],
                   [(27, 9), (25, 14), (27, 21), (24, 28)],
                   [(8, 21), (11, 23), (12, 28)]):
        draw.line(points, fill=MOSS[0], width=2)
        for x, y in points:
            draw.rectangle((x - 1, y - 1, x + 1, y), fill=MOSS[2])
            draw.point((x - 1, y - 1), fill=MOSS[3])
    image.putpixel((0, 0), (0, 0, 0, 0))
    return image


def mossy_floor():
    """The opened gate: the mossy block sunk level with the floor."""
    return floor()


def pressure_plate():
    """A round green push button recessed into the paving, like the original."""
    image = Image.new('RGBA', (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 27, 27), fill=(47, 58, 53, 255))
    draw.ellipse((5, 5, 26, 26), fill=(201, 208, 198, 255))
    draw.ellipse((7, 7, 24, 24), fill=(29, 85, 37, 255))
    draw.ellipse((8, 8, 23, 23), fill=(57, 157, 61, 255))
    draw.arc((8, 8, 23, 23), 195, 285, fill=(149, 212, 109, 255), width=1)
    draw.arc((8, 8, 23, 23), 15, 105, fill=(37, 115, 44, 255), width=1)
    return image


def gate(opened=False):
    image = Image.new('RGBA', (SIZE, SIZE))
    stone = (164, 176, 179, 255)
    for box in ((1, 2, 5, 29), (26, 2, 30, 29), (4, 2, 27, 6)):
        bevel(image, box, stone, 1, light=1.24, dark=0.58)
    draw = ImageDraw.Draw(image)
    for x in ((7, 9) if opened else (8, 13, 18, 23)):
        draw.rectangle((x, 7, x + 1, 27), fill=(40, 65, 77, 255))
        draw.line((x, 8, x, 25), fill=(117, 159, 176, 255))
    if not opened:
        draw.rectangle((7, 17, 24, 19), fill=(45, 73, 87, 255))
        draw.point((16, 18), fill=(236, 181, 76, 255))
    return image


def lever(active=False):
    image = Image.new('RGBA', (SIZE, SIZE))
    bevel(image, (7, 23, 24, 29), (151, 163, 165, 255), 2)
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 19, 19, 26), fill=(39, 57, 65, 255))
    x, y = (23, 7) if active else (8, 11)
    draw.line((16, 22, x, y), fill=(30, 48, 58, 255), width=4)
    draw.line((15, 22, x - 1, y), fill=(155, 186, 194, 255), width=2)
    bevel(image, (x - 4, y - 2, x + 3, y + 3),
          (100, 181, 123, 255) if active else (221, 137, 64, 255), 1)
    return image


def pit(colour):
    """A coloured pit filling nearly the whole cell, like the original's."""
    image = Image.new('RGBA', (SIZE, SIZE))
    bevel(image, (1, 1, 30, 30), colour, 4, raised=False)
    px = image.load()
    # The rim's shadow falls into the top left of the pit.
    for y in range(5, 27):
        for x in range(5, 27):
            depth = min(x - 5, y - 5)
            px[x, y] = shade(colour, 0.8 + 0.05 * min(depth, 4))
    return image


def block(colour):
    """A colour block: a raised grey stone block with the coloured block set in it."""
    image = Image.new('RGBA', (SIZE, SIZE))
    bevel(image, (2, 2, 29, 29), (186, 190, 189, 255), 3, light=1.32, dark=0.5)
    bevel(image, (8, 8, 23, 23), colour, 2, light=1.3, dark=0.6)
    return image


def star_block():
    """A raised stone block with a round inset holding a bright four-point star."""
    image = Image.new('RGBA', (SIZE, SIZE))
    face = (186, 190, 189, 255)
    bevel(image, (2, 2, 29, 29), face, 3, light=1.32, dark=0.5)
    px = image.load()
    centre = 15.5
    for y in range(SIZE):
        for x in range(SIZE):
            d = math.hypot(x - centre, y - centre)
            if 9.0 <= d < 10.2:
                px[x, y] = shade(face, 0.62 if x + y < 31 else 1.22)
            elif d < 9.0:
                px[x, y] = shade(face, 0.9)
    # The star: an astroid, so its four points are sharp and its sides curve in.
    for y in range(SIZE):
        for x in range(SIZE):
            u, v = abs(x - centre) / 8.6, abs(y - centre) / 8.6
            reach = math.sqrt(u) + math.sqrt(v)
            if reach <= 1.0:
                px[x, y] = (150, 236, 246, 255) if (x - centre) + (y - centre) < -2 else (52, 196, 220, 255)
            elif reach <= 1.16:
                px[x, y] = (18, 110, 140, 255)
    return image


def crate_goal():
    image = Image.new('RGBA', (SIZE, SIZE))
    px = image.load()
    brown = (122, 86, 60, 255)
    for cx, cy in ((5, 5), (26, 5), (5, 26), (26, 26)):
        sx, sy = (1 if cx < 16 else -1), (1 if cy < 16 else -1)
        for t in range(7):
            for w in range(2):
                px[cx + sx * t, cy + sy * w] = brown
                px[cx + sx * w, cy + sy * t] = brown
    return image


def colour_goal():
    image = Image.new('RGBA', (SIZE, SIZE))
    px = image.load()
    red, pale = (204, 82, 66, 255), (238, 200, 190, 255)
    for y in range(6, 26):
        for x in range(6, 26):
            px[x, y] = red if (x + y) % 6 < 2 else pale
    return image


def ring(colour, dots, lit=None, angle=None):
    image = Image.new('RGBA', (SIZE, SIZE))
    px = image.load()
    for step in range(dots):
        a = 2 * math.pi * step / dots
        x, y = 16 + round(9 * math.cos(a)), 16 + round(9 * math.sin(a))
        for dx in (-1, 0):
            for dy in (-1, 0):
                px[x + dx, y + dy] = colour
    if angle is not None:
        a = math.radians(angle)
        x, y = 16 + round(9 * math.cos(a)), 16 + round(9 * math.sin(a))
        for dx in (-2, -1, 0, 1):
            for dy in (-2, -1, 0, 1):
                if abs(dx + 0.5) + abs(dy + 0.5) <= 2.5:
                    px[x + dx, y + dy] = lit
    return image


def over_floor(sprite):
    return sprite.copy()


def on_grass(sprite):
    image = grass()
    image.alpha_composite(sprite)
    return image


def recolour(sprite, test, hue):
    pixels = np.asarray(sprite).copy()
    for y in range(SIZE):
        for x in range(SIZE):
            r, g, b, a = pixels[y, x]
            if not a:
                continue
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if test(h * 360, s, v):
                r, g, b = colorsys.hsv_to_rgb(hue / 360, s, v)
                pixels[y, x, :3] = (round(r * 255), round(g * 255), round(b * 255))
    return Image.fromarray(pixels, 'RGBA')


def glow(sprite, colour=(242, 204, 80, 255)):
    """A one-pixel yellow halo around a character: charged Shovey."""
    alpha = np.asarray(sprite)[..., 3] > 0
    around = np.zeros_like(alpha)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            around |= np.roll(np.roll(alpha, dy, 0), dx, 1)
    image = Image.new('RGBA', (SIZE, SIZE))
    px = image.load()
    for y, x in zip(*np.nonzero(around & ~alpha)):
        px[int(x), int(y)] = colour
    image.alpha_composite(sprite)
    return image

# ------------------------------------------------------- newer tiles (57 to 76)


def scatter(image, seed, count, paint):
    """Drops `count` small marks at random places that keep to the cell's middle."""
    rng = random.Random(seed)
    for _ in range(count):
        paint(image.load(), rng.randrange(3, SIZE - 4), rng.randrange(3, SIZE - 4), rng)
    return image


def flowers():
    image = Image.new('RGBA', (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    for x, y, petal in ((8, 9, (255, 246, 226, 255)),
                        (24, 8, (249, 171, 126, 255)),
                        (18, 23, (223, 195, 255, 255))):
        draw.line((x, y + 2, x, y + 7), fill=(35, 86, 48, 255), width=2)
        draw.polygon([(x, y + 6), (x - 5, y + 3), (x - 4, y + 6), (x, y + 8)], fill=(52, 123, 62, 255))
        draw.polygon([(x + 1, y + 5), (x + 5, y + 2), (x + 5, y + 5)], fill=(110, 173, 75, 255))
        for dx, dy in ((0, -3), (3, 0), (0, 3), (-3, 0)):
            draw.rectangle((x + dx - 1, y + dy - 1, x + dx + 1, y + dy + 1), fill=petal)
        draw.rectangle((x - 1, y - 1, x + 1, y + 1), fill=(147, 88, 28, 255))
        draw.rectangle((x - 1, y - 1, x, y), fill=(255, 215, 76, 255))
    return image


def grass_tufts():
    image = Image.new('RGBA', (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    for x, y in ((7, 15), (24, 13), (17, 29)):
        draw.polygon([(x - 3, y), (x - 6, y - 8), (x - 1, y - 5),
                      (x, y - 12), (x + 2, y - 5), (x + 6, y - 9), (x + 4, y)],
                     fill=(34, 79, 45, 255))
        draw.line((x - 2, y - 1, x - 4, y - 6), fill=(119, 186, 82, 255), width=2)
        draw.line((x, y - 1, x, y - 9), fill=(163, 208, 102, 255), width=2)
        draw.line((x + 2, y - 1, x + 4, y - 6), fill=(102, 165, 69, 255), width=2)
    return image


def pebbles():
    def pebble(px, x, y, rng):
        colour = shade(FLOOR, rng.choice((0.72, 0.8, 0.9)))
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1), (-1, 0)):
            px[x + dx, y + dy] = colour
        px[x - 1, y - 1] = shade(FLOOR, 1.12)
    return scatter(Image.new('RGBA', (SIZE, SIZE)), 47, 8, pebble)


def checker():
    image = floor()
    px = image.load()
    for y in range(SIZE):
        for x in range(SIZE):
            if (x // 8 + y // 8) % 2 == 0 and 1 <= x < SIZE - 1 and 1 <= y < SIZE - 1:
                px[x, y] = shade(px[x, y], 0.9)
                px[x, y] = (px[x, y][0] - 6, px[x, y][1] - 1, px[x, y][2] + 4, 255)
    return image


def stripes():
    image = floor()
    px = image.load()
    for y in range(1, SIZE - 1):
        for x in range(1, SIZE - 1):
            if (x + y) % 8 < 2:
                px[x, y] = (150, 186, 196, 255)
    return image


def cracks(image, seed, colour=(52, 56, 56, 255), lines=3):
    rng = random.Random(seed)
    px = image.load()
    for _ in range(lines):
        x, y = rng.randrange(6, SIZE - 6), rng.randrange(2, 8)
        for _ in range(rng.randrange(12, 22)):
            px[x, y] = colour
            x = max(2, min(SIZE - 3, x + rng.choice((-1, 0, 0, 1))))
            y += 1
            if y >= SIZE - 2:
                break
    return image


def fracture(image, wall=False):
    draw = ImageDraw.Draw(image)
    paths = [[(17, 4), (14, 10), (17, 15), (13, 21), (15, 28)],
             [(14, 10), (10, 12), (6, 9)],
             [(17, 15), (22, 18), (26, 14)],
             [(13, 21), (9, 25)]]
    shadow = (64, 76, 73, 255) if wall else (99, 112, 107, 255)
    highlight = (218, 229, 221, 255) if wall else (239, 244, 237, 255)
    for points in paths:
        draw.line([(x + 1, y) for x, y in points], fill=highlight, width=1)
        draw.line(points, fill=shadow, width=1)
    draw.polygon([(14, 11), (17, 14), (15, 17)], fill=shadow)
    return image


def cracked_wall():
    return fracture(Image.new('RGBA', (SIZE, SIZE)))


def sand():
    return grain(Image.new('RGBA', (SIZE, SIZE), (218, 199, 151, 255)),
                 78, dark=0.88, light=1.10, share=0.56)


def water_edge(frame=0):
    """A repeating pool surface; its quiet ripples drift without tile rims."""
    image = Image.new('RGBA', (SIZE, SIZE), (66, 139, 171, 255))
    px = image.load()
    for y in range(SIZE):
        for x in range(SIZE):
            depth = math.sin(2 * math.pi * x / SIZE) * math.sin(2 * math.pi * y / SIZE)
            px[x, y] = shade((66, 139, 171, 255), 1 + depth * 0.045)
    for row, offset in ((6, 1), (21, 17)):
        for dx in range(10):
            x = (offset + dx + frame) % SIZE
            y = (row + (1 if dx < 2 or dx > 7 else 0)) % SIZE
            px[x, y] = (108, 178, 198, 255)
            if 2 <= dx <= 7:
                px[x, (y + 1) % SIZE] = (77, 151, 181, 255)
    return image


def hole():
    """Adjacent abyss cells join into one opening, without internal rims."""
    return Image.new('RGBA', (SIZE, SIZE), (2, 4, 5, 255))


def abyss_edge(mask):
    image = hole()
    px = image.load()
    for y in range(SIZE):
        for x in range(SIZE):
            distances = [d for side, d in enumerate((x, y, SIZE - 1 - x, SIZE - 1 - y)) if mask & (1 << side)]
            distance = min(distances, default=SIZE)
            if distance < 3:
                px[x, y] = ((151, 164, 161, 255), (57, 68, 69, 255), (17, 25, 28, 255))[distance]
    return image


def arrow(direction):
    """A one-way arrow; direction 0 left, 1 up, 2 right, 3 down."""
    image = Image.new('RGBA', (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    body = (62, 118, 150, 255)
    draw.polygon([(16, 5), (26, 16), (20, 16), (20, 26), (12, 26), (12, 16), (6, 16)], fill=body, outline=(30, 62, 84, 255))
    draw.polygon([(16, 8), (22, 15), (18, 15), (18, 24), (14, 24), (14, 15), (10, 15)], fill=(96, 158, 190, 255))
    turns = {1: 0, 0: 90, 3: 180, 2: -90}
    rotated = image.rotate(turns[direction])
    return rotated


def ice_patch():
    image = Image.new('RGBA', (SIZE, SIZE), (178, 216, 232, 255))
    grain(image, 67, dark=0.92, light=1.06, share=0.2)
    px = image.load()
    for i in range(SIZE):
        px[i, 0] = px[0, i] = (222, 242, 250, 255)
        px[i, SIZE - 1] = px[SIZE - 1, i] = (126, 172, 196, 255)
    for y in range(6, 14):
        px[6 + (y - 6), y] = (244, 252, 255, 255)
        px[7 + (y - 6), y] = (230, 246, 252, 255)
    for y in range(18, 24):
        px[18 + (y - 18), y] = (244, 252, 255, 255)
    return image


def cracked_floor():
    return fracture(Image.new('RGBA', (SIZE, SIZE)))


def bomb_crate():
    image = crate_sprite()
    draw = ImageDraw.Draw(image)
    draw.ellipse((9, 11, 23, 25), fill=(34, 36, 40, 255), outline=(10, 10, 12, 255))
    draw.ellipse((12, 14, 15, 17), fill=(120, 126, 132, 255))
    draw.line((20, 12, 24, 7), fill=(150, 112, 70, 255), width=1)
    draw.point((25, 6), fill=(250, 170, 60, 255))
    draw.point((24, 5), fill=(250, 222, 110, 255))
    return image


def colour_portal(hue):
    return over_floor(recolour(native('teleporter'), lambda h, s, v: s > 0.12, hue))


def grainy(sprite, seed):
    """Shovey's coat, speckled like the stone around him."""
    return grain(sprite.copy(), seed, dark=0.8, light=1.16, share=0.42)


# ---------------------------------------------------------------- the set


def crate_sprite():
    sprite = native('crate-v2')
    sprite = sprite.crop(sprite.getbbox()).resize((28, 28), Image.Resampling.NEAREST)
    image = Image.new('RGBA', (SIZE, SIZE))
    image.alpha_composite(sprite, (2, 2))
    return image


def sprites():
    green = lambda h, s, v: 60 <= h <= 180 and s > 0.2
    blue = lambda h, s, v: 170 <= h <= 230 and s > 0.25
    # Shovey is seen from above and looks where it goes, so one picture facing
    # up is turned for the other directions, as in the original.
    up = native('player')
    # The comb and beak in the kept source point up already.
    chicken = native('chicken')
    players = {'up': up, 'right': up.rotate(-90), 'down': up.rotate(180), 'left': up.rotate(90)}
    mirror = recolour(players['up'], green, 330)
    shot = Image.new('RGBA', (SIZE, SIZE))
    shot_draw = ImageDraw.Draw(shot)
    shot_draw.ellipse((6, 6, 25, 25), fill=(74, 85, 83, 255), outline=(35, 43, 42, 255))
    shot_draw.ellipse((10, 9, 17, 16), fill=(117, 130, 127, 255))
    shot_draw.point((12, 11), fill=(190, 201, 198, 255))
    out = {
        'tile-0': ('floor: a pale grey paving stone', floor()),
        'tile-1': ('red ball (pushable)', native('ball-red')),
        'tile-2': ('blue ball (pushable)', native('ball-blue')),
        'tile-3': ('green ball (pushable)', native('ball-green')),
        'tile-4': ('red pit: takes the red ball', native('pit-red-original').resize((SIZE, SIZE), Image.Resampling.NEAREST)),
        'tile-5': ('blue pit: takes the blue ball', native('pit-blue-original').resize((SIZE, SIZE), Image.Resampling.NEAREST)),
        'tile-6': ('green pit: takes the green ball', native('pit-green-original').resize((SIZE, SIZE), Image.Resampling.NEAREST)),
        'tile-7': ('home: a small cottage with a jade roof and a lit door, on grass', native('home')),
        'tile-8': ('teleporter: a recessed opening with an inward blue-green spiral', over_floor(native('teleporter'))),
        'tile-9': ('crate: clean chestnut planks with crossed wooden braces (pushable)', crate_sprite()),
        'tile-10': ('start position, drawn as floor', floor()),
        'tile-11': ('trail field: a ring with a bar, drawn in deep teal', over_floor(recolour(native('trail'), lambda h, s, v: s > 0.2, 188))),
        'tile-12': ('wall: a raised grey stone block', wall()),
        'tile-13': ('pressure plate: a round green button recessed into the paving', pressure_plate()),
        'tile-14': ('mossy stone wall: sinks when a pressure plate is held', mossy_wall()),
        'tile-15': ('red paint puddle, matching the other paint silhouettes', recolour(native('paint-green'), green, 0)),
        'tile-16': ('blue paint puddle, matching the other paint silhouettes', recolour(native('paint-green'), green, 240)),
        'tile-17': ('green paint puddle', native('paint-green')),
        'tile-18': ('crate goal: four corner brackets', crate_goal()),
        'tile-19': ('star block: a stone block with a bright star (pushable)', star_block()),
        'tile-20': ('sensor not yet visited: a grey ring with a red dot', ring((150, 158, 156, 255), 12, (206, 62, 50, 255), -90)),
        'tile-21': ('apple', native('apple')),
        'tile-22': ('active sensor', ring((120, 186, 214, 255), 12, (240, 248, 250, 255), -90)),
        'tile-23': ('closed sensor: a raised block with a red light', over_floor(native('sensor-closed'))),
        'tile-24': ('active sensor', ring((120, 186, 214, 255), 12, (240, 248, 250, 255), -90)),
        'tile-25': ('reverse controls: a token with two opposite arrows', native('reverse')),
        'tile-26': ('ammunition: one iron shot', shot),
        'tile-27': ('charge: a token with a lightning bolt', native('charge')),
        'tile-28': ('target: a red and white target board (pushable)', native('target')),
        'tile-29': ('moving block: a stone puck with a blue light', over_floor(native('puck'))),
        'tile-30': ('fresh path: a ring of blue dots', ring((63, 111, 143, 255), 10)),
        'tile-31': ('used path: a ring of grey dots', ring((150, 158, 156, 255), 10)),
        'tile-32': ('moving block stopping: its light turns red', over_floor(recolour(native('puck'), blue, 4))),
        'tile-33': ('key', native('key')),
        'tile-34': ('lock: a padlock', native('lock')),
        'tile-35': ('slide power: a token with an ice crystal', native('slide')),
        'tile-36': ('red colour block (pushable)', block((228, 38, 28, 255))),
        'tile-37': ('blue colour block (pushable)', block((30, 84, 228, 255))),
        'tile-38': ('yellow colour block (pushable)', block((242, 206, 36, 255))),
        'tile-39': ('colour block goal: a red hatched square', colour_goal()),
        'tile-40': ('mirror Shovey (pink)', mirror),
        'tile-57': ('flowers scattered on the floor (decoration)', flowers()),
        'tile-58': ('grass tufts on the floor (decoration)', grass_tufts()),
        'tile-59': ('pebbles on the floor (decoration)', pebbles()),
        'tile-60': ('checker floor (decoration)', checker()),
        'tile-61': ('striped floor (decoration)', stripes()),
        'tile-62': ('legacy transparent crack on a wall', cracked_wall()),
        'tile-63': ('mossy wall (decoration, solid)', moss(wall(), 63, 12)),
        'tile-64': ('water edge (decoration, solid)', water_edge()),
        'tile-65': ('abyss: a bottomless black drop that Shovey falls into', hole()),
        'tile-66': ('one-way arrow left', arrow(0)),
        'tile-67': ('one-way arrow up', arrow(1)),
        'tile-68': ('one-way arrow right', arrow(2)),
        'tile-69': ('one-way arrow down', arrow(3)),
        'tile-70': ('ice patch: Shovey slides across', ice_patch()),
        'tile-71': ('crack: a transparent fracture placed over a floor or wall', cracked_floor()),
        'tile-72': ('bomb crate (pushable): breaks a cracked wall', bomb_crate()),
        'tile-73': ('cyan portal', colour_portal(180)),
        'tile-74': ('purple portal', colour_portal(275)),
        'tile-75': ('yellow portal', colour_portal(48)),
        'tile-76': ('legacy wall, shown as a plain stone wall', wall()),
        'tile-77': ('grass floor tile, independent of objects', grass()),
        'tile-78': ('sand: pale warm grains with scattered darker and lighter flecks', sand()),
        'tile-82': ('chicken: a cream-white bird with an orange comb', chicken),
        'tile-83': ('turtle: a clean jade shell with pale yellow feet', native('turtle')),
        'tile-84': ('tree: a broad jade canopy and brown trunk; blocks movement', native('tree')),
        'tile-85': ('red portal', colour_portal(0)),
        'tile-86': ('green portal', colour_portal(125)),
        'tile-87': ('orange portal', colour_portal(28)),
        'tile-88': ('crab: a bright orange shell and clear raised pincers', native('crab')),
        'tile-92': ('iron gate: opened by pushing a lever', gate()),
        'tile-93': ('lever: push to open the iron gates', lever()),
        'tile-94': ('lever switched on: push again to close the iron gates', lever(True)),
        'gate-open': ('iron gate with its bars drawn aside', gate(True)),
        'tile-95': ('slate wall: dark blue-grey stone slabs', wall_variant(0)),
        'tile-96': ('brick wall: warm bricks with pale mortar', wall_variant(1)),
        'tile-97': ('sandstone wall: pale carved blocks', wall_variant(2)),
        'tile-98': ('timber wall: upright planks with iron straps', wall_variant(3)),
        'tile-99': ('slate floor: flat blue-grey stone paving', material_floor(0)),
        'tile-100': ('brick floor: flat warm brick paving', material_floor(1)),
        'tile-101': ('sandstone floor: flat pale sandstone paving', material_floor(2)),
        'tile-102': ('timber floor: flat wooden floorboards', material_floor(3)),
        'tile-103': ('mossy floor: flat stone paving with green moss', material_floor(4)),
        'shadow': ('mirror Shovey (pink)', mirror),
        'door-open': ('mossy wall lowered, leaving a moss-covered stone rim', mossy_floor()),
        'projectile': ('a flying iron shot', native('projectile')),
    }
    for facing, sprite in players.items():
        out[f'player-{facing}'] = (f'Shovey looking {facing}', sprite)
        out[f'charged-{facing}'] = (f'charged Shovey looking {facing}', glow(sprite))
    for animal in ('dog', 'turtle'):
        up = chicken if animal == 'dog' else native(animal)
        for facing, angle in (('up', 0), ('right', -90), ('down', 180), ('left', 90)):
            out[f'{animal}-{facing}'] = (f'{"chicken" if animal == "dog" else animal} facing {facing}', up.rotate(angle))
    for facing, angle in (('up', 0), ('right', -90), ('down', 180), ('left', 90)):
        out[f'crab-{facing}'] = (f'crab facing {facing}', native('crab').rotate(angle))
    for frame in range(4):
        out[f'water-{frame}'] = ('gentle seamless water ripples', water_edge(frame))
    for fish, kind in (('gold', 89), ('koi', 90), ('minnow', 91)):
        # The fitted fish sources face up, like the land animals.
        def centered_fish(frame):
            source = native(f'fish-{fish}-{frame}')
            bounds = source.getchannel('A').point(lambda alpha: 255 if alpha > 128 else 0).getbbox()
            sprite = source.crop(bounds)
            sprite.thumbnail((26, 26), Image.Resampling.NEAREST)
            image = Image.new('RGBA', (SIZE, SIZE))
            image.alpha_composite(sprite, ((SIZE - sprite.width) // 2, (SIZE - sprite.height) // 2))
            return image
        out[f'tile-{kind}'] = (f'{fish} fish: rests on water', centered_fish(0))
        for frame in range(4):
            for facing, angle in (('up', 0), ('right', -90), ('down', 180), ('left', 90)):
                out[f'fish-{fish}-{frame}-{facing}'] = (f'{fish} fish, frame {frame}, facing {facing}', centered_fish(frame).rotate(angle))
    for mask in range(16):
        out[f'grass-edge-{mask}'] = ('grass blending into adjacent paving with connected corners', grass_edge(mask))
        out[f'abyss-edge-{mask}'] = ('abyss with a recessed stone lip only where it meets solid ground', abyss_edge(mask))
    for frame in range(1, 9):
        out[f'sensor-{frame}'] = (f'active sensor, frame {frame} of 8',
                                  ring((120, 186, 214, 255), 12, (240, 248, 250, 255), -90 + 45 * (frame - 1)))
    return out


# The game card: Shovey pushes a red ball towards its pit in the courtyard.
CARD = [
    '###############',
    '#.............#',
    '#..H......*...#',
    '#.............#',
    '#....P1...r...#',
    '#.............#',
    '#..c......k...#',
    '#.............#',
    '###############',
]


def card(sheet):
    image = Image.new('RGBA', (len(CARD[0]) * SIZE, len(CARD) * SIZE))
    pieces = {'#': 'tile-12', '.': 'tile-0', 'H': 'tile-7', 'r': 'tile-4', '1': 'tile-1',
              'P': 'player-right', 'c': 'tile-9', '*': 'tile-19', 'k': 'tile-33'}
    for y, row in enumerate(CARD):
        for x, cell in enumerate(row):
            if cell not in '#r':
                image.alpha_composite(sheet['tile-77' if cell == 'H' else 'tile-0'][1], (x * SIZE, y * SIZE))
            image.alpha_composite(sheet[pieces[cell]][1], (x * SIZE, y * SIZE))
    return image


def saturate(image, amount=1.18):
    """A little more colour; greys stay grey."""
    from PIL import ImageEnhance
    alpha = image.getchannel('A')
    image = ImageEnhance.Color(image.convert('RGB')).enhance(amount).convert('RGBA')
    image.putalpha(alpha)
    return image


def build():
    manifest = []
    sheet = {name: (depicts, image if name in ('tile-4', 'tile-5', 'tile-6') else saturate(image)) for name, (depicts, image) in sprites().items()}
    preview = ROOT / 'assets/shovey/preview.png'
    buffer = io.BytesIO()
    card(sheet).save(buffer, 'PNG', optimize=True)
    preview.write_bytes(buffer.getvalue())
    manifest.append({'path': 'preview.png', 'depicts': 'Shovey Classic card: Shovey pushes a red ball towards its pit in a grey stone courtyard',
                     'sha256': hashlib.sha256(buffer.getvalue()).hexdigest()})
    for name, (depicts, image) in sheet.items():
        path = SPRITES / f'{name}.png'
        buffer = io.BytesIO()
        image.resize((SIZE * SCALE, SIZE * SCALE), Image.NEAREST).save(buffer, 'PNG', optimize=True)
        path.write_bytes(buffer.getvalue())
        manifest.append({'path': f'sprites/{name}.png', 'depicts': depicts,
                         'sha256': hashlib.sha256(buffer.getvalue()).hexdigest()})
    # The cyan, purple and yellow pieces and the cherry are kept pictures; list them.
    extra = {44: 'cyan ball (pushable)', 45: 'purple ball (pushable)', 46: 'yellow ball (pushable)',
             47: 'cyan pit: takes the cyan ball', 48: 'purple pit: takes the purple ball',
             49: 'yellow pit: takes the yellow ball', 50: 'cyan paint puddle', 51: 'purple paint puddle',
             52: 'yellow paint puddle', 53: 'cyan colour block (pushable)', 54: 'purple colour block (pushable)',
             55: 'yellow colour block (pushable)', 56: 'cherry'}
    for kind, depicts in extra.items():
        data = (SPRITES / f'tile-{kind}.png').read_bytes()
        manifest.append({'path': f'sprites/tile-{kind}.png', 'depicts': depicts,
                         'sha256': hashlib.sha256(data).hexdigest()})
    # Keep what other tools describe in the same folder, such as the card.
    art_path = ROOT / 'assets/shovey/art.json'
    art = json.loads(art_path.read_text())
    kept = [item for item in art['files'] if not item['path'].startswith('sprites/') and item['path'] != 'preview.png']
    art['files'] = manifest + kept
    art['generator'] = 'tools/pixel/pixel.py'
    art['method'] = ('Pixel sprites drawn by tools/pixel/pixel.py or generated for Shovey by an image model '
                     'and fitted to a 32 by 32 grid; the card is composed from them. No outside image is used.')
    art_path.write_text(json.dumps(art, indent=2) + '\n')
    from share_player import share_player
    share_player()
    print(f'wrote {len(manifest) - 1} sprites and the card')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    make = commands.add_parser('generate')
    make.add_argument('names', nargs='*')
    make.add_argument('--again', action='store_true', help='draw again even when a sprite exists')
    refit = commands.add_parser('fit', help='fit the kept raw pictures again')
    refit.add_argument('names', nargs='*')
    commands.add_parser('build')
    args = parser.parse_args()
    if args.command == 'generate':
        generate(set(args.names), args.again)
    elif args.command == 'fit':
        for name in args.names or list(SPEC['generated']) + list(SPEC['edited']):
            fit(name)
    else:
        build()


if __name__ == '__main__':
    main()
