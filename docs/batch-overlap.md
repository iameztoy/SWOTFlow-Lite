# Batch overlap and worker tuning — v0.5.1

In **Process**, select **Fully automatic** and optionally enable **Prepare the next batch while EE ingests the previous one**. The same controls apply to tile and zone/hemisphere grouping. The unfinished-batch limit appears when overlap is enabled. Existing projects default to sequential behavior. Manual preparation ignores this option.

One local batch is prepared at a time. Once its Cloud transfers have finished and ingestion task IDs are durably recorded, the app can prepare the next batch while EE works remotely. This overlaps remote ingestion with local preparation; it does not run two independent project controllers or start the next batch while the previous batch is still transferring bytes.

**Maximum unfinished ingestion batches** defaults to 2 (range 1–8). This is separate from **Maximum active EE ingestions** and **Concurrent Cloud transfers**. The uploader may need to wait for earlier ingestions within a large batch to respect the EE limit. The benefit therefore depends on batch size, available work and ingestion time; no fixed speedup is promised.

Before preparing more data, the scheduler polls saved operations, cleans verified copies, and enforces the unfinished-batch cap. If local storage is tight, it waits for recorded ingestions and attempts guarded cleanup before pausing. Existing complete-day/source-byte limits, free-space reserve, prepared-mosaic cap and staging-byte cap remain in effect. A single oversized file is never silently allowed past the bucket cap.

At the end, the app verifies the remaining tasks. Stop or a monitoring timeout retains pending files, task IDs and exact source checksums. Resume reconciles those tasks before deciding whether any work needs replay. Failed/uncertain ingestion is not proof of corrupt source data and is not successful completion. It remains visible for review and recovery. Statistics keeps the full requested period incomplete until every expected source has matching EE evidence.

Cloud copies are checked/deleted during upload and between local batches. If ingestion finishes during a long local processing stage, deletion can wait until that stage/batch yields control. This mode does not promise instant bucket deletion, nor does it raise the staging cap or enable paid services. Local mosaics still require confirmed ingestion and matching provenance; no routine full pixel comparison is added.

## Worker controls

| Control | What it means | How to tune |
|---|---|---|
| Parallel downloads | Concurrent NASA file downloads inside a network batch | 30 is supported; begin with 8–16 and compare throughput/errors before raising it. |
| NASA network batch size | Number of files handed to one download call | 50 files does not mean 50 simultaneous transfers. Keep this at least as large as the desired download concurrency when enough files are available. |
| Extraction workers | Separate processes extracting independent originals | Four is supported; increase only with enough RAM, CPU and disk throughput. |
| Mosaic workers | Separate processes building independent date/cycle/pass/grid mosaics | Four is supported when four groups are ready. One mosaic still uses one worker; a batch with only one group cannot use four. |
| Concurrent Cloud transfers | Files being sent to the bucket at once; 1–16 | Try 4, then 8. Use 16 only if measured throughput improves without retries, RAM/disk pressure or exceeding the selected staging budget. |
| Maximum active EE ingestions | Outstanding ingestions admitted by the app | Independent of transfers; keep the current setting until measured server behavior supports increasing it. The server may queue admitted tasks. |
| Maximum unfinished ingestion batches | Batches allowed to remain unfinished across local preparation | Two is a conservative starting point; additional batches retain more work and require more storage. |

More workers divide shared bandwidth and resources; they do not multiply them. Available files, groups and byte limits can reduce actual concurrency below a selected ceiling. Download, extraction and mosaicking remain staged within one local batch, so their worker counts are not all active simultaneously. Lossless mosaic compression uses one codec thread per worker to avoid nested compression oversubscription.

Change worker/overlap settings between runs, then Resume. These are scheduling settings, not scientific settings, so they do not trigger reprocessing of valid receipts. Keep project records and all unverified data. Do not replace application files underneath a running job.

Validation includes deterministic two-batch scheduling, pending/failed task recovery, interruption/Resume, Statistics, guarded cleanup and concurrent-transfer tests. Network transports are simulated in regression tests; those tests establish behavior, not real-world speed or Cloud billing. Measure throughput on the intended machine before adopting high worker counts for continental production.
