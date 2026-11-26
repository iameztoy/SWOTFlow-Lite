# Release history

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
