# SWOTFlow Lite v0.1.0 validation

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

- Test approved network/proxy access on the workplace computer.
- Compare practical transfer concurrency and inspect actual Cloud billing before large volumes.
- Increase geographic/time coverage gradually; keep periodic independent source and EE checks.
- Storage estimates are backpressure, not a hard disk quota. Oversized complete days require an explicit limit adjustment.
- Browser manual uploads are not subject to the app's staging cap and briefly coexist with an owned server-side copy.
