"""Read-only full project accounting and strict full-period tile summaries."""
from __future__ import annotations

from collections import Counter
import csv
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from swotflow.catalog.history import CatalogHistory, canonical_name, read_project_snapshot
from swotflow.core.metadata import parse_swot_l2_hr_raster_metadata
from swotflow.project.insights import ProjectInsights, project_insights_snapshot
from swotflow_lite.planner import science_identity
from swotflow_lite.project import write_json
from swotflow_lite.grouping import batch_tiles, tile_inputs


def requested_scope(config: dict) -> dict:
    """Return the saved project scope, never the latest individual batch window."""
    download = config.get("download", {})
    return {"tiles": list(download.get("utm_tiles", [])), "start": download.get("start_date", ""),
            "end": download.get("end_date", "")}


def scope_matches(project: object, plan: dict) -> bool:
    """Match the same scope/science contract used by Resume."""
    return bool(plan and plan.get("scope") == requested_scope(project.config)
                and plan.get("science") == science_identity(project.config))


def period_rows(project: object, plan: dict, represented: dict, lineage: dict) -> tuple[list, list]:
    """Require every requested yearly catalogue window before colouring a tile complete."""
    scope = requested_scope(project.config)
    current = scope_matches(project, plan)
    tiles, windows = [], []
    try:
        start, end = date.fromisoformat(scope["start"]), date.fromisoformat(scope["end"])
        years = range(start.year, end.year + 1) if start <= end else []
    except ValueError:
        years = []
    scans = {(s["tile"], s["start"], s["end"]): [] for s in plan.get("scans", [])}
    for scan in plan.get("scans", []):
        scans[(scan["tile"], scan["start"], scan["end"])].append(scan)
    for tile in dict.fromkeys(scope["tiles"]):
        batch_rows = [b for b in plan.get("batches", []) if tile in batch_tiles(b) and tile_inputs(b,tile)]
        expected = {k:v for b in batch_rows for k,v in tile_inputs(b,tile).items()}
        count = sum(represented.get(k) == v for k,v in expected.items())
        checked, no_data, window_inputs = 0, 0, 0
        for year in years:
            first, last = max(scope["start"], f"{year}-01-01"), min(scope["end"], f"{year}-12-31")
            entries = scans.get((tile, first, last), [])
            batches = [b for b in batch_rows if first <= b["start"] <= b["end"] <= last]
            sources = {k:v for b in batches for k,v in tile_inputs(b,tile).items()}
            window_inputs += len(sources)
            verified = sum(represented.get(k) == v for k,v in sources.items())
            valid = current and len(entries) == 1 and entries[0].get("preferred_files") == len(sources)
            checked += int(valid); no_data += int(valid and not sources)
            state = ("plan_required" if not valid else "no_available_acquisitions" if not sources else
                     "inputs_verified" if verified == len(sources) else "pending")
            windows.append({"tile":tile, "year":year, "start":first, "end":last,
                            "expected":len(sources), "verified":verified, "pending":len(sources)-verified,
                            "catalogue_checked":valid, "state":state,
                            "scan_id":entries[0].get("scan_id", "") if len(entries)==1 else ""})
        states = {b.get("state", "pending") for b in batch_rows}
        checked_all = (bool(years) and checked == len(years) and window_inputs == len(expected)
                       and sum(len(tile_inputs(b,tile)) for b in batch_rows) == len(expected))
        if not current or not checked_all:
            state = "plan_required"
        elif not expected:
            state = "no_available_acquisitions"
        elif count == len(expected):
            if lineage.get("conflicts") or lineage.get("unresolved_assets"):
                state = "collection_review_required"
            elif lineage.get("status") != "current":
                state = "verification_stale"
            else:
                state = "complete"
        elif "attention" in states:
            state = "attention"
        elif states & {"paused", "storage_pause"}:
            state = "paused"
        elif "running" in states:
            state = "running_checkpoint"
        elif states and states <= {"locally_ready", "ee_verified", "ee_pending"}:
            state = "upload_pending"
        else:
            state = "pending"
        tiles.append({"tile":tile, "start":scope["start"], "end":scope["end"], "state":state,
                      "expected":len(expected), "verified":count, "pending":len(expected)-count,
                      "years_checked":checked, "years_requested":len(years), "years_without_acquisitions":no_data,
                      "batches":len(batch_rows), "verified_batches":sum(bool(tile_inputs(b,tile)) and
                          all(represented.get(k)==v for k,v in tile_inputs(b,tile).items()) for b in batch_rows)})
    return tiles, windows


def engine_tables(insights: Any) -> tuple[dict, dict]:
    """Retain every full-app table, including full lineage beyond the old UI preview cap."""
    if not isinstance(insights, ProjectInsights):
        return {}, {}
    saved = project_insights_snapshot(insights)
    saved["mosaic_lineage_rows"] = insights.mosaic_lineage_rows
    saved["product_version_audit_rows"] = insights.product_version_audit_rows
    tables = {k:v for k,v in saved.items() if isinstance(v, list)}
    tables.pop("metrics", None)
    tables["all_update_coverage"] = [{"campaign_id":name,**row} for name,rows in saved.get("update_coverage_campaign_rows",{}).items() for row in rows]
    return tables, saved.get("count_definitions", {})


def nasa_searches(project: object) -> list[dict]:
    """Read complete and interrupted search history without contacting NASA."""
    result = []
    for row in CatalogHistory(project.root/"00_logs/nasa_catalog_history.sqlite3").scans():
        scope = json.loads(row["scope"])
        result.append({**row, "scope":scope, "tiles":scope.get("tiles", scope.get("utm_tiles", [])),
                       "start":scope.get("start", scope.get("start_date", "")),
                       "end":scope.get("end", scope.get("end_date", ""))})
    return result


def nasa_search_details(project: object, scan_id: str) -> dict:
    """Load exact candidate filenames, version decisions and download events on demand."""
    saved = CatalogHistory(project.root/"00_logs/nasa_catalog_history.sqlite3").snapshot(scan_id)
    choices = {r["filename"]:r for r in saved["selections"]}
    candidates = [{**row, **{k:v for k,v in choices.get(row["filename"], {}).items() if k != "filename"}}
                  for row in saved["candidates"]]
    events = []
    for event in saved["transfers"]:
        payload = json.loads(event["payload"])
        for row in payload if isinstance(payload, list) else [payload]:
            events.append({"utc":event["utc"], "action":event["action"], **row})
    comparison = {"rows":[],"note":"This search does not have a comparable tile/date scope."}
    if all(k in saved["scope"] for k in ("tiles","start","end")):
        from swotflow.catalog.history import represented_inputs, compare_versions
        from swotflow.verification.pipeline import VerificationStore, load_inventory, bound_ingestion
        history=read_project_snapshot(project.root)
        store=VerificationStore(project.root/"00_logs")
        inventory=load_inventory(store,project.config["destination_parent"]) or {"assets":[],"collection":project.config["destination_parent"]}
        members,_=represented_inputs(inventory,history["mosaic_manifest"])
        receipts=store.ingestions()
        for asset in inventory["assets"]:
            receipt=receipts.get(asset["id"],{})
            if bound_ingestion(receipt,asset):
                members.extend({"filename":n,"asset_id":asset["id"]} for n in receipt.get("sources",{}))
        comparison=compare_versions(saved,members,inventory.get("finished_utc",""),
            [r.get("file_name","") for r in history["download_manifest"] if r.get("downloaded")=="yes"])
    return {"scan_id":scan_id, "scope":saved["scope"], "candidates":candidates, "events":events,"comparison":comparison}


def cloud_table(rows: list[dict]) -> list[dict]:
    """Expose staging, ingestion and cleanup without exporting session identifiers."""
    result = []
    for row in rows:
        manual = row.get("manual_import", {})
        result.append({"asset_id":row["asset_id"], "state":row["state"],
            "route":"manual import" if manual else "automatic transfer", "local_file":row.get("local_file", ""),
            "bucket":row.get("bucket", ""), "object":row.get("object", ""), "bytes":row.get("size", 0),
            "operation":row.get("operation", ""), "updated_at":row.get("updated_at", ""),
            "cloud_deleted_at":row.get("deleted_at", ""), "manual_deleted_at":manual.get("deleted_at", ""),
            "manual_generation":manual.get("generation", ""), "generation":row.get("generation", ""),
            "error":row.get("error", ""), "cleanup_error":row.get("cleanup_error", manual.get("cleanup_error", "")),
            "source_count":len(row.get("receipt", {}).get("sources", {}))})
    return result


def input_rows(plan: dict, represented: dict, history: dict) -> list[dict]:
    """Exact preferred source accounting; historical stage records are not pixel checks."""
    downloads = {canonical_name(r.get("file_name") or r.get("filename") or r.get("local_path", "")):r
                 for r in history["download_manifest"]}
    extracts = {canonical_name(r.get("input_nc") or r.get("source") or r.get("source_file") or r.get("input_file", "")):r
                for r in history["extract_manifest"]}
    rows, seen = [], set()
    for batch in plan.get("batches", []):
        for filename, checksum in batch["expected"].items():
            if filename in seen:
                continue
            seen.add(filename)
            parsed = parse_swot_l2_hr_raster_metadata(filename)
            fields = parsed.fields if parsed else {}
            downloaded = downloads.get(canonical_name(filename), {})
            extracted = extracts.get(canonical_name(filename), {})
            rows.append({"filename":filename, "tile":fields.get('coordinate_system',batch['tile']), "batch":batch["id"],
                "crid":fields.get("crid", ""), "counter":fields.get("product_counter", ""),
                "start":fields.get("range_beginning", ""), "end":fields.get("range_ending", ""),
                "ee_verified":represented.get(filename)==checksum, "checksum":checksum,
                "download_status":downloaded.get("last_status", "not recorded"),
                "downloaded_at":downloaded.get("last_downloaded", downloaded.get("downloaded_at", "")),
                "extraction_status":extracted.get("status", "not recorded")})
    return rows


def run_history(project: object, plan: dict) -> tuple[list, list]:
    """Read Lite plan revisions and stage outcomes; no checkpoint is rewritten."""
    revisions, stages = [], []
    versions = [("current", plan)]
    for path in sorted((project.root/"00_logs/lite_plan_history").glob("*.json")):
        versions.append((path.name, json.loads(path.read_text(encoding="utf-8"))))
    seen = set()
    for name, version in versions:
        scope = version.get("scope", {})
        revisions.append({"revision":name, **scope, "batches":len(version.get("batches", [])),
                          "expected":len({k for b in version.get("batches", []) for k in b["expected"]})})
        for batch in version.get("batches", []):
            folder = batch.get("run_dir")
            if not folder or folder in seen:
                continue
            seen.add(folder); path = Path(folder)/"automation_run.json"
            # Old projects can refer to moved folders; never traverse outside this project.
            if not path.resolve().is_relative_to(project.root.resolve()) or not path.is_file():
                continue
            saved = json.loads(path.read_text(encoding="utf-8"))
            for row in saved.get("stage_results", []):
                stages.append({"batch":batch["id"], "mode":batch.get("run_mode", ""),
                               "run_started":saved.get("started_at", ""), **row})
    return revisions, stages


def collect_details(project: object, plan: dict, represented: dict, lineage: dict,
                    insights: Any, cloud: list[dict]) -> dict:
    """Build the full display off the UI thread, recording unavailable sections explicitly."""
    tables, definitions = engine_tables(insights)
    tiles, windows = period_rows(project, plan, represented, lineage)
    tables.update(tiles=tiles, years=windows, cloud=cloud_table(cloud),
                  collection_unknown=lineage.get("unresolved_assets", []), collection_conflicts=lineage.get("conflicts", []))
    warnings = []
    def read_section(label: str, job: Any) -> Any:
        try:return job()
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            warnings.append(f"{label} unavailable: {exc}");return None
    history = read_section("File history", lambda:read_project_snapshot(project.root))
    if history is not None:
        tables.update(history)
        tables["preferred_inputs"] = input_rows(plan, represented, history)
    tables["nasa_searches"] = read_section("NASA search history", lambda:nasa_searches(project)) or []
    runs = read_section("Run history", lambda:run_history(project, plan))
    if runs:
        tables["plan_revisions"], tables["stage_history"] = runs
        tables["cleanup_history"] = [r for r in runs[1] if "cleanup" in r.get("stage", "").lower() or r.get("deleted_files", 0)]
    def register() -> dict:
        from swotflow.consolidation.register import ReplacementRegister, default_path
        collection = project.config.get("destination_parent", "")
        if not collection:
            return {}
        return ReplacementRegister(default_path(collection), collection).coverage()
    coverage = read_section("Consolidation register", register) or {}
    for key in ("tiles", "products", "conflicts"):
        tables["consolidation_"+key] = coverage.get(key, [])
    tables["consolidation_summary"] = [{"metric":k,"value":v} for k,v in coverage.get("summary",{}).items()]
    tables["consolidation_untracked"] = coverage.get("untracked",[])
    tables["cleanup"] = [{"metric":k, "value":v} for k,v in insights.metrics.items()
                         if any(word in k.lower() for word in ("cleanup", "on disk", "folder size", "no longer present", "staging", "copies removed"))]
    definitions.update({
        "tiles":"Current saved tile/date scope. Complete requires every yearly catalogue window and exact preferred-source EE evidence with a current, conflict-free inventory.",
        "years":"Catalogue and source coverage per requested year. Inputs verified is not a full-tile completion claim.",
        "preferred_inputs":"Exact preferred filenames and checksums in the saved plan. Download/extraction statuses describe retained records; absence is not proof that NASA lacks the file.",
        "cloud":"Project Cloud journal: pending/failed copies remain retained. Deleted timestamps prove recorded staging cleanup. No live Cloud request is made by Refresh Statistics.",
        "cleanup":"Disk presence and cleanup history are separate from cumulative processing counts. An absent local file alone does not prove cleanup or EE ingestion. Cleanup eligibility is evaluated by the existing cleanup workflow.",
        "nasa_searches":"All retained catalogue searches, including interrupted searches. Select a search and Load NASA search to inspect its exact filenames, version choices and download events.",
        "stage_history":"Recorded stage outcomes, including retries. A running checkpoint is historical evidence, not proof that a worker is currently alive.",
        "plan_revisions":"Current and archived Lite scopes. Old rows remain history; current tile completion uses only the current saved scope.",
        "consolidation_tiles":"Read-only replacement register, if present. Lite does not create or approve consolidations; empty means no register in this app's storage, not zero NASA files.",
    })
    return {"generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tables":tables, "definitions":definitions, "tiles":tiles, "years":windows,
            "requested_scope":requested_scope(project.config), "scope_matches":scope_matches(project, plan),
            "finished_tiles":sum(t["state"]=="complete" for t in tiles),
            "tile_status_counts":dict(Counter(t["state"] for t in tiles)), "warnings":warnings}


def export_statistics(result: dict, folder: Path) -> Path:
    """Export all rows, independent of the UI's pagination and current filter."""
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder/"statistics.json", result)
    for name, rows in result.get("tables", {}).items():
        if not rows:
            continue
        columns = list(dict.fromkeys(k for row in rows for k in row))
        with (folder/(name+".csv")).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, columns);writer.writeheader()
            for row in rows:
                writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})
    return folder/"statistics.json"
