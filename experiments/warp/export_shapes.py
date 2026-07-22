# /// script
# requires-python = ">=3.11"
# dependencies = ["shapely>=2.0"]
# ///
"""Export the 19 real neighborhood polygons (page coords) → shapes.json.

Uses the same page transform as render_map.py so experiment results
transfer 1:1 to the real map.
"""

import json
import sys
from pathlib import Path

from shapely.geometry import shape, mapping
from shapely.ops import transform, unary_union

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

PAGE_W, MARGIN, FRINGE = 3400, 40, 2200  # keep in sync with render_map.py


def main():
    hoods = [
        (f["properties"]["name"], shape(f["geometry"]))
        for f in json.loads((ROOT / "data/neighborhoods.geojson").read_text())["features"]
    ]
    city = unary_union([g for _, g in hoods])
    minx, miny, maxx, maxy = city.buffer(FRINGE).bounds
    scale = (PAGE_W - 2 * MARGIN) / (maxx - minx)
    page_h = int((maxy - miny) * scale + 2 * MARGIN)

    def to_page(g):
        return transform(lambda x, y: ((x - minx) * scale + MARGIN,
                                       page_h - ((y - miny) * scale + MARGIN)), g)

    out = {
        "features": [
            {"name": name, "polygon": mapping(to_page(g).simplify(1.5))}
            for name, g in sorted(hoods)
        ]
    }
    path = Path(__file__).parent / "shapes.json"
    path.write_text(json.dumps(out))
    print(f"wrote {path} ({len(out['features'])} shapes)")


if __name__ == "__main__":
    main()
