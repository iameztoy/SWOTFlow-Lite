# Release history

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
