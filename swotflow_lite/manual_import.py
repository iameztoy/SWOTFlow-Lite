"""Import an explicitly planned browser-upload batch without local byte transfer.

Browser objects are copied server-side into unique, app-owned staging paths.
The ordinary Cloud manifest, provenance, EE verification and cleanup machinery
then handles those copies. Only the exact original generations selected by the
plan may be deleted, and only after verified EE ingestion and owned-copy cleanup.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable, Iterator
from urllib.parse import quote
import uuid

from swotflow.earthengine.cloud.journal import utc
from swotflow.earthengine.cloud.transport import CloudHTTPError
from swotflow.earthengine.cloud.worker import CloudUploader
from swotflow.project.lock import _operation_lock
from swotflow.verification.download import assert_project_not_reset
from swotflow.verification.pipeline import digest

PLAN_VERSION = 1
WAITING = "WAITING_FOR_BROWSER_UPLOAD"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically replace a non-secret JSON checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(payload, stream, indent=2)
        stream.flush()
        import os
        os.fsync(stream.fileno())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _upload_lock(worker: CloudUploader) -> Iterator[None]:
    """Use the same cross-process lock as ordinary Cloud/browser uploads."""
    logs = worker.config.artifacts.report_csv.parent
    assert_project_not_reset(logs)
    with _operation_lock(logs / ".upload.lock", "Another upload/sync worker is using this project."):
        try:
            yield
        finally:
            worker.report.write()


def _entry(row: dict[str, Any]) -> dict[str, Any]:
    """Return immutable plan identity independently of transient queue state."""
    source = row["manual_import"]
    return {"asset_id": row["asset_id"], "filename": source["filename"],
            "source_bucket": source["bucket"], "source_object": source["object"],
            "owned_object": row["object"], "size": row["size"], "md5": row["md5"],
            "sha256": row["sha256"], "receipt": deepcopy(row["receipt"]),
            "manifest": deepcopy(row["manifest"])}


def _load_plan(worker: CloudUploader, plan_path: Path) -> dict[str, Any]:
    """Reject edited, foreign or orphaned plans instead of trusting filenames."""
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    if (plan.get("schema_version") != PLAN_VERSION or plan.get("owner") != worker.owner
            or plan.get("collection") != worker.config.destination_parent
            or plan.get("bucket") != worker.cloud.bucket):
        raise ValueError("Manual batch belongs to another project, bucket or collection.")
    files = plan.get("files")
    if not isinstance(files, list) or not files or len({r.get("asset_id") for r in files}) != len(files):
        raise ValueError("Manual batch is empty or has duplicate asset identities.")
    if digest(files) != plan.get("files_digest"):
        raise ValueError("Manual batch content changed; prepare a fresh reviewed plan.")
    for entry in files:
        if entry.get("source_object") != f"{plan.get('source_prefix')}/{entry.get('filename')}":
            raise ValueError("Manual source folder differs from its planned file paths.")
        row = worker.journal.get(entry["asset_id"])
        if (not row or row.get("manual_import", {}).get("batch_id") != plan["batch_id"]
                or _entry(row) != entry):
            raise ValueError("Manual batch does not match the project's retained provenance journal.")
    return plan


def prepare_manual_batch(worker: CloudUploader, plan_path: Path, source_prefix: str, *, limit: int = 50) -> dict[str, Any]:
    """Export a verified batch and reserve its records, without remote writes.

    Args:
        worker: Ordinary CloudUploader configured for the project and destination.
        plan_path: New JSON path, normally inside the project's logs directory.
        source_prefix: Dedicated bucket folder to which the user uploads TIFFs.
        limit: Maximum number of complete local mosaics selected for this batch.

    Returns:
        The durable plan. Reopening the same plan preserves its original members.
    """
    prefix = source_prefix.strip().strip("/")
    if (not prefix or not re.fullmatch(r"[A-Za-z0-9/_-]+", prefix)
            or any(part in {"", ".", ".."} for part in prefix.split("/"))):
        raise ValueError("Choose a dedicated, nonempty manual-upload batch prefix.")
    if prefix == worker.cloud.prefix or prefix.startswith(worker.cloud.prefix + "/"):
        raise ValueError("Manual source folder must be separate from app-owned staging.")
    if type(limit) is not int or not 1 <= limit <= 10000:
        raise ValueError("Manual batch size must be between 1 and 10000 mosaics.")
    path = Path(plan_path)
    with _upload_lock(worker):
        assigned = [r for r in worker.rows() if r.get("manual_import", {}).get("plan_path") == str(path.resolve())]
        if assigned:
            batch_ids = {r["manual_import"]["batch_id"] for r in assigned}
            if len(batch_ids) != 1:
                raise ValueError("Several manual batches own this plan path; review required.")
            if any(r["manual_import"]["object"] != f"{prefix}/{r['manual_import']['filename']}" for r in assigned):
                raise ValueError("Retained manual batch uses another source prefix.")
            # Recover a crash between the journal commit and portable JSON write.
            recovered = {"schema_version": PLAN_VERSION, "batch_id": next(iter(batch_ids)), "owner": worker.owner,
                         "collection": worker.config.destination_parent, "bucket": worker.cloud.bucket,
                         "source_prefix": prefix, "created_at": assigned[0]["created_at"],
                         "files": [_entry(r) for r in assigned]}
            recovered["files_digest"] = digest(recovered["files"])
            if path.exists():
                existing = _load_plan(worker, path)
                if any(e not in recovered["files"] for e in existing["files"]):
                    raise ValueError("Manual plan differs from its assigned journal rows.")
            _write_json(path, recovered)
            return recovered
        if path.exists():
            return _load_plan(worker, path)
        items = worker.build_upload_plan()
        selected = []
        filenames: set[str] = set()
        for item in items:
            previous = worker.journal.get(item.asset_id)
            if previous and previous.get("manual_import"):
                continue  # Never reassign another manual batch, including pending ones.
            if previous and previous["state"] not in {"VERIFIED"}:
                raise ValueError("An automatic upload already owns a selected mosaic; reconcile it before manual preparation.")
            if previous and previous["state"] == "VERIFIED":
                continue
            if item.local_file.name in filenames:
                raise ValueError("Duplicate local basenames would collide in the manual batch folder.")
            filenames.add(item.local_file.name)
            selected.append(item)
            if len(selected) == limit:
                break
        if not selected:
            raise ValueError("No unassigned verified local mosaics are ready for manual upload.")
        batch_id = uuid.uuid4().hex
        plan = {"schema_version": PLAN_VERSION, "batch_id": batch_id, "owner": worker.owner,
                "collection": worker.config.destination_parent, "bucket": worker.cloud.bucket,
                "source_prefix": prefix, "created_at": utc(), "files": []}
        for item in selected:
            original_save = worker.save
            def save_tagged(row: dict[str, Any]) -> None:
                """Persist manual ownership in the very first queue commit."""
                row["manual_import"] = {"batch_id": batch_id, "bucket": worker.cloud.bucket,
                                        "object": f"{prefix}/{item.local_file.name}",
                                        "filename": item.local_file.name, "plan_path": str(path.resolve()), "status": WAITING}
                original_save(row)
            worker.save = save_tagged
            try:
                row = worker.prepare(item)
            finally:
                worker.save = original_save
            plan["files"].append(_entry(row))
            plan["files_digest"] = digest(plan["files"])
            _write_json(path, plan)  # Assigned rows recover the JSON if interrupted here.
        return plan


class ManualObjectTransport:
    """Generation-guarded GCS server-side copies and original-object cleanup."""

    def __init__(self, worker: CloudUploader) -> None:
        self.worker = worker
        self.transport = worker.transport
        self.deadline = float("inf")

    def source_object(self, row: dict[str, Any]) -> dict[str, Any] | None:
        """Read one exact planned object, never enumerate arbitrary bucket data."""
        return self.transport.object(row["manual_import"])

    def copy_to_owned(self, row: dict[str, Any], checkpoint: Callable[[], None]) -> dict[str, Any]:
        """Rewrite an exact source generation into a new app-owned object."""
        source = row["manual_import"]
        url = (f"https://storage.googleapis.com/storage/v1/b/{quote(source['bucket'], safe='')}/o/"
               f"{quote(source['object'], safe='')}/rewriteTo/b/{quote(row['bucket'], safe='')}/o/"
               f"{quote(row['object'], safe='')}")
        while True:
            if time.monotonic() >= self.deadline:
                raise TimeoutError("Cloud copy checkpoint retained at monitor deadline.")
            params = {"ifSourceGenerationMatch": source["generation"], "ifGenerationMatch": "0"}
            if source.get("rewrite_token"):
                params["rewriteToken"] = source["rewrite_token"]
            response = self.transport.request("POST", url, action="Adopt manually uploaded mosaic", params=params,
                json={"contentType": "image/tiff", "metadata": {"swotflow_owner": row["owner"], "sha256": row["sha256"]}})
            if response.status_code != 200:
                if response.status_code in {400, 410} and source.pop("rewrite_token", None):
                    checkpoint()  # Resume may restart only this generation-bound copy.
                raise CloudHTTPError("Adopt manually uploaded mosaic", response.status_code)
            result = response.json()
            if result.get("done"):
                source.pop("rewrite_token", None)
                checkpoint()
                return result["resource"]
            token = result.get("rewriteToken")
            if not token:
                raise ValueError("Cloud copy returned no rewrite checkpoint.")
            source["rewrite_token"] = token
            checkpoint()

    def delete_source(self, row: dict[str, Any]) -> None:
        """Delete only the accepted original generation after final verification."""
        source = row["manual_import"]
        url = self.transport.object_url(source)
        response = self.transport.request("DELETE", url, action="Remove verified manual source",
                                          params={"ifGenerationMatch": source["generation"]})
        if response.status_code not in {204, 404}:
            raise CloudHTTPError("Remove verified manual source", response.status_code)


def _check_source(row: dict[str, Any], obj: dict[str, Any]) -> str:
    """Require finalized matching bytes and a stable original generation."""
    source = row["manual_import"]
    if (int(obj.get("size", -1)) != row["size"] or obj.get("md5Hash") != row["md5"]
            or not obj.get("generation")):
        raise ValueError("Manual source size/checksum is missing or differs; nothing is copied or deleted.")
    generation = str(obj["generation"])
    if source.get("generation") and source["generation"] != generation:
        raise ValueError("Manual source was overwritten after adoption; retain it for review.")
    return generation


@contextmanager
def _batch_rows(worker: CloudUploader, assets: set[str]) -> Iterator[None]:
    """Limit ordinary reconciliation to this explicit manual batch."""
    original = worker.rows
    worker.rows = lambda pending_only=False: [r for r in original(pending_only=pending_only) if r["asset_id"] in assets]
    try:
        yield
    finally:
        worker.rows = original


def manual_batch_status(worker: CloudUploader, plan: dict[str, Any]) -> dict[str, Any]:
    """Separate ready/uploaded/verified/cleaned state and both physical copies."""
    rows = [worker.journal.get(entry["asset_id"]) for entry in plan["files"]]
    return {"planned": len(rows),
            "waiting": sum(r["state"] == "PREPARED" and not r["manual_import"].get("generation") for r in rows),
            "ingesting": sum(r["state"] in {"SUBMITTING", "INGESTING"} for r in rows),
            "verified": sum(r["state"] == "VERIFIED" for r in rows),
            "failed_or_blocked": sum(r["state"] in {"FAILED", "BLOCKED"} for r in rows),
            "owned_copies_removed": sum(bool(r.get("deleted_at")) for r in rows),
            "manual_sources_removed": sum(bool(r["manual_import"].get("deleted_at")) for r in rows),
            "manual_source_bytes": sum(r["size"] for r in rows if r["manual_import"].get("generation") and not r["manual_import"].get("deleted_at")),
            "owned_staging_bytes": sum(r["size"] for r in rows if r.get("generation") and not r.get("deleted_at")),
            "complete": all(r["state"] == "VERIFIED" for r in rows),
            "cleanup_complete": all(r.get("deleted_at") and r["manual_import"].get("deleted_at") for r in rows),
            "details": [{"asset_id": r["asset_id"], "state": r["state"], "manual": deepcopy(r["manual_import"]),
                         "error": r.get("error", ""), "cleanup_error": r.get("cleanup_error", "")} for r in rows]}


def _cleanup_manual_source(worker: CloudUploader, row: dict[str, Any], adapter: Any) -> None:
    """Recheck EE immediately before deleting the exact accepted original."""
    if row["state"] != "VERIFIED":
        return
    worker.cleanup(row)
    source = row["manual_import"]
    if not row.get("deleted_at") or source.get("deleted_at"):
        return
    try:
        asset = worker.transport.asset(row["asset_id"])
        if not asset:
            raise ValueError("Verified EE asset is no longer present; retain original source.")
        worker.validate_asset(row, asset)
    except ValueError as exc:
        row.update(state="BLOCKED", error=str(exc))
        source["cleanup_error"] = str(exc)
        worker.save(row)
        return
    except Exception as exc:
        source["cleanup_error"] = f"EE recheck unavailable ({type(exc).__name__}); original copy retained."
        worker.save(row)
        return
    try:
        if not source.get("generation"):
            raise ValueError("No accepted original generation is recorded; retain original copy.")
        obj = adapter.source_object(row)
        if obj is not None:
            _check_source(row, obj)
            adapter.delete_source(row)
        source.update(deleted_at=utc(), cleanup_error="", status="REMOVED")
    except ValueError as exc:
        source["cleanup_error"] = str(exc)
    except Exception as exc:
        source["cleanup_error"] = f"Original cleanup deferred ({type(exc).__name__}); exact copy retained for retry."
    worker.save(row)


def _check_owned_copies(worker: CloudUploader, assets: set[str]) -> None:
    """Reject replaced/missing owned objects before metadata can promote an asset."""
    for asset in assets:
        row = worker.journal.get(asset)
        if row.get("generation") and not row.get("deleted_at") and row["state"] not in {"BLOCKED", "FAILED"}:
            obj = worker.transport.object(row)
            try:
                if obj is None:
                    raise ValueError("App-owned staged copy disappeared before verification; retained for review.")
                worker.transport.check_object(row, obj)
            except ValueError as exc:
                row.update(state="BLOCKED", error=str(exc)); worker.save(row)


def sync_manual_batches(worker: CloudUploader, plan_paths: list[Path], *, object_transport: Any = None) -> list[dict[str, Any]]:
    """Reconcile existing manual tasks and cleanup; never copy, upload or submit."""
    with _upload_lock(worker):
        plans = [_load_plan(worker, Path(path)) for path in plan_paths]
        if not plans:
            return []
        if worker.config.execution.dry_run:
            return [{**manual_batch_status(worker, plan), "dry_run": True} for plan in plans]
        worker.connect()
        adapter = object_transport or ManualObjectTransport(worker)
        assets = {entry["asset_id"] for plan in plans for entry in plan["files"]}
        _check_owned_copies(worker, assets)
        with _batch_rows(worker, assets):
            worker.reconcile()
        for asset in assets:
            row = worker.journal.get(asset)
            _cleanup_manual_source(worker, row, adapter)
        worker.sync_earth_engine_inventory()
        results = []
        for path, plan in zip(plan_paths, plans):
            result = manual_batch_status(worker, plan)
            _write_json(Path(path).with_suffix(".status.json"), result)
            results.append(result)
        return results


def import_manual_batch(worker: CloudUploader, plan_path: Path, *, wait_for_ee: bool = True,
                        stop_event: Any = None, object_transport: Any = None) -> dict[str, Any]:
    """Adopt planned uploads, ingest with unchanged metadata, then clean safely.

    Missing browser uploads are WAITING, not failures. With wait_for_ee=False one
    bounded scan is made; callers may invoke it again while browser uploads run.
    With True, poll until complete, a user stop, or the existing monitor deadline.
    No local raster byte upload is performed in either mode.
    """
    with _upload_lock(worker):
        plan = _load_plan(worker, Path(plan_path))
        if worker.config.execution.dry_run:
            return {**manual_batch_status(worker, plan), "dry_run": True}
        worker.connect()
        worker.transport.bucket_info()
        adapter = object_transport or ManualObjectTransport(worker)
        deadline = time.monotonic() + worker.config.execution.wait_timeout_minutes * 60
        if isinstance(adapter, ManualObjectTransport):
            adapter.deadline = deadline
        limit = worker.config.upload.max_active_ingestions or 2
        assets = {entry["asset_id"] for entry in plan["files"]}
        attempts: dict[str, int] = {}
        halted = False
        # Only a definite failed remote task permits a new request on explicit Resume.
        for asset in assets:
            row = worker.journal.get(asset)
            if row["state"] == "FAILED" and row.get("operation"):
                operation = worker.transport.operation(row["operation"])
                if operation.get("done") and operation.get("error"):
                    row.update(state="STAGED", request_id=uuid.uuid4().hex, operation="", error="", submitted_at="")
                    worker.save(row)
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            _check_owned_copies(worker, assets)
            with _batch_rows(worker, assets):
                worker.reconcile()
            active = sum(r["state"] in {"SUBMITTING", "INGESTING"} for r in worker.rows(pending_only=True))
            for asset in sorted(assets):
                row = worker.journal.get(asset)
                source = row["manual_import"]
                if row["state"] == "VERIFIED":
                    _cleanup_manual_source(worker, row, adapter)
                    continue
                if row["state"] in {"FAILED", "BLOCKED"} or attempts.get(asset, 0) >= worker.config.upload.retry_attempts:
                    continue
                try:
                    if row["state"] == "PREPARED":
                        owned = worker.transport.object(row)
                        if owned is not None:
                            if not source.get("generation"):
                                raise ValueError("Owned copy has no saved manual-source generation; review required.")
                            generation = worker.transport.check_object(row, owned)
                        else:
                            obj = adapter.source_object(row)
                            if obj is None:
                                source["status"] = WAITING
                                worker.save(row)
                                continue
                            source["generation"] = _check_source(row, obj)
                            source.update(status="COPY_PENDING", observed_at=utc())
                            worker.save(row)  # Durable intent before server-side copy.
                            owned_bytes = sum(r["size"] for r in worker.rows()
                                if r["asset_id"] != asset and not r.get("deleted_at") and
                                (r.get("generation") or (not r.get("manual_import") and r["state"] in {"PREPARED", "TRANSFERRING"})
                                 or r.get("manual_import", {}).get("status") == "COPY_PENDING"))
                            if owned_bytes + row["size"] > worker.cloud.staging_limit_gib * 2**30:
                                source["status"] = "WAITING_FOR_STAGING_SPACE"; worker.save(row)
                                continue
                            copied = adapter.copy_to_owned(row, lambda: worker.save(row))
                            generation = worker.transport.check_object(row, copied)
                        source.update(status="COPIED", copied_at=utc())
                        row.update(state="STAGED", generation=generation, staged_at=utc(), error="")
                        worker.save(row)
                    if row["state"] in {"STAGED", "SUBMITTING"} and (row["state"] == "SUBMITTING" or active < limit):
                        already_active = row["state"] == "SUBMITTING"
                        worker.advance(row)
                        if not already_active and row["state"] in {"SUBMITTING", "INGESTING"}:
                            active += 1
                except ValueError as exc:
                    row.update(state="BLOCKED", error=str(exc)); worker.save(row)
                    halted = worker.config.upload.fail_fast
                except Exception as exc:
                    attempts[asset] = attempts.get(asset, 0) + 1
                    row["error"] = f"Manual import interrupted ({type(exc).__name__}); saved source/copy/request retained for Resume."
                    worker.save(row)
                    if worker.config.upload.fail_fast:
                        halted = True
                        break
                if halted:
                    break
            status = manual_batch_status(worker, plan)
            _write_json(Path(plan_path).with_suffix(".status.json"), status)
            if (halted or not wait_for_ee or status["complete"] or time.monotonic() >= deadline
                    or status["failed_or_blocked"] == status["planned"]):
                break
            if not any(worker.journal.get(a)["state"] in {"PREPARED", "STAGED", "SUBMITTING", "INGESTING"}
                       and attempts.get(a, 0) < worker.config.upload.retry_attempts for a in assets):
                break
            time.sleep(max(0.05, min(worker.config.execution.task_poll_seconds, 5)))
        worker.sync_earth_engine_inventory()
        result = manual_batch_status(worker, plan)
        _write_json(Path(plan_path).with_suffix(".status.json"), result)
        return result
