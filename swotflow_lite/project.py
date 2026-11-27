"""Independent Lite projects, durable JSON and conservative storage settings."""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

import yaml
from swotflow.paths import APP_ROOT
from swotflow.project.model import create_project, load_project, save_project, SWOTFlowProject
from swotflow.processing.download import normalize_utm_tiles, validate_date_text
from swotflow.earthengine.cloud.config import CloudConfig

LITE_DEFAULTS = {"schema_version": 1, "batch_mosaics": 50, "batch_source_gib": 2.0,
                 "max_prepared_gib": 20.0, "min_free_gib": 10.0, "zone_batch_window": "adaptive",
                 "mode": "prepare", "cleanup_intermediates": True, "cleanup_mosaics": True}


@contextmanager
def lite_lock(root: Path):
    """Exclude a second Lite controller; the OS releases the lock after a crash."""
    from swotflow.project.lock import _operation_lock
    with _operation_lock(root/"00_logs/.lite.lock", "Another Lite operation is using this project."):
        yield


def write_json(path: Path, payload: Any) -> None:
    """Atomically replace a checkpoint; partial writes cannot hide prior progress."""
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as stream:
            name = Path(stream.name)
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        name.replace(path)
    finally:
        if name is not None:
            name.unlink(missing_ok=True)


def defaults_path() -> Path:
    """Return the Lite-only, nonsecret personal settings location."""
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()/".config") / "SWOTFlowLite" / "defaults.json"


def create(root: Path, name: str) -> SWOTFlowProject:
    """Create an independent project with native grids and fresh history."""
    if root.resolve().is_relative_to(APP_ROOT.resolve()):
        raise ValueError("Choose a data folder outside the application checkout.")
    base = yaml.safe_load((APP_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    personal = json.loads(defaults_path().read_text(encoding="utf-8")) if defaults_path().exists() else {}
    base.update({k: deepcopy(v) for k, v in personal.items() if k in {"cloud_upload", "destination_parent", "gdal"}})
    base.setdefault("upload", {}).update(backend="gcs", completion_mode="wait_for_ee", max_active_ingestions=2,
        pyramiding_policy={"default": "SAMPLE", "per_band": {}})
    base.setdefault("execution", {}).update(dry_run=False, require_confirmation=False)
    project = create_project(root, name, base)
    project.config["lite"] = deepcopy(LITE_DEFAULTS)
    project.config["upload"].update(base["upload"])
    project.config.setdefault("cloud_upload", {}).setdefault("concurrent_uploads", 2)
    project.config["automation"].update(include_upload=False, process_by_year=True)
    save_project(project)
    return project


def open_project(root: Path) -> SWOTFlowProject:
    """Open Lite projects only; never silently migrate a working GeeUp project."""
    project = load_project(root)
    if project.config.get("lite", {}).get("schema_version") != 1:
        raise ValueError("Choose a SWOTFlow Lite project. Existing GeeUp projects remain separate; create a new Lite project.")
    return project


def validate(config: dict, *, cloud: bool = False) -> None:
    """Validate scope and storage controls before allocating work."""
    download = config["download"]
    first = validate_date_text(download.get("start_date", ""), "Start date")
    last = validate_date_text(download.get("end_date", ""), "End date")
    if first > last or not normalize_utm_tiles(download.get("utm_tiles", [])):
        raise ValueError("Select UTM tiles and an increasing date range.")
    settings = config["lite"]
    if type(settings["batch_mosaics"]) is not int or not 1 <= settings["batch_mosaics"] <= 500:
        raise ValueError("Batch target must be between 1 and 500 complete mosaics.")
    for key in ("batch_source_gib", "max_prepared_gib", "min_free_gib"):
        if not math.isfinite(float(settings[key])) or float(settings[key]) <= 0:
            raise ValueError(key + " must be a positive, finite GiB value.")
    from swotflow_lite.grouping import WINDOWS
    if settings.get("zone_batch_window", "adaptive") not in WINDOWS.values():
        raise ValueError("Select a supported zone processing window.")
    if settings["mode"] not in {"prepare", "automatic"}:
        raise ValueError("Select Prepare locally or Fully automatic.")
    if config["extract"].get("target_crs_mode") != "original" or config["mosaic"].get("grouping_mode") not in {"utm_zone", "utm_zone_hemisphere"}:
        raise ValueError("Lite supports original 100 m grids: exact tiles or UTM zone/hemisphere groups.")
    if not Path(config["gdal"]["python"]).is_file():
        raise ValueError("Select the Python executable in your GDAL environment.")
    if cloud:
        CloudConfig.from_dict(config["cloud_upload"]).validate()
        if not config.get("destination_parent", "").startswith("projects/"):
            raise ValueError("Enter the full Earth Engine ImageCollection ID.")
