# /// script
# requires-python = ">=3.11"
# dependencies = ["shapely>=2.0", "pyproj>=3.6"]
# ///
"""Assemble the Somerville typographic map as separate toggleable layers.

Outputs:
  out/layers/L1_basemap.svg    schematic reference (the one drawn layer)
  out/layers/L2_neighborhoods.svg   region tints + faint name wash
  out/layers/L3_transit.svg    T stations + the Community Path
  out/layers/L4_adjacent.svg   Medford / Cambridge / Charlestown / …
  out/layers/L5_heroes.svg     fitted neighborhood hero typography
  out/layers/L6_typography.svg streets / parks / water as text
  out/somerville.svg           combined print map (all-text layers, no basemap)
"""

import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, shape
from shapely.ops import linemerge, transform, unary_union

from config.style import HERO_CYCLE, LAYERS, PAPER
from config.words import LINE_COLORS, STATION_LINES, TOWNS, WORD_OVERRIDES
from typemap.fills import (arched_label, contour_fill, fitted_hero,
                           linepack_fill, polygon_ds, street_label)
from typemap.osm import load_layers, _relation_polygon
from typemap.svgdoc import SvgDoc, est_width, path_d, write_combined

ROOT = Path(__file__).parent
PAGE_W = 3400
MARGIN = 40
FRINGE = 2200  # ft of surrounding towns shown beyond the city limits

to_stateplane = Transformer.from_crs("EPSG:4326", "EPSG:2249", always_xy=True).transform


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

    def ll_to_page(g):
        return to_page(transform(to_stateplane, g))

    osm = load_layers(json.loads((ROOT / "data/cache/overpass.json").read_text()))
    towns_raw = json.loads((ROOT / "data/cache/boundaries.json").read_text())["elements"]

    city_pg = to_page(city)
    hoods_pg = sorted((name, to_page(g)) for name, g in hoods)
    hood_color = {name: HERO_CYCLE[i % len(HERO_CYCLE)] for i, (name, _) in enumerate(hoods_pg)}
    street_clip = city_pg.buffer(6)
    frame = to_page(city.buffer(FRINGE).envelope)

    docs = {}

    def layer(key: str) -> SvgDoc:
        return docs.setdefault(key, SvgDoc(PAGE_W, page_h, background=None, id_prefix=key))

    # ── L1 basemap: the one deliberately-drawn layer, for reference only
    L1 = layer("L1_basemap")
    stroke_w = {"major": 5, "mid": 3, "minor": 1.5}
    base = []
    for _, geom in osm["water"]:
        g = ll_to_page(geom).intersection(frame)
        if not g.is_empty:
            base.append(f'<path d="{" ".join(polygon_ds(g))}" fill="#cfe0ee" fill-rule="evenodd"/>')
    for _, geom in osm["parks"]:
        g = ll_to_page(geom).intersection(frame)
        if not g.is_empty and g.area > 400:
            base.append(f'<path d="{" ".join(polygon_ds(g))}" fill="#dce8d8" fill-rule="evenodd"/>')
    for name, cls, line in osm["streets"]:
        g = ll_to_page(line).simplify(1.5).intersection(frame)
        for part in getattr(g, "geoms", [g]):
            if isinstance(part, LineString):
                base.append(f'<path d="{path_d(part.coords)}" fill="none" '
                            f'stroke="#d8d2c6" stroke-width="{stroke_w[cls]}"/>')
    base.append(f'<path d="{" ".join(polygon_ds(city_pg))}" fill="none" '
                f'stroke="#8a8378" stroke-width="3" stroke-dasharray="14 10"/>')
    L1.group(base)

    # ── L2 neighborhood regions: flat tint + faint wash of the name
    L2 = layer("L2_neighborhoods")
    for name, geom in hoods_pg:
        L2.raw(f'<path d="{" ".join(polygon_ds(geom))}" fill="{hood_color[name]}" '
               f'opacity="0.10" fill-rule="evenodd"/>')
        words = WORD_OVERRIDES.get(name, [name.lower()])
        style = {**LAYERS["neighborhood_fill"], "font_size": 11,
                 "fill": hood_color[name], "opacity": 0.45}
        linepack_fill(L2, geom.simplify(2), words, style, leading=1.6)

    # ── L3 transit: Community Path + T stations
    L3 = layer("L3_transit")
    named_paths = {}
    for name, line in osm["cycleways"]:
        if name:
            named_paths.setdefault(name, []).append(line)
    for name, segs in named_paths.items():
        merged = unary_union([ll_to_page(s) for s in segs])
        if isinstance(merged, MultiLineString):
            merged = linemerge(merged)
        for part in getattr(merged, "geoms", [merged]):
            part = part.simplify(1.5).intersection(street_clip)
            for line in getattr(part, "geoms", [part]):
                if isinstance(line, LineString) and line.length > est_width(name, 13):
                    street_label(L3, line, name, LAYERS["path"], sep="  »  ")
    seen = set()
    for name, pt in osm["stations"]:
        if name not in STATION_LINES or name in seen:
            continue
        seen.add(name)
        p = ll_to_page(pt)
        color = LINE_COLORS[STATION_LINES[name]]
        L3.text(p.x, p.y, f"Ⓣ {name.upper()}", {**LAYERS["station"], "fill": color})

    # ── L4 adjacent municipalities: tint + sparse name fill + big label
    L4 = layer("L4_adjacent")
    for el in towns_raw:
        tags = el.get("tags", {})
        cfg = TOWNS.get(tags.get("name", ""))
        if not cfg or el["type"] != "relation":
            continue
        poly = _relation_polygon(el)
        if poly is None:
            continue
        g = ll_to_page(poly).intersection(frame).difference(city_pg.buffer(4))
        if g.is_empty or g.area < 15000:
            continue
        display = cfg.get("display", tags["name"])
        L4.raw(f'<path d="{" ".join(polygon_ds(g))}" fill="{cfg["color"]}" '
               f'opacity="0.08" fill-rule="evenodd"/>')
        fill_style = {**LAYERS["neighborhood_fill"], "font_size": 15,
                      "fill": cfg["color"], "opacity": 0.35, "letter_spacing": 2}
        linepack_fill(L4, g.simplify(3), [display.lower()], fill_style, leading=2.2)
        # label the chunk nearest the city, not just the biggest —
        # Boston's biggest visible chunk is East Boston, but the part
        # that borders Somerville is Charlestown
        cc = city_pg.centroid
        chunk = max(getattr(g, "geoms", [g]),
                    key=lambda p: p.area / (1 + p.distance(cc)))
        fitted_hero(L4, chunk, display,
                    {**LAYERS["hero"], "fill": cfg["color"], "opacity": 0.85},
                    max_size=72)

    # ── L5 neighborhood hero typography (fitted, not just a curve)
    L5 = layer("L5_heroes")
    for name, geom in hoods_pg:
        fitted_hero(L5, geom, name, {**LAYERS["hero"], "fill": hood_color[name]})
    tspans = "".join(
        f'<tspan fill="{HERO_CYCLE[i % len(HERO_CYCLE)]}">{ch}</tspan>'
        for i, ch in enumerate("SOMERVILLE"))
    L5.raw(f'<text x="{PAGE_W / 2}" y="{page_h - 24}" text-anchor="middle" '
           f'font-family="{LAYERS["hero"]["font_family"]}" font-size="110" '
           f'font-weight="900" letter-spacing="30" stroke="{PAPER}" '
           f'stroke-width="4" paint-order="stroke">{tspans}</text>')

    # ── L6 typography for parks / water / streets
    L6 = layer("L6_typography")
    for name, geom in osm["parks"]:
        g = ll_to_page(geom).intersection(city_pg)
        if g.is_empty or g.area < 900:
            continue
        words = WORD_OVERRIDES.get(name, [name.lower() if name else "park"])
        linepack_fill(L6, g.simplify(2), words, LAYERS["park_fill"])
    for name, geom in osm["water"]:
        g = ll_to_page(geom).intersection(frame)
        if g.is_empty or g.area < 900:
            continue
        words = WORD_OVERRIDES.get(name, [name.upper() if name else "water ~"])
        contour_fill(L6, g.simplify(2), " ".join(words), LAYERS["water_fill"])
    order = {"minor": 0, "mid": 1, "major": 2}
    for name, cls, line in sorted(osm["streets"], key=lambda s: order[s[1]]):
        g = ll_to_page(line).simplify(1.5).intersection(street_clip)
        style = LAYERS[f"street_{cls}"]
        for part in getattr(g, "geoms", [g]):
            if isinstance(part, LineString) and part.length > est_width(name, style["font_size"]) * 0.8:
                street_label(L6, part, name, style)

    # ── write per-layer SVGs + the combined print map
    outdir = ROOT / "out/layers"
    outdir.mkdir(parents=True, exist_ok=True)
    for key, doc in docs.items():
        doc.write(outdir / f"{key}.svg")
        print(f"wrote {outdir / f'{key}.svg'}")
    print_order = ["L4_adjacent", "L2_neighborhoods", "L6_typography",
                   "L3_transit", "L5_heroes"]
    write_combined(ROOT / "out/somerville.svg", [docs[k] for k in print_order],
                   PAGE_W, page_h, background=PAPER)
    print(f"wrote {ROOT / 'out/somerville.svg'} ({PAGE_W}×{page_h})")


if __name__ == "__main__":
    main()
