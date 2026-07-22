# /// script
# requires-python = ">=3.11"
# ///
"""Fetch OSM features for the Somerville bbox → data/cache/overpass.json.

Layers: named roads, parks/green space, water, the Community Path
(cycleways), and T stations (Red/Orange + the 2022 Green Line Extension).

Network-tolerant: on any failure the existing cache is left untouched and
we exit 0. Overpass mirrors overload often, so the main endpoint falls
back to the .fr mirror. Data © OpenStreetMap contributors (ODbL).
"""

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BBOX = "42.3550,-71.1550,42.4350,-71.0400"  # S,W,N,E — Somerville + surroundings
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]
CACHE = Path(__file__).parent / "data/cache/overpass.json"

QUERY = f"""
[out:json][timeout:180][bbox:{BBOX}];
(
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street|pedestrian)$"]["name"];
  way["highway"="cycleway"];
  way["highway"~"^(path|footway)$"]["name"];
  way["leisure"~"^(park|garden|playground|common)$"];
  relation["leisure"="park"];
  way["landuse"~"^(recreation_ground|cemetery|grass)$"];
  way["natural"="water"];
  relation["natural"="water"];
  way["waterway"~"^(river|stream|canal)$"];
  way["railway"~"^(rail|light_rail)$"];
  nwr["railway"="station"];
  nwr["public_transport"="station"];
);
out geom;
"""

GLX = {"Union Square", "East Somerville", "Gilman Square", "Magoun Square", "Ball Square"}


def summarize(data: dict) -> None:
    kinds: dict[str, int] = {}
    stations = []
    for el in data["elements"]:
        tags = el.get("tags", {})
        if tags.get("name") and (tags.get("railway") == "station"
                                 or tags.get("public_transport") == "station"):
            stations.append(tags["name"])
        for key in ("highway", "leisure", "landuse", "natural", "waterway"):
            if key in tags:
                kinds[f"{key}={tags[key]}"] = kinds.get(f"{key}={tags[key]}", 0) + 1
                break
    print(f"{len(data['elements']):,} elements")
    for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5d}  {k}")
    print("stations:", ", ".join(sorted(set(stations))))
    missing = GLX - {s.split(" (")[0] for s in stations}
    print("GLX check:", "all present ✓" if not missing else f"MISSING {sorted(missing)}")


def main() -> None:
    body = urllib.parse.urlencode({"data": QUERY}).encode()
    for url in ENDPOINTS:
        try:
            print(f"querying {url} …")
            req = urllib.request.Request(url, data=body, headers={
                "User-Agent": "somerville-typemap/0.1 (+https://github.com/jsundram/somerville-typemap)"})
            with urllib.request.urlopen(req, timeout=240) as r:
                data = json.loads(r.read())
            if not data.get("elements"):
                raise ValueError("empty result")
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(data))
            print(f"wrote {CACHE}")
            summarize(data)
            return
        except Exception as e:
            print(f"  failed: {e}", file=sys.stderr)
    print("all endpoints failed; keeping existing cache", file=sys.stderr)


if __name__ == "__main__":
    main()
