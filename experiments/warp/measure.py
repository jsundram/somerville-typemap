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
    print(f"{'neighborhood':<22} {'coverage':>9} {'spill':>7}")
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
        print(f"{c['name']:<22} {coverage:>8.1%} {spill:>6.1%}")

    print("-" * 40)
    print(f"{'median':<22} {statistics.median(coverages):>8.1%} "
          f"{statistics.median(spills):>6.1%}")
    print(f"{'worst':<22} {min(coverages):>8.1%} {max(spills):>6.1%}")


if __name__ == "__main__":
    main()
