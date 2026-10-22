"""Generates the app and tray icons: a blue tile with a white ">" prompt and a black "sm" tab.

The drawing reproduces docs/manual/assets/icona.png at any size. Coordinates are in that
image's units: the blue tile spans 151 px, from (12, 10) to (162, 160).
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)

BLUE = (45, 107, 214, 255)
BLACK = (22, 24, 28, 255)
WHITE = (255, 255, 255, 255)
TILE_X, TILE_Y, TILE = 12, 10, 151
FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def icon(size: int) -> Image.Image:
    scale = 4
    s = size * scale
    pad = s * 0.04
    unit = (s - 2 * pad) / TILE

    def p(x: float, y: float) -> tuple[float, float]:
        return pad + (x - TILE_X) * unit, pad + (y - TILE_Y) * unit

    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((pad, pad, s - pad, s - pad), radius=34 * unit, fill=BLUE)

    # ">" prompt: two strokes with round caps and a round joint
    stroke = 16.5 * unit
    chevron = [p(43.5, 51), p(82, 85), p(43.5, 119)]
    d.line(chevron, fill=WHITE, width=round(stroke), joint="curve")
    for cx, cy in (chevron[0], chevron[2]):
        r = stroke / 2
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=WHITE)

    # black tab with "sm" read bottom to top
    d.rounded_rectangle((*p(102, 44), *p(141, 127)), radius=1.5 * unit, fill=BLACK)
    text = Image.new("L", (s, s), 0)
    ImageDraw.Draw(text).text((s // 4, s // 4), "sm", font=font(s // 4), fill=255)
    text = text.crop(text.getbbox()).rotate(90, expand=True)
    left, top = p(113, 80)
    box_w, box_h = 17 * unit, 38 * unit
    k = min(box_w / text.width, box_h / text.height)
    text = text.resize((max(1, round(text.width * k)), max(1, round(text.height * k))), Image.LANCZOS)
    x = left + (box_w - text.width) / 2
    y = top + (box_h - text.height)
    img.paste(Image.new("RGBA", text.size, WHITE), (round(x), round(y)), text)

    return img.resize((size, size), Image.LANCZOS)


icon(256).save(out / "icon.png")
icon(32).save(out / "tray.png")
icon(256).save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icons written to", out)
