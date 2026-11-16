# SPDX-License-Identifier: MIT
"""Generate the original vector Deck controller art and its checked runtime RLE.

Development-only dependencies: CairoSVG and Pillow (pinned in
.gitlab/art/pipcompile.lock.txt). Runtime uses neither; the committed header is
the shipped artifact.

Two hard contracts keep the art compatible with the game's own help screen:
  * The callout anchors are authoritative texture pixels, derived here from the
    same source coordinates the bflyt solver uses (see deck_font_world.py,
    pt(x, y) = (.96x + 13, .75y + 72)). Every drawn control is centered on its
    anchor, so a redraw never moves a callout.
  * The RLE stream stores greyscale plus alpha, so the drawing must stay grey.
Physical Deck letters name positions; this drawing never remaps gameplay inputs.
"""
import io
from pathlib import Path
import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
W, H = 580, 340
# Anchor coordinates the bflyt patch targets. Source space; MATRIX maps to texture.
MATRIX = (0.96, 0.75, 13.0, 72.0)
# Source-space control centers from the bflyt layout; MATRIX projects them to texture pixels.
SRC = {'dpad': (38, 79), 'left_stick': (88, 88), 'right_stick': (470, 88),
       'view': (126, 53), 'menu': (451, 53),
       'south': (517, 106), 'east': (535, 89), 'west': (499, 89), 'north': (517, 71),
       'left_bumper': (58, 30), 'right_bumper': (522, 30)}
TRIGGERS = {'left': (58, 50), 'right': (522, 50)}  # rear triggers: raw texture pixels


def anchor(source):
    sx, sy = SRC[source]
    return (MATRIX[0] * sx + MATRIX[2], MATRIX[1] * sy + MATRIX[3])


def grey(v):
    return f'#{v:02x}{v:02x}{v:02x}'


def paint(v):
    return v if isinstance(v, str) else grey(v)


def shape(x, y, w, h, r, fill, stroke=None, width=1.2, opacity=None):
    o = '' if opacity is None else f' opacity="{opacity}"'
    s = '' if stroke is None else (f' stroke="{grey(stroke)}" stroke-width="{width}"')
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}"'
            f' fill="{paint(fill)}"{s}{o}/>')


def place(cx, cy, w, h, r, fill, stroke=None, width=1.2, opacity=None):
    return shape(cx - w / 2, cy - h / 2, w, h, r, fill, stroke, width, opacity)


def text(cx, cy, string, cap, v, weight='normal', spacing=0):
    ls = '' if not spacing else f' letter-spacing="{spacing}"'
    return (f'<text x="{cx}" y="{cy + cap * 0.36}" text-anchor="middle"{ls}'
            f' font-family="sans-serif" font-size="{cap}" font-weight="{weight}"'
            f' fill="{grey(v)}">{string}</text>')


def label(cx, cy, string, cap, v=242):
    """Center a label on an anchor; the baseline offset keeps the cap height on target."""
    return text(cx, cy, string, cap, v, 'bold')


def shoulder(side, fill, stroke, lit):
    """Trigger hump plus the bumper on the top edge, each centered on its anchor."""
    trig = TRIGGERS[side]
    name = 'L' if side == 'left' else 'R'
    bumper = anchor(f'{side}_bumper')
    return [
        place(trig[0], trig[1], 66, 26, 12, fill, stroke, 1.3),        # rear trigger
        label(trig[0], trig[1], name + '2', 12),
        place(bumper[0], bumper[1], 68, 21, 9, fill, stroke, 1.3),     # bumper on the edge
        label(bumper[0], bumper[1], name + '1', 12),
        place(bumper[0], bumper[1] - 8, 60, 3, 1.5, lit),
    ]


def stick(cx, cy, tag):
    return [f'<g><circle cx="{cx}" cy="{cy}" r="16" fill="{grey(20)}" stroke="{grey(158)}" stroke-width="1.3"/>'
            f'<circle cx="{cx}" cy="{cy}" r="11.5" fill="{grey(44)}" stroke="{grey(120)}" stroke-width="1"/>'
            f'<circle cx="{cx}" cy="{cy}" r="7.5" fill="{grey(26)}" stroke="{grey(96)}" stroke-width=".8"/></g>',
            label(cx, cy, tag, 8, 214)]


def dpad(cx, cy):
    arm, thick = 38, 15
    parts = [place(cx, cy, arm, thick, 4, 22, 168, 1.1),
             place(cx, cy, thick, arm, 4, 22, 168, 1.1)]
    arrow = grey(206)
    for dx, dy, points in ((0, -13, f'{cx},{cy-17} {cx-4},{cy-11} {cx+4},{cy-11}'),
                           (0, 13, f'{cx},{cy+17} {cx-4},{cy+11} {cx+4},{cy+11}'),
                           (-13, 0, f'{cx-17},{cy} {cx-11},{cy-4} {cx-11},{cy+4}'),
                           (13, 0, f'{cx+17},{cy} {cx+11},{cy-4} {cx+11},{cy+4}')):
        parts.append(f'<polygon points="{points}" fill="{arrow}" opacity=".9"/>')
    return parts


def face_buttons():
    parts = []
    for key, letter in (('south', 'A'), ('east', 'B'), ('west', 'X'), ('north', 'Y')):
        cx, cy = anchor(key)
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="12" fill="{grey(22)}" stroke="{grey(196)}" stroke-width="1.3"/>')
        parts.append(label(cx, cy, letter, 13))
    return parts


def small_button(key, bars):
    """Mark the two small buttons the way the accepted BOTW diagram does: a dash, or Deck's menu bars."""
    cx, cy = anchor(key)
    parts = [place(cx, cy, 27, 18, 5, 22, 170, 1.1)]
    if bars:
        parts += [shape(cx - 8, cy - 5 + i * 4.2, 16, 2, 1, 216) for i in range(3)]
    else:
        parts.append(shape(cx - 6, cy - 1, 12, 2.4, 1.2, 216))
    return parts


def body():
    top, bottom, left, right = 62, 326, 8, 572
    path = (f'M{left+34} {top}H{right-34}Q{right} {top} {right} {top+38}V{bottom-62}'
            f'Q{right} {bottom} {right-62} {bottom}H{left+62}Q{left} {bottom} {left} {bottom-62}'
            f'V{top+38}Q{left} {top} {left+34} {top}Z')
    parts = [f'<path d="{path}" fill="#000000" fill-opacity=".38" transform="translate(0 6)"/>',
             f'<path d="{path}" fill="{grey(58)}"/>',
             # Flat depth bands: the RLE stream cannot carry a gradient without paying one
             # run per pixel, so shading is a few wide flat steps instead.
             f'<path d="{path}" fill="{grey(70)}" clip-path="url(#upper)"/>',
             f'<path d="{path}" fill="{grey(46)}" clip-path="url(#lower)"/>',
             f'<path d="{path}" fill="none" stroke="{grey(178)}" stroke-width="1.6"/>',
             place((left + right) / 2, top + 8, right - left - 26, 7, 3, 255, opacity=.14),
             place(left + 30, bottom - 86, 22, 120, 11, 255, opacity=.07),
             place(right - 30, bottom - 86, 22, 120, 11, 255, opacity=.07)]
    bezel = shape(152, 84, 276, 188, 10, 18, 140, 1.5)
    parts += [bezel, shape(162, 94, 256, 168, 4, 12),
              f'<polygon points="162,94 300,94 162,214" fill="{grey(255)}" opacity=".06"/>',
              shape(162, 94, 256, 168, 4, 'none')]
    for side, cx in (('left', 96), ('right', 466)):
        parts += [place(cx, 214, 56, 56, 12, 30, 150, 1.2),
                  place(cx, 214, 46, 46, 9, 24, opacity=.7),
                  shape(cx - 21, 195, 42, 3, 1.5, 255, opacity=.18)]
        parts += [shape(cx - 26, 282 + i * 8, 52, 2.6, 1.3, 138, opacity=.85) for i in range(3)]
    parts += [place(128, 300, 46, 17, 8, 22, 165, 1.1), text(128, 300, 'STEAM', 9, 220, 'bold', .8),
              place(452, 300, 46, 17, 8, 22, 165, 1.1),
              ''.join(f'<circle cx="{443 + i * 9}" cy="300" r="2.1" fill="{grey(224)}"/>' for i in range(3)),
              text(290, 300, 'STEAM DECK', 11, 128, 'normal', 3)]
    return parts


def drawing(rear_triggers):
    """One complete Deck view, drawn straight in texture pixels.

    Controls are placed on anchor(), so every callout marker the game patches in
    lands on the control it names. The rear trigger pills only appear on the view
    that shows the back edge.
    """
    rear = ''.join(shoulder('left', 34, 178, 210)[:2] + shoulder('right', 34, 178, 210)[:2]) \
        if rear_triggers else ''
    edge = ''.join(shoulder('left', 34, 178, 210)[2:] + shoulder('right', 34, 178, 210)[2:])
    controls = ''.join(dpad(*anchor('dpad'))
                       + stick(*anchor('left_stick'), 'L3')
                       + stick(*anchor('right_stick'), 'R3')
                       + face_buttons()
                       + small_button('view', False)
                       + small_button('menu', True))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % (W, H, W, H)
            + '<defs><clipPath id="upper"><rect x="0" y="0" width="%d" height="130"/></clipPath>'
              '<clipPath id="lower"><rect x="0" y="250" width="%d" height="%d"/></clipPath></defs>' % (W, W, H - 250)
            + rear + ''.join(body()) + controls + edge + '</svg>')


def rle(svg):
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=W * 2, output_height=H * 2)
    image = Image.open(io.BytesIO(png)).convert('RGBA').resize((W, H), Image.Resampling.LANCZOS)
    raw = image.tobytes()
    runs = []
    for i in range(0, len(raw), 4):
        r, g, b, a = raw[i:i + 4]
        if r != g or g != b:
            raise ValueError(f'Art must be greyscale (found {(r, g, b)} at pixel {i // 4})')
        if a == 0:
            g = 0
        if runs and runs[-1][1:] == [g, a] and runs[-1][0] < 65535:
            runs[-1][0] += 1
        else:
            runs.append([1, g, a])
    return image, runs


def assert_anchors_covered(image, rear_triggers):
    """Every callout anchor must land on a drawn control, not on bare body or background.

    The bflyt patch places the game's callout markers on these exact pixels, so a
    redraw that slides a control off its anchor silently breaks the help screen.
    The rear triggers are only part of the view that shows the back edge.
    """
    pixels = image.load()
    body_greys = {pixels[x, y][0] for x, y in ((300, 70), (30, 250), (550, 250))}
    names = list(SRC) + (list(TRIGGERS) if rear_triggers else [])
    points = [anchor(key) for key in SRC] + (list(TRIGGERS.values()) if rear_triggers else [])
    for name, (cx, cy) in zip(names, points):
        x, y = int(round(cx)), int(round(cy))
        grey_value, alpha = pixels[x, y][0], pixels[x, y][3]
        if alpha < 250:
            raise ValueError(f'anchor {name} at {x},{y} is transparent')
        if grey_value in body_greys:
            raise ValueError(f'anchor {name} at {x},{y} sits on the bare body')


def main():
    assets = ROOT / 'assets/controller'
    assets.mkdir(parents=True, exist_ok=True)
    header = ROOT / 'src/gfx/totk_deck_bitmaps.h'
    old = header.read_text()
    tail = old[old.index('static inline int nd_deck_source_view'):]
    out = ['/* Original vector Deck artwork generated by tools/draw_deck_art.py. */',
           '/* Callout anchors keep their established texture pixels; nothing is re-mapped. */',
           '#ifndef ND_TOTK_DECK_BITMAPS_H', '#define ND_TOTK_DECK_BITMAPS_H',
           '#include <stdint.h>', '#include <stddef.h>', '#include <string.h>',
           f'enum {{ ND_DECK_W={W}, ND_DECK_H={H}, ND_DECK_BYTES={W * H * 4} }};',
           'typedef struct { uint16_t n; uint8_t grey, alpha; } nd_deck_run;']
    for view, rear, art in (('front', False, drawing(False)), ('inclined', True, drawing(True))):
        (assets / (view + '.svg')).write_text(art + '\n')
        image, runs = rle(art)
        assert_anchors_covered(image, rear)
        out.append(f'static const nd_deck_run nd_deck_{view}[] = {{')
        out.extend(''.join('{%d,%d,%d},' % tuple(run) for run in runs[i:i + 12])
                   for i in range(0, len(runs), 12))
        out.append('};')
        image.save(assets / (view + '.png'))
        print(f'{view}: {len(runs)} runs')
    out.append(tail)
    header.write_text('\n'.join(out))
    print('Authored SVG, preview PNG and runtime header regenerated')


if __name__ == '__main__':
    main()
