"""Bounded overlap with remote EE work; never run two local project writers."""
from __future__ import annotations

from copy import deepcopy
import time

from swotflow.project.lock import automation_lock
from swotflow_lite.project import write_json

ACTIVE = {"PREPARED", "TRANSFERRING", "STAGED", "SUBMITTING", "INGESTING"}


def enabled(config: dict) -> bool:
    """Older projects and manual preparation keep their existing behavior."""
    lite = config.get("lite", {})
    return lite.get("mode") == "automatic" and lite.get("overlap_ee_ingestion", False)


def completion_mode(config: dict) -> str:
    return "submit_and_continue" if enabled(config) else "wait_for_ee"


def submitted(batch: dict, represented: dict, rows: list[dict]) -> bool:
    """Skip replay only when every exact source is verified or has a saved EE task."""
    covered = dict(represented)
    for row in rows:
        if row["state"] == "INGESTING" and row.get("operation"):
            for name, checksum in row["receipt"]["sources"].items():
                if batch["expected"].get(name) == checksum:
                    covered[name] = checksum
    return bool(batch["expected"]) and all(covered.get(k) == v for k, v in batch["expected"].items())


def active_batches(plan: dict, rows: list[dict]) -> set[str]:
    """Count unfinished batches from durable operations, including uncertain outcomes."""
    sources = {name for row in rows if row["state"] in ACTIVE for name in row["receipt"]["sources"]}
    return {b["id"] for b in plan["batches"] if sources.intersection(b["expected"])}


def reconcile(project: object, progress, *, context: dict | None = None) -> None:
    """Poll recorded tasks and reuse guarded cleanup, without a full inventory scan.

    Called only between local stages/batches under the project operation lock.
    A fresh report owner per waiting period avoids overwriting changes made by
    an upload subprocess. Reuse it only while no local stage can write history.
    """
    from swotflow_lite import runner
    context = {} if context is None else context
    with automation_lock(project.root):
        if "worker" not in context:
            context["worker"] = runner.make_cloud_worker(project)
        worker = context["worker"]
        try:
            worker.reconcile()
        finally:
            worker.report.write()
        verified = frozenset((r['asset_id'], r['receipt'].get('token',''))
                             for r in worker.rows() if r['state']=='VERIFIED')
        if project.config["lite"]["cleanup_mosaics"] and context.get('cleaned') != verified:
            config = deepcopy(project.config)
            config.setdefault("cleanup", {}).update(mosaics_enabled=True, mosaic_policy="confirmed_ingestion")
            for section in ("processing", "download"):
                for key in ("acquisition_start_date", "acquisition_end_date"):
                    config.get(section, {}).pop(key, None)
            count, size, errors = runner.engine.cleanup_stage(config, "", "mosaic")
            if count or errors:
                progress(f"Overlap cleanup: {count} verified files; {size/2**30:.3f} GiB; {len(errors)} retained errors.")
            if not errors:
                context['cleaned'] = verified


def refresh(project: object, plan: dict) -> tuple[dict, list[dict]]:
    """Persist completion only from the same source evidence used by Statistics."""
    from swotflow_lite import runner
    represented, conflicts = runner.verified_source_evidence(project)
    rows = runner.cloud_rows(project)
    if conflicts:
        raise ValueError("Conflicting source ownership in EE; retain files and review before continuing.")
    for batch in plan["batches"]:
        if runner.batch_verified(batch, represented):
            batch.update(state="ee_verified", detail="All preferred sources have matching confirmed EE provenance.")
        elif submitted(batch, represented, rows):
            batch.update(state="ee_pending", detail="EE tasks recorded; local and bucket files retained until verified.")
        elif batch["state"] == "ee_pending" and not active_batches({"batches": [batch]}, rows):
            batch.update(state="attention", detail="EE ingestion remains incomplete; retained files and task errors are available for Resume.")
    plan.setdefault("pipeline", {}).update(pending_batches=len(active_batches(plan, rows)))
    write_json(project.root/"00_logs/lite_plan.json", plan)
    return represented, rows


def wait_for_room(project: object, plan: dict, stop, progress, *, current: str = "", drain: bool = False) -> bool:
    """Wait interruptibly at the bound or at run end; timeout never means completion."""
    execution = project.config.get("execution", {})
    deadline = time.monotonic() + max(1, float(execution.get("wait_timeout_minutes", 720))) * 60
    interval = max(5, float(execution.get("task_poll_seconds", 20)))
    limit = int(project.config["lite"].get("max_pending_batches", 2))
    announced = False
    context: dict = {}
    while not stop.is_set():
        reconcile(project, progress, context=context)
        _, rows = refresh(project, plan)
        pending = active_batches(plan, rows) - ({current} if current else set())
        if not pending or (not drain and len(pending) < limit):
            plan["pipeline"].update(state="ready", detail="")
            write_json(project.root/"00_logs/lite_plan.json", plan)
            return True
        detail = f"Waiting for {len(pending)} unfinished EE ingestion batches; prepared files and provenance retained."
        if not announced:
            progress(detail); announced = True
        plan["pipeline"].update(state="waiting_for_ee", detail=detail)
        write_json(project.root/"00_logs/lite_plan.json", plan)
        if time.monotonic() >= deadline:
            plan["pipeline"].update(state="verification_pending", detail="EE monitoring deadline reached. Resume polls saved operations before any retry.")
            write_json(project.root/"00_logs/lite_plan.json", plan)
            progress(plan["pipeline"]["detail"])
            return False
        stop.wait(min(interval, max(0, deadline-time.monotonic())))
    plan.setdefault("pipeline", {}).update(state="paused", detail="Stopped between stages; recorded EE tasks may continue remotely.")
    write_json(project.root/"00_logs/lite_plan.json", plan)
    return False
