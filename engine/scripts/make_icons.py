"""Generates the app and tray icons (a vault door with a vector dot grid)."""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)


def icon(size: int) -> Image.Image:
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = s * 0.06
    d.rounded_rectangle((pad, pad, s - pad, s - pad), radius=s * 0.22, fill=(15, 108, 189, 255))
    c, r = s / 2, s * 0.27
    d.ellipse((c - r, c - r, c + r, c + r), outline=(255, 255, 255, 255), width=int(s * 0.06))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            dot = s * 0.035
            x, y = c + dx * s * 0.1, c + dy * s * 0.1
            d.ellipse((x - dot, y - dot, x + dot, y + dot), fill=(255, 255, 255, 255))
    return img.resize((size, size), Image.LANCZOS)


icon(256).save(out / "icon.png")
icon(32).save(out / "tray.png")
icon(256).save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icons written to", out)
