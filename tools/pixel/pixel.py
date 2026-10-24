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


# The original pits are flat pure colours; each keeps the original pattern
# (the dark dithered rim top left, the white glint) with its colour and rim
# pulled halfway towards the body and shade of the ball it takes.
PIT_COLOURS = {
    'red': ((255, 0, 0), (132, 0, 0), (230, 0, 0), (167, 0, 0)),
    'blue': ((0, 0, 255), (0, 0, 132), (24, 99, 220), (7, 44, 130)),
    'green': ((0, 255, 0), (0, 130, 0), (65, 180, 70), (34, 122, 47)),
    'cyan': ((0, 255, 255), (0, 132, 132), (65, 176, 180), (34, 109, 122)),
    'purple': ((170, 0, 255), (88, 0, 132), (119, 24, 220), (76, 7, 130)),
    'yellow': ((255, 255, 0), (132, 132, 0), (230, 227, 0), (167, 165, 0)),
}


def pit(colour, pull=0.5):
    pit_body, pit_rim, ball_body, ball_shade = PIT_COLOURS[colour]
    mix = lambda a, b: tuple(round(x + (y - x) * pull) for x, y in zip(a, b)) + (255,)
    swap = {(255, 0, 0, 255): mix(pit_body, ball_body), (132, 0, 0, 255): mix(pit_rim, ball_shade)}
    image = native('pit-red-original').resize((SIZE, SIZE), Image.Resampling.NEAREST)
    image.putdata([swap.get(pixel, pixel) for pixel in image.getdata()])
    return image


def shade(colour, factor):
    return tuple(max(0, min(255, round(c * factor))) for c in colour[:3]) + (255,)


FLOOR = (208, 211, 210, 255)
GRASS = (104, 172, 92, 255)
ORANGE = (221, 137, 64, 255)
MOSS_BUTTON_COLORS = ((57, 157, 61, 255), (65, 137, 211, 255),
                      (207, 75, 60, 255), (224, 180, 47, 255), (155, 92, 204, 255))


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


STONE = (178, 178, 174, 255)
MATERIALS = ((104, 126, 137, 255), (166, 102, 78, 255),
             (198, 177, 128, 255), (145, 110, 76, 255))


def wall(face=STONE):
    image = Image.new('RGBA', (SIZE, SIZE))
    if face == STONE:
        bevel(image, (0, 0, SIZE - 1, SIZE - 1), face, 4, light=1.36, dark=0.46)
        bevel(image, (10, 10, 21, 21), face, 2, raised=False, light=1.3, dark=0.55)
        return grain(image, 21, dark=0.86, light=1.1, share=0.3)
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


def mossy_wall(style=-1):
    """The gate a button opens: the wall image with moss on top."""
    image = moss(wall() if style < 0 else wall_variant(style), 31 + style + 1, 11)
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


def mossy_floor(style=-1):
    """A lowered wall: a flat material panel inside its recessed mossy seam."""
    image = floor() if style < 0 else material_floor(style)
    draw = ImageDraw.Draw(image)
    face = (130, 139, 122, 255) if style < 0 else MATERIALS[style]
    # A thin inner seam and inset corner marks identify the moving slab,
    # without the raised edge and central recess of a standing wall.
    draw.rectangle((3, 3, 28, 28), outline=shade(face, 0.49), width=1)
    draw.line((4, 29, 29, 29, 29, 4), fill=shade(face, 1.25), width=1)
    for x, y, dx, dy in ((6, 6, 1, 1), (25, 6, -1, 1), (6, 25, 1, -1), (25, 25, -1, -1)):
        draw.line((x + dx * 3, y, x, y, x, y + dy * 3), fill=MOSS[0], width=1)
        draw.point((x + dx, y + dy), fill=MOSS[2])
    return image


def pressure_plate(colour=None, material=None):
    """A round green push button recessed into the paving, like the original."""
    image = Image.new('RGBA', (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 27, 27), fill=(47, 58, 53, 255))
    draw.ellipse((5, 5, 26, 26), fill=shade(material, 1.25) if material else (201, 208, 198, 255))
    draw.ellipse((7, 7, 24, 24), fill=shade(colour, 0.50) if colour else (29, 85, 37, 255))
    draw.ellipse((8, 8, 23, 23), fill=colour or MOSS_BUTTON_COLORS[0])
    draw.arc((8, 8, 23, 23), 195, 285, fill=shade(colour, 1.5) if colour else (149, 212, 109, 255), width=1)
    draw.arc((8, 8, 23, 23), 15, 105, fill=shade(colour, 0.72) if colour else (37, 115, 44, 255), width=1)
    return image


def boulder():
    image = Image.new('RGBA', (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 25, 29, 30), fill=(38, 40, 34, 90))
    draw.polygon(((3, 15), (7, 7), (16, 3), (25, 7), (29, 17), (26, 26), (17, 29), (6, 26)), fill=(82, 84, 76, 255))
    draw.polygon(((5, 15), (9, 8), (16, 5), (24, 9), (22, 15), (12, 18)), fill=(177, 178, 166, 255))
    draw.polygon(((5, 16), (12, 18), (16, 27), (7, 24)), fill=(141, 143, 131, 255))
    draw.polygon(((13, 19), (22, 16), (27, 18), (24, 25), (17, 27)), fill=(111, 115, 103, 255))
    draw.polygon(((24, 10), (27, 16), (23, 14)), fill=(146, 149, 136, 255))
    draw.line((9, 9, 16, 6, 22, 9), fill=(206, 205, 191, 255))
    draw.line((13, 18, 17, 13, 21, 13), fill=(126, 130, 116, 255))
    return grain(image, 122, dark=0.94, light=1.04, share=0.22)


def lantern():
    image = Image.new('RGBA', (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    frame = (70, 65, 48, 255)
    draw.ellipse((7, 25, 25, 29), fill=(35, 39, 34, 90))
    draw.ellipse((12, 2, 20, 11), outline=frame, width=2)
    draw.polygon(((7, 11), (11, 7), (21, 7), (25, 11)), fill=frame)
    draw.line((10, 9, 22, 9), fill=(153, 137, 83, 255))
    for y in range(12, 25):
        draw.line((10, y, 22, y), fill=(247, 159 + (24 - y) * 5, 57 + (24 - y) * 7, 255))
    draw.polygon(((14, 23), (13, 19), (16, 14), (16, 18), (19, 20), (18, 23)), fill=(255, 242, 162, 255))
    draw.rectangle((8, 12, 10, 25), fill=frame)
    draw.rectangle((22, 12, 24, 25), fill=frame)
    draw.line((9, 12, 9, 23), fill=(163, 146, 94, 255))
    draw.rectangle((7, 25, 25, 27), fill=frame)
    draw.line((9, 25, 23, 25), fill=(175, 150, 89, 255))
    return image


def door(opened=False, colour=None):
    # An overlay on the selected wall, without a built-in wall or floor.
    image = Image.new('RGBA', (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    wood = colour or (158, 109, 61, 255)
    if opened:
        draw.polygon(((3, 3), (10, 7), (10, 29), (3, 29)), fill=wood)
        draw.line((3, 3, 10, 7, 10, 28), fill=shade(wood, 1.26))
        draw.line((4, 7, 4, 27), fill=shade(wood, 0.62))
        draw.point((9, 18), fill=(246, 203, 89, 255))
    else:
        bevel(image, (3, 3, 28, 29), wood, 2, light=1.24, dark=0.60)
        for box in ((7, 7, 24, 14), (7, 20, 24, 26)):
            bevel(image, box, shade(wood, 0.92), 1, raised=False, light=1.20, dark=0.64)
        draw.rectangle((24, 16, 26, 18), fill=shade(wood, 0.50))
        draw.rectangle((25, 16, 26, 17), fill=(235, 184, 67, 255))
        draw.point((25, 16), fill=(255, 225, 136, 255))
    for y in (9, 24):
        draw.line((3, y, 5, y), fill=(66, 68, 63, 255))
        draw.point((3, y), fill=(207, 208, 195, 255))
    return image


def gate(opened=False, colour=None):
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
    if colour:
        draw.line((5, 5, 26, 5), fill=colour, width=2)
        for x in (4, 26):
            draw.rectangle((x, 22, x + 1, 27), fill=colour)
        if not opened:
            draw.line((8, 18, 23, 18), fill=colour)
    return image


def lever(active=False, colour=None):
    image = Image.new('RGBA', (SIZE, SIZE))
    bevel(image, (7, 23, 24, 29), (151, 163, 165, 255), 2)
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 19, 19, 26), fill=(39, 57, 65, 255))
    x, y = (23, 7) if active else (8, 11)
    draw.line((16, 22, x, y), fill=(30, 48, 58, 255), width=4)
    draw.line((15, 22, x - 1, y), fill=(155, 186, 194, 255), width=2)
    bevel(image, (x - 4, y - 2, x + 3, y + 3),
          colour or ((100, 181, 123, 255) if active else (221, 137, 64, 255)), 1)
    if colour:
        draw.line((10, 27, 21, 27), fill=colour, width=2)
        draw.point((22, 25), fill=(239, 226, 162, 255) if active else (64, 71, 66, 255))
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
    """A solid ring of the colour, with a darker rim, and optionally a lit
    bead on it at angle degrees. dots is kept for its callers' readability."""
    image = Image.new('RGBA', (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    draw.ellipse((6, 6, 25, 25), outline=shade(colour, 0.7), width=1)
    draw.ellipse((7, 7, 24, 24), outline=colour, width=2)
    if angle is not None:
        a = math.radians(angle)
        x, y = 16 + round(8.5 * math.cos(a)), 16 + round(8.5 * math.sin(a))
        draw.ellipse((x - 2, y - 2, x + 1, y + 1), fill=lit)
    return image


def sensor(state, frame=0):
    """A sensor, close to the original but standing on our floor: a solid red
    ring with a white inner line and a red bead at its top. 'idle' waits;
    'active' glows and its bead circles the ring, frame 0 to 7; 'closed' is a
    raised stone block with a big red gem, as the original's sealed sensor."""
    image = Image.new('RGBA', (SIZE, SIZE))
    if state == 'closed':
        bevel(image, (4, 4, 27, 27), (206, 207, 202, 255), 3, raised=True, light=1.22, dark=0.5)
        grain(image, 2050, dark=0.92, light=1.05, share=0.18)
    draw = ImageDraw.Draw(image)
    glow = state == 'active'
    red = (232, 70, 44, 255) if glow else (196, 40, 36, 255)
    dark_red = (120, 18, 16, 255)
    centre, radius = 16, (8 if state != 'closed' else 7)
    if glow:
        draw.ellipse((centre - radius - 2, centre - radius - 2, centre + radius + 1, centre + radius + 1), outline=(255, 170, 120, 255), width=1)
    draw.ellipse((centre - radius, centre - radius, centre + radius - 1, centre + radius - 1), outline=dark_red, width=1)
    draw.ellipse((centre - radius + 1, centre - radius + 1, centre + radius - 2, centre + radius - 2), outline=red, width=2)
    draw.ellipse((centre - radius + 3, centre - radius + 3, centre + radius - 4, centre + radius - 4), outline=(250, 244, 236, 255), width=1)

    def bead(x, y, r):
        draw.ellipse((x - r, y - r, x + r - 1, y + r - 1), fill=dark_red)
        draw.ellipse((x - r + 1, y - r + 1, x + r - 2, y + r - 2), fill=red)
        draw.point((x - r + 2, y - r + 2), fill=(255, 214, 200, 255))
    if state == 'closed':
        bead(centre, centre, 5)
    else:
        angle = math.radians(-90 + 45 * frame)
        bead(round(centre + math.cos(angle) * (radius - 1)), round(centre + math.sin(angle) * (radius - 1)), 3)
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
    """An abyss on its own, ground on every side (the palette's picture)."""
    return abyss_edge(15)


def abyss_edge(mask):
    """A drop into darkness, seen from above and a little from the front.
    mask bits 0-3 (left, top, right, bottom on screen) mark solid ground on
    that side. Under ground at the top, the far cliff shows: a soil lip, then
    bands of rock fading into the dark. Ground at the sides gives a narrow
    rock wall; ground at the bottom, the near lip with its shadow. Open sides
    join the next abyss cell seamlessly."""
    rng = random.Random(6500 + mask)
    image = Image.new('RGBA', (SIZE, SIZE))
    px = image.load()
    # The dark: near black with a cold tint and a faint grain.
    for y in range(SIZE):
        for x in range(SIZE):
            n = rng.randint(-2, 2)
            px[x, y] = (6 + n, 9 + n, 13 + n, 255)
    # Grey stone, the colour of the paving and walls around most drops.
    strata = [(172, 172, 166), (150, 150, 144), (130, 130, 126), (158, 156, 150), (118, 118, 114), (140, 138, 134), (106, 106, 102)]
    def blend(colour, factor, x, y):
        base = px[x, y]
        return tuple(round(base[i] * (1 - factor) + colour[i] * factor) for i in range(3)) + (255,)
    if mask & 2:
        height = 16
        for y in range(height):
            light = max(0.0, 1.0 - (y - 2) / (height - 2)) ** 0.8 if y >= 2 else 1.0
            for x in range(SIZE):
                if y == 0:
                    colour = (196, 198, 192)        # the paving's edge
                elif y == 1:
                    colour = (92, 94, 92)
                else:
                    band = strata[min(len(strata) - 1, (y - 2) // 2)]
                    seam = (y - 2) % 2 == 1 and rng.random() < 0.55
                    jitter = rng.uniform(0.92, 1.08)
                    colour = tuple(min(255, round(c * jitter * (0.78 if seam else 1.0))) for c in band)
                    if rng.random() < 0.04: colour = (70, 72, 70)   # a crack
                    if y == 2: colour = tuple(min(255, c + 22) for c in colour)  # lit top of the rock
                px[x, y] = blend(colour, light, x, y)
    for side in (0, 2):
        if not mask & (1 << side):
            continue
        for y in range(SIZE):
            for depth in range(4):
                x = depth if side == 0 else SIZE - 1 - depth
                if depth == 0:
                    colour, factor = (184, 184, 178), 1.0
                else:
                    colour = (104, 106, 102) if side == 0 else (124, 124, 120)
                    factor = 0.75 - depth * 0.2
                px[x, y] = blend(colour, factor, x, y)
    if mask & 8:
        for x in range(SIZE):
            px[x, SIZE - 1] = (200, 202, 196, 255)
            px[x, SIZE - 2] = blend((84, 86, 84), 0.9, x, SIZE - 2)
            px[x, SIZE - 3] = blend((20, 16, 14), 0.6, x, SIZE - 3)
    return image


def abyss_corner(bits):
    """What an abyss cell adds at an inner corner, over its own picture:
    bits 0-3 mark solid ground diagonally up-left, up-right, down-left and
    down-right (on screen) while both cells beside it are abyss. Under ground
    up-left or up-right, the rock wall of that ground runs on down beside
    the far cliff; under ground below, the near lip turns the corner."""
    image = Image.new('RGBA', (SIZE, SIZE))
    px = image.load()
    height = 16
    for corner, side in ((1, 0), (2, 2)):
        if not bits & corner:
            continue
        for y in range(height):
            light = max(0.0, 1.0 - y / height) ** 0.8
            for depth in range(4):
                x = depth if side == 0 else SIZE - 1 - depth
                if depth == 0:
                    colour = (184, 184, 178)
                else:
                    colour = (104, 106, 102) if side == 0 else (124, 124, 120)
                alpha = round(255 * light * (1.0 if depth == 0 else 0.75 - depth * 0.2))
                if alpha > 0:
                    px[x, y] = colour + (alpha,)
    for corner, left in ((4, True), (8, False)):
        if not bits & corner:
            continue
        for depth in range(3):
            x = depth if left else SIZE - 1 - depth
            px[x, SIZE - 1] = (200, 202, 196, 255)
            px[x, SIZE - 2] = (84, 86, 84, 230)
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


def burst(frame):
    """A target struck by a shot, frame 0 to 5: a flash, then red and cream
    splinters flying out inside a fading ring of dust."""
    image = Image.new('RGBA', (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    if frame == 0:
        draw.ellipse((10, 10, 21, 21), fill=(255, 246, 214, 255))
        draw.ellipse((13, 13, 18, 18), fill=(255, 255, 255, 255))
        return image
    reach = 3 + frame * 2.4
    dust = max(0, 170 - frame * 30)
    if dust:
        r = reach + 2
        draw.ellipse((16 - r, 16 - r, 15 + r, 15 + r), outline=(222, 212, 192, dust), width=1)
    rng = random.Random(500 + frame)
    for piece in range(10):
        angle = 2 * math.pi * piece / 10 + rng.uniform(-0.18, 0.18)
        x = 16 + math.cos(angle) * reach
        y = 16 + math.sin(angle) * reach + frame * 0.6
        size = 3 if frame < 3 else 2 if frame < 5 else 1
        colour = (206, 58, 48, 255) if piece % 2 else (240, 230, 212, 255)
        draw.rectangle((round(x), round(y), round(x) + size - 1, round(y) + size - 1), fill=colour)
    return image


def explosion(frame):
    """A bomb crate going off, frame 0 to 7: a spark, a fireball with a dark
    red rim and flying stone chips, then billowing smoke that drifts apart."""
    image = Image.new('RGBA', (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    def disc(r, colour, cx=16, cy=16):
        draw.ellipse((round(cx - r), round(cy - r), round(cx + r) - 1, round(cy + r) - 1), fill=colour)
    rng = random.Random(900 + frame)
    fire = [(4, 3), (7, 6), (10, 9), (13, 12), (10, 8), (0, 0), (0, 0), (0, 0)][frame]
    # Smoke first, so the shrinking fireball still glows inside it.
    if frame >= 4:
        fade = [0, 0, 0, 0, 255, 235, 170, 90][frame]
        spread = [0, 0, 0, 0, 10, 9, 11, 12][frame]
        for puff in range(7):
            angle = 2 * math.pi * puff / 7 + frame * 0.3
            cx = 16 + math.cos(angle) * spread + rng.uniform(-1, 1)
            cy = 16 + math.sin(angle) * spread - (frame - 4) * 1.2
            r = [0, 0, 0, 0, 5, 6, 5, 3][frame]
            disc(r, (118, 116, 112, fade), cx, cy)
            disc(max(1, r - 2), (164, 160, 152, fade), cx, cy)
        if frame <= 5:
            for ember in range(5):
                angle = rng.uniform(0, 2 * math.pi)
                x, y = 16 + math.cos(angle) * rng.uniform(3, 9), 16 + math.sin(angle) * rng.uniform(3, 9)
                draw.point((round(x), round(y)), fill=(255, 176, 60, 255))
    if frame <= 4:
        outer, core = fire
        disc(outer, (150, 34, 26, 255))
        disc(outer - 1, (228, 92, 36, 255))
        disc(max(1, outer * 0.72), (247, 168, 52, 255))
        disc(max(1, outer * 0.45), (255, 236, 150, 255))
        if frame < 3: disc(max(1, outer * 0.22), (255, 255, 246, 255))
    if 2 <= frame <= 6:
        reach = [0, 0, 11, 13, 14.5, 15, 15.5][frame]
        for chip in range(8):
            angle = 2 * math.pi * chip / 8 + 0.4
            x = 16 + math.cos(angle) * reach
            y = 16 + math.sin(angle) * reach + (frame - 2) * 0.8
            colour = (196, 176, 132, 255) if chip % 2 else (124, 122, 118, 255)
            size = 2 if frame < 6 else 1
            draw.rectangle((round(x), round(y), round(x) + size - 1, round(y) + size - 1), fill=colour)
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


def locked_door():
    """A lock as a door in the wall: the stone block of a wall with an arched
    wooden door set into it, two iron bands and a brass lock plate whose
    keyhole a key opens."""
    image = Image.new('RGBA', (SIZE, SIZE))
    bevel(image, (0, 0, SIZE - 1, SIZE - 1), STONE, 4, light=1.36, dark=0.46)
    grain(image, 34, dark=0.86, light=1.1, share=0.3)
    draw = ImageDraw.Draw(image)
    wood = MATERIALS[3]
    # The doorway: a dark reveal, then the door inside it with a round top.
    draw.rectangle((6, 12, 25, 29), fill=shade(STONE, 0.42))
    draw.ellipse((6, 4, 25, 21), fill=shade(STONE, 0.42))
    draw.rectangle((7, 12, 24, 29), fill=wood)
    draw.ellipse((7, 5, 24, 20), fill=wood)
    planks = ImageDraw.Draw(image)
    for x in (11, 15, 20):
        planks.line((x, 6 if x == 15 else 8, x, 29), fill=shade(wood, 0.62))
        planks.line((x + 1, 7 if x == 15 else 9, x + 1, 29), fill=shade(wood, 1.16))
    grain(image, 340, dark=0.9, light=1.08, share=0.2)
    # Iron bands with rivets.
    iron, rivet = (64, 66, 70, 255), (150, 154, 160, 255)
    for y in (11, 24):
        draw.rectangle((7, y, 24, y + 1), fill=iron)
        for x in (9, 22):
            draw.point((x, y), fill=rivet)
    # The brass lock plate and its keyhole.
    brass, dark_brass = (222, 176, 62, 255), (138, 98, 26, 255)
    draw.rectangle((13, 14, 19, 21), fill=dark_brass)
    draw.rectangle((13, 14, 18, 20), fill=brass)
    draw.point((13, 14), fill=(250, 226, 140, 255))
    draw.rectangle((15, 16, 16, 17), fill=(30, 24, 18, 255))
    draw.line((15, 18, 16, 18), fill=(30, 24, 18, 255))
    draw.point((15, 19), fill=(30, 24, 18, 255))
    draw.point((16, 19), fill=(30, 24, 18, 255))
    # Drawn over the floor like the moss gate, which marks it the same way.
    image.putpixel((0, 0), (0, 0, 0, 0))
    return image


def trail_marker():
    image = Image.new('RGBA', (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 27, 27), fill=(103, 47, 112, 255))
    draw.ellipse((5, 5, 26, 26), fill=(206, 102, 209, 255))
    draw.ellipse((7, 7, 24, 24), fill=(236, 157, 233, 255))
    draw.ellipse((8, 8, 23, 23), fill=(0, 0, 0, 0))
    draw.line((7, 15, 24, 15), fill=(242, 179, 239, 255), width=1)
    draw.rectangle((6, 16, 25, 17), fill=(190, 78, 193, 255))
    draw.line((7, 18, 24, 18), fill=(112, 46, 123, 255), width=1)
    return image


def slide_chevrons():
    """The original's slide power: a green dot with two rings of chevrons
    pointing outwards, the inner ring bright and the outer one deeper."""
    image = Image.new('RGBA', (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    # One chevron pointing up, short enough to stay apart from its
    # neighbours, lit on its outer edge and shaded on its inner one; the
    # other three are the same turned about the centre.
    for apex, lit, dark in ((8, (96, 230, 80, 255), (30, 128, 44, 255)), (3, (60, 186, 64, 255), (22, 96, 36, 255))):
        for t in range(3):
            for x in (15 - t, 16 + t):
                draw.point((x, apex + t), fill=lit)
                draw.point((x, apex + t + 1), fill=dark)
    for turn in (90, 180, 270):
        image.alpha_composite(image.rotate(turn))
    draw = ImageDraw.Draw(image)
    draw.rectangle((14, 14, 17, 17), fill=(30, 128, 44, 255))
    draw.rectangle((14, 14, 16, 16), fill=(96, 230, 80, 255))
    draw.point((15, 15), fill=(206, 250, 186, 255))
    for corner in ((14, 14), (17, 14), (14, 17), (17, 17)):
        draw.point(corner, fill=(0, 0, 0, 0))
    return image


def sprites():
    green = lambda h, s, v: 60 <= h <= 180 and s > 0.2
    blue = lambda h, s, v: 170 <= h <= 230 and s > 0.25
    # Shovey is seen from above and looks where it goes, so one picture facing
    # up is turned for the other directions, as in the original.
    up = native('player')
    # The comb and beak in the kept source point up already.
    duck = native('duck-up')
    players = {'up': up, 'right': up.rotate(-90), 'down': up.rotate(180), 'left': up.rotate(90)}
    mirror = recolour(players['up'], green, 330)
    # A small shot lying on the floor, about the size of the original's,
    # with its shadow to the lower right.
    shot = Image.new('RGBA', (SIZE, SIZE))
    shot_draw = ImageDraw.Draw(shot)
    shot_draw.ellipse((12, 13, 24, 24), fill=(0, 0, 0, 70))
    shot_draw.ellipse((9, 9, 21, 21), fill=(60, 68, 67, 255), outline=(26, 32, 32, 255))
    shot_draw.ellipse((12, 11, 16, 15), fill=(112, 124, 121, 255))
    shot_draw.point((13, 12), fill=(196, 206, 203, 255))
    out = {
        'tile-0': ('floor: a pale grey paving stone', floor()),
        'tile-1': ('red ball (pushable)', native('ball-red')),
        'tile-2': ('blue ball (pushable)', native('ball-blue')),
        'tile-3': ('green ball (pushable)', native('ball-green')),
        'tile-4': ('red pit: takes the red ball', pit('red')),
        'tile-5': ('blue pit: takes the blue ball', pit('blue')),
        'tile-6': ('green pit: takes the green ball', pit('green')),
        'tile-47': ('cyan pit: takes the cyan ball', pit('cyan')),
        'tile-48': ('purple pit: takes the purple ball', pit('purple')),
        'tile-49': ('yellow pit: takes the yellow ball', pit('yellow')),
        'tile-7': ('home: a small cottage with a jade roof and a lit door, on grass', native('home')),
        'tile-8': ('teleporter: a recessed opening with an inward blue-green spiral', over_floor(native('teleporter'))),
        'tile-9': ('crate: clean chestnut planks with crossed wooden braces (pushable)', crate_sprite()),
        'tile-10': ('start position, drawn as floor', floor()),
        'tile-11': ('trail field: a lilac ring with a straight horizontal bar', trail_marker()),
        'tile-12': ('wall: a raised grey stone block', wall()),
        'tile-13': ('pressure plate: a round green button recessed into the paving', pressure_plate()),
        'tile-14': ('mossy stone wall: sinks when a pressure plate is held', mossy_wall()),
        'tile-15': ('red paint puddle, matching the other paint silhouettes', recolour(native('paint-green'), green, 0)),
        'tile-16': ('blue paint puddle, matching the other paint silhouettes', recolour(native('paint-green'), green, 240)),
        'tile-17': ('green paint puddle', native('paint-green')),
        'tile-18': ('crate goal: four corner brackets', crate_goal()),
        'tile-19': ('star block: a stone block with a bright star (pushable)', star_block()),
        'tile-20': ('sensor not yet visited: a stone plate with a red ring and a red bead at its top', sensor('idle')),
        'tile-21': ('apple', native('apple')),
        'tile-22': ('active sensor: its red ring glows', sensor('active')),
        'tile-23': ('closed sensor: a raised stone block with a red gem', sensor('closed')),
        'tile-24': ('active sensor: its red ring glows', sensor('active')),
        'tile-25': ('reverse controls: clean green four-way arrows on the floor', native('reverse-arrows')),
        'tile-26': ('ammunition: one iron shot', shot),
        'tile-27': ('charge: a lightning bolt engraved into the floor, with yellow sparks', native('charge-engraved')),
        'tile-28': ('target: a red and white target board (pushable)', native('target')),
        'tile-29': ('moving block: a stone puck with a blue light', over_floor(native('puck'))),
        'tile-30': ('fresh path: a solid blue ring', ring((63, 111, 143, 255), 10)),
        'tile-31': ('used path: a solid grey ring', ring((150, 158, 156, 255), 10)),
        'tile-32': ('moving block stopping: its light turns red', over_floor(recolour(native('puck'), blue, 4))),
        'tile-33': ('key', native('key')),
        'tile-34': ('lock: a locked wooden door set into the wall, opened with a key', locked_door()),
        'tile-35': ('slide power: green chevrons spreading out from a dot', slide_chevrons()),
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
        'tile-82': ('garden duck: a cream-white duck with a brown wing and orange bill', duck),
        'tile-83': ('turtle: a clean jade shell with pale yellow feet', native('turtle')),
        'tile-84': ('tree: a broad jade canopy and brown trunk; blocks movement', native('tree')),
        'tile-85': ('red portal', colour_portal(0)),
        'tile-86': ('green portal', colour_portal(125)),
        'tile-87': ('orange portal', colour_portal(28)),
        'tile-88': ('crab: a bright orange shell and clear raised pincers', native('crab')),
        'tile-92': ('orange gate: controlled by matching orange levers', gate(colour=ORANGE)),
        'tile-93': ('orange lever: switched off', lever(colour=ORANGE)),
        'tile-94': ('orange lever: switched on', lever(True, ORANGE)),
        'gate-open': ('orange gate with its bars drawn aside', gate(True, ORANGE)),
        'tile-95': ('slate wall: dark blue-grey stone slabs', wall_variant(0)),
        'tile-96': ('brick wall: warm bricks with pale mortar', wall_variant(1)),
        'tile-97': ('sandstone wall: pale carved blocks', wall_variant(2)),
        'tile-98': ('timber wall: upright planks with iron straps', wall_variant(3)),
        'tile-99': ('slate floor: flat blue-grey stone paving', material_floor(0)),
        'tile-100': ('brick floor: flat warm brick paving', material_floor(1)),
        'tile-101': ('sandstone floor: flat pale sandstone paving', material_floor(2)),
        'tile-102': ('timber floor: flat wooden floorboards', material_floor(3)),
        'tile-103': ('mossy floor: flat stone paving with green moss', material_floor(4)),
        'tile-104': ('wooden door: opens when Shovey walks through it', door()),
        'tile-105': ('wooden door standing open, with a clear passage', door(True)),
        'tile-106': ('floor lantern: warm glass in a metal frame; blocks movement', lantern()),
        'tile-122': ('boulder: a solid faceted stone that blocks movement', boulder()),
        'tile-123': ('orange gate: starts open and closes when its lever is on', gate(True, ORANGE)),
        'tile-135': ('mushrooms: red-orange spotted caps on the floor (decoration)', native('mushrooms')),
        'tile-136': ('fallen autumn leaves on the floor (decoration)', native('fallen-leaves')),
        'tile-137': ('bluebells: blue bell flowers on the floor (decoration)', native('bluebells')),
        'tile-138': ('lily pads with a pink lotus, floating on water (decoration)', native('lily-pads')),
        'tile-139': ('berry bush: a round leafy bush with red berries; blocks movement', native('berry-bush')),
        'tile-140': ('flower pot: terracotta pot of pink, yellow and white flowers; blocks movement', native('flower-pot')),
        'tile-141': ('barrel: an upright wooden barrel with iron hoops; blocks movement', native('barrel')),
        'tile-142': ('tree stump: a cut stump with rings and a green sprout; blocks movement', native('tree-stump')),
        'shadow': ('mirror Shovey (pink)', mirror),
        'door-open': ('mossy wall lowered, leaving a moss-covered stone rim', mossy_floor()),
        'projectile': ('a flying iron shot', native('projectile')),
    }
    for color, (name, colour) in enumerate((('red', (180, 78, 66, 255)),
                                           ('blue', (67, 117, 172, 255)),
                                           ('green', (80, 143, 88, 255)))):
        kind = 107 + color * 3
        out[f'tile-{kind}'] = (f'{name} gate: controlled by matching levers', gate(colour=colour))
        out[f'tile-{kind + 1}'] = (f'{name} lever: switched off', lever(colour=colour))
        out[f'tile-{kind + 2}'] = (f'{name} lever: switched on', lever(True, colour))
        out[f'gate-open-{color}'] = (f'{name} gate standing open', gate(True, colour))
        out[f'tile-{124 + color}'] = (f'{name} gate: starts open and closes when its lever is on', gate(True, colour))
        out[f'tile-{116 + color * 2}'] = (f'{name} wooden door: opens when walked through', door(colour=colour))
        out[f'tile-{117 + color * 2}'] = (f'{name} wooden door standing open', door(True, colour))
    for style, name in enumerate(('slate', 'brick', 'sandstone', 'timber')):
        out[f'tile-{127 + style}'] = (f'mossy {name} wall: lowers onto its matching floor while its button is held', mossy_wall(style))
        out[f'tile-{131 + style}'] = (f'{name} pressure button: controls matching mossy {name} walls', pressure_plate(MOSS_BUTTON_COLORS[style + 1], MATERIALS[style]))
        out[f'moss-lowered-{style}'] = (f'{name} wall lowered into a flat slab with a recessed mossy seam', mossy_floor(style))
    for facing, sprite in players.items():
        out[f'player-{facing}'] = (f'Shovey looking {facing}', sprite)
        out[f'charged-{facing}'] = (f'charged Shovey looking {facing}', glow(sprite))
    for animal in ('dog', 'turtle'):
        for facing, angle in (('up', 0), ('right', -90), ('down', 180), ('left', 90)):
            sprite = native(f'duck-{facing}') if animal == 'dog' else native(animal).rotate(angle)
            out[f'{animal}-{facing}'] = (f'{"garden duck" if animal == "dog" else animal} facing {facing}', sprite)
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
        out[f'abyss-corner-{mask}'] = ('an abyss inner corner: rock walls running on down and the near lip turning', abyss_corner(mask))
        out[f'abyss-edge-{mask}'] = ('abyss: a cliff of rock bands under the far ground, narrow walls at the sides and a lip at the near edge', abyss_edge(mask))
    for frame in range(6):
        out[f'burst-{frame}'] = (f'a target struck by a shot, frame {frame + 1} of 6', burst(frame))
    for frame in range(8):
        out[f'explosion-{frame}'] = (f'a bomb crate going off, frame {frame + 1} of 8', explosion(frame))
    for frame in range(1, 9):
        out[f'sensor-{frame}'] = (f'active sensor, its bead circling the glowing ring, frame {frame} of 8',
                                  sensor('active', frame - 1))
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


PIT_TILES = ('tile-4', 'tile-5', 'tile-6', 'tile-47', 'tile-48', 'tile-49')


def build():
    manifest = []
    sheet = {name: (depicts, image if name in PIT_TILES else saturate(image)) for name, (depicts, image) in sprites().items()}
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
    # The cyan, purple and yellow balls, puddles and blocks and the cherry are
    # kept pictures; list them.
    extra = {44: 'cyan ball (pushable)', 45: 'purple ball (pushable)', 46: 'yellow ball (pushable)',
             50: 'cyan paint puddle', 51: 'purple paint puddle',
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
