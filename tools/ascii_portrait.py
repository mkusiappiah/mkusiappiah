"""Turn a portrait photo into the ASCII art on the profile card.

Usage: python tools/ascii_portrait.py photo.jpg --mode dark|light [--cols 76] [--rows 52] [--crop L T R B] > art/dark.txt

How it keeps a face recognisable:
- The plain backdrop is keyed out by its colour (sampled from the top corners) and left blank.
- Contrast is set twice: across the person (histogram equalisation), then locally, so eyes, glasses, nose and smile stand out from
  the skin around them whatever the lighting.
- Every character cell is compared with how each printable character actually looks in a monospace font (rendered with Pillow),
  and the closest one in shape and darkness is used: edges become / \\ ( ) _ | and similar instead of a flat shade.
- On the dark card characters are light ink, so bright areas get more ink; on the light card dark areas do.
Lines are padded to the full width, so the card can stretch each one to the same length in any font.
Needs Pillow, numpy and scipy; the daily stats job does not.
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

CHARS = [chr(code) for code in range(32, 127)]
FONTS = ['/System/Library/Fonts/Menlo.ttc', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 'C:/Windows/Fonts/consola.ttf']
LINE = 1.2                         # line height / font size, as the card draws the portrait


def glyphs(cell_w, cell_h):
    """How much ink each character puts in each pixel of a cell_w x cell_h cell: (characters, cell_h, cell_w), 0 to 1."""
    path = next(font for font in FONTS if Path(font).exists())
    size = 96
    font = ImageFont.truetype(path, size)
    width, height = round(font.getlength('M')), round(size * LINE)
    ascent, descent = font.getmetrics()
    maps = []
    for char in CHARS:
        image = Image.new('L', (width, height), 0)
        ImageDraw.Draw(image).text((0, (height - ascent - descent) / 2), char, fill=255, font=font)
        maps.append(np.asarray(image.resize((cell_w, cell_h), Image.BOX), dtype=np.float32) / 255)
    return np.stack(maps)


def person(rgb, tolerance):
    """1 for the person, 0 for the backdrop, from the distance to the top corners' colour; edges softened by a pixel."""
    h, w, _ = rgb.shape
    corners = np.array([rgb[2, 2], rgb[2, w - 3], rgb[h // 4, 2], rgb[h // 4, w - 3]])
    distance = np.abs(rgb - corners.mean(axis=0)).sum(axis=2)
    mask = ndimage.median_filter((distance > tolerance).astype(np.float32), size=5)
    mask = ndimage.binary_fill_holes(mask > 0.5).astype(np.float32)
    return ndimage.gaussian_filter(mask, 0.8)


def tone(rgb, mask, local, head):
    """Brightness of the person from 0 to 1: equalised over the head, then with local contrast mixed in."""
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    h = lum.shape[0]
    sample = lum[: int(h * head)][mask[: int(h * head)] > 0.5]
    ranks = np.searchsorted(np.sort(sample), lum) / max(1, sample.size)        # equalised: the head spans the whole range
    blur = ndimage.gaussian_filter(ranks, sigma=max(2.0, h / 40))
    spread = np.sqrt(ndimage.gaussian_filter((ranks - blur) ** 2, sigma=max(2.0, h / 40))) + 0.05
    # local contrast boosts edges (features against their surroundings) and leaves flat areas as they are
    return np.clip(ranks + local * 0.35 * np.clip((ranks - blur) / spread, -2, 2), 0, 1)


def portrait(photo, cols, rows, mode, crop=None, tolerance=110, local=0.45, head=0.55, cell=(6, 12), tone_weight=6.0, neck=0.6, body=None,
             gamma=0.8, outline=0.6):
    body = body if body is not None else (0.2 if mode == 'dark' else 1.0)    # a white shirt on the light card is already quiet
    cell_w, cell_h = cell
    image = Image.open(photo).convert('RGB')
    if crop:
        image = image.crop(crop)
    image = image.resize((cols * cell_w, rows * cell_h), Image.LANCZOS)
    rgb = np.asarray(image, dtype=np.float32) / 255
    mask = person(rgb, tolerance / 255)
    light = tone(rgb, mask, local, head)
    if mode == 'dark':
        light = light ** gamma                                                  # light ink on black: lift the face's mid-tones
    ink = (light if mode == 'dark' else 1 - light) * mask                       # the backdrop carries no ink
    # a clean silhouette: a line just inside the edge of the person, so head and shoulders read at a glance
    inside = mask > 0.5
    edge = inside & ~ndimage.binary_erosion(inside, iterations=max(1, cell_w // 3), border_value=1)   # the photo's own edge is no outline
    ink = np.maximum(ink, outline * edge)
    # the body is quieter than the face: below the neck, ink fades to ``body`` of its value, so a bright shirt does not outshine it
    fade = np.clip((np.arange(ink.shape[0]) / ink.shape[0] - neck) / 0.15, 0, 1)[:, None]
    ink = ink * (1 - (1 - body) * fade)
    maps = glyphs(cell_w, cell_h)
    coverage = maps.mean(axis=(1, 2))
    patches = ink.reshape(rows, cell_h, cols, cell_w).transpose(0, 2, 1, 3).reshape(rows * cols, cell_h, cell_w)
    # Darkness first: a cell's ink, scaled to what the densest character can carry, must match the character's coverage.
    # Then shape, among characters of about that darkness: the slightly blurred pattern of the cell (its ink less its mean)
    # against each character's, so a strong edge picks / \ ( ) _ | rather than any character of the right darkness.
    target = patches.mean(axis=(1, 2)) * coverage.max()
    soften = lambda stack: ndimage.gaussian_filter(stack, sigma=(0, 0.8, 0.8))
    shape_p = soften(patches - patches.mean(axis=(1, 2), keepdims=True)).reshape(len(patches), -1) * coverage.max()
    shape_g = soften(maps - coverage[:, None, None]).reshape(len(maps), -1)
    tone_cost = (target[:, None] - coverage[None, :]) ** 2 * shape_p.shape[1]
    shape_cost = (shape_g ** 2).sum(axis=1)[None, :] - 2 * shape_p @ shape_g.T
    best = np.argmin(tone_weight * tone_cost + shape_cost, axis=1)
    return [''.join(CHARS[index] for index in best[row * cols:(row + 1) * cols]) for row in range(rows)]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('photo')
    parser.add_argument('--mode', choices=('dark', 'light'), required=True, help='the card the art is for')
    parser.add_argument('--cols', type=int, default=76)
    parser.add_argument('--rows', type=int, default=52)
    parser.add_argument('--crop', type=int, nargs=4, metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'), help='crop box in pixels, before conversion')
    parser.add_argument('--tolerance', type=int, default=110, help='how far from the backdrop colour still counts as backdrop')
    parser.add_argument('--local', type=float, default=0.45, help='how much local contrast to mix in, 0 to 1')
    args = parser.parse_args()
    print('\n'.join(portrait(args.photo, args.cols, args.rows, args.mode, args.crop, args.tolerance, args.local)))
