# SWOTFlow Lite v0.4.1

A separate, four-tab desktop application for native 100 m SWOT processing and ordinary Earth Engine ingestion through Google Cloud Storage. GeeUp remains a separate application.

## Two routes

- **Prepare locally:** download, verify, extract and mosaic; keep prepared mosaics for manual browser upload. Export a batch plan, upload its TIFFs to the exact listed bucket folder, then use **Import / Resume bucket batch**.
- **Fully automatic:** complete one bounded batch, upload finished mosaics with editable concurrency, ingest each into EE, verify metadata/provenance, clean owned Cloud copies and optionally local mosaics, then continue.

NASA catalogue snapshots, preferred-version selection, downloaded filenames, source checksums, acquisition times, paired elevation/quality mosaicking, recovery and Statistics reuse the verified GeeUp v0.9.1 engine. See [engine provenance](ORIGIN.md).

## Start on Windows

1. Use approved **64-bit Python 3.11 or 3.12** (including 3.12.10) with Tkinter, and your separate GDAL/NetCDF environment. The app and GDAL Python versions do not need to match.
2. Run `Setup_SWOTFlow_Lite.ps1` from PowerShell. Respect your organisation's software/network policies.
3. Open `Start_SWOTFlow_Lite.cmd`. Keep its console available for NASA sign-in.
4. Create a **new Lite project outside the application folder**, set UTM tiles, dates, GDAL Python and Cloud destination. Select tiles on the offline map, type their names, or combine continent presets.
5. Use **Authenticate NASA**, **Catalogue / plan**, then **Start / Resume**. Review the plan before a large run.

Setup preserves an existing supported `.venv`. For a fresh installation it tries Python 3.12, then 3.11 through the Windows launcher, then `python` on PATH. To choose explicitly, run `./Setup_SWOTFlow_Lite.ps1 -PythonPath 'C:\path\to\Python312\python.exe'`. Add `-CheckOnly` to check compatibility without installing anything. Do not copy another computer's `.venv`; create it on the destination computer.

Follow [the Lite setup/workflow guide](docs/lite-setup.md), including Google billing/ADC setup. No bucket, collection or paid run is created just by opening the app. Existing GeeUp projects are not silently migrated.

Choose an **empty EE collection for a new Lite project**. To add tiles/dates or switch between automatic and manual upload, reopen the same project with its retained history. Separate projects sharing a collection cannot establish each other's source lineage; unknown assets block collection completeness and safe local cleanup without discarding your own verified-upload counts.

## Storage and cleanup

Defaults are targets of 50 complete mosaics and 2 GiB of original-source bytes per batch, 20 GiB retained prepared mosaics, and 10 GiB free disk reserve. Complete UTC acquisition days are kept together: a single oversized day is reported rather than split. NetCDF compression varies, so these are batching/backpressure measures, not a hard filesystem quota. The engine also checks free reserve between consuming stages.

- Clean originals only after verified extraction, and extracted TIFFs only after verified mosaicking.
- Clean local mosaics only after confirmed EE ingestion with matching source/byte provenance.
- Clean staging objects only after verified EE assets; generation conditions protect replaced files.
- Keep failed/pending work and durable histories. Storage pauses allow upload/cleanup recovery without demanding space for a second local processing pass.

Manual imports make a server-side copy into an app-owned revision path before ingestion. There is **no second local upload**, but briefly two bucket copies and an extra copy operation. The manual original is deleted only after EE verification and owned-copy cleanup. Browser uploads are outside the app's automatic storage cap. Keep batches small and import while uploads continue.

## Tile selection

In **Project**, check several continents and choose **Add checked continents** to combine them with the current tiles, or **Use only checked continents** to replace the list. Shared tiles appear once. **Select on map…** lets you fine-tune that same list by clicking tiles, zooming and panning, with country boundaries/names for reference. You can also add a whole UTM zone for either or both hemispheres. Apply commits the map selection; Cancel leaves it unchanged.

The offline map uses the existing bundled UTM grid and continent presets, plus public-domain Natural Earth country outlines. Blue means selected scope, not successful processing or NASA coverage. Presets include all intersecting grid tiles; **Catalogue / plan** checks available acquisitions. Reopen the same project and refresh its plan after adding tiles/dates; retained histories and completed work remain available. See [reference sources](spatial_presets/README.md).

## Processing scope

**Process Zones** adds a focused zone queue preview and optional adaptive, half-month or calendar-month preparation windows. Complete all dates for each selected zone/hemisphere before the next zone. The normal Process workflow, Cloud settings and source histories remain shared. See [zone scheduling and Resume](docs/lite-setup.md#process-zones-complete-selected-zones-in-bounded-windows).

**Project → Mosaic grouping** defaults to **Tile by tile**. The optional **Original projection / group UTM latitude bands by hemisphere** combines the selected latitude-band tiles within each numbered UTM zone and hemisphere, separately for each UTC acquisition-start date, cycle and pass. Outputs use the full app's `UTM36N` / `UTM36S` convention (north/south); their original source bands remain recorded. No reprojection is performed: north uses EPSG:326xx and south EPSG:327xx, at 100 m. Lowest-quality-code selection keeps elevation and quality paired.

Select the mode before the first Catalogue / plan. To cover a whole zone, select its bands with **Select on map → Add zone**; grouping alone does not expand the chosen area. All contributing bands are collected before each mosaic, with whole-day batch boundaries and disk checks. Both automatic and manual Cloud routes use the grouped mosaics. Statistics shows expected asset reduction and attributes source coverage to the original tiles.

An existing plan's grouping cannot be silently changed. Adding new dates or unrelated groups is supported; adding bands or revised sources to an already-started date/pass group requires a reviewed replacement in a separate project/collection. The app blocks that change without replacing the old plan or assets. This release does not automatically rebuild existing grouped assets.

The simplified UI does not expose browser automation, reprojection or cross-zone EE consolidation. Compatibility modules remain internally to preserve tested science/history contracts; Lite never starts ChromeDriver.

Statistics restores the full engine's detailed information: **finished/pending tiles and years, status map and plots, download/extraction filenames, source-to-mosaic lineage, processing versions, mosaics, upload outcomes, NASA search/version history, update/run history, disk usage and cleanup**. The two menus choose a category and table. Search, both scrollbars, full-row details and CSV/JSON exports keep every row available, including histories larger than the old preview limits.

A tile is finished only when its **entire requested date range** has catalogue coverage and all preferred inputs have matching EE evidence in a current, conflict-free inventory. An empty catalogue window is distinguished from pending work. Cumulative processing history remains visible after local cleanup. Refresh Statistics reads local records in a background thread; it does not download, upload or delete files. **Cloud → Sync EE / clean verified copies** performs the existing remote verification/cleanup workflow. See [Statistics instructions](docs/lite-setup.md#statistics-and-recovery) for evidence freshness and NASA comparisons.

Only one controller may operate on a project at a time. Back up project databases and logs. New dates/tiles use a refreshed catalogue plan; completed scientific receipts are reused. Changes to scientific choices or the destination require a separate project. Newly published processing revisions may need explicit replacement review; existing assets are never silently overwritten.

## Validation

Application regression tests live in `tests`. One-off pilots, downloaded files, reports, credentials and personal settings do not belong in this repository. Release notes distinguish offline checks, live pilot evidence and remaining workplace proxy/throughput testing.

Python **3.12.10** clean installation, GUI/imports and the full regression suite were checked for v0.1.1: **813 passed, five skipped**. Read-only NASA, Cloud Storage and EE checks also passed. See [compatibility validation](docs/lite-validation.md).

See [v0.1.0 validation](docs/lite-validation.md): 809 passing regression tests, five skips (the GDAL source oracle passed separately), and two live mosaics with exact agreement in the sampled elevation/quality/masks. Both upload routes, cleanup and Resume were checked in one project. The manual browser transfer was emulated; workplace connectivity remains to be tested.
