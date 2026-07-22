# /// script
# requires-python = ">=3.11"
# dependencies = ["shapely>=2.0", "pyproj>=3.6"]
# ///
"""Assemble the full Somerville typographic map → out/somerville.svg.

Reads the cached Overpass response and the official city neighborhood
polygons, projects everything to MA State Plane (EPSG:2249), scales to
page coordinates, and renders every feature as typography.
"""

import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point, shape
from shapely.ops import linemerge, transform, unary_union

from config.style import HERO_CYCLE, LAYERS, PAPER
from config.words import LINE_COLORS, STATION_LINES, WORD_OVERRIDES
from typemap.fills import arched_label, contour_fill, linepack_fill, street_label
from typemap.osm import load_layers
from typemap.svgdoc import SvgDoc, est_width

ROOT = Path(__file__).parent
PAGE_W = 3400
MARGIN = 60

to_stateplane = Transformer.from_crs("EPSG:4326", "EPSG:2249", always_xy=True).transform


def main():
    hoods = [
        (f["properties"]["name"], shape(f["geometry"]))
        for f in json.loads((ROOT / "data/neighborhoods.geojson").read_text())["features"]
    ]
    city = unary_union([g for _, g in hoods])

    # Page transform: EPSG:2249 ft → page px, y flipped for SVG
    minx, miny, maxx, maxy = city.buffer(400).bounds
    scale = (PAGE_W - 2 * MARGIN) / (maxx - minx)
    page_h = int((maxy - miny) * scale + 2 * MARGIN)

    def to_page(geom_2249):
        return transform(
            lambda x, y: ((x - minx) * scale + MARGIN,
                          page_h - ((y - miny) * scale + MARGIN)),
            geom_2249)

    def ll_to_page(geom_ll):
        return to_page(transform(to_stateplane, geom_ll))

    layers = load_layers(json.loads((ROOT / "data/cache/overpass.json").read_text()))
    city_pg = to_page(city)
    hoods_pg = sorted((name, to_page(g)) for name, g in hoods)
    street_clip = city_pg.buffer(6)

    doc = SvgDoc(PAGE_W, page_h, background=PAPER)
    hood_color = {name: HERO_CYCLE[i % len(HERO_CYCLE)] for i, (name, _) in enumerate(hoods_pg)}

    # 1 — neighborhood interiors: faint linepack of the neighborhood's own name
    for name, geom in hoods_pg:
        words = WORD_OVERRIDES.get(name, [name.lower()])
        style = {**LAYERS["neighborhood_fill"], "fill": hood_color[name], "opacity": 0.3}
        linepack_fill(doc, geom.simplify(2), words, style)

    # 2 — parks (clipped to the city)
    for name, geom in layers["parks"]:
        g = ll_to_page(geom).intersection(city_pg)
        if g.is_empty or g.area < 900:
            continue
        words = WORD_OVERRIDES.get(name, [name.lower() if name else "park"])
        linepack_fill(doc, g.simplify(2), words, LAYERS["park_fill"])

    # 3 — water (clipped to the page frame, not the city: the Mystic is the border)
    frame = to_page(city.buffer(400).envelope)
    for name, geom in layers["water"]:
        g = ll_to_page(geom).intersection(frame)
        if g.is_empty or g.area < 900:
            continue
        words = WORD_OVERRIDES.get(name, [name.upper() if name else "water ~"])
        contour_fill(doc, g.simplify(2), " ".join(words), LAYERS["water_fill"])

    # 4 — the Community Path (named cycleways, merged)
    named_paths = {}
    for name, line in layers["cycleways"]:
        if name:
            named_paths.setdefault(name, []).append(line)
    for name, segs in named_paths.items():
        merged = unary_union([ll_to_page(s) for s in segs])
        if isinstance(merged, MultiLineString):
            merged = linemerge(merged)
        parts = merged.geoms if isinstance(merged, MultiLineString) else [merged]
        for part in parts:
            part = part.simplify(1.5).intersection(street_clip)
            for line in getattr(part, "geoms", [part]):
                if isinstance(line, LineString) and line.length > est_width(name, 13):
                    street_label(doc, line, name, LAYERS["path"], sep="  »  ")

    # 5 — streets, minor → major so bigger names sit on top
    order = {"minor": 0, "mid": 1, "major": 2}
    for name, cls, line in sorted(layers["streets"], key=lambda s: order[s[1]]):
        g = ll_to_page(line).simplify(1.5).intersection(street_clip)
        style = LAYERS[f"street_{cls}" if cls != "mid" else "street_mid"]
        for part in getattr(g, "geoms", [g]):
            if isinstance(part, LineString) and part.length > est_width(name, style["font_size"]) * 0.8:
                street_label(doc, part, name, style)

    # 6 — T stations (whitelisted lines only; keeps out neighboring cities' stops)
    seen = set()
    for name, pt in layers["stations"]:
        if name not in STATION_LINES or name in seen:
            continue
        seen.add(name)
        p = ll_to_page(pt)
        color = LINE_COLORS[STATION_LINES[name]]
        doc.text(p.x, p.y, f"Ⓣ {name.upper()}", {**LAYERS["station"], "fill": color})

    # 7 — hero labels, one per neighborhood
    for name, geom in hoods_pg:
        c = geom.representative_point()
        bw = geom.bounds[2] - geom.bounds[0]
        size = max(30, min(76, (geom.area ** 0.5) * 0.22))
        style = {**LAYERS["hero"], "font_size": round(size), "fill": hood_color[name]}
        arched_label(doc, (c.x, c.y + size * 0.3), name.upper(), style,
                     width=max(bw * 0.75, est_width(name, size) * 0.8), bulge=0.16)

    # 8 — title
    title_y = page_h - 24
    tspans = "".join(
        f'<tspan fill="{HERO_CYCLE[i % len(HERO_CYCLE)]}">{ch}</tspan>'
        for i, ch in enumerate("SOMERVILLE"))
    doc.raw(f'<text x="{PAGE_W / 2}" y="{title_y}" text-anchor="middle" '
            f'font-family="{LAYERS["hero"]["font_family"]}" font-size="110" '
            f'font-weight="900" letter-spacing="30">{tspans}</text>')

    out = ROOT / "out/somerville.svg"
    out.parent.mkdir(exist_ok=True)
    doc.write(out)
    print(f"wrote {out} ({PAGE_W}×{page_h})")


if __name__ == "__main__":
    main()
