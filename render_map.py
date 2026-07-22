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
from shapely import STRtree
from shapely.geometry import LineString, MultiLineString, shape
from shapely.ops import linemerge, transform, unary_union

from config.style import HERO_CYCLE, LAYERS, PAPER
from config.words import (LINE_COLORS, PATH_FAMILY, RAIL_RENAME, STATION_LINES,
                          TOWNS, WORD_OVERRIDES)
from typemap.borders import classify, shared_borders
from typemap.fills import (arched_label, contour_fill, fitted_hero,
                           linepack_fill, polygon_ds, street_label)
from typemap.osm import load_layers, _relation_polygon
from typemap.svgdoc import SvgDoc, est_width, path_d, write_combined

ROOT = Path(__file__).parent
PAGE_W = 3400
MARGIN = 40
FRINGE = 2200  # ft of surrounding towns shown beyond the city limits

to_stateplane = Transformer.from_crs("EPSG:4326", "EPSG:2249", always_xy=True).transform


def color_regions(regions, palette, fixed=()):
    """Greedy graph coloring: no two touching regions share a color.

    regions: [(name, geom)] to color; fixed: [(color, geom)] pre-colored
    areas (adjacent towns) whose colors neighbors must also avoid.
    """
    from itertools import combinations

    grown = {n: g.buffer(20) for n, g in regions}
    neigh = {n: set() for n, _ in regions}
    for (a, _), (b, _) in combinations(regions, 2):
        if grown[a].intersects(grown[b]):
            neigh[a].add(b)
            neigh[b].add(a)
    forbidden = {n: set() for n, _ in regions}
    for color, g in fixed:
        gb = g.buffer(20)
        for n, _ in regions:
            if grown[n].intersects(gb):
                forbidden[n].add(color)
    colors = {}
    for n in sorted(neigh, key=lambda n: -len(neigh[n])):
        used = {colors[m] for m in neigh[n] if m in colors} | forbidden[n]
        colors[n] = next((c for c in palette if c not in used), palette[0])
    return colors


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
    street_clip = city_pg.buffer(6)
    frame = to_page(city.buffer(FRINGE).envelope)

    # Adjacent towns (page-space, clipped) — needed before coloring so
    # neighborhoods also avoid clashing with the town next door.
    towns_pg = []
    for el in towns_raw:
        tags = el.get("tags", {})
        cfg = TOWNS.get(tags.get("name", ""))
        if not cfg or el["type"] != "relation":
            continue
        poly = _relation_polygon(el)
        if poly is None:
            continue
        g = ll_to_page(poly).intersection(frame).difference(city_pg.buffer(4))
        if not g.is_empty and g.area >= 15000:
            towns_pg.append((cfg.get("display", tags["name"]), cfg["color"], g))

    hood_color = color_regions(hoods_pg, HERO_CYCLE,
                               fixed=[(color, g) for _, color, g in towns_pg])

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

    # ── L3 transit: the path family (Community Path and its continuations
    # past Davis: Alewife Linear Park, Minuteman Bikeway) + T stations
    L3 = layer("L3_transit")
    named_paths = {}
    for name, line in osm["cycleways"]:
        if name in PATH_FAMILY:
            named_paths.setdefault(name, []).append(line)
    path_parts = []  # kept for border classification below
    for name, segs in named_paths.items():
        merged = unary_union([ll_to_page(s) for s in segs])
        if isinstance(merged, MultiLineString):
            merged = linemerge(merged)
        for part in getattr(merged, "geoms", [merged]):
            part = part.simplify(1.5).intersection(frame)
            for line in getattr(part, "geoms", [part]):
                if not isinstance(line, LineString):
                    continue
                path_parts.append((name, line))
                if line.length > est_width(name, 13):
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
    for display, color, g in towns_pg:
        L4.raw(f'<path d="{" ".join(polygon_ds(g))}" fill="{color}" '
               f'opacity="0.08" fill-rule="evenodd"/>')
        fill_style = {**LAYERS["neighborhood_fill"], "font_size": 15,
                      "fill": color, "opacity": 0.35, "letter_spacing": 2}
        linepack_fill(L4, g.simplify(3), [display.lower()], fill_style, leading=2.2)
        # label the chunk nearest the city, not just the biggest —
        # Boston's biggest visible chunk is East Boston, but the part
        # that borders Somerville is Charlestown
        cc = city_pg.centroid
        chunk = max(getattr(g, "geoms", [g]),
                    key=lambda p: p.area / (1 + p.distance(cc)))
        fitted_hero(L4, chunk, display,
                    {**LAYERS["hero"], "fill": color, "opacity": 0.85},
                    max_size=72, cram=0.5)

    # ── shared feature preprocessing (used by L7 classification and L6)
    street_parts = []
    for name, cls, line in osm["streets"]:
        g = ll_to_page(line).simplify(1.5).intersection(frame)
        for part in getattr(g, "geoms", [g]):
            if isinstance(part, LineString):
                street_parts.append((name, cls, part))

    rails_grouped = {}
    for name, line in osm["rails"]:
        rails_grouped.setdefault(RAIL_RENAME.get(name, name), []).append(line)
    rail_parts = []
    for name, segs in rails_grouped.items():
        merged = unary_union([ll_to_page(s) for s in segs])
        if isinstance(merged, MultiLineString):
            merged = linemerge(merged)
        for part in getattr(merged, "geoms", [merged]):
            p = part.simplify(1.5).intersection(frame)
            for line in getattr(p, "geoms", [p]):
                if isinstance(line, LineString) and line.length > 40:
                    rail_parts.append((name or "rail line", line))

    water_pg = []
    for name, geom in osm["water"]:
        g = ll_to_page(geom).intersection(frame)
        if not g.is_empty and g.area >= 900:
            water_pg.append((name, g))
    merged_water = unary_union([g for _, g in water_pg])
    water_comps = []
    for comp in getattr(merged_water, "geoms", [merged_water]):
        if comp.area < 900:
            continue
        wname = next((n for n, g in sorted(water_pg, key=lambda w: -w[1].area)
                      if n and g.intersects(comp)), "")
        water_comps.append((wname, comp))

    # ── L7 boundaries: styled + labeled by what physically demarcates them
    waterway_parts = []
    for name, line in osm["waterways"]:
        g = ll_to_page(line).simplify(1.5).intersection(frame)
        for part in getattr(g, "geoms", [g]):
            if isinstance(part, LineString) and part.length > 40:
                waterway_parts.append((name, part))

    feats = ([("street", n, g) for n, _, g in street_parts]
             + [("rail", n, g) for n, g in rail_parts]
             + [("path", n, g) for n, g in path_parts]
             + [("water", n, g) for n, g in waterway_parts]  # named centerlines first
             + [("water", n or "water", g) for n, g in water_comps])
    tree = STRtree([g for _, _, g in feats])

    BORDER_STYLE = {
        "street": ("#3a3a3a", ""),
        "rail": ("#8a5fbf", ' stroke-dasharray="12 7"'),
        "path": ("#2f8f4e", ""),
        "water": ("#3f7fbf", ""),
        None: ("#b0a898", ' stroke-dasharray="2 7"'),  # nothing on the ground
    }
    L7 = layer("L7_boundaries")
    L7.raw(f'<path d="{" ".join(polygon_ds(city_pg))}" fill="none" '
           f'stroke="#3a3a3a" stroke-width="4" opacity="0.5"/>')
    hood_names = {n for n, _ in hoods_pg}
    regions_all = hoods_pg + [(d, g) for d, _, g in towns_pg]
    for na, nb, seg in shared_borders(regions_all, tol=8):
        if na not in hood_names and nb not in hood_names:
            continue  # town-town borders out in the fringe aren't our story
        kind, fname = classify(seg, feats, tree)
        color, dash = BORDER_STYLE[kind]
        for part in getattr(seg, "geoms", [seg]):
            if isinstance(part, LineString):
                L7.raw(f'<path d="{path_d(part.coords)}" fill="none" '
                       f'stroke="{color}" stroke-width="3"{dash}/>')
        if fname:
            longest = max((p for p in getattr(seg, "geoms", [seg])
                           if isinstance(p, LineString)),
                          key=lambda p: p.length, default=None)
            if longest and longest.length > est_width(fname, 13) * 1.3:
                coords = list(longest.simplify(1).coords)
                if coords[-1][0] < coords[0][0]:
                    coords.reverse()
                L7.text_on_path(path_d(coords), fname,
                                {**LAYERS["border_label"], "fill": color},
                                start_offset="50%")

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

    # Parks: drop near-duplicate geometries (way + relation mapping the
    # same park), then carve nested features (a playground inside a park)
    # out of the parent's fill so their texts never overlap.
    parks_pg = []
    for name, geom in osm["parks"]:
        g = ll_to_page(geom).intersection(city_pg)
        # an area feature earns a text fill only if it could hold at least
        # one row of park text — kills median strips and traffic islands
        if not g.is_empty and g.area >= 900 and not g.buffer(-7).is_empty:
            parks_pg.append((name, g))
    parks_pg.sort(key=lambda p: -p[1].area)
    parks_kept = []
    for name, g in parks_pg:
        if not any(g.intersection(kg).area > 0.6 * g.area for _, kg in parks_kept):
            parks_kept.append((name, g))
    for i, (name, g) in enumerate(parks_kept):
        inner = [kg for _, kg in parks_kept[i + 1:] if kg.intersects(g)]
        fill_geom = g.difference(unary_union(inner).buffer(3)) if inner else g
        if fill_geom.is_empty:
            continue
        words = WORD_OVERRIDES.get(name, [name.lower() if name else "park"])
        linepack_fill(L6, fill_geom.simplify(2), words, LAYERS["park_fill"])

    # Water: merged components (deduped way+relation double-mapping above)
    for name, comp in water_comps:
        words = WORD_OVERRIDES.get(name, [name.upper() if name else "water ~"])
        contour_fill(L6, comp.simplify(2), " ".join(words), LAYERS["water_fill"])

    # Streets: suppress dual-carriageway twins — a second component that
    # runs parallel within a few px of an already-labeled longer one.
    order = {"minor": 0, "mid": 1, "major": 2}
    by_name = {}
    for name, cls, part in street_parts:
        g = part.intersection(street_clip)
        for p in getattr(g, "geoms", [g]):
            if isinstance(p, LineString):
                by_name.setdefault((name, cls), []).append(p)
    for (name, cls), parts in sorted(by_name.items(), key=lambda kv: order[kv[0][1]]):
        style = LAYERS[f"street_{cls}"]
        parts.sort(key=lambda p: -p.length)
        kept = []
        for part in parts:
            if part.length <= est_width(name, style["font_size"]) * 0.8:
                continue
            if kept and part.intersection(unary_union(kept).buffer(18)).length > 0.6 * part.length:
                continue
            kept.append(part)
            street_label(L6, part, name, style)

    # ── write per-layer SVGs + the combined print map
    outdir = ROOT / "out/layers"
    outdir.mkdir(parents=True, exist_ok=True)
    for key, doc in docs.items():
        doc.write(outdir / f"{key}.svg")
        print(f"wrote {outdir / f'{key}.svg'}")
    print_order = ["L4_adjacent", "L2_neighborhoods", "L7_boundaries",
                   "L6_typography", "L3_transit", "L5_heroes"]
    write_combined(ROOT / "out/somerville.svg", [docs[k] for k in print_order],
                   PAGE_W, page_h, background=PAPER)
    print(f"wrote {ROOT / 'out/somerville.svg'} ({PAGE_W}×{page_h})")


if __name__ == "__main__":
    main()
