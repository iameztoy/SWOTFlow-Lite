"""Bounded batches around the unchanged, verified processing engine."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import threading
from typing import Callable

import yaml
from swotflow.processing import automation as engine
from swotflow.project.lock import automation_lock
from swotflow.earthengine.cloud.journal import read_rows
from swotflow_lite.planner import science_identity
from swotflow_lite.project import validate, write_json, lite_lock
from swotflow_lite.grouping import HEMISPHERE


def cloud_rows(project: object) -> list[dict]:
    """Read only this project's chosen collection; pending is never completed."""
    return [r for r in read_rows(project.root/"00_logs/cloud_uploads.sqlite3")
            if r["collection"] == project.config["destination_parent"]]


def verified_sources(project: object) -> dict[str, dict]:
    """Return source checksums from the last proven EE ingestion observations."""
    return verified_source_evidence(project)[0]


def verified_source_evidence(project: object) -> tuple[dict[str, dict], list[dict]]:
    """Reject duplicate acquisition ownership instead of hiding it in a dictionary."""
    from swotflow.core.metadata import product_identity_key
    represented: dict[str, dict] = {}
    owners: dict[str, list] = {}
    for row in cloud_rows(project):
        if row["state"] == "VERIFIED":
            for name, checksum in row["receipt"]["sources"].items():
                key = product_identity_key(name) or name
                owners.setdefault(key, []).append((name, checksum, row["asset_id"]))
    conflicts = []
    for key, entries in owners.items():
        if len({(name, asset) for name, _, asset in entries}) != 1:
            conflicts.append({"acquisition": key, "sources": sorted({x[0] for x in entries}),
                              "assets": sorted({x[2] for x in entries})})
        else:
            represented[entries[0][0]] = entries[0][1]
    return represented, conflicts


def completed_local_checkpoint(folder: Path) -> bool:
    """Permit recovery uploads/cleanup without reserving a second local replay."""
    path = folder/"automation_run.json"
    if not path.is_file():
        return False
    state = engine.load_automation_run_state(path)
    mosaics = [r for r in state.stage_results if r.stage == "mosaic"]
    return bool(mosaics and mosaics[-1].status in {"success", "skipped"})


def batch_verified(batch: dict, represented: dict) -> bool:
    """Require every preferred source and its exact NASA checksum."""
    return bool(batch["expected"]) and all(represented.get(k) == v for k, v in batch["expected"].items())


def storage_problem(project: object, batch: dict) -> str:
    """Apply between-batch headroom and retained-mosaic backpressure.

    The expansion allowance is conservative scheduling guidance, not a hard
    per-file filesystem quota; the engine also checks reserve between stages.
    """
    limits = project.config["lite"]
    retained = sum(p.stat().st_size for p in (project.root/"03_mosaics").rglob("*") if p.is_file())
    if retained >= float(limits["max_prepared_gib"]) * 2**30:
        return (f"Prepared-mosaic storage limit reached: {retained/2**30:.1f} GiB retained; "
                f"configured limit {float(limits['max_prepared_gib']):.1f} GiB; "
                f"{shutil.disk_usage(project.root).free/2**30:.1f} GiB free on disk. "
                "This is a retained-mosaic cap, not a full disk. Raise it in Process and Resume, "
                "or import/verify in EE before guarded cleanup. Keep unuploaded mosaics.")
    if batch["source_bytes"] > float(limits["batch_source_gib"]) * 2**30:
        return "One complete acquisition day exceeds the source-byte batch limit. Increase that limit explicitly; its inputs will not be split."
    free = shutil.disk_usage(project.root).free
    # NetCDF compression varies. Also allocate a raster allowance per original
    # and per mosaic, instead of treating compressed source bytes as TIFF size.
    allowance = max(batch["source_bytes"] * 6,
                    (len(batch["expected"]) + batch["groups"]) * 512 * 2**20)
    required = float(limits["min_free_gib"]) * 2**30 + allowance
    if free < required:
        return f"Insufficient estimated processing headroom: {free/2**30:.1f} GiB free; {required/2**30:.1f} GiB reserve plus allowance required. Free space, reduce batch size and re-plan, or adjust limits."
    return ""


def cloud_config_path(project: object) -> Path:
    """Keep worker settings inside the data project, never in the application."""
    base = deepcopy(project.config)
    base["upload"].update(backend="gcs", scope="all", ee_sync_before_upload=True)
    base["execution"].update(dry_run=False, require_confirmation=False, resume=True)
    # Cloud sync must include earlier batches and newly completed ingestions.
    for section in ("processing", "download"):
        for key in ("acquisition_start_date", "acquisition_end_date"):
            base.get(section, {}).pop(key, None)
    path = project.root/"00_logs/lite_cloud.yaml"
    path.write_text(yaml.safe_dump(base, sort_keys=False), encoding="utf-8")
    return path


def make_cloud_worker(project: object) -> object:
    """Use the same uploader metadata, provenance and report builder."""
    from swotflow.earthengine.uploader import load_config_file, configure_logging
    from swotflow.earthengine.cloud.worker import CloudUploader
    config = load_config_file(cloud_config_path(project))
    return CloudUploader(config, configure_logging(config, False), assume_yes=True)


def sync_and_cleanup(project: object, progress: Callable[[str], None] = lambda _: None) -> None:
    """Refresh existing EE evidence, then use the established local cleanup guard."""
    from swotflow.earthengine.uploader import main
    with automation_lock(project.root):
        from swotflow_lite.manual_import import sync_manual_batches
        plans = sorted(p for p in (project.root/"00_logs/manual_batches").glob("*.json") if not p.name.endswith(".status.json"))
        if plans:
            worker = make_cloud_worker(project)
            try:
                sync_manual_batches(worker, plans)
            finally:
                worker.report.write()
        result = main(["--config", str(cloud_config_path(project)), "--sync-only", "--yes"])
        if result:
            raise RuntimeError("EE sync did not complete; retained files remain protected.")
        if project.config["lite"]["cleanup_mosaics"]:
            config = deepcopy(project.config)
            config.setdefault("cleanup", {}).update(mosaics_enabled=True, mosaic_policy="confirmed_ingestion")
            for section in ("processing", "download"):
                for key in ("acquisition_start_date", "acquisition_end_date"):
                    config.get(section, {}).pop(key, None)
            count, size, errors = engine.cleanup_stage(config, "", "mosaic")
            progress(f"Verified local cleanup: {count} files; {size/2**30:.3f} GiB. {len(errors)} retained cleanup errors.")
            if errors:
                progress("; ".join(errors[:3]))


def run(project: object, stop: threading.Event, progress: Callable[[str], None] = lambda _: None) -> dict:
    """Resume batches while preserving the existing per-stage durable checkpoints."""
    config = project.config
    validate(config, cloud=config["lite"]["mode"] == "automatic")
    path = project.root/"00_logs/lite_plan.json"
    if not path.exists():
        raise ValueError("Run Catalogue / plan first.")
    plan = json.loads(path.read_text(encoding="utf-8"))
    current_scope = {"tiles": list(config["download"]["utm_tiles"]),
                     "start": config["download"]["start_date"], "end": config["download"]["end_date"]}
    if plan["science"] != science_identity(config) or plan["scope"] != current_scope:
        raise ValueError("Scope/scientific settings changed. Refresh the plan before Resume.")
    automatic = config["lite"]["mode"] == "automatic"
    # A project-wide Lite lock prevents a second controller changing batch state.
    with lite_lock(project.root):
        if automatic:
            sync_and_cleanup(project, progress)
        for batch_number, batch in enumerate(plan["batches"], 1):
            if stop.is_set():
                progress("Stopped between batches; Resume preserves completed stages.")
                break
            represented = verified_sources(project)
            if batch_verified(batch, represented):
                batch.update(state="ee_verified", detail="All preferred sources have matching confirmed EE provenance.")
                write_json(path, plan)
                continue
            if batch["state"] == "locally_ready" and not automatic:
                continue
            mode = "automatic" if automatic else "prepare"
            folder = project.root/"00_logs/lite_runs"/batch["id"]/mode
            if config['mosaic'].get('grouping_mode') == HEMISPHERE:
                # Switching manual/automatic transfer must retain the same local
                # prefix, including proof for already-cleaned originals/extracts.
                folder = project.root/'00_logs/lite_runs'/batch['id']/'grouped'
            recovery_ready = batch["state"] == "locally_ready" or completed_local_checkpoint(folder)
            problem = "" if recovery_ready else storage_problem(project, batch)
            if problem:
                batch.update(state="storage_pause", detail=problem)
                write_json(path, plan); progress(problem); break
            base = deepcopy(config)
            for section in ("processing", "download"):
                base.setdefault(section, {}).update(acquisition_start_date=batch["start"], acquisition_end_date=batch["end"])
            base["download"].update(start_date=batch["start"], end_date=batch["end"], utm_tiles=[batch["tile"]])
            base["cleanup"].update(mosaics_enabled=config["lite"]["cleanup_mosaics"], mosaic_policy="confirmed_ingestion")
            base["upload"].update(backend="gcs", completion_mode="wait_for_ee")
            # A prepared-only run can later upload using a separate orchestration
            # checkpoint. Scientific receipts prevent downloading/processing again.
            automation = engine.AutomationConfig(project.root, base, [batch["tile"]], batch["start"], batch["end"],
                include_upload=automatic, cleanup_enabled=config["lite"]["cleanup_intermediates"],
                min_free_space_gb=config["lite"]["min_free_gib"], continue_on_tile_failure=True,
                run_id=batch["id"]+"_"+mode, run_dir=folder, refresh_cmr=True, process_by_year=True)
            state_path = folder/"automation_run.json"
            previous = engine.load_automation_run_state(state_path) if state_path.exists() else None
            batch.update(state="running", run_dir=str(folder), run_mode=mode, detail="")
            write_json(path, plan)
            progress(f"Batch {batch_number}/{len(plan['batches'])}: {batch['tile']} "
                     f"{batch['start']} to {batch['end']}: {len(batch['expected'])} originals, about {batch['groups']} mosaics")
            try:
                if config['mosaic'].get('grouping_mode') == HEMISPHERE:
                    from swotflow_lite.grouped_runner import run_group_batch
                    state = run_group_batch(project,batch,folder,automatic,stop,progress)
                else:
                    state = engine.run_automation(automation, preflight_state=previous, stop_event=stop,
                        progress_callback=lambda tile, stage, status, message: progress(f"{tile} / {stage}: {message}"))
                if state.stopped:
                    batch.update(state="paused", detail=state.stop_reason or "Stopped after current stage")
                elif state.errors or not state.preflight_ok or any(b.get("status") not in {"complete", "upload_pending"} for b in state.year_batches):
                    batch.update(state="attention", detail="; ".join(state.errors) or "A stage requires review; records and files retained.")
                elif automatic:
                    batch.update(state="ee_verified" if batch_verified(batch, verified_sources(project)) else "ee_pending",
                                 detail="Cloud/EE outcomes retained in upload report.")
                else:
                    batch.update(state="locally_ready", detail="Processing finished; manual bucket upload / EE ingestion still required.")
            except Exception as exc:
                batch.update(state="attention", detail=str(exc))
                progress(f"Batch retained for review: {exc}")
            write_json(path, plan)
            if batch["state"] in {"paused", "storage_pause"}:
                break
        return plan
