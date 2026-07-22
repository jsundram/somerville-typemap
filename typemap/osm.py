"""Turn a cached Overpass response into shapely geometries by layer."""

from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import linemerge, polygonize, unary_union

MAJOR = {"motorway", "trunk", "primary"}
MID = {"secondary", "tertiary"}
PARK_LEISURE = {"park", "garden", "playground", "common"}
PARK_LANDUSE = {"recreation_ground", "cemetery"}


def _way_coords(el):
    return [(g["lon"], g["lat"]) for g in el.get("geometry", [])]


def _relation_polygon(el):
    """Assemble a (multi)polygon from a relation's outer/inner member ways."""
    outers, inners = [], []
    for m in el.get("members", []):
        # bbox-clipped output puts null placeholders for out-of-bbox vertices
        coords = [(g["lon"], g["lat"]) for g in (m.get("geometry") or []) if g]
        if len(coords) < 2:
            continue
        (outers if m.get("role") != "inner" else inners).append(LineString(coords))
    shell = unary_union(list(polygonize(linemerge(MultiLineString(outers)))))
    if shell.is_empty:
        return None
    holes = unary_union(list(polygonize(linemerge(MultiLineString(inners))))) if inners else None
    return shell.difference(holes) if holes else shell


def load_layers(data: dict) -> dict:
    """Overpass JSON → {'streets', 'cycleways', 'parks', 'water', 'stations'}."""
    streets = {}  # name -> {"cls": best class, "segs": [LineString]}
    cycleways, parks, water, stations, waterways = [], [], [], [], []
    rank = {"minor": 0, "mid": 1, "major": 2}

    for el in data["elements"]:
        tags = el.get("tags", {})
        if el["type"] == "way":
            coords = _way_coords(el)
            if len(coords) < 2:
                continue
            hwy = tags.get("highway")
            closed = coords[0] == coords[-1] and len(coords) >= 4
            if hwy == "cycleway":
                cycleways.append((tags.get("name", ""), LineString(coords)))
            elif hwy and tags.get("name"):
                cls = "major" if hwy in MAJOR else "mid" if hwy in MID else "minor"
                # one entry per name (not per class): a street whose class
                # changes along its run would otherwise be labeled twice
                entry = streets.setdefault(tags["name"], {"cls": cls, "segs": []})
                if rank[cls] > rank[entry["cls"]]:
                    entry["cls"] = cls
                entry["segs"].append(LineString(coords))
            elif closed and (tags.get("leisure") in PARK_LEISURE
                             or tags.get("landuse") in PARK_LANDUSE):
                parks.append((tags.get("name", ""), Polygon(coords)))
            elif closed and tags.get("natural") == "water":
                water.append((tags.get("name", ""), Polygon(coords)))
            elif tags.get("waterway") and tags.get("name"):
                waterways.append((tags["name"], LineString(coords)))
        elif el["type"] == "relation":
            poly = _relation_polygon(el)
            if poly is None:
                continue
            if tags.get("natural") == "water":
                water.append((tags.get("name", ""), poly))
            elif tags.get("leisure") in PARK_LEISURE:
                parks.append((tags.get("name", ""), poly))
        if tags.get("name") and (tags.get("railway") == "station"
                                 or tags.get("public_transport") == "station"):
            stations.append((tags["name"], _center(el)))

    merged_streets = []
    for name, entry in streets.items():
        geom = unary_union(entry["segs"])
        if isinstance(geom, MultiLineString):
            geom = linemerge(geom)
        lines = geom.geoms if isinstance(geom, MultiLineString) else [geom]
        merged_streets.extend((name, entry["cls"], line) for line in lines)
    # Unnamed water polygons inherit the name of a waterway centerline
    # crossing them (OSM names the line, rarely the riverbank polygon).
    water = [
        (name or next((wname for wname, wline in waterways if wline.intersects(poly)), ""),
         poly)
        for name, poly in water
    ]
    return {"streets": merged_streets, "cycleways": cycleways,
            "parks": parks, "water": water, "stations": stations}


def _center(el) -> Point:
    if el["type"] == "node":
        return Point(el["lon"], el["lat"])
    if "bounds" in el:
        b = el["bounds"]
        return Point((b["minlon"] + b["maxlon"]) / 2, (b["minlat"] + b["maxlat"]) / 2)
    coords = _way_coords(el)
    return LineString(coords).centroid if len(coords) > 1 else Point(coords[0])
