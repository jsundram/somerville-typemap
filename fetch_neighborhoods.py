# /// script
# requires-python = ">=3.11"
# dependencies = ["pyshp>=2.3"]
# ///
"""Fetch official Somerville neighborhood polygons → data/neighborhoods.geojson.

Source: City of Somerville open data portal (Public Domain).
https://data.somervillema.gov/GIS-Data/Neighborhoods/n5md-vqta

Network-tolerant: the downloaded zip is cached in data/cache/; on fetch
failure the cache is left untouched and we exit 0 so a flaky network never
corrupts the build. Output coordinates are left in the shapefile's native
CRS: NAD83 Massachusetts State Plane Mainland, US survey feet (EPSG:2249).
"""

import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

import shapefile

URL = "https://data.somervillema.gov/download/n5md-vqta/application%2Fzip"
ROOT = Path(__file__).parent
CACHE = ROOT / "data/cache/Neighborhoods.zip"
OUT = ROOT / "data/neighborhoods.geojson"


def fetch() -> None:
    try:
        with urllib.request.urlopen(URL, timeout=60) as r:
            blob = r.read()
        zipfile.ZipFile(io.BytesIO(blob)).testzip()  # sanity before replacing cache
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(blob)
        print(f"fetched {len(blob):,} bytes → {CACHE}")
    except Exception as e:
        print(f"fetch failed ({e}); keeping existing cache", file=sys.stderr)


def convert() -> None:
    if not CACHE.exists():
        print("no cached Neighborhoods.zip; run again with network", file=sys.stderr)
        return
    z = zipfile.ZipFile(CACHE)
    names = {Path(n).suffix: n for n in z.namelist()}
    sf = shapefile.Reader(
        shp=io.BytesIO(z.read(names[".shp"])),
        shx=io.BytesIO(z.read(names[".shx"])),
        dbf=io.BytesIO(z.read(names[".dbf"])),
    )
    features = [
        {
            "type": "Feature",
            "properties": {"name": rec["NBHD"]},
            "geometry": shp.__geo_interface__,
        }
        for shp, rec in zip(sf.shapes(), sf.records())
    ]
    OUT.write_text(json.dumps(
        {"type": "FeatureCollection", "crs_note": "EPSG:2249 (MA State Plane, US ft)",
         "features": features}))
    print(f"wrote {OUT} ({len(features)} neighborhoods)")


if __name__ == "__main__":
    fetch()
    convert()
