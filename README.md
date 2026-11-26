# SWOTFlow Lite v0.1.1

A separate, four-tab desktop application for native 100 m SWOT processing and ordinary Earth Engine ingestion through Google Cloud Storage. GeeUp remains a separate application.

## Two routes

- **Prepare locally:** download, verify, extract and mosaic; keep prepared mosaics for manual browser upload. Export a batch plan, upload its TIFFs to the exact listed bucket folder, then use **Import / Resume bucket batch**.
- **Fully automatic:** complete one bounded batch, upload finished mosaics with editable concurrency, ingest each into EE, verify metadata/provenance, clean owned Cloud copies and optionally local mosaics, then continue.

NASA catalogue snapshots, preferred-version selection, downloaded filenames, source checksums, acquisition times, paired elevation/quality mosaicking, recovery and Statistics reuse the verified GeeUp v0.9.1 engine. See [engine provenance](ORIGIN.md).

## Start on Windows

1. Use approved **64-bit Python 3.11 or 3.12** (including 3.12.10) with Tkinter, and your separate GDAL/NetCDF environment. The app and GDAL Python versions do not need to match.
2. Run `Setup_SWOTFlow_Lite.ps1` from PowerShell. Respect your organisation's software/network policies.
3. Open `Start_SWOTFlow_Lite.cmd`. Keep its console available for NASA sign-in.
4. Create a **new Lite project outside the application folder**, set UTM tiles, dates, GDAL Python and Cloud destination.
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

## Scope of v0.1.0

The simplified UI supports native 100 m **exact UTM tiles** and deterministic lowest-quality-code mosaicking. It does not expose browser automation, reprojection or cross-zone EE consolidation. Compatibility modules remain internally to preserve tested science/history contracts; Lite never starts ChromeDriver.

Statistics separates local preparation, manual upload waiting, bucket staging, EE ingestion, verification and cleanup. It covers the full current tile/date plan and withholds complete coverage for duplicate acquisition ownership. An empty catalogue is reported as no available acquisitions. EE counts describe the last verification; use Sync EE for a fresh remote check.

Only one controller may operate on a project at a time. Back up project databases and logs. New dates/tiles use a refreshed catalogue plan; completed scientific receipts are reused. Changes to scientific choices or the destination require a separate project. Newly published processing revisions may need explicit replacement review; existing assets are never silently overwritten.

## Validation

Application regression tests live in `tests`. One-off pilots, downloaded files, reports, credentials and personal settings do not belong in this repository. Release notes distinguish offline checks, live pilot evidence and remaining workplace proxy/throughput testing.

Python **3.12.10** clean installation, GUI/imports and the full regression suite were checked for v0.1.1: **813 passed, five skipped**. Read-only NASA, Cloud Storage and EE checks also passed. See [compatibility validation](docs/lite-validation.md).

See [v0.1.0 validation](docs/lite-validation.md): 809 passing regression tests, five skips (the GDAL source oracle passed separately), and two live mosaics with exact agreement in the sampled elevation/quality/masks. Both upload routes, cleanup and Resume were checked in one project. The manual browser transfer was emulated; workplace connectivity remains to be tested.
