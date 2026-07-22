# /// script
# requires-python = ">=3.11"
# ///
"""Fetch municipal boundaries around Somerville → data/cache/boundaries.json.

admin_level 8 = cities/towns (Medford, Cambridge, Everett, Boston, …);
admin_level 10 = named districts inside them (e.g. Charlestown).
Same network-tolerance contract as fetch_osm.py: cache on success,
exit 0 on failure, mirror fallback. © OpenStreetMap contributors, ODbL.
"""

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BBOX = "42.3550,-71.1550,42.4350,-71.0400"
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]
CACHE = Path(__file__).parent / "data/cache/boundaries.json"

QUERY = f"""
[out:json][timeout:120][bbox:{BBOX}];
relation["boundary"="administrative"]["admin_level"~"^(8|10)$"];
out geom;

"""


def main() -> None:
    body = urllib.parse.urlencode({"data": QUERY}).encode()
    for url in ENDPOINTS:
        try:
            print(f"querying {url} …")
            req = urllib.request.Request(url, data=body, headers={
                "User-Agent": "somerville-typemap/0.1 (+https://github.com/jsundram/somerville-typemap)"})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read())
            if not data.get("elements"):
                raise ValueError("empty result")
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(data))
            names = sorted({(el["tags"].get("admin_level"), el["tags"].get("name"))
                            for el in data["elements"] if el.get("tags", {}).get("name")})
            print(f"wrote {CACHE}")
            for lvl, name in names:
                print(f"  L{lvl}  {name}")
            return
        except Exception as e:
            print(f"  failed: {e}", file=sys.stderr)
    print("all endpoints failed; keeping existing cache", file=sys.stderr)


if __name__ == "__main__":
    main()
