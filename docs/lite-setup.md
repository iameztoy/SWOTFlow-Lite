# SWOTFlow Lite v0.5.0 — setup and workflow

## First installation

Use a separate application folder and a separate data project. Run Setup_SWOTFlow_Lite.ps1 in PowerShell, then Start_SWOTFlow_Lite.cmd. The launcher console is also used for memory-only NASA sign-in. Select your GDAL environment's Python executable in Project. Do not delete your project databases/logs when cleaning raster files.

The application supports **64-bit Python 3.11 and 3.12**, including **3.12.10**. Tkinter and venv must be available in that Python installation. Setup preserves an existing supported app environment. On a fresh installation it checks `py -3.12`, then `py -3.11`, then `python` on PATH. It prints the version and executable selected.

From the extracted Lite application folder, run:

```powershell
.\Setup_SWOTFlow_Lite.ps1
.\Start_SWOTFlow_Lite.cmd
```

If several Python installations exist, or the Windows launcher does not find yours, specify your actual executable path:

```powershell
.\Setup_SWOTFlow_Lite.ps1 -PythonPath 'C:\path\to\Python312\python.exe'
```

Use `-CheckOnly` with either setup command to check without installing dependencies. Setup does not silently replace an existing `.venv` with a different interpreter. To switch interpreters, close Lite, extract the release into a fresh application folder, and run setup there; keep the external data project and its history. Do not copy `.venv` between computers. Follow your organisation's software and PowerShell execution policies.

**GDAL is separate:** Python 3.12 runs the interface, NASA catalogue/download and Cloud upload components. Extraction and mosaicking use the GDAL Python executable selected in Project; an existing validated GDAL environment on Python 3.11 can stay on 3.11. Do not point the GDAL field at a plain Python 3.12 installation without GDAL and the NetCDF driver. Setup does not alter that processing environment.

For Google project registration, billing, private Standard bucket permissions, disabled soft delete/versioning for disposable staging, and Application Default Credentials, follow [the Google Cloud setup guide](cloud-upload-setup.md), steps 1–7. ChromeDriver is not used. Browser proxy sign-in and Python API access are separate; test workplace policy/access before large transfers. If necessary, control ingestion from another approved network while manually uploading at work.

Choose an existing empty/pilot EE ImageCollection first. The app does not automatically create collections or modify bucket retention policies. A billing alert is not a hard spending cap. US multi-region replication and other location-dependent charges may apply even when objects are deleted quickly.

Use a **new empty collection for a new Lite project**. To extend an existing collection with more tiles or dates, reopen its original project and retain its databases/logs. Use automatic and manual upload routes within that same project. Separate projects sharing one collection do not share source history: an untracked asset may contain duplicate acquisitions, so the cleanup guard retains local mosaics until that history is resolved. Do not bypass the guard or delete production assets to clear it.

## Project and plan

1. New project: choose a separate data folder; all downloaded, extracted, mosaic, log and history paths are created under it.
2. Select UTM tiles, full acquisition date range, GDAL Python, Cloud project, bucket and EE ImageCollection ID. Use the comma-separated tile field, **Select on map…**, or check multiple continents and **Add checked continents**. **Use only checked continents** explicitly replaces the list. Leave **Mosaic grouping** at **Tile by tile (default)**, or choose the native zone/hemisphere option before the first plan.
3. Process: select Prepare locally or Fully automatic. Set complete-mosaic/source-byte batch targets, disk reserve and prepared-mosaic limit. Download network batches are a separate setting.
   Automatic mode can optionally prepare the next batch while recorded EE ingestions finish. Keep the unfinished-batch limit at 2 initially. Cloud transfers accept 1–16 workers; the independent ingestion and staging limits still apply. See [batch overlap and worker tuning](batch-overlap.md).
4. Authenticate NASA in the launch console. Credentials are not saved by Lite.
5. Catalogue / plan queries both official NASA catalogues and records every candidate and preferred-version selection. Review the expected batches. Refresh the plan when extending dates/tiles or reconciling publication changes.
6. Start / Resume reuses recorded work. Stop after current stage retains checkpoints; sudden shutdown also retains completed receipts. Changing workers/cleanup is supported on Resume; source/scientific/destination changes are not silently accepted.

## Selecting your tiles

The map opens from Project and works offline. Click a tile to toggle it; use the wheel or Zoom buttons, right-drag to pan, and Fit selection to frame the chosen grids. Country boundaries/names and tile labels can be toggled. Labels appear as you zoom in. **Add zone** selects all available latitude-band tiles in a numbered UTM zone, with North, South or Both hemispheres. Latitude-band letters are not hemisphere suffixes: for example, UTM36S is a northern tile.

Select several continent checkboxes before adding them. Overlapping presets are deduplicated. The checkboxes choose which presets to add; the tile field/map shows the actual selection, which can then be adjusted manually. Apply selection commits map edits to the field; Cancel discards them. Save settings persists the list. Open/New resets the preset checkboxes without changing the saved tile list.

The map is a longitude/latitude reference view, covering the UTM range from 80°S to 84°N. Country boundaries are low-resolution Natural Earth references, not authoritative administrative limits. Blue indicates selected scope only. A preset includes intersecting grid cells and may include areas without NASA acquisitions. Refresh **Catalogue / plan** after changing scope. Existing project history is retained, and active workers keep their original frozen settings. Selection does not change extraction, mosaicking, metadata, cleanup or Statistics rules.

## Optional native zone/hemisphere mosaics

In **Project → Mosaic grouping**, choose **Original projection / group UTM latitude bands by hemisphere** before running Catalogue / plan. All selected latitude-band tiles in the same numbered zone and hemisphere are collected together. A group/year is processed in bounded batches; a complete UTC start-date is never split to meet a size target. Different cycles and passes stay separate. Northern and southern inputs never share an output, and different UTM zones never share an output. No resampling or reprojection is added.

For example, selected UTM36N, UTM36P and UTM36Q inputs can produce one `UTM36N` mosaic for a date/cycle/pass; UTM36L and UTM36M can produce a separate `UTM36S` mosaic. This reuses the full application's naming convention. In an **output**, N/S indicates hemisphere; in an **original source filename**, the final letter is a latitude band (source UTM36S is north of the equator). Cloud metadata records the grouping mode and original source tiles; full filenames, versions, checksums and acquisition intervals stay in project history.

Grouping uses your selected area only. To request a complete zone, select all its bands using **Select on map → Add zone → North, South or Both**. NASA catalogue checks establish which preferred inputs are available. A complete catalogue/file set does not promise gap-free satellite coverage or valid data in every pixel.

Grouped mosaics work with both transfer routes. Extraction completes for all members before mosaicking, and extracted cleanup requires complete date/pass source membership. Raw cleanup retains its verified-extraction check; local mosaic cleanup still requires confirmed EE ingestion and matching provenance. Resume reuses the same local checkpoint when switching from Prepare locally to Fully automatic. Failed or incomplete outputs are retained. Larger grouped days may exceed the storage limit: increase it explicitly or choose a smaller area before planning; the app will not silently split that day.

Statistics retains the original tile/year/source counts and shows planned mosaic count, tile-by-tile count and the difference in asset count. One grouped asset may contribute to several tiles; it is one asset, not several uploads. Each tile must still satisfy its full requested date range before it is finished.

Choose grouping before the first plan. Existing planned projects retain their mode. New dates/unrelated groups can be added with a refreshed plan, but adding a band or changed source that alters an already-started mosaic is blocked. Such a change needs a reviewed replacement in a separate project/collection; this release does not silently overwrite or rebuild earlier grouped assets. The old plan and assets are kept intact.

## Process Zones: complete selected zones in bounded windows

Keep **Project** as the single source of area/date selection. Combine Europe and Africa, or choose individual bands manually. Select **Original projection / group UTM latitude bands by hemisphere** before the first plan, either in Project or with **Process Zones → Use zone/hemisphere grouping**. An existing tile-by-tile project must not be switched after planning: start a separate project/collection for that change.

**Process Zones** is a focused view of the same controller, not a second independent workflow. It shares the local/automatic transfer choice with Process. Worker counts, source-byte/mosaic limits, disk reserve and cleanup remain in **Process**; destinations and transfers remain in **Cloud**. Only one operation can run on a project. Editing controls never changes the active worker's frozen settings.

The queue takes the first selected numbered zone, finishes the entire requested period for one selected hemisphere, finishes its other selected hemisphere if present, then moves to the next numbered zone. It gathers all selected latitude bands in a group before producing its mosaics. Northern and southern outputs remain separate; grouping does not implicitly add omitted bands or fill genuine NASA nodata.

Choose a processing window:

- **Adaptive (existing size limits)** preserves the previous batching behavior and remains the default.
- **Half-month (1–15 / 16–end)** prevents a new batch from crossing a calendar half-month boundary. The second half can contain 16 days.
- **Calendar month** prevents a new batch from crossing a month boundary.

These are maximum preparation windows, not temporal aggregation. Each UTC acquisition-start date/cycle/pass still creates its own native 100 m mosaic, with paired elevation/quality and the existing version priority. Source-byte and mosaic-count limits can produce smaller batches inside any window. A complete date is never split merely to satisfy a size target. If even one whole day exceeds the source limit or estimated disk headroom, processing pauses explicitly; no incomplete mosaic is silently accepted.

For Africa and Europe, begin with half-month windows plus the existing byte/count limits, then adjust from actual disk use. A fixed month alone cannot guarantee a small disk footprint. Catalogue planning can inspect a whole group/year without downloading those rasters; only the next processing batch is downloaded. In Prepare locally, finished mosaics accumulate until imported and verified. In automatic mode, a verified batch can be cleaned before the next batch. Do not remove unuploaded mosaics to make space.

After changing a window or batch limits, run **Catalogue / plan zones** to apply them to unstarted work. Existing started, interrupted and completed batch IDs, scopes and checkpoints are retained; this may leave some earlier batches larger than the newly selected window. **Start / Resume zones** alone uses the saved queue. New NASA membership inside an already-started window requires explicit replacement review; the old plan remains intact if that check fails.

**Statistics → Tiles and dates → Zone / hemisphere coverage** summarizes each group over the entire requested period. **Processing batches** gives queue order, dates, window, preferred inputs and expected mosaics. Original tile/year counts, full filenames, version choices, checksums and source-to-mosaic lineage remain available. Local-ready is separate from verified EE completion. One grouped mosaic is counted once, even though it represents several original tiles.

## Fully automatic route

The app completes a bounded local batch, then transfers mosaics to the bucket. It starts EE ingestion for completed files while other files transfer, verifies the EE metadata and source revision, and removes exact owned staging copies. With local mosaic cleanup enabled, it removes the corresponding TIFFs and sidecars before proceeding. Failed copies remain recorded and protected. Another batch cannot start if retained files or estimated processing headroom exceed the configured disk limits.

Start with two Cloud transfers and two EE ingestions. You can configure 1 to 16 concurrent Cloud transfers. Throughput depends on your connection. The staging cap includes tracked reservations and failed retained copies. The app must be running for its verification/deletion work; already submitted EE tasks can continue while the computer is off. On return, Sync EE and Resume catch up.

## Manual browser upload route

1. Select Prepare locally and run the local batches. Local-ready is not EE-complete. Prepared-mosaic backpressure will pause further processing before files accumulate indefinitely.
2. Cloud → Prepare manual batch. The JSON plan is saved under the project's 00_logs/manual_batches folder. It lists exact filenames, expected sizes/checksums, source folder, asset IDs and metadata. The UI prints the exact bucket folder.
3. In Cloud Console, open that bucket and exact folder; use Upload files to select only the listed TIFFs from 03_mosaics. Do not rename them. Do not overwrite prior batches. Keep the project records on the controller; TIFFs alone are insufficient to reconstruct every original processing revision.
4. Select the plan and Import / Resume bucket batch. This can run while more browser uploads arrive. Unavailable files remain waiting. Existing completed uploads are matched by bytes/checksum, not names alone.
5. Import makes a generation-checked **server-side copy** into an app-owned revision path. This avoids an overwrite of the browser source changing the bytes EE ingests. No raster is uploaded again from your computer. It temporarily creates two billed copies and a copy request; default automatic transfer avoids this extra copy.
6. EE ingestion uses the same metadata manifest as automatic upload. Only after verification are the owned copy and exact manual original generation deleted. Replaced/unlisted files are retained. Local mosaic cleanup remains separately selected and uses the same evidence as automatic mode.
7. Use Sync EE / clean verified copies to catch up, including earlier manual batches. Import status JSON files are reports, not additional batch plans.

Browser uploads cannot be constrained by the app's staging cap. Upload manageable batches and leave the controller running so objects are ingested/deleted promptly. Do not run two controllers on the same project. Moving between computers requires the project folder/history and a valid ADC sign-in on the controller; personal resumable secrets are not part of project exports.

## Statistics and recovery

Open **Statistics** and choose a category with the first menu and a table with the second. **Tiles and dates → Finished and pending tiles** shows each selected tile across the entire saved project period. **Entire period by tile/year** shows what remains in each year. **Status map / plots** displays the same full-period status with reference boundaries and historical upload counts.

The other categories restore detailed engine accounting: exact download/extraction filenames, source-to-mosaic lineage, processing versions, mosaic membership/exclusions, uploaded assets and pending/errors, run/update history, disk/cleanup totals, and recorded local and Cloud cleanup timestamps. A saved running checkpoint is not proof that a worker is still running. Manual original and app-owned bucket copies are listed separately. Consolidation information is read-only and only appears if this installation has a replacement register; Lite does not run consolidations.

**NASA history → All catalogue searches** includes completed and interrupted searches. Select a row and click **Load NASA search** for its filenames, selected/excluded versions and download events. The NASA-versus-EE version view compares that saved search with retained EE lineage using the existing version priority; it is not a new NASA query or a spatial-gap measurement. Refresh **Catalogue / plan** to obtain newer NASA observations.

Tables support row filtering, vertical/horizontal scrolling, pages of 200 rows and full selected-row metadata. **Export all tables** writes JSON and CSVs for all loaded tables; **Export displayed table** exports every row in that table, not just the visible page or filtered subset. NASA candidate/event/version tables refer to the selected loaded search; all original searches remain in the project database.

Statistics refreshes on opening the project/tab and periodically while a workflow is active and Statistics is visible. Refresh reads local records in a separate thread and performs no remote transfer or deletion. A read error leaves the workflow running and is displayed for retry. Large histories may take longer to read; the small retained pilot needed about 0.1 seconds per refresh, not a continent-scale performance estimate.

A complete first year never makes later years complete. Every requested yearly catalogue window must be accounted for, with all preferred sources verified against matching provenance and a current, conflict-free EE inventory. Empty completed searches are marked no available acquisitions; missing searches require a new plan. A stale inventory (older than the existing 24-hour validity period) withholds a finished tile label without erasing historical counts. Extending the scope clears the old tile completion claim until Catalogue / plan is refreshed. A newer inventory that no longer contains an asset cannot count its old VERIFIED queue row as current coverage.

Local raw/extracted/mosaic files may disappear after safe cleanup while cumulative processing counts and filenames remain in history. Disk presence, source counts, processing-stage records and mosaic asset counts are different units. The map does not certify pixel coverage or the absence of source nodata. **Cloud → Sync EE / clean verified copies** refreshes remote evidence and runs the existing guarded cleanup; it is distinct from the read-only Statistics refresh.

Project source counts remain visible if another asset in the collection has unknown lineage. Statistics reports those unresolved collection assets separately and withholds collection completeness; **Sync EE** refreshes the inventory. This does not mean the project's already verified uploads failed.

On an error, retain the project and both pending raster copies. Read the stage log or manual batch status. Retry/Resume uses stable request IDs and already completed stages. Repeated upload failure does not prove source corruption. Source changes, stale/mismatched provenance or changed object generations require review rather than blind overwrite/deletion.

Local source/metadata verification is not a guarantee of pixel-level scientific correctness across the continent. The test report documents the small sample checked. Periodic independent source/EE checks remain useful.

## Costs

Use Billing → Reports, filter to the project and Cloud Storage, group by SKU. Costs typically arrive within a day but can take longer. Disabling soft delete affects future deletions; previously deleted copies keep their prior expiry. The app tracks bytes/states, not a guaranteed final invoice. Inspect the pilot bill before terabyte-scale work.

## Lossless mosaic compression

In **Process** or **Process Zones**, choose **Mosaic compression**. Both views share one setting. New projects use ZSTD; existing projects keep their saved setting (older projects without it remain uncompressed). DEFLATE is also available. All three options preserve values, quality codes, masks and native grids. The choice applies to newly created mosaics in both prepare-only and fully automatic workflows. Resume reuses already verified mosaics; it does not recompress or reupload them. See [compression details](mosaic-compression.md).
