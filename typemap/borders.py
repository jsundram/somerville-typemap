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


def chain_route(streets, sequence, start_dir, end_dir, bridge=60.0, snap=15.0):
    """One polyline following named streets in order — a *perceived*
    border (the line locals draw), not an administrative one.

    streets: [(name, LineString)] in page coords. sequence: street names
    in travel order. Each street is walked (shortest path over its own
    segments) from the junction with the previous street to the junction
    with the next; the first/last street run out to their extreme node in
    start_dir/end_dir ("east"/"west"/"north"/"south"). Junction gaps up to
    `bridge` px (Cambridge St → Beacon St at Inman) are bridged straight.
    Returns [(name, LineString)] — one piece per street, in order.
    """
    import heapq

    from shapely.geometry import Point
    from shapely.ops import nearest_points

    key = {"east": lambda p: p[0], "west": lambda p: -p[0],
           "south": lambda p: p[1], "north": lambda p: -p[1]}

    def graph(name):
        adj = {}
        ends = []
        for n, line in streets:
            if n != name:
                continue
            for part in getattr(line, "geoms", [line]):
                if not isinstance(part, LineString) or part.is_empty:
                    continue
                cs = [(round(x, 1), round(y, 1)) for x, y in part.coords]
                ends += [cs[0], cs[-1]]
                for a, b in zip(cs, cs[1:]):
                    d = math.dist(a, b)
                    adj.setdefault(a, []).append((b, d))
                    adj.setdefault(b, []).append((a, d))
        # clipping and dual carriageways leave near-touching ends
        for i, a in enumerate(ends):
            for b in ends[i + 1:]:
                d = math.dist(a, b)
                if 0 < d <= snap:
                    adj[a].append((b, d))
                    adj[b].append((a, d))
        return adj

    def dijkstra(adj, src):
        dist, prev, pq = {src: 0.0}, {}, [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            for v, w in adj[u]:
                if d + w < dist.get(v, math.inf):
                    dist[v], prev[v] = d + w, u
                    heapq.heappush(pq, (d + w, v))
        return dist, prev

    def walk(prev, dst):
        out = [dst]
        while out[-1] in prev:
            out.append(prev[out[-1]])
        return out[::-1]

    graphs = {n: graph(n) for n in sequence}
    geoms = {n: MultiLineString([LineString(list(graph_line))
                                 for graph_line in _edges(graphs[n])])
             for n in sequence}

    def nearest_node(adj, pt):
        return min(adj, key=lambda q: math.dist(q, pt))

    # junction points between consecutive streets
    joins = []
    for a, b in zip(sequence, sequence[1:]):
        pa, pb = nearest_points(geoms[a], geoms[b])
        if pa.distance(pb) > bridge:
            raise ValueError(f"{a} and {b} don't meet (gap {pa.distance(pb):.0f}px)")
        joins.append(((pa.x, pa.y), (pb.x, pb.y)))

    pieces = []
    for i, name in enumerate(sequence):
        adj = graphs[name]
        src = nearest_node(adj, joins[i - 1][1]) if i else None
        dst = nearest_node(adj, joins[i][0]) if i < len(sequence) - 1 else None
        if src is None:  # first street: run out to its start_dir extreme
            dist, prev = dijkstra(adj, dst)
            src = max(dist, key=key[start_dir])
            path = walk(prev, src)[::-1]
        else:
            dist, prev = dijkstra(adj, src)
            if dst is None:
                dst = max(dist, key=key[end_dir])
            path = walk(prev, dst)
        if pieces and i:  # bridge the junction gap onto this piece
            path = [pieces[-1][1].coords[-1]] + path
        if len(path) >= 2:
            pieces.append((name, LineString(path)))
    return pieces


def _edges(adj):
    seen = set()
    for a, nbrs in adj.items():
        for b, _ in nbrs:
            if (b, a) not in seen:
                seen.add((a, b))
                yield (a, b)
