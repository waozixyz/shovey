#!/usr/bin/env python3
"""Compare preserved before/after player captures without retouching them."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[3]
ART = ROOT / 'art/modern'
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


def main():
    for orientation, width, height in [('landscape', 960, 600), ('portrait', 600, 900)]:
        margin, heading, gap, label = 20, 78, 20, 38
        canvas = Image.new('RGB', (2 * width + 3 * margin,
                                  heading + 2 * (height + label + gap)), '#f3efe4')
        draw = ImageDraw.Draw(canvas)
        title = ImageFont.truetype(FONT, 26)
        text = ImageFont.truetype(FONT, 19)
        draw.text((margin, 14), 'Before', font=title, fill='#283d2b')
        draw.text((width + 2 * margin, 14), 'After', font=title, fill='#283d2b')
        draw.text((margin, 49), 'Actual player captures · same window size', font=text, fill='#556452')
        for row, scene in enumerate(('classic', 'editor')):
            top = heading + row * (height + label + gap)
            for col, phase in enumerate(('before', 'after')):
                image = Image.open(ART / f'title-{scene}-{orientation}-{phase}.png').convert('RGB')
                assert image.width * height == image.height * width
                image = image.resize((width, height), Image.Resampling.LANCZOS)
                x = margin + col * (width + margin)
                draw.text((x, top), scene.title(), font=text, fill='#283d2b')
                canvas.paste(image, (x, top + label))
        target = ART / f'titles-before-after-{orientation}.png'
        canvas.save(target)
        print(target.relative_to(ROOT))


if __name__ == '__main__':
    main()
