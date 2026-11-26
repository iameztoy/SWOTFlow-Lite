# Offline tile-selection references

- `utm_display_geometries.json`: existing bundled EPSG:3857 UTM grid/continent display geometry, generated 16 May 2026. Source layer names and bounds are recorded in the file.
- `continent_utm_tiles.json`: existing continent intersection presets. Several presets can share tiles; Lite selects their union. The geometry and membership are unchanged by Lite v0.2.0.
- `country_reference.json`: compact longitude/latitude outlines and label positions from **Natural Earth 1:110m Admin 0 Countries, v5.1.2**, retrieved 26 November 2026. For orientation only; not authoritative administrative boundaries, a NASA coverage layer, or an analysis mask.

Natural Earth data is [public domain](https://www.naturalearthdata.com/about/terms-of-use/). The pinned [GeoJSON source](https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_110m_admin_0_countries.geojson) SHA-256 is `6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f`.

Rebuild the country reference from a downloaded copy using:

```powershell
python -m swotflow.tools.build_country_reference path/to/ne_110m_admin_0_countries.geojson spatial_presets/country_reference.json
```

The Lite selector converts only display geometry to longitude/latitude for a wide desktop map. North is up; UTM coverage is 80°S–84°N. There are no area comparisons or distance claims. Blue fill/dark outline means selected; unselected grids remain unfilled. Country lines are muted gray, separate from the blue selection. Scientific rasters retain their original native grids.
