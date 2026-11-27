"""Catalogue-complete batches keep whole UTC days and native mosaic groups."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Callable

from swotflow.processing.download import DownloadGranule, build_download_preview, parse_config
from swotflow.core.metadata import parse_swot_l2_hr_raster_metadata
from swotflow.catalog.history import CatalogHistory
from swotflow.verification.pipeline import expected_checksum, product_name
from swotflow_lite.project import write_json, validate, lite_lock
from swotflow_lite.grouping import EXACT, HEMISPHERE, scope_groups, source_tile, protect_started_groups, WINDOWS
from swotflow.processing.mosaic import MosaicConfig, group_key


def science_identity(config: dict) -> str:
    """Workers/cleanup may change; source selection, science and destination may not."""
    value = {k: config.get(k, {}) for k in ("metadata", "destination_parent")}
    value.update(projection=config["extract"].get("target_crs_mode"),
        resampling=config["extract"].get("resampling_alg"), grouping=config["mosaic"].get("grouping_mode"),
        versions=config["download"].get("product_version_filter"),
        pyramids=config["upload"].get("pyramiding_policy"))
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def group_batches(granules: list[DownloadGranule], *, target: int, source_gib: float,
                  expected: dict[str, dict], grouping_mode: str = EXACT, window: str = "adaptive") -> list[dict]:
    """Accumulate whole acquisition days; a larger day is explicitly oversized.

    Day boundaries preserve all cycle/pass/descriptor groups, including overlaps.
    The byte value is provider source volume, not a claim about TIFF expansion.
    """
    if window not in WINDOWS.values():
        raise ValueError("Unsupported processing window: " + window)
    def window_key(day: str) -> str:
        if window == "month":
            return day[:7]
        if window == "half_month":
            return day[:7] + ("-first" if int(day[8:10]) <= 15 else "-second")
        return "adaptive"

    days: dict[str, list] = defaultdict(list)
    grouping = MosaicConfig(Path('.'), Path('.'), grouping_mode=grouping_mode)
    grids = set()
    for granule in granules:
        parsed = parse_swot_l2_hr_raster_metadata(granule.file_name)
        if not parsed or not expected.get(product_name(granule.file_name), {}).get("hash"):
            raise ValueError("Missing filename/provider checksum evidence: " + granule.file_name)
        fields = parsed.fields
        key = group_key(parsed, grouping)
        grids.add(key.coordinate_system)
        stamp = fields["range_beginning"][:8]
        day = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8])).isoformat()
        days[day].append((granule, key))
    if len(grids) > 1:
        raise ValueError("A Lite batch must stay within one native tile or zone/hemisphere.")
    result: list[dict] = []
    active: list = []

    def finish() -> None:
        if not active:
            return
        files = sorted(product_name(g.file_name) for _, g, _ in active)
        checksums = {name: expected[name] for name in files}
        volume = sum(v["size"] for v in checksums.values())
        groups = len({key for _, _, key in active})
        identity = hashlib.sha256(json.dumps(checksums, sort_keys=True).encode()).hexdigest()[:16]
        token = active[0][2].coordinate_system
        result.append({"id": token + "_" + active[0][0] + "_" + identity,
                       "tile": token, "start": active[0][0], "end": active[-1][0],
                       "expected": checksums, "groups": groups, "source_bytes": volume,
                       "oversized_day": volume > source_gib * 2**30 or groups > target,
                       "state": "pending", "detail": "", "processing_window": window})
        active.clear()

    for day, rows in sorted(days.items()):
        day_bytes = sum(expected[product_name(g.file_name)]["size"] for g, _ in rows)
        groups = {k for _, _, k in active} | {k for _, k in rows}
        size = sum(expected[product_name(g.file_name)]["size"] for _, g, _ in active)
        if active and (window_key(day) != window_key(active[0][0]) or len(groups) > target or size + day_bytes > source_gib * 2**30):
            finish()
        active.extend((day, granule, key) for granule, key in rows)
    finish()
    return result


def plan_zone_batches(granules: list[DownloadGranule], *, previous: list[dict], token: str,
                      start: str, end: str, expected: dict[str, dict], target: int,
                      source_gib: float, window: str) -> list[dict]:
    """Rebatch only unstarted work; retain completed/interrupted windows and IDs.

    Keeping old windows intact prevents new download scopes overlapping cleaned
    or partially completed work. Changed NASA membership inside a started window
    needs explicit replacement review, not an implicit second mosaic.
    """
    protected = sorted((b for b in previous if b['tile'] == token
        and b['end'] >= start and b['start'] <= end
        and (b.get('run_dir') or b.get('state', 'pending') not in {'pending', 'storage_pause'})),
        key=lambda b: b['start'])
    days = defaultdict(list)
    for granule in granules:
        stamp = parse_swot_l2_hr_raster_metadata(granule.file_name).fields['range_beginning'][:8]
        days[date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8])).isoformat()].append(granule)
    ordered = sorted(days)
    position = 0
    result = []
    def append_pending(items: list) -> None:
        result.extend(group_batches(items, target=target, source_gib=source_gib,
            expected=expected, grouping_mode=HEMISPHERE, window=window))
    last_end = ''
    for old in protected:
        if old['start'] < start or old['end'] > end or old['start'] <= last_end:
            raise ValueError('Started zone windows cannot be truncated or overlap. Keep the original scope or use a separate project.')
        before = []
        while position < len(ordered) and ordered[position] < old['start']:
            before.extend(days[ordered[position]]); position += 1
        append_pending(before)
        names = []
        while position < len(ordered) and ordered[position] <= old['end']:
            names.extend(product_name(g.file_name) for g in days[ordered[position]])
            position += 1
        if {n: expected[n] for n in names} != old['expected']:
            raise ValueError('NASA inputs changed inside an already-started zone batch. Existing checkpoints are preserved; use a separate project/collection for replacement review.')
        result.append(deepcopy(old))
        last_end = old['end']
    append_pending([g for day in ordered[position:] for g in days[day]])
    return result


def build_plan(project: object, progress: Callable[[str], None] = lambda _: None) -> dict:
    """Persist every NASA scan and reuse immutable batches on explicit refresh."""
    from swotflow.project.lock import automation_lock
    with lite_lock(project.root), automation_lock(project.root):
        return _build_plan(project, progress)


def _build_plan(project: object, progress: Callable[[str], None]) -> dict:
    """Build under project locks; failed searches never replace the old plan."""
    config, root = project.config, project.root
    validate(config)
    path = root / "00_logs" / "lite_plan.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    signature = science_identity(config)
    if old and old["science"] != signature:
        raise ValueError("Science or EE destination changed. Create a separate project; existing checkpoints remain unchanged.")
    prior = {b["id"]: b for b in old.get("batches", [])}
    batches, scans = [], []
    first, last = config["download"]["start_date"], config["download"]["end_date"]
    grouping_mode = config["mosaic"].get("grouping_mode", EXACT)
    for token, tiles in scope_groups(config).items():
        for year in range(int(first[:4]), int(last[:4]) + 1):
            start, end = max(first, f"{year}-01-01"), min(last, f"{year}-12-31")
            scope = deepcopy(config)
            scope["download"].update(start_date=start, end_date=end, utm_tiles=tiles,
                                     acquisition_start_date=start, acquisition_end_date=end)
            progress(f"NASA catalogue: {token} ({', '.join(tiles)}), {start} to {end}")
            preview = build_download_preview(parse_config(scope, root))
            snapshot = CatalogHistory(root/"00_logs/nasa_catalog_history.sqlite3").snapshot(preview.history_scan_id)
            if snapshot["status"] != "complete":
                raise ValueError("NASA search is incomplete; no processing plan was replaced.")
            expected = {product_name(c["filename"]): expected_checksum(c) for c in snapshot["candidates"]}
            options = dict(target=config["lite"]["batch_mosaics"],
                           source_gib=config["lite"]["batch_source_gib"], expected=expected)
            if grouping_mode == HEMISPHERE:
                current = plan_zone_batches(preview.selected_granules, previous=list(prior.values()),
                    token=token, start=start, end=end,
                    window=config["lite"].get("zone_batch_window", "adaptive"), **options)
            else:
                current = group_batches(preview.selected_granules, grouping_mode=grouping_mode, **options)
            for batch in current:
                batch["scan_id"] = preview.history_scan_id
                if grouping_mode == HEMISPHERE:
                    batch.update(tiles=list(tiles), grouping_mode=grouping_mode)
                if batch["id"] in prior:
                    for k in ("state", "detail", "run_mode", "run_dir"):
                        if k in prior[batch["id"]]:
                            batch[k] = prior[batch["id"]][k]
                batches.append(batch)
            for tile in tiles:
                scans.append({"tile": tile, "start": start, "end": end, "scan_id": preview.history_scan_id,
                              "preferred_files": sum(source_tile(g.file_name)==tile for g in preview.selected_granules),
                              "all_candidates": sum(source_tile(g.file_name)==tile for g in preview.granules)})
    if grouping_mode == HEMISPHERE:
        protect_started_groups(old, batches)
    plan = {"schema_version": 1, "science": signature,
            "scope": {"tiles": list(config["download"]["utm_tiles"]), "start": first, "end": last},
            "scans": scans, "batches": batches,
            "scheduling": {"zone_batch_window": config["lite"].get("zone_batch_window", "adaptive"),
                           "batch_mosaics": config["lite"]["batch_mosaics"],
                           "batch_source_gib": config["lite"]["batch_source_gib"]}}
    if old:
        archive = root/"00_logs/lite_plan_history"/(hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest()+".json")
        write_json(archive, old)
    write_json(path, plan)
    return plan
