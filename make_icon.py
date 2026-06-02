"""Generate app.ico for Veloxa Video Editor (run once at build time)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ORANGE = (245, 130, 32, 255)
DARK = (12, 14, 18, 255)
SIZES = [16, 24, 32, 48, 64, 128, 256]


def render_at(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), DARK)
    d = ImageDraw.Draw(img)
    font = None
    for fname in ("arialbd.ttf", "arial.ttf", "segoeuib.ttf",
                  "calibrib.ttf", "tahomabd.ttf"):
        try:
            font = ImageFont.truetype(fname, int(size * 0.72))
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()

    text = "V"
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1] + max(2, size // 16)
    d.text((x, y), text, fill=ORANGE, font=font)

    # Umlaut dots above V
    dot = max(2, size // 14)
    dy = max(1, size // 12)
    cx = size // 2
    gap = max(2, size // 7)
    d.rectangle([cx - gap - dot // 2, dy, cx - gap + dot // 2, dy + dot],
                fill=ORANGE)
    d.rectangle([cx + gap - dot // 2, dy, cx + gap + dot // 2, dy + dot],
                fill=ORANGE)
    return img


def main():
    here = Path(__file__).parent
    out = here / "app.ico"
    # Render the highest-resolution image and let Pillow embed all standard sizes.
    base = render_at(256)
    base.save(out, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"Wrote {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
