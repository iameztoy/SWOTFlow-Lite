# Release history

## v0.4.1 — 27 November 2026

- Extend the existing zone/hemisphere workflow with a focused Process Zones tab, selected-band queue preview and optional half-month/calendar-month batch windows. Keep adaptive sizing and tile-by-tile processing as existing defaults.
- Complete each selected zone through its full date range, with hemispheres separate and adjacent in the queue. Byte/count limits may shorten windows; dates, cycles and passes remain distinct native 100 m mosaics.
- Preserve started/interrupted/completed batch IDs and checkpoints when refreshing scheduling limits. Rebatch only unstarted windows; refuse changed historical membership without replacing the saved plan.
- Add full-period zone/hemisphere Statistics and ordered batch details while retaining original tile/year/source accounting and shared Cloud/cleanup behavior.
- Clarify retained-mosaic storage pauses with retained size, configured cap and available disk space. Unuploaded mosaics remain protected.
- No new dependencies, Cloud services or routine pixel checks. Validation results are recorded in docs/lite-validation.md.

## v0.4.0 — 26 November 2026

- Add optional native UTM zone/hemisphere grouping in Project; tile-by-tile stays the default. Reuse the full engine's UTMxxN/UTMxxS naming, 100 m grids, separate UTC dates/cycles/passes and paired lowest-quality selection.
- Plan/query all contributing selected bands together before mosaicking. Keep whole-day batches, disk reserves, exact catalogue membership, guarded cleanup and durable interruption/Resume checkpoints, including switching from local preparation to automatic Cloud transfer.
- Attribute Statistics, upload filtering and source history to the actual original latitude bands, not the output hemisphere suffix. Show planned asset reduction; add grouped source-tile metadata to both Cloud routes.
- Reject silent grouping changes or additions that would alter already-started mosaics. Preserve existing plans/assets for explicit replacement review.
- Validate north/south real-GDAL fixtures against the original-source pixel oracle, interruption/resume and cleanup, plus planning, metadata, Cloud recovery and Statistics regressions. No live NASA download or Cloud/EE mutation is needed for these checks. See docs/lite-validation.md for counts and limits.

## v0.3.0 — 26 November 2026

- Restore full Statistics categories in Lite: tile/year completion, dates, processing versions, exact file histories, source lineage, mosaics, uploads, NASA searches, run/update history, storage and cleanup. Retain all table rows instead of the older preview caps.
- Add a full-period status map, completion/upload plots, search, pagination, horizontal/vertical scrolling, selected-row metadata, and full CSV/JSON export.
- Require every requested year and matching current EE evidence before marking a tile finished. Separate empty catalogue windows, pending work, stale verification and conflicting/unknown lineage. A new inventory can invalidate an old VERIFIED upload row without erasing cumulative processing history.
- Display saved NASA filename/version choices, download events and comparisons with loaded EE source lineage. Existing processing-version priority remains unchanged.
- Refresh Statistics in a separate thread, preserve workflow execution on display errors, and reject delayed results after a project/scope change. No new network requests or per-file processing checks are introduced.
- Preserve scientific processing, upload/cleanup behavior, Resume checkpoints and project schemas. The release adds information views; it does not migrate GeeUp projects or modify cloud assets.
- Validation: 842 tests passed with five existing optional/environment skips (847 total); all 17 focused Statistics checks passed after the final layout adjustment. Metadata-only replays of both retained pilot routes and desktop table/map checks passed. No live uploads or asset changes were performed.

## v0.2.0 — 26 November 2026

- Add an offline Project tile map with clickable UTM grids, zoom/pan, fit selection, country boundaries/names and tile labels.
- Combine multiple continent presets, preserving manual additions unless replacement is explicitly selected. Shared tiles are included once.
- Add whole-zone selection by northern/southern/both hemispheres; retain direct tile-name entry. All controls use the same saved project tile list.
- Keep active workflow settings frozen, preserve project history and require catalogue replanning for changed scope. Scientific processing, metadata, cleanup, Resume and Statistics contracts remain unchanged.
- Bundle public-domain Natural Earth reference boundaries with pinned source attribution; no browser, map service, extra dependency or network access is required to select tiles.
- Validation: 825 tests passed and five existing environment/opt-in skips; 16 focused map/project tests passed, with desktop visual checks of individual tiles and the combined Africa/Europe selection.

## v0.1.1 — 26 November 2026

- Support 64-bit Python 3.12, including 3.12.10, alongside Python 3.11 in the Windows setup script.
- Discover supported Python through the Windows launcher or PATH; allow an explicit `-PythonPath` and a non-mutating `-CheckOnly` check.
- Preserve existing app environments and reject incomplete or mismatched ones rather than silently rebuilding them. Check dependency consistency and app imports after installation.
- Clarify that the configured GDAL environment is independent and need not match the app's Python version. Source processing, project history, cleanup and metadata rules are unchanged.
- Validation on Python 3.12.10: clean installation, dependency/import checks, 813 passing tests and five skips, plus successful read-only NASA/Cloud/EE checks. Installer preservation checks also passed under Python 3.11.

## v0.1.0 — 26 November 2026

- Create independent SWOTFlow Lite, with Project, Process, Cloud and Statistics tabs and separate project/default files.
- Reuse the GeeUp v0.9.1 processing/verification engine, keeping native 100 m exact UTM grids, source priority, paired WSE/quality, NASA discovery/history and existing metadata contracts.
- Add catalogue-derived bounded batches with complete acquisition days, source-byte limits, free-disk reserve and prepared-mosaic backpressure.
- Support prepare-only/manual browser staging and fully automatic Cloud upload/ingestion/verification/cleanup, with separate transfer and ingestion concurrency.
- Adopt only explicit manual batch files after checksum/size/generation checks. Copy server-side into unique owned staging objects; protect unknown/replaced files and retain failures.
- Preserve Resume checkpoints, independent raw/extracted/local-mosaic/Cloud cleanup, full-plan Statistics and duplicate-acquisition detection.
- Add independent review regressions and two-route acceptance testing. Workplace browser/proxy behavior and continent-scale throughput remain environment-specific tests.
- Isolate per-user application state from GeeUp, and make all desktop launchers open Lite. Flag unknown collection lineage and cross-asset duplicate acquisitions without erasing this project's verified counts.
- Validation: 809 tests passed, five skipped; the GDAL source oracle also passed separately. Two live mosaics passed 819,200 sampled-cell checks, cleanup and Resume. See docs/lite-validation.md for scope and limitations.
