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
from shapely.geometry import LineString, MultiLineString, Point, shape
from shapely.ops import linemerge, substring, transform, unary_union

from config.style import HERO_CYCLE, LAYERS, PAPER
from config.words import (LINE_COLORS, PATH_FAMILY, RAIL_MAINLINES, RAIL_RENAME,
                          STATION_LINES, TOWNS, WORD_OVERRIDES)
from typemap.borders import _clean_lines, classify, shared_borders, split_chunks
from typemap.fills import (arched_label, contour_fill, fitted_hero,
                           linepack_fill, polygon_ds, street_label)
from typemap.osm import load_layers, _relation_polygon
from typemap.svgdoc import (SvgDoc, est_width, path_d, repeat_to_length,
                            write_combined)

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

    hoods_pg = sorted((name, to_page(g)) for name, g in hoods)
    frame = to_page(city.buffer(FRINGE).envelope)

    # The neighborhoods dataset doesn't quite tile the municipal boundary
    # (e.g. a wedge between Hillside and the Mystic). Absorb each gap
    # piece of the OSM admin polygon into the neighborhood it borders
    # most, so no sliver of Somerville goes unfilled.
    som_el = next((el for el in towns_raw if el["type"] == "relation"
                   and el.get("tags", {}).get("name") == "Somerville"), None)
    if som_el is not None:
        admin_pg = ll_to_page(_relation_polygon(som_el)).buffer(0)
        gaps = admin_pg.difference(
            unary_union([g for _, g in hoods_pg]).buffer(1))
        for piece in getattr(gaps, "geoms", [gaps]):
            # skip tiny scraps and long invisible slivers (the legal
            # boundary spike along the rail corridor toward Charlestown) —
            # a piece too thin to see shouldn't mint phantom borders
            if piece.area < 400 or piece.buffer(-6).is_empty:
                continue
            i = max(range(len(hoods_pg)),
                    key=lambda i: piece.buffer(8).intersection(hoods_pg[i][1]).area)
            name, geom = hoods_pg[i]
            hoods_pg[i] = (name, unary_union([geom, piece.buffer(1)]).buffer(0))

    city_pg = unary_union([g for _, g in hoods_pg]).buffer(0)
    street_clip = city_pg.buffer(6)
    # For the drawn outline and exterior borders: morphological opening
    # removes sub-visible spikes (North Point's legal sliver along the
    # rail corridor toward Charlestown would otherwise mint a phantom
    # border out to Community College).
    city_outline_pg = city_pg.buffer(-5).buffer(5).buffer(0)

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
                elif line.length > 30:  # too short for the name: show continuity
                    street_label(L3, line, "»", LAYERS["path"], sep="  ")
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
    known_rail = set(RAIL_MAINLINES) | {"Grand Junction", "Green Line"}
    for name, line in osm["rails"]:
        name = RAIL_RENAME.get(name, name)
        if name not in known_rail:
            name = ""  # yard-track names ("4th Iron", "Track 9") inherit below
        rails_grouped.setdefault(name, []).append(ll_to_page(line).simplify(1.5))
    # unnamed yard/siding tracks inherit the name of the named line they
    # run beside — the Fitchburg Line corridor is mostly unnamed tracks
    named_geom = {n: unary_union(segs) for n, segs in rails_grouped.items() if n}
    for seg in rails_grouped.pop("", []):
        dists = {n: seg.distance(g) for n, g in named_geom.items()}
        best = min(dists, default=None, key=dists.get)
        if best is not None and dists[best] < 15:
            # prefer a mainline over a branch when both are plausibly close
            for main in RAIL_MAINLINES:
                if dists.get(main, 1e9) < 25:
                    best = main
                    break
            rails_grouped[best].append(seg)
        else:
            rails_grouped.setdefault("rail line", []).append(seg)
    rail_parts = []
    for name, segs in rails_grouped.items():
        merged = unary_union(segs)
        if isinstance(merged, MultiLineString):
            merged = linemerge(merged)
        for part in getattr(merged, "geoms", [merged]):
            p = part.intersection(frame)
            for line in getattr(p, "geoms", [p]):
                if isinstance(line, LineString) and line.length > 40:
                    rail_parts.append((name, line))

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
             # GLX tracks share the commuter corridors; borders read as the
             # corridor's line (Fitchburg/Lowell), never a blend with GLX
             + [("rail", n, g) for n, g in rail_parts if n != "Green Line"]
             + [("path", n, g) for n, g in path_parts]
             + [("water", n, g) for n, g in waterway_parts]  # named centerlines
             + [("waterbody", n or "water", g) for n, g in water_comps])
    tree = STRtree([g for _, _, g in feats])

    BORDER_STYLE = {
        "street": ("#3a3a3a", ""),
        "rail": ("#8a5fbf", ' stroke-dasharray="12 7"'),
        "path": ("#2f8f4e", ""),
        "water": ("#3f7fbf", ""),
        "waterbody": ("#3f7fbf", ""),
        None: ("#b0a898", ' stroke-dasharray="2 7"'),  # nothing on the ground
    }
    ABBREV = {"Street": "St", "Avenue": "Ave", "Boulevard": "Blvd",
              "Highway": "Hwy", "Parkway": "Pkwy", "Road": "Rd"}

    def label_that_fits(name: str, length: float) -> str | None:
        if est_width(name, 13) * 1.15 <= length:
            return name
        short = " ".join(ABBREV.get(w, w) for w in name.split())
        return short if est_width(short, 13) * 1.15 <= length else None
    L7 = layer("L7_boundaries")
    L7.raw(f'<path d="{" ".join(polygon_ds(city_outline_pg))}" fill="none" '
           f'stroke="#3a3a3a" stroke-width="4" opacity="0.35"/>')

    def draw_run(run, kind, fname, fgeom, width):
        """One contiguous border run with a single classification."""
        color, dash = BORDER_STYLE[kind]
        # the demarcating feature: draw its real geometry near the border
        # (a census-block border zigzags along a rail corridor; the train
        # doesn't) — water bodies/unmatched keep the border line itself.
        # Cut the feature EXACTLY between the projections of the run's
        # endpoints so the stroke starts and stops where the border does.
        stroke = run
        if kind in ("street", "rail", "path", "water"):
            if isinstance(fgeom, LineString):
                s0 = fgeom.project(Point(run.coords[0]))
                s1 = fgeom.project(Point(run.coords[-1]))
                if abs(s1 - s0) >= 20:
                    stroke = substring(fgeom, min(s0, s1), max(s0, s1))
                else:
                    stroke = None
            else:
                stroke = _clean_lines(
                    fgeom.intersection(run.buffer(18, cap_style="flat")))
            # a matched stroke must actually hug the border: trim whatever
            # strays beyond the slack ribbon (tails curving away at the
            # ends), and if less than half the run survives, the match was
            # spurious — a parallel street a block off (Porter St) is not
            # this border
            slack = 60 if kind == "rail" else 20  # rail corridors are wide
            if stroke is not None:
                stroke = _clean_lines(
                    stroke.intersection(run.buffer(slack, cap_style="flat")))
            kept = sum(p.length for p in getattr(stroke, "geoms", [stroke])
                       if isinstance(p, LineString)) if stroke is not None else 0
            if kept < 0.5 * run.length:
                stroke, kind, fname = run, None, ""
                color, dash = BORDER_STYLE[None]
        if stroke is None:
            return
        parts = [p for p in getattr(stroke, "geoms", [stroke])
                 if isinstance(p, LineString)]
        for part in parts:
            L7.raw(f'<path d="{path_d(part.simplify(1).coords)}" fill="none" '
                   f'stroke="{color}" stroke-width="{width}"{dash}/>')
        if fname and parts:
            longest = max(parts, key=lambda p: p.length)
            label = label_that_fits(fname, longest.length)
            if label:
                coords = list(longest.simplify(1).coords)
                if coords[-1][0] < coords[0][0]:
                    coords.reverse()
                style = {**LAYERS["border_label"], "fill": color}
                if longest.length > est_width(label, 13) * 3.2:
                    # a long border repeats its name along its whole extent
                    text = repeat_to_length(label, longest.length * 0.94, 13)
                    style.pop("text_anchor", None)
                    L7.text_on_path(path_d(coords), text, style)
                else:
                    L7.text_on_path(path_d(coords), label, style,
                                    start_offset="50%")

    def draw_border(seg, width=3.0):
        # the administrative line itself, always, as a hairline
        for part in getattr(seg, "geoms", [seg]):
            if isinstance(part, LineString):
                L7.raw(f'<path d="{path_d(part.coords)}" fill="none" '
                       f'stroke="#b0a898" stroke-width="1.2"/>')
        # classify piecewise: a long frontage may run along water for a
        # stretch and a street for the next — group equal chunks into runs
        for part in getattr(seg, "geoms", [seg]):
            if not isinstance(part, LineString) or part.length < 20:
                continue
            pieces = split_chunks(part, 160)
            verdicts = [classify(p, feats, tree) for p in pieces]
            # smoothing: a lone flickering chunk between two agreeing
            # neighbors adopts their verdict if their feature plausibly
            # covers it too (extends Kidder Ave to meet College Ave)
            for k in range(1, len(pieces) - 1):
                prev, nxt = verdicts[k - 1], verdicts[k + 1]
                if (prev[:2] == nxt[:2] and prev[:2] != verdicts[k][:2]
                        and prev[0] is not None
                        and pieces[k].intersection(prev[2].buffer(16)).length
                        >= 0.3 * pieces[k].length):
                    verdicts[k] = prev
            # extension: a matched feature grows across adjacent unmatched
            # chunks for as long as it keeps hugging the border — so a
            # street runs to the border's corner, not to where the
            # classifier's confidence ran out
            def hugs(verdict, chunk):
                kind, _, fg = verdict
                slack = 60 if kind == "rail" else 22
                if isinstance(fg, LineString):
                    s0 = fg.project(Point(chunk.coords[0]))
                    s1 = fg.project(Point(chunk.coords[-1]))
                    if abs(s1 - s0) < 8:
                        return False
                    sub = substring(fg, min(s0, s1), max(s0, s1))
                    return sub.hausdorff_distance(chunk) <= slack
                return chunk.within(fg.buffer(slack))

            changed = True
            while changed:
                changed = False
                for k in range(len(pieces)):
                    if verdicts[k][0] is not None:
                        continue
                    for nb in (k - 1, k + 1):
                        if (0 <= nb < len(pieces) and verdicts[nb][0] is not None
                                and hugs(verdicts[nb], pieces[k])):
                            verdicts[k] = verdicts[nb]
                            changed = True
                            break
            # snap-to-corner: a short unmatched stub (one chunk) beside a
            # feature run joins it, so Central St meets its corner instead
            # of stopping a half-block short
            for k in range(len(pieces)):
                if verdicts[k][0] is None and pieces[k].length <= 180:
                    for nb in (k - 1, k + 1):
                        if 0 <= nb < len(pieces) and verdicts[nb][0] is not None:
                            verdicts[k] = verdicts[nb]
                            break
            i = 0
            while i < len(pieces):
                j = i
                while (j + 1 < len(pieces)
                       and verdicts[j + 1][:2] == verdicts[i][:2]):
                    j += 1
                run = linemerge(MultiLineString(pieces[i:j + 1])) \
                    if j > i else pieces[i]
                if isinstance(run, MultiLineString):
                    run = max(run.geoms, key=lambda g: g.length)
                kind, fname, fgeom = verdicts[i]
                draw_run(run, kind, fname, fgeom, width)
                i = j + 1

    # interior borders: neighborhood vs neighborhood
    for na, nb, seg in shared_borders(hoods_pg, tol=8):
        draw_border(seg)
    # exterior borders: each neighborhood's frontage on the city limit —
    # classified the same way (the Mystic frontage reads as water, the
    # Cambridge line as the street it follows, …)
    city_edge = city_outline_pg.boundary.buffer(3)
    for name, geom in hoods_pg:
        seg = _clean_lines(geom.boundary.intersection(city_edge))
        if seg is not None and seg.length > 30:
            draw_border(seg, width=4.0)

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
