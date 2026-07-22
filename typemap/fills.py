"""The typographic area-fill engine.

Two methods, per the Axis Maps look:

- `linepack_fill` — straight rows of repeated text spanning the polygon's
  bbox, clipped to the polygon. Letters get sliced mid-glyph at the
  boundary, which is the signature look. Best for parks / land /
  neighborhood interiors.

- `contour_fill` — text flows along nested inward-buffered rings of the
  polygon, so the words ripple parallel to the shoreline. Best for water.

Both return lists of SVG element strings (via SvgDoc helpers) so callers
control layering.
"""

from shapely.geometry import LineString, MultiPolygon, Polygon

from .svgdoc import SvgDoc, est_width, path_d, repeat_to_length


def _polygons(geom):
    """Iterate the Polygon members of a (Multi)Polygon, skipping empties."""
    if geom.is_empty:
        return
    if isinstance(geom, Polygon):
        yield geom
    elif isinstance(geom, MultiPolygon):
        yield from geom.geoms


def _upright_runs(coords) -> list[list]:
    """Split a coordinate sequence into runs of consistent x-direction,
    reversing the right-to-left runs so glyphs never render upside-down."""
    pts = list(coords)
    runs, cur, cur_sign = [], [pts[0]], 0
    for a, b in zip(pts, pts[1:]):
        dx = b[0] - a[0]
        s = 1 if dx > 0 else (-1 if dx < 0 else cur_sign)
        if cur_sign == 0:
            cur_sign = s
        elif s != cur_sign:
            runs.append((cur_sign, cur))
            cur, cur_sign = [a], s
        cur.append(b)
    runs.append((cur_sign or 1, cur))
    return [pts[::-1] if sign < 0 else pts for sign, pts in runs]


def polygon_ds(geom) -> list[str]:
    """SVG path data (exteriors + holes) for a (Multi)Polygon."""
    ds = []
    for poly in _polygons(geom):
        ds.append(path_d(poly.exterior.coords, close=True))
        ds.extend(path_d(ring.coords, close=True) for ring in poly.interiors)
    return ds


def linepack_fill(doc: SvgDoc, polygon, words: list[str], style: dict,
                  leading: float = 1.15, stagger: float = 0.4) -> None:
    """Fill `polygon` with straight rows of repeated `words`, clipped.

    `words` cycles row by row; `stagger` shifts alternate rows left by
    that fraction of a word so the columns don't align.
    """
    size = style["font_size"]
    minx, miny, maxx, maxy = polygon.bounds
    clip_id = doc.add_clip(polygon_ds(polygon))
    rows: list[str] = []
    step = size * leading
    y = miny + size  # first baseline
    i = 0
    while y < maxy + size:
        word = words[i % len(words)]
        shift = (i % 3) * stagger / 3 * len(word) * size * 0.6
        x0 = minx - shift - size
        text = repeat_to_length(word, (maxx - x0), size)
        d = f"M {x0:.2f},{y:.2f} L {maxx + size:.2f},{y:.2f}"
        doc.text_on_path(d, text, style, group=rows)
        y += step
        i += 1
    doc.group(rows, clip_id=clip_id)


def contour_fill(doc: SvgDoc, polygon, text: str, style: dict,
                 spacing: float | None = None, max_rings: int = 200) -> None:
    """Fill `polygon` with `text` flowing along nested inward contours."""
    size = style["font_size"]
    spacing = spacing if spacing is not None else size * 1.3
    elements: list[str] = []
    # First ring slightly inset so glyphs don't poke past the boundary.
    inset = size * 0.45
    for k in range(max_rings):
        ring_geom = polygon.buffer(-(inset + k * spacing), join_style="round")
        if ring_geom.is_empty:
            break
        for poly in _polygons(ring_geom):
            for ring in (poly.exterior, *poly.interiors):
                for run in _upright_runs(ring.coords):
                    line = LineString(run)
                    if line.length < size * 2:  # too small to hold glyphs
                        continue
                    doc.text_on_path(path_d(run),
                                     repeat_to_length(text, line.length, size),
                                     style, group=elements)
    doc.group(elements)


def street_label(doc: SvgDoc, line, name: str, style: dict, sep: str = " · ") -> None:
    """Repeat `name` along the street centerline (left-to-right overall)."""
    coords = list(line.coords)
    if coords[-1][0] < coords[0][0]:  # net right-to-left → flip for upright text
        coords.reverse()
    text = repeat_to_length(name, line.length, style["font_size"], sep=sep)
    doc.text_on_path(path_d(coords), text, style)


def fitted_hero(doc: SvgDoc, polygon, name: str, style: dict,
                bulge: float = 0.10, max_size: float = 84, min_size: float = 13) -> None:
    """A hero label that actually fits inside `polygon`.

    The baseline follows the polygon's own orientation: the long axis of
    its minimum rotated rectangle, moved to a chord through the label
    point and clipped to the polygon. Font size is chosen so the text
    fits the chord and the polygon's short dimension; names that still
    can't fit on one line are stacked word-wise on parallel baselines.
    """
    import math

    mrr = polygon.minimum_rotated_rectangle
    corners = list(mrr.exterior.coords)[:4]
    edges = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    lengths = [math.dist(a, b) for a, b in edges]
    i_long = lengths.index(max(lengths))
    (ax, ay), (bx, by) = edges[i_long]
    long_len, short_len = lengths[i_long], lengths[(i_long + 1) % 4]
    ux, uy = (bx - ax) / long_len, (by - ay) / long_len
    if ux < 0:  # keep text left-to-right
        ux, uy = -ux, -uy
    px, py = -uy, ux
    if py < 0:  # keep the perpendicular pointing screen-down, for stacking lines
        px, py = -px, -py

    c = polygon.representative_point()
    chord = LineString([(c.x - ux * long_len, c.y - uy * long_len),
                        (c.x + ux * long_len, c.y + uy * long_len)]).intersection(polygon)
    if hasattr(chord, "geoms"):
        chord = max(chord.geoms, key=lambda g: g.length, default=None)
    usable = chord.length * 0.92 if chord is not None and not chord.is_empty else long_len * 0.6

    text = name.upper()
    per_char = 0.68  # rounded-bold caps run wider than the body estimate
    size = min(max_size, short_len * 0.40, usable / (per_char * len(text)))
    lines = [text]
    if size < 24 and " " in text:  # stack the words instead
        words = text.split()
        k = min(range(1, len(words)),
                key=lambda k: abs(len(" ".join(words[:k])) - len(" ".join(words[k:]))))
        lines = [" ".join(words[:k]), " ".join(words[k:])]
        longest = max(len(ln) for ln in lines)
        size = min(max_size, short_len * 0.28, usable / (per_char * longest))
    size = max(size, min_size)

    mx, my = (chord.interpolate(0.5, normalized=True).coords[0]
              if chord is not None and not chord.is_empty else (c.x, c.y))
    style = {**style, "font_size": round(size, 1), "text_anchor": "middle"}
    leading = size * 1.12
    for i, ln in enumerate(lines):
        off = (i - (len(lines) - 1) / 2) * leading + size * 0.35  # baseline sits below center
        ox, oy = mx + px * off, my + py * off
        half = est_width(ln, size) * 0.75
        x0, y0 = ox - ux * half, oy - uy * half
        x1, y1 = ox + ux * half, oy + uy * half
        # bow the baseline gently "up" (against the stacking direction)
        cxp = (x0 + x1) / 2 - px * bulge * 2 * half
        cyp = (y0 + y1) / 2 - py * bulge * 2 * half
        d = f"M {x0:.2f},{y0:.2f} Q {cxp:.2f},{cyp:.2f} {x1:.2f},{y1:.2f}"
        doc.text_on_path(d, ln, style, start_offset="50%")


def arched_label(doc: SvgDoc, center: tuple[float, float], text: str, style: dict,
                 width: float, bulge: float = 0.25) -> None:
    """A hero label on an upward-bulging arc centered at `center`.

    `width` is the chord length; `bulge` is arc height as a fraction of it.
    Negative `bulge` arches downward. The chord is widened if needed so the
    text always fits — glyphs past a path's end are silently dropped by SVG.
    """
    size = style["font_size"]
    ls = float(style.get("letter_spacing", 0))
    needed = est_width(text, size) * 1.25 + ls * len(text)
    width = max(width, needed)
    cx, cy = center
    x0, x1 = cx - width / 2, cx + width / 2
    # Quadratic Bézier through the apex: control point 2×bulge above chord.
    d = f"M {x0:.2f},{cy:.2f} Q {cx:.2f},{cy - 2 * bulge * width:.2f} {x1:.2f},{cy:.2f}"
    style = {"text_anchor": "middle", **style}
    doc.text_on_path(d, text, style, start_offset="50%")
