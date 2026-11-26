"""Shared engine statistics with explicit full-scope Lite coverage."""
from __future__ import annotations

import json
from swotflow.project.insights import collect_project_insights
from swotflow_lite.runner import verified_source_evidence, batch_verified, cloud_rows
from swotflow_lite.statistics_details import collect_details


def collection_lineage(project: object) -> dict:
    """Expose unknown collection members without erasing this project's receipts.

    This is read-only accounting from the last complete inventory. It does not
    create lineage for a foreign asset or weaken the shared cleanup guard.
    """
    from swotflow.catalog.history import read_project_snapshot, represented_inputs, recent
    from swotflow.consolidation.core import snapshot_asset
    from swotflow.core.metadata import product_identity_key
    from swotflow.verification.pipeline import VerificationStore, load_inventory, bound_ingestion, digest

    store = VerificationStore(project.root / "00_logs")
    try:
        inventory = load_inventory(store, project.config["destination_parent"])
        if not inventory:
            return {"status": "not_checked", "unresolved_assets": [], "conflicts": [], "checked_at": ""}
        manifest = read_project_snapshot(project.root)["mosaic_manifest"]
        represented, unresolved = represented_inputs(inventory, manifest)
        known = {row["asset_id"] for row in represented}
        memberships = {(row["asset_id"], row["filename"]) for row in represented}
        ingestions, pixels = store.ingestions(), store.cloud_receipts()
        observed_sources = {}
        for asset in inventory["assets"]:
            receipt = ingestions.get(asset["id"], {})
            pixel = pixels.get(asset["id"], {})
            sources = (receipt.get("sources") if bound_ingestion(receipt, asset) else
                       pixel.get("sources") if pixel.get("passed") is True and pixel.get("mode") == "full"
                       and pixel.get("asset_fingerprint") == digest(snapshot_asset(asset)) else {})
            if sources:
                observed_sources.update(sources)
                known.add(asset["id"])
                memberships.update((asset["id"], name) for name in sources)
        owners = {}
        for asset_id, name in memberships:
            owners.setdefault(product_identity_key(name) or name, set()).add((asset_id, name))
        conflicts = [{"acquisition": identity, "assets": sorted({a for a, _ in values}),
                      "sources": sorted({n for _, n in values})}
                     for identity, values in owners.items() if len(values) > 1]
        return {"status": "current" if recent(inventory.get("finished_utc")) else "stale",
                "unresolved_assets": [row for row in unresolved if row["asset_id"] not in known],
                "conflicts": conflicts,
                "observed_sources": observed_sources,
                "checked_at": inventory.get("finished_utc", "")}
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return {"status": "invalid", "unresolved_assets": [], "conflicts": [], "checked_at": "",
                "error": f"Inventory/lineage check unavailable ({type(exc).__name__}); Sync EE or review project history."}


def snapshot(project: object) -> dict:
    """Never count a local or bucket copy as a completed EE acquisition."""
    insights = collect_project_insights(project.config, include_cleanup=False, include_all_rows=True)
    metrics = dict(insights.metrics)
    path = project.root/"00_logs/lite_plan.json"
    plan = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    represented, conflicts = verified_source_evidence(project)
    lineage = collection_lineage(project)
    # A newer inventory can invalidate a previously VERIFIED queue receipt.
    if lineage["status"] == "current":
        observed = lineage.get("observed_sources", {})
        represented = {k:v for k,v in represented.items() if observed.get(k) == v}
    rows = []
    for batch in plan.get("batches", []):
        count = sum(represented.get(k) == v for k,v in batch["expected"].items())
        state = "ee_verified" if batch_verified(batch, represented) else batch["state"]
        if state == "ee_verified" and count != len(batch["expected"]):
            state = "ee_pending"
        rows.append({"id": batch["id"], "tile": batch["tile"], "start": batch["start"], "end": batch["end"],
                     "expected":len(batch["expected"]), "verified": count, "state": state, "detail":batch.get("detail", "")})
    expected = {k:v for b in plan.get("batches", []) for k,v in b["expected"].items()}
    verified = sum(represented.get(k) == v for k,v in expected.items())
    metrics = {"Lite preferred NASA originals in current plan":str(len(expected)),
               "Lite originals represented in last verified EE assets":str(verified),
               "Lite originals still awaiting verified EE coverage":str(len(expected)-verified),
               "Lite conflicting acquisition ownership":str(len(conflicts)),
               "Lite collection lineage inventory":lineage["status"],
               "Lite collection assets with unresolved source lineage":str(len(lineage["unresolved_assets"])),
               "Lite collection conflicting acquisition ownership":str(len(lineage["conflicts"])),
               "Lite plan scope":str(plan.get("scope", "Not planned")), **metrics}
    cloud = cloud_rows(project)
    manual = [r for r in cloud if r.get("manual_import")]
    metrics.update({
        "Manual batches: source copies removed":str(sum(bool(r["manual_import"].get("deleted_at")) for r in manual)),
        "Manual batches: known original bucket GiB retained":f"{sum(r['size'] for r in manual if r['manual_import'].get('generation') and not r['manual_import'].get('deleted_at'))/2**30:.3f}",
        "Manual batches: owned-copy GiB retained":f"{sum(r['size'] for r in manual if r.get('generation') and not r.get('deleted_at'))/2**30:.3f}",
        "Manual batches: originals awaiting browser upload":str(sum(not r['manual_import'].get('generation') for r in manual)),
        "Manual batches: source cleanup errors":str(sum(bool(r['manual_import'].get('cleanup_error')) for r in manual))})
    inputs_complete = bool(expected) and not conflicts and verified == len(expected)
    details = collect_details(project, plan, represented, lineage, insights, cloud)
    complete = inputs_complete and bool(details["tiles"]) and all(t["state"] in {"complete", "no_available_acquisitions"} for t in details["tiles"])
    metrics = {"Lite finished tiles across entire requested period":f"{details['finished_tiles']}/{len(details['tiles'])}",
               "Lite tile completion states":str(details["tile_status_counts"]),
               "Lite saved plan matches project scope":"Yes" if details["scope_matches"] else "No — refresh Catalogue / plan",
               "EE inventory checked at":lineage.get("checked_at", "") or "Not checked", **metrics}
    details["tables"]["metrics"] = [{"metric":k,"value":v} for k,v in metrics.items()]
    details["tables"]["batches"] = rows
    return {**details,"metrics":metrics,"batches":rows,"scope":plan.get("scope"),
            "empty_catalogue_windows":[s for s in plan.get("scans",[]) if s["preferred_files"]==0],
            "project_inputs_complete":inputs_complete, "complete":complete,
            "status":"not_planned" if not plan else "plan_required" if not details["scope_matches"] or any(t["state"]=="plan_required" for t in details["tiles"]) else "no_available_acquisitions" if not expected else "ee_verified" if complete else "collection_review_required" if inputs_complete else "incomplete",
            "collection_lineage":lineage,
            "conflicts":conflicts,
            "note":"EE values reflect recorded verification; use Sync EE for a fresh remote check. Local-only processing is not EE completion."}
