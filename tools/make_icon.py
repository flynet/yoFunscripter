"""Generate assets/icon.ico: the icon of the window, the installer and the .exe.

    python tools/make_icon.py

A dark rounded square with a purple wave (the funscript curve) and a play triangle,
the colors of the Neon theme of the app. Pillow writes the multi-size .ico in one file:
256/128/64/48/32/16 px, so the title bar, the task bar and the installer all get a
crisp copy.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parents[1] / "assets"
SIZE = 256
BG = (14, 14, 26, 255)          # neon background #0e0e1a
PANEL = (26, 26, 46, 255)       # neon panel #1a1a2e
ACCENT = (139, 92, 246, 255)    # neon accent #8b5cf6
LIGHT = (224, 224, 240, 255)


def draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = size // 16
    radius = size // 8
    d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=radius, fill=BG)
    d.rounded_rectangle([pad * 2, pad * 2, size - pad * 2, size - pad * 2],
                        radius=radius, fill=PANEL)

    # the wave: one period across the panel, drawn as a thick polyline
    top, bottom = size // 3, size * 2 // 3
    mid = (top + bottom) // 2
    points = []
    steps = 60
    for i in range(steps + 1):
        x = pad * 3 + (size - pad * 6) * i / steps
        y = mid + int((bottom - top) // 2 * math.sin(i / steps * 2 * math.pi - math.pi / 2))
        points.append((x, y))
    width = max(2, size // 16)
    for a, b in zip(points, points[1:]):
        d.line([a, b], fill=ACCENT, width=width)

    # play triangle at the right, the cut marker at the left
    d.polygon([(size - pad * 4, mid - size // 10), (size - pad * 4, mid + size // 10),
               (size - pad * 7, mid)], fill=LIGHT)
    d.line([(pad * 3, top - pad), (pad * 3, bottom + pad)], fill=LIGHT, width=width)
    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    base = draw(SIZE)
    target = ASSETS / "icon.ico"
    base.save(target, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(f"{target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
