# SWOTFlow Lite validation

## v0.5.0 — optional overlap with EE ingestion

The focused regression suite passed **255 checks**, with no failures or skips. A separate configured-GDAL run passed **49 checks**, including the small north/south extracted-source, mosaic, interrupted Resume and cleanup example. After refining the count of partially submitted batches in Statistics, all **29 targeted scheduler/Statistics checks** passed. These are execution counts, not a claim that all checks are unique or that the entire inherited suite was rerun.

The two-batch scheduler example prepares the second batch while the first remains INGESTING, drains verification at the end and performs no repeated processing on Resume. A separate two-mosaic example uses the actual Cloud uploader, durable journal, metadata/provenance and guarded staging deletion with a simulated remote transport. It verifies exact retained source history and no repeated transfer/task submission. Fault cases cover stop, timeout, failed/uncertain ingestion, source mismatch, local storage pressure and unchanged cleanup rules. Both exact-tile and zone/hemisphere orchestration pass through the selected completion mode.

Sixteen-transfer tests verify concurrent worker execution with a single journal/report writer; other tests retain the independent ingestion and aggregate staged-byte limits. GUI controls round-trip 30 downloads, four extraction/mosaic workers and 16 Cloud transfers without changing scientific identity. The source pixel algorithms and dependencies are unchanged. Python 3.12 syntax remains supported; this change was exercised with the installed 3.11 and configured GDAL environments, not a new clean 3.12 installation.

Remote services are simulated for these feature regressions: this is not a live overlap-speed or billing benchmark. No test assets or paid services were created. The existing February 2025 pilot remains on its frozen v0.4.2 source files; it was not used as an uncontrolled concurrency experiment.

## v0.4.2 — selectable lossless mosaic compression

The complete suite ran **886 tests: 860 passed, 26 environment/opt-in skips**. All **57 configured-GDAL raster/planning checks** passed separately, including full decoded array/mask equality for both codecs, overlap ties, singletons, separated gaps and both hemispheres. Final GUI checks passed after restoring unchanged Unicode labels. This release preserves Python 3.11/3.12 compatibility without changing dependencies; a clean 3.12 installation was not repeated.

Process and Process Zones share one persisted setting, for prepare-only and automatic routes. Existing projects without a codec retain uncompressed behavior; new projects use ZSTD. Ordinary/yearly Resume and cleaned-input regression cases preserve completed work after only an encoding change. Source filename history, scientific identities, metadata, current-file checksums and guarded cleanup remain intact. No routine full-pixel comparison was added. See [compression behavior](mosaic-compression.md).


A separate two-mosaic live pilot (north/south Zone 35) passed with 23 exact retained NASA inputs. The actual new writer produced full decoded-array/mask equality against the baseline; both codecs ingested successfully into an isolated EE test collection, with exact sampled cloud equality. Metadata, source accounting, duplicate-free Resume, staging deletion and local TIFF/world-file cleanup passed. Statistics retained 4/4 tiles and 23/23 inputs after cleanup. Production assets were unchanged. These release checks are not enabled during ordinary runs.

## v0.4.1 — bounded zone windows and a focused workflow view

The UI-environment suite ran **878 tests: 853 passed, 25 environment/opt-in skips**. A separate configured-GDAL run passed all **53 raster/planning checks**, including the 21 GDAL-dependent checks skipped by the UI environment. Combined coverage is **874 unique passing checks and four remaining skips** (three inherited browser DOM tests and a Windows symlink privilege test). All 14 new zone scheduling/UI checks passed. No dependencies or Python version support changed; a new Python 3.12 installation was not repeated.

The suite uses main-thread cyclic collection for Tk fixtures; initial ordinary discovery exposed destroyed Tk interpreters being collected by unrelated worker tests. Windows multiprocessing also requires a real script/module entry point. The maintained `python -m tests.run_suite` runner captures these constraints without changing the assertions. Initial test-launch failures remain in the separate investigation evidence. GDAL checks use the app's runtime configuration to load the already-installed NetCDF driver.

Zone cases cover half-month/month boundaries, leap days, complete-date preservation under a smaller byte limit, first-selected zone order with separate hemispheres, exact source membership, failed refresh protection, preserved started/interrupted batch IDs, local-ready Resume, GUI settings and full-period Statistics. A simulated multi-zone/two-year catalogue contains 30 preferred originals, yielding 18 zone/date mosaics instead of 30 tile/date mosaics; every original is accounted for exactly once. Cloud transport remains covered by the existing simulated automatic/manual suites. This is workflow validation, not a new NASA completeness survey or continent-scale throughput benchmark.

The existing tiny northern/southern NetCDF fixture passed actual extraction, paired quality/elevation mosaicking, interrupted Resume and guarded cleanup. Scientific functions were unchanged. The Process Zones tab, full layout and all window choices were inspected in the desktop app without opening a real project. No NASA originals were downloaded, no Cloud objects or EE assets were created/changed, and no paid service was activated. Investigation outputs remain outside the repository. No routine pixel comparisons were added to the processing workflow.

## v0.4.0 — optional native hemisphere grouping

The Windows/Python 3.11 suite ran **864 tests: 858 passed, six optional/environment skips**. Two GDAL-dependent tests (the new north/south workflow fixture and the existing source replay/injected-shift oracle) then passed separately using the configured GDAL runtime. Three inherited browser checks and the Windows symlink check remain optional. Dependencies and Python 3.11/3.12 support are unchanged. This release did not repeat the previous clean Python 3.12 installation: that temporary interpreter had been removed after its earlier compatibility test.

The new fixture uses four tiny synthetic NetCDF sources with deliberate overlap and nodata: two northern latitude bands in EPSG:32636 and two southern bands in EPSG:32736. It uses the actual app extraction/mosaic executors and source oracle. Each pair becomes one 100 m mosaic, with the lower quality code selecting its accompanying elevation. The independent comparison agrees with the original arrays. The fixture interrupts after extraction, resumes without downloading again, cleans verified raw/extracted files, and resumes again without repeating scientific stages. These are synthetic code regressions, not fresh NASA data or continent-wide validation.

Focused checks cover selected-band catalogue partitioning, empty bands, whole-day batching, distinct cycles/passes/dates, frozen membership, failed-search preservation, partial-group rejection, prepare-to-automatic checkpoint reuse, cleanup order, interrupted runs, original tile/year Statistics, GUI persistence, ambiguous N/S source filtering and grouped Cloud metadata. Existing automatic/manual import, ingestion failure, duplicate ownership, generation checks and cleanup tests remain passing. Cloud transport is simulated; there was no paid transfer, live NASA download or EE mutation in this release's validation.

The Project selector was inspected in the desktop UI with tile-by-tile selected by default and both choices visible. Existing planned workflows cannot silently change grouping; changed membership of an already-started group requires explicit replacement review. Grouping only includes selected bands and cannot fill intrinsic source nodata. Whole grouped days can require more disk space than exact-tile batches.

## v0.3.0 — full Statistics

The Windows/Python 3.11 application suite ran **847 tests: 842 passed, five existing optional/environment skips**. All 17 new Statistics regressions also passed after the final column-order adjustment. Dependencies and Python 3.11/3.12 support are unchanged; this release did not repeat the earlier clean Python 3.12 installation test.

New tests cover full requested tile/year completion, explicitly empty searches, missing/duplicate windows, expanded scope, pending uploads, stale/conflicting EE lineage, disappearance of previously verified assets from a newer inventory, preservation of cleaned-file histories, both Cloud routes, NASA version priority/events, archived run/cleanup history, exports above 1,000 rows, table pagination/filtering, map rendering, and isolation of Statistics errors/delayed results from the active workflow.

The actual Statistics collector was exercised on separate metadata-only copies of both retained v0.1.0 pilot projects. It exposed exact filenames, source lineage, NASA searches, stages and cleanup results without changing the original metadata. Refresh took approximately 0.1 seconds per small copied project. This is not a large-project performance estimate. The replay uses historical verification: the pilot's test assets had already been removed, so it does not establish current remote asset presence. No NASA downloads, Cloud transfers or EE mutations were performed for this Statistics release.

Desktop review checked the tile table, full-period map/plots, category navigation and loading a retained NASA search. Scientific processing and the existing guarded cleanup/Resume workflows were not changed. Statistics now calls the existing engine's accounting with its row limits disabled; Lite's coverage calculation requires full-scope evidence, and display refresh runs separately from workflow execution.

## v0.1.1 — Python 3.12.10 compatibility

Validated on Windows using a clean **64-bit CPython 3.12.10** installation and the actual PowerShell installer. All pinned dependencies installed; `pip check` and application imports passed. The full suite ran **818 tests: 813 passed, five skipped** (the same optional browser, symlink and in-process GDAL checks described below). GDAL subprocess tests used the existing separate Python 3.11 GDAL/NetCDF environment. Installer preservation tests also passed under the existing Python 3.11 app environment.

Additional checks exercised launcher discovery, explicit executable selection, fallback to `python` on PATH without the launcher, non-mutating checks, and refusal to replace an environment belonging to another interpreter. Read-only live service checks found seven preferred NASA originals for one UTM/date and confirmed bucket and EE collection access. No files were downloaded/uploaded and no assets were changed in this compatibility test. Workplace proxy policies remain a separate environment constraint.

## v0.1.0 — workflow acceptance

Validated on Windows on 26 November 2026. This is a small acceptance test, not continent-wide certification.

## Automated checks

The complete suite ran 814 tests: **809 passed, five skipped**. Three skipped checks exercise the inherited browser UI (not a Lite upload route), one requires Windows symlink privileges, and one requires the GDAL environment. The latter source-to-mosaic oracle was then run separately with the application's GDAL runtime setup and passed. It checks paired quality selection, older-version exclusion, Resume, and detection of an injected shift.

Independent review added tests for whole acquisition days, storage backpressure, interrupted Resume, manual object generation/checksum checks, lost responses, mixed-mode ownership, cleanup, incomplete years, unknown collection lineage and duplicate acquisitions. GUI tests cover settings persistence and frozen in-flight settings. The inherited engine suite covers metadata, catalogue history, cleanup and recovery.

Run the standard suite from this app's root:

```powershell
.\.venv\Scripts\python.exe -m tests --gdal-python 'C:\path\to\gdal\python.exe'
```

These tests do not launch a paid Cloud pilot. One-off scripts/data/reports are deliberately outside this repository.

## Small live pilot

One Lite project processed UTM35L for 20 and 21 September 2023: 12 preferred NASA originals and two native 100 m mosaics. It used the automatic route first, then extended the same project with prepare-only/manual import, then switched back to automatic Resume.

| Check | Result |
|---|---|
| Source selection | Fresh official dual-catalogue queries; exact cached NASA bytes and checksums |
| Local processing | Actual extraction and paired lowest-quality-code mosaicking |
| Cloud / EE | Actual object transfer/copy, ingestion, metadata and provenance verification |
| Native samples | 819,200 sampled cells, including 19,915 valid paired cells; zero elevation, quality or mask differences |
| Local cleanup | Raw, extracted, mosaic TIFF and sidecar files removed after required downstream evidence |
| Bucket cleanup | Owned staging copies and the manual source object absent after EE verification |
| Resume | No new upload request or object generation for completed work |
| Statistics | All 12 originals represented across the full two-date plan |
| Final test cleanup | Two final test images and temporary collection removed; production inventories unchanged |

The manual browser-transfer step was emulated by uploading an ordinary object without application metadata. The actual app then adopted it by checksum and generation, copied it server-side into its owned prefix, ingested it, and removed both copies. Workplace browser/proxy access was **not** tested. Cached originals mean this pilot did not measure fresh NASA download performance. Sampled pixel agreement is not full-image or source-science certification.

An initial pilot used separate project histories in one collection. Cleanup correctly refused to delete while another active asset had unknown lineage. That test asset was removed after evidence retention, and both routes were tested within one shared project. No cleanup safeguard was bypassed. Use a new empty collection for a new project; retain the original project/history when extending it.

## Remaining validation

### v0.2.0 selection interface

Full application suite on Python 3.11: **825 passed, five existing environment/opt-in skips** (830 total). No dependency or scientific-processing change was introduced.

The offline map was visually inspected with individual African tiles and the combined Africa/Europe selection (154 unique tiles). Focused regressions cover continent unions and explicit replacement, manual extras, Cancel/Apply, hemisphere selection, Norway/Svalbard special grid boundaries, country label coordinates, pan/zoom and aspect-fit margins. Project tests confirm that selection edits preserve histories and scientific/Cloud settings and cannot change an active worker's scope. All 16 focused tests passed. The app continues to use the existing catalogue plan and full-scope Statistics; the map represents selection, not ingestion coverage.

No new NASA downloads, Cloud transfers or EE asset changes are needed for map validation. Reference geometry and all preset tiles are bundled, so the selector works offline. The setup guide and app keep Python 3.11/3.12 support.

### Operational checks

- Test approved network/proxy access on the workplace computer.
- Compare practical transfer concurrency and inspect actual Cloud billing before large volumes.
- Increase geographic/time coverage gradually; keep periodic independent source and EE checks.
- Storage estimates are backpressure, not a hard disk quota. Oversized complete days require an explicit limit adjustment.
- Browser manual uploads are not subject to the app's staging cap and briefly coexist with an owned server-side copy.
