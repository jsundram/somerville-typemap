"""What physically demarcates each neighborhood boundary?

For every border segment shared by two regions, find the linear feature
(street, rail line, path, water) that runs along it, if any. The renderer
then styles the border by demarcation kind and labels it with the
feature's name — so the map explains *why* the line is where it is.
"""

import math

from shapely import STRtree
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge, substring

# Priority among features that qualify as "running along" a border.
# Waterway centerlines beat merged water bodies (a body's buffer matches
# anything near the bank; the centerline carries the local name — Alewife
# Brook, not the Mystic it drains into). A path beats the rail line it
# was built beside; both beat the street grid.
KIND_PRIORITY = {"water": 4, "waterbody": 3, "path": 2, "rail": 1, "street": 0}


def shared_borders(regions, tol: float = 3.0):
    """Border segments shared by each pair of adjacent regions.

    regions: [(name, polygon)] → yields (name_a, name_b, MultiLineString).
    """
    from itertools import combinations

    for (na, ga), (nb, gb) in combinations(regions, 2):
        seg = ga.boundary.intersection(gb.boundary.buffer(tol))
        seg = _clean_lines(seg)
        if seg is not None and seg.length > 30:
            yield na, nb, seg


def _clean_lines(geom):
    """Keep only the linear parts of an intersection result, merged."""
    lines = []
    for part in getattr(geom, "geoms", [geom]):
        if isinstance(part, LineString) and part.length > 1:
            lines.append(part)
        elif isinstance(part, MultiLineString):
            lines.extend(part.geoms)
    if not lines:
        return None
    merged = linemerge(MultiLineString(lines)) if len(lines) > 1 else lines[0]
    return merged


def classify(border, features, tree: STRtree, tol: float = 14,
             min_ratio: float = 0.5, qualify: float = 0.62):
    """Which feature runs along `border`?

    features: [(kind, name, geom)] indexed by `tree` over `geoms`.
    Any feature covering ≥ `qualify` of the border "runs along" it — among
    those, KIND_PRIORITY picks (so the Community Path beats the Lowell
    Line it parallels). Below that, best coverage ≥ `min_ratio` wins.
    Returns (kind, name, matched_geom) or (None, "", None).
    """
    qualified, fallback = [], []
    for idx in tree.query(border.buffer(tol)):
        kind, name, geom = features[idx]
        ratio = border.intersection(geom.buffer(tol)).length / border.length
        if ratio >= qualify:
            qualified.append((KIND_PRIORITY[kind], ratio, kind, name, geom))
        elif ratio >= min_ratio:
            fallback.append((ratio, KIND_PRIORITY[kind], kind, name, geom))
    if qualified:
        _, _, kind, name, geom = max(qualified, key=lambda q: (q[0], q[1]))
        return kind, name, geom
    if fallback:
        _, _, kind, name, geom = max(fallback, key=lambda q: (q[0], q[1]))
        return kind, name, geom
    return None, "", None


def split_chunks(line: LineString, max_len: float = 220.0) -> list[LineString]:
    """Cut a polyline into ≈equal pieces no longer than `max_len`, so a
    border that runs along water for a while and then inland classifies
    piecewise instead of all-or-nothing."""
    n = max(1, math.ceil(line.length / max_len))
    step = line.length / n
    return [substring(line, k * step, (k + 1) * step) for k in range(n)]
