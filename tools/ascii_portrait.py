"""Turn a portrait photo into the ASCII art on the profile card.

Usage: python tools/ascii_portrait.py photo.jpg [--crop L T R B] [--mode dark|light] [--cols 42] [--rows 25]

The plain backdrop is keyed out by its colour (sampled from the corners) and left blank. The face sets the contrast (histogram
equalisation over the head only), and a sharpening pass keeps glasses, eyes and smile through the downscale. Brightness becomes
characters from dense to sparse: on the dark card the characters are light ink, so bright areas are dense; on the light card dark
areas are. Only characters that need no escaping in SVG text are used. Needs Pillow; the daily stats job does not.
"""
import argparse

from PIL import Image, ImageFilter, ImageOps

RAMP = "@%MNWHBmqpdkbhjxl|i!;:,.'` "          # dense to sparse; no < > & so the art needs no escaping in SVG


def flat(image):
    return image.get_flattened_data() if hasattr(image, 'get_flattened_data') else image.getdata()


def backdrop(image, tolerance):
    """A mask: 255 where a pixel is close to the colour of the top corners (the backdrop)."""
    w, h = image.size
    corners = [image.getpixel((x, y)) for x, y in ((3, 3), (w - 4, 3), (3, h // 4), (w - 4, h // 4))]
    ref = tuple(sum(c[i] for c in corners) // len(corners) for i in range(3))
    mask = Image.new('L', (w, h))
    mask.putdata([255 if abs(r - ref[0]) + abs(g - ref[1]) + abs(b - ref[2]) < tolerance else 0 for r, g, b in flat(image)])
    return mask.filter(ImageFilter.MedianFilter(5))


def portrait(path, cols, rows, crop, tolerance, mode, head, blank):
    image = Image.open(path).convert('RGB')
    if crop:
        image = image.crop(crop)
    mask = backdrop(image, tolerance)
    grey = ImageOps.grayscale(image).filter(ImageFilter.UnsharpMask(radius=3, percent=180, threshold=2))
    w, h = grey.size
    # the contrast comes from the head (the top part of the picture), so the face keeps its detail
    sample = [v for i, (v, m) in enumerate(zip(flat(grey), flat(mask))) if m == 0 and i // w < h * head]
    histogram = [0] * 256
    for v in sample:
        histogram[v] += 1
    total, running, lut = max(1, len(sample)), 0, []
    for count in histogram:
        running += count
        lut.append(int(255 * running / total))
    grey = grey.point(lut)
    small, small_mask = grey.resize((cols, rows), Image.LANCZOS), mask.resize((cols, rows), Image.BILINEAR)
    steps = len(RAMP) - 1                       # the last character (a space) is kept for the backdrop
    lines = []
    for y in range(rows):
        line = ''
        for x in range(cols):
            if small_mask.getpixel((x, y)) > 150:
                line += ' '
                continue
            v = small.getpixel((x, y))
            level = v if mode == 'dark' else 255 - v          # how much ink the cell should carry
            if level < blank:                                 # near-paper areas get one faint, even texture instead of noise,
                edge = any(0 <= x + dx < cols and 0 <= y + dy < rows and small_mask.getpixel((x + dx, y + dy)) > 150
                           for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)))
                line += ':' if edge else '.'                  # and the silhouette a slightly stronger outline
                continue
            line += RAMP[min(steps - 1, (255 - level) * steps // 256)]
        lines.append(line.rstrip())
    return lines


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('photo')
    parser.add_argument('--cols', type=int, default=42)
    parser.add_argument('--rows', type=int, default=25)
    parser.add_argument('--crop', type=int, nargs=4, metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'), help='crop box in pixels, before conversion')
    parser.add_argument('--tolerance', type=int, default=110, help='how far from the backdrop colour still counts as backdrop')
    parser.add_argument('--mode', choices=('dark', 'light'), default='dark', help='the card the art is for')
    parser.add_argument('--head', type=float, default=0.5, help='share of the picture, from the top, that sets the contrast')
    parser.add_argument('--blank', type=int, default=0, help='cells with less ink than this (0-255) get a faint even texture')
    args = parser.parse_args()
    print('\n'.join(portrait(args.photo, args.cols, args.rows, args.crop, args.tolerance, args.mode, args.head, args.blank)))
