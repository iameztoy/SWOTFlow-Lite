"""Build the offline selection-map reference from Natural Earth country GeoJSON."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def build(source: Path, destination: Path) -> None:
    """Keep reference outlines and labels, without changing selection presets."""
    raw = source.read_bytes()
    countries = []
    for feature in json.loads(raw)["features"]:
        props, geom = feature["properties"], feature["geometry"]
        polygons = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        countries.append({
            "name": props["NAME_LONG"],
            "label": [props["LABEL_X"], props["LABEL_Y"]],
            "rings": [[[round(x, 5), round(y, 5)] for x, y in ring]
                      for polygon in polygons for ring in polygon],
        })
    result = {"schema_version": 1, "crs": "OGC:CRS84", "source": {
        "name": "Natural Earth 1:110m Admin 0 Countries", "version": "5.1.2",
        "url": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_110m_admin_0_countries.geojson",
        "license": "Public domain", "license_url": "https://www.naturalearthdata.com/about/terms-of-use/",
        "sha256": hashlib.sha256(raw).hexdigest(),
    }, "countries": countries}
    destination.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build(args.source, args.destination)
