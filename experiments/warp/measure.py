# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10"]
# ///
"""Score a rasterized contact sheet: per-shape ink coverage and spill.

    uv run experiments/warp/measure.py sheet.png

Ink = dark pixels (luminance < 128); the polygon outline is light gray so
it never counts. Coverage = inked polygon pixels / polygon pixels.
Spill = ink outside the polygon / all ink in the cell.
"""

import json
import statistics
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

HERE = Path(__file__).parent


def count(img: Image.Image) -> int:
    """Number of white (255) pixels in a binary L-mode image."""
    return img.histogram()[255]


def main():
    png = Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "sheet.png")
    meta = json.loads((HERE / "sheet_layout.json").read_text())
    img = Image.open(png).convert("L")
    kx = img.width / (meta["cols"] * meta["cell"])  # screenshot scale factor
    cell = meta["cell"]

    print(f"algorithm: {meta['algorithm']}")
    extra = any("min_cap" in c for c in meta["cells"])
    print(f"{'neighborhood':<22} {'coverage':>9} {'spill':>7}"
          + (f" {'cap px':>7}  label" if extra else ""))
    caps = []
    coverages, spills = [], []
    for i, c in enumerate(meta["cells"]):
        cx, cy = (i % meta["cols"]) * cell, (i // meta["cols"]) * cell
        box = (int(cx * kx), int(cy * kx), int((cx + cell) * kx), int((cy + cell) * kx))
        tile = img.crop(box)
        ink = tile.point(lambda v: 255 if v < 128 else 0)

        mask = Image.new("L", tile.size, 0)
        draw = ImageDraw.Draw(mask)
        rings = c["exterior"]
        if rings and isinstance(rings[0][0], (int, float)):
            rings = [rings]
        for ring in rings:
            draw.polygon([((x - cx) * kx, (y - cy) * kx) for x, y in ring], fill=255)

        ink_total = count(ink)
        ink_inside = count(ImageChops.multiply(ink, mask).point(lambda v: 255 if v else 0))
        poly_px = count(mask)
        coverage = ink_inside / poly_px if poly_px else 0.0
        spill = (ink_total - ink_inside) / ink_total if ink_total else 0.0
        coverages.append(coverage)
        spills.append(spill)
        line = f"{c['name']:<22} {coverage:>8.1%} {spill:>6.1%}"
        if extra:
            caps.append(c.get("min_cap", 0))
            line += f" {c.get('min_cap', 0):>7.1f}  {c.get('label', '—')}"
        print(line)

    print("-" * 40)
    print(f"{'median':<22} {statistics.median(coverages):>8.1%} "
          f"{statistics.median(spills):>6.1%}"
          + (f" {statistics.median(caps):>7.1f}" if extra else ""))
    print(f"{'worst':<22} {min(coverages):>8.1%} {max(spills):>6.1%}"
          + (f" {min(caps):>7.1f}" if extra else ""))


if __name__ == "__main__":
    main()
