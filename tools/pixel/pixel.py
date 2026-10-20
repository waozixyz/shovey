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


def wall(face=(178, 182, 181, 255)):
    image = Image.new('RGBA', (SIZE, SIZE))
    bevel(image, (0, 0, SIZE - 1, SIZE - 1), face, 4, light=1.36, dark=0.46)
    bevel(image, (10, 10, 21, 21), face, 2, raised=False, light=1.3, dark=0.55)
    return grain(image, 21, dark=0.86, light=1.1, share=0.3)


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
    return moss(wall(), 31, 5)


def mossy_floor():
    """The opened gate: the mossy block sunk level with the floor."""
    image = floor()
    bevel(image, (3, 3, 28, 28), shade(FLOOR, 0.9), 1, raised=False)
    return moss(image, 33, 4)


def pit(colour):
    """A coloured pit filling nearly the whole cell, like the original's."""
    image = floor()
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
    image = floor()
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
    image = floor()
    px = image.load()
    red, pale = (204, 82, 66, 255), (238, 200, 190, 255)
    for y in range(6, 26):
        for x in range(6, 26):
            px[x, y] = red if (x + y) % 6 < 2 else pale
    return image


def ring(colour, dots, lit=None, angle=None):
    image = floor()
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
    image = floor()
    image.alpha_composite(sprite)
    return image


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

# ---------------------------------------------------------------- the set


def sprites():
    green = lambda h, s, v: 60 <= h <= 180 and s > 0.2
    blue = lambda h, s, v: 170 <= h <= 230 and s > 0.25
    # Shovey is seen from above and looks where it goes, so one picture facing
    # up is turned for the other directions, as in the original.
    up = native('player')
    players = {'up': up, 'right': up.rotate(-90), 'down': up.rotate(180), 'left': up.rotate(90)}
    mirror = recolour(players['down'], green, 330)
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
        'tile-4': ('red pit: takes the red ball', pit((222, 40, 30, 255))),
        'tile-5': ('blue pit: takes the blue ball', pit((28, 92, 222, 255))),
        'tile-6': ('green pit: takes the green ball', pit((36, 172, 52, 255))),
        'tile-7': ('home: a small cottage with a jade roof and a lit door, on grass', on_grass(native('home'))),
        'tile-8': ('teleporter: a stone pad with blue rings', over_floor(native('teleporter'))),
        'tile-9': ('crate (pushable)', native('crate')),
        'tile-10': ('start position, drawn as floor', floor()),
        'tile-11': ('trail field: a lilac ring mark', over_floor(native('trail'))),
        'tile-12': ('wall: a raised grey stone block', wall()),
        'tile-13': ('pressure plate: a round orange button', over_floor(native('plate'))),
        'tile-14': ('closed gate: a stone block overgrown with moss', mossy_wall()),
        'tile-15': ('red paint puddle', native('paint-red')),
        'tile-16': ('blue paint puddle', native('paint-blue')),
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
        'shadow': ('mirror Shovey (pink)', mirror),
        'door-open': ('open gate: the mossy block sunk level with the floor', mossy_floor()),
        'projectile': ('a flying iron shot', native('projectile')),
    }
    for facing, sprite in players.items():
        out[f'player-{facing}'] = (f'Shovey looking {facing}', sprite)
        out[f'charged-{facing}'] = (f'charged Shovey looking {facing}', glow(sprite))
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
            if cell not in '#Hr':
                image.alpha_composite(sheet['tile-0'][1], (x * SIZE, y * SIZE))
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
    sheet = {name: (depicts, saturate(image)) for name, (depicts, image) in sprites().items()}
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
    # Keep what other tools describe in the same folder, such as the card.
    art_path = ROOT / 'assets/shovey/art.json'
    art = json.loads(art_path.read_text())
    kept = [item for item in art['files'] if not item['path'].startswith('sprites/') and item['path'] != 'preview.png']
    art['files'] = manifest + kept
    art['generator'] = 'tools/pixel/pixel.py'
    art['method'] = ('Pixel sprites drawn by tools/pixel/pixel.py or generated for Shovey by an image model '
                     'and fitted to a 32 by 32 grid; the card is composed from them. No outside image is used.')
    art_path.write_text(json.dumps(art, indent=2) + '\n')
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
