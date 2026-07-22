# /// script
# requires-python = ">=3.11"
# dependencies = ["shapely>=2.0"]
# ///
"""Render the engine-proving fixture scene → out/fixture.svg.

No network, no projection: fixture coordinates are already SVG user units.
Proves all four typographic devices: line-pack fill, contour fill,
street-on-a-path, and the arched hero label.
"""

import json
from pathlib import Path

from shapely.geometry import shape

from config.style import HERO_COLORS, HERO_CYCLE, LAYERS, PAPER
from typemap.fills import arched_label, contour_fill, linepack_fill, street_label
from typemap.svgdoc import SvgDoc

W, H = 1000, 700
ROOT = Path(__file__).parent


def hero_color(name: str, i: int) -> str:
    return HERO_COLORS.get(name, HERO_CYCLE[i % len(HERO_CYCLE)])


def main():
    features = json.loads((ROOT / "data/fixtures/fixture.geojson").read_text())["features"]
    by_kind = {}
    for f in features:
        by_kind.setdefault(f["properties"]["kind"], []).append(f)

    doc = SvgDoc(W, H, background=PAPER)

    # Layer order: neighborhood interiors → parks → water → streets → heroes
    for f in by_kind.get("neighborhood", []):
        linepack_fill(doc, shape(f["geometry"]), f["properties"]["fill_words"],
                      LAYERS["neighborhood_fill"])
    for f in by_kind.get("park", []):
        linepack_fill(doc, shape(f["geometry"]), f["properties"]["fill_words"],
                      LAYERS["park_fill"])
    for f in by_kind.get("water", []):
        contour_fill(doc, shape(f["geometry"]), f["properties"]["name"].upper(),
                     LAYERS["water_fill"])
    for f in by_kind.get("street", []):
        style = LAYERS[f"street_{f['properties'].get('class', 'minor')}"]
        street_label(doc, shape(f["geometry"]), f["properties"]["name"], style)
    for i, f in enumerate(by_kind.get("neighborhood", [])):
        geom = shape(f["geometry"])
        name = f["properties"]["name"]
        c = geom.centroid
        style = {**LAYERS["hero"], "fill": hero_color(name, i)}
        arched_label(doc, (c.x, c.y + 20), name.upper(), style,
                     width=geom.bounds[2] - geom.bounds[0] - 60, bulge=0.22)

    out = ROOT / "out/fixture.svg"
    out.parent.mkdir(exist_ok=True)
    doc.write(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
