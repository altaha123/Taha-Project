#!/usr/bin/env python3
"""build-brand.py — recolours the Altaha mark into the Navy and Cognac palette.

The mark was drawn in black, white and two greys. This maps those four tones
onto the theme and writes every size the site serves:

    altaha-logo.png        navy A, cognac arrow      (light theme)
    altaha-logo-dark.png   cognac A, ivory arrow     (dark theme)
    icon-512.png, apple-touch-icon.png, favicon.ico  ivory A on navy

Run from the repository root with the three greyscale originals:

    python3 frontend/tools/build-brand.py logo.png logo-dark.png icon-512.png

The colours are the ones in frontend/tokens.css. They are repeated here, and
nowhere else, because an image cannot read a CSS variable.
"""
import sys, os
from PIL import Image, ImageFilter

NAVY, IVORY = (0x14, 0x21, 0x3D), (0xF7, 0xF3, 0xEC)
COGNAC, COGNAC_LT = (0xA8, 0x64, 0x2C), (0xC9, 0x93, 0x5C)
D_COGNAC, D_IVORY, D_IVORY_DIM = (0xC4, 0x7A, 0x3A), (0xF2, 0xEA, 0xDF), (0xC9, 0xBF, 0xB0)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def ramp(level, stops):
    """stops: [(grey level, colour)], ascending. Linear between neighbours."""
    if level <= stops[0][0]:
        return stops[0][1]
    for (l0, c0), (l1, c1) in zip(stops, stops[1:]):
        if level <= l1:
            return mix(c0, c1, (level - l0) / float(l1 - l0))
    return stops[-1][1]


def recolour(src, stops):
    im = Image.open(src).convert('RGBA')
    out = Image.new('RGBA', im.size)
    px, po = im.load(), out.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            po[x, y] = ramp((r + g + b) / 3.0, stops) + (a,)
    return out


def icon(src):
    """Dark A and grey arrow on white -> ivory A and cognac arrow on navy.

    A pixel on the edge of the A is grey too, by anti-aliasing. It is told
    from the arrow by its neighbourhood: an edge has both black and white
    within two pixels, the arrow does not."""
    im = Image.open(src).convert('RGBA')
    grey = im.convert('L')
    lo, hi = grey.filter(ImageFilter.MinFilter(5)).load(), grey.filter(ImageFilter.MaxFilter(5)).load()
    g, px = grey.load(), im.load()
    out = Image.new('RGBA', im.size)
    po = out.load()
    for y in range(im.height):
        for x in range(im.width):
            level, a = g[x, y], px[x, y][3]
            edge = lo[x, y] < 40 and hi[x, y] > 225
            if edge or level < 50 or level > 215:
                c = mix(IVORY, NAVY, level / 255.0)
            else:
                c = ramp(level, [(60, IVORY), (100, D_COGNAC), (150, (0xE3, 0xA8, 0x69)), (215, NAVY)])
                if lo[x, y] > 40 and level > 170:
                    c = mix((0xE3, 0xA8, 0x69), NAVY, (level - 170) / 60.0)
            po[x, y] = c + (a,)
    return out


def main(logo, logo_dark, icon512):
    recolour(logo, [(20, NAVY), (95, COGNAC), (150, COGNAC_LT), (255, COGNAC_LT)]).save(os.path.join(OUT, 'altaha-logo.png'), optimize=True)
    recolour(logo_dark, [(0, D_IVORY_DIM), (130, D_IVORY_DIM), (180, D_IVORY), (235, D_COGNAC)]).save(os.path.join(OUT, 'altaha-logo-dark.png'), optimize=True)
    big = icon(icon512)
    big.save(os.path.join(OUT, 'icon-512.png'), optimize=True)
    big.resize((180, 180), Image.LANCZOS).save(os.path.join(OUT, 'apple-touch-icon.png'), optimize=True)
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, 'favicon.ico'), sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == '__main__':
    main(*sys.argv[1:4])
