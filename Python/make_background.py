"""Generate the dashboard page background: a soft mint-grey gradient with faint contour lines on the
right edge and a faint dot grid. Kept very low contrast so it frames the report without competing
with the charts. Output: dashboard/assets/page_background.png (1280x720, drawn at 2x for sharpness)."""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dashboard" / "assets" / "page_background.png"
S = 2                                   # supersampling
W, H = 1280 * S, 720 * S
TOP, BOTTOM = (240, 246, 245), (222, 235, 232)   # mint-grey gradient (matches the theme's #EEF4F3)


def main():
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        t = y / (H - 1)
        row = tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM))
        for x in range(W):
            px[x, y] = row

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    # faint dot grid across the content area
    for y in range(110 * S, H, 28 * S):
        for x in range(190 * S, W, 28 * S):
            d.ellipse([x - S, y - S, x + S, y + S], fill=(15, 118, 110, 45))
    # soft contour lines sweeping in from the bottom-right corner
    cx, cy = W + 120 * S, H + 160 * S
    for k in range(9):
        r = (260 + k * 70) * S
        d.arc([cx - r, cy - r, cx + r, cy + r], 180, 270, fill=(15, 118, 110, 60 - k * 4), width=2 * S)
    # and a mirrored set, fainter, top-right under the header
    cx, cy = W + 60 * S, -220 * S
    for k in range(6):
        r = (300 + k * 80) * S
        d.arc([cx - r, cy - r, cx + r, cy + r], 90, 180, fill=(15, 118, 110, 32), width=2 * S)

    img = Image.alpha_composite(img.convert("RGBA"), overlay.filter(ImageFilter.GaussianBlur(0.6 * S)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").resize((1280, 720), Image.LANCZOS).save(OUT, optimize=True)
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
