# /// script
# requires-python = ">=3.11"
# dependencies = ["shapely>=2.0", "fonttools>=4.50", "numpy"]
# ///
"""Choose the legibility floor by taste: every shape under several floors.

    uv run experiments/warp/floor_sweep.py        # → compare/floors.svg

One row per neighborhood, one column per setting of hero_layout's
objective: the most ink among layouts whose smallest letter is ≥ floor ×
the best achievable smallest letter — floors 0.40 / 0.55 / 0.70 / 0.85 —
plus the legacy legibility-led score. Each cell shows its ink coverage
and its smallest letter; read down a column to judge a floor.
"""

import json
import sys
from pathlib import Path

from shapely.affinity import scale as ascale, translate
from shapely.geometry import shape
from shapely.ops import unary_union

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import render_sheet as RS  # noqa: E402
from typemap import hero_layout as hl  # noqa: E402
from typemap.fills import polygon_ds  # noqa: E402
from typemap.svgdoc import SvgDoc  # noqa: E402

CELL, PAD, HEAD, GUTTER = 340, 18, 64, 230
SETTINGS = [("floor 0.40", "ink", 0.40), ("floor 0.55", "ink", 0.55),
            ("floor 0.70", "ink", 0.70), ("floor 0.85", "ink", 0.85),
            ("legacy score", "legacy", None)]


def main():
    feats = json.loads((HERE / "shapes.json").read_text())["features"]
    M = hl.Metrics.load(RS.FONT_PATH)
    saved = hl.OBJECTIVE, hl.LEGIBILITY_FLOOR
    W = GUTTER + len(SETTINGS) * CELL
    doc = SvgDoc(W, HEAD + len(feats) * (CELL + HEAD), background="#ffffff")
    for col, (title, obj, floor) in enumerate(SETTINGS):
        doc.raw(f'<text x="{GUTTER + col * CELL + CELL / 2}" y="44" font-size="30" '
                f'font-weight="bold" font-family="monospace" text-anchor="middle" '
                f'fill="#222">{title}</text>')
    for row, f in enumerate(feats):
        y0 = HEAD + row * (CELL + HEAD)
        doc.raw(f'<text x="{GUTTER - 20}" y="{y0 + CELL / 2 + HEAD / 2}" font-size="24" '
                f'font-weight="bold" font-family="monospace" text-anchor="end" '
                f'fill="#222">{f["name"]}</text>')
        for col, (title, obj, floor) in enumerate(SETTINGS):
            hl.OBJECTIVE = obj
            if floor is not None:
                hl.LEGIBILITY_FLOOR = floor
            poly = shape(f["polygon"])
            minx, miny, maxx, maxy = poly.bounds
            k = min((CELL - 2 * PAD) / (maxx - minx), (CELL - 2 * PAD) / (maxy - miny))
            x0 = GUTTER + col * CELL
            poly = translate(ascale(poly, k, k, origin=(minx, miny)),
                             x0 + PAD - minx, y0 + HEAD + PAD - miny)
            doc.raw(f'<path d="{" ".join(polygon_ds(poly))}" fill="none" '
                    f'stroke="#888" stroke-width="3"/>')
            res = hl.search(poly, f["name"], M)
            if res is None:
                continue
            hl.render(doc, res, M, "#333")
            ink = unary_union([hl.outline(r, M) for r in res["rows"]])
            cov = ink.intersection(poly).area / poly.area
            small = min(min(hl._sizes(r)) for r in res["rows"]) * M.cap
            doc.raw(f'<text x="{x0 + 10}" y="{y0 + 34}" font-size="28" font-weight="bold" '
                    f'font-family="monospace" fill="#222">{cov:.1%}</text>')
            doc.raw(f'<text x="{x0 + 130}" y="{y0 + 34}" font-size="15" '
                    f'font-family="monospace" fill="#777">min cap {small:.0f}px</text>')
            doc.raw(f'<text x="{x0 + 10}" y="{y0 + 56}" font-size="14" '
                    f'font-family="monospace" fill="#999">{" / ".join(res["lines"])}</text>')
        print(f"{f['name']} done", flush=True)
    hl.OBJECTIVE, hl.LEGIBILITY_FLOOR = saved
    out = HERE / "compare/floors.svg"
    doc.write(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
