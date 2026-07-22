"""What physically demarcates each neighborhood boundary?

For every border segment shared by two regions, find the linear feature
(street, rail line, path, water) that runs along it, if any. The renderer
then styles the border by demarcation kind and labels it with the
feature's name — so the map explains *why* the line is where it is.
"""

from shapely import STRtree
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge

# Priority when overlap ratios tie: water beats rail beats path beats street.
KIND_PRIORITY = {"water": 3, "rail": 2, "path": 1, "street": 0}


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
             min_ratio: float = 0.45):
    """Which feature runs along `border`?

    features: [(kind, name, geom)] indexed by `tree` over `geoms`.
    Returns (kind, name) or (None, "").
    """
    best_kind, best_name, best_score = None, "", 0.0
    for idx in tree.query(border.buffer(tol)):
        kind, name, geom = features[idx]
        ratio = border.intersection(geom.buffer(tol)).length / border.length
        if ratio < min_ratio:
            continue
        score = ratio + KIND_PRIORITY[kind] * 0.001  # priority as tie-break
        if score > best_score:
            best_kind, best_name, best_score = kind, name, score
    return best_kind, best_name
