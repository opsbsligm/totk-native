"""Compose the authored Deck prompt masks into one review image.

The C test checks the geometry with numbers; this answers the other question, which is what the
prompts look like once the game colours them. It draws the plate the layout supplies under each
mask, downsamples to the size a prompt actually occupies on a 1280x800 Deck screen, and writes one
PNG per context. Standard library only, so any checkout can run it.

usage: python3 tools/deck_prompt_sheet.py --output DIR [--cc cc] [--size 40] [--upscale 4]
"""
import argparse
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 108
CODES = (("b", 0), ("a", 1), ("y", 2), ("x", 3), ("l1", 4), ("l2", 5))
# The layout supplies the colour; these are the four face plates and the neutral shoulder plate.
PLATES = {"a": (214, 58, 58), "b": (60, 120, 232), "y": (58, 178, 96), "x": (228, 168, 44),
          "l1": (92, 92, 98), "l2": (92, 92, 98)}
BACKDROP = (30, 32, 38)
GUTTER = 10


def build_preview(cc, workdir):
    exe = Path(workdir) / "deck-prompt-preview"
    subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "src/gfx"),
                    str(ROOT / "tools" / "deck_prompt_preview.c"), "-lm", "-o", str(exe)], check=True)
    return exe


def read_pgm(path):
    """Raw PGM (P5) reader: three header tokens, then width*height bytes of pixels."""
    data = path.read_bytes()
    if not data.startswith(b"P5"):
        raise SystemExit("not a raw PGM: " + str(path))
    fields, offset = [], 2
    while len(fields) < 3:
        while offset < len(data) and data[offset:offset + 1].isspace():
            offset += 1
        end = offset
        while end < len(data) and not data[end:end + 1].isspace():
            end += 1
        if end == offset:
            raise SystemExit("truncated PGM header: " + str(path))
        fields.append(data[offset:end])
        offset = end
    width, height, maxval = (int(field) for field in fields)
    while offset < len(data) and data[offset:offset + 1].isspace():
        offset += 1          # the single gap between the header and the raster
    pixels = data[offset:]
    if width != height or maxval != 255 or len(pixels) != width * height:
        raise SystemExit("unexpected PGM body: " + str(path))
    return pixels


def load_masks(exe, source):
    with tempfile.TemporaryDirectory() as work:
        subprocess.run([str(exe), work, str(source)], check=True, cwd=ROOT)
        return {(context, code): read_pgm(Path(work) / f"{context}_{name}.pgm")
                for name, code in CODES for context in ("world", "menu")}


def downscale(mask, size, source):
    """Box filter, close enough to the game's own minification to judge legibility."""
    step = source // size
    return bytes(sum(mask[row * source + column] for row in range(y * step, (y + 1) * step)
                     for column in range(x * step, (x + 1) * step)) // (step * step)
                 for y in range(size) for x in range(size))


def compose(context, found, source, cell, upscale):
    """One row of prompts at their real size, scaled up so a person can read them."""
    width = len(CODES) * (cell * upscale + GUTTER) + GUTTER
    height = cell * upscale + 2 * GUTTER
    rgb = bytearray(bytes(BACKDROP) * (width * height))
    for column, (name, code) in enumerate(CODES):
        small = downscale(found[(context, code)], cell, source)
        plate = PLATES[name]
        for y in range(cell):
            for x in range(cell):
                alpha = small[y * cell + x]
                pixel = bytes((plate[c] * alpha + BACKDROP[c] * (255 - alpha)) // 255 for c in range(3))
                block = pixel * upscale          # one source texel, scaled up whole
                for dy in range(upscale):
                    row = GUTTER + y * upscale + dy
                    base = 3 * (row * width + GUTTER + column * (cell * upscale + GUTTER) + x * upscale)
                    rgb[base:base + 3 * upscale] = block
    return width, height, bytes(rgb)


def png(path, width, height, rgb):
    raw = b"".join(b"\x00" + rgb[row * width * 3:(row + 1) * width * 3] for row in range(height))
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--cc", default="cc")
    ap.add_argument("--size", type=int, default=40, help="prompt size in screen pixels")
    ap.add_argument("--upscale", type=int, default=4)
    args = ap.parse_args(argv)
    if not 8 <= args.size <= SOURCE or not 1 <= args.upscale <= 8:
        raise SystemExit("size/upscale out of range")
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as work:
        found = load_masks(build_preview(args.cc, work), SOURCE)
    for context in ("world", "menu"):
        width, height, rgb = compose(context, found, SOURCE, args.size, args.upscale)
        out = args.output / f"deck-prompts-{context}.png"
        png(out, width, height, rgb)
        print(f"{out} {width}x{height}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
