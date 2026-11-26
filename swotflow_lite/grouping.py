"""Native grouping contracts shared by planning, execution and Statistics."""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from swotflow.core.metadata import parse_swot_l2_hr_raster_metadata
from swotflow.processing.mosaic import utm_zone_hemisphere_token, MosaicConfig, group_key

EXACT = "utm_zone"
HEMISPHERE = "utm_zone_hemisphere"
LABELS = {
    "Tile by tile (default)": EXACT,
    "Original projection / group UTM latitude bands by hemisphere": HEMISPHERE,
}


def source_tile(filename: str) -> str:
    """Return the original latitude-band tile, never an output-grid guess."""
    parsed = parse_swot_l2_hr_raster_metadata(filename)
    if not parsed:
        raise ValueError("Unrecognised SWOT source filename: " + filename)
    return parsed.fields["coordinate_system"]


def scope_groups(config: dict) -> dict[str, list[str]]:
    """Partition selected tiles by the configured native grid, in selection order."""
    grouped = config["mosaic"].get("grouping_mode", EXACT) == HEMISPHERE
    result: dict[str, list[str]] = OrderedDict()
    for tile in config["download"]["utm_tiles"]:
        token = utm_zone_hemisphere_token(tile) if grouped else tile
        if tile not in result.setdefault(token, []):
            result[token].append(tile)
    return result


def batch_tiles(batch: dict) -> list[str]:
    """Read new multi-band batches and existing exact-tile checkpoints."""
    return batch.get("tiles", [batch["tile"]])


def tile_inputs(batch: dict, tile: str) -> dict:
    """Attribute a shared mosaic's expected sources to their actual input tile."""
    if tile not in batch_tiles(batch):
        return {}
    if "tiles" not in batch:
        return batch["expected"]
    return {name: proof for name, proof in batch["expected"].items() if source_tile(name) == tile}


def input_groups(expected: dict, mode: str = HEMISPHERE) -> dict:
    """Partition exact original checksums using the actual mosaic engine's key."""
    config = MosaicConfig(Path('.'), Path('.'), grouping_mode=mode)
    result = {}
    for name, proof in expected.items():
        parsed = parse_swot_l2_hr_raster_metadata(name)
        if not parsed:
            raise ValueError("Unrecognised original: " + name)
        result.setdefault(group_key(parsed, config), {})[name] = proof
    return result


def protect_started_groups(old: dict, batches: list[dict]) -> None:
    """Refuse implicit replacement when an added band changes an existing mosaic."""
    protected = {}
    for batch in old.get("batches", []):
        if batch.get("state", "pending") != "pending" or batch.get("run_dir"):
            protected.update(input_groups(batch["expected"]))
    wanted = input_groups({n:p for batch in batches for n,p in batch["expected"].items()})
    for key in protected.keys() & wanted.keys():
        if protected[key] != wanted[key]:
            raise ValueError(f"Already-started mosaic membership changed: {key.coordinate_system}, {key.start_date}, pass {key.pass_id}. "
                             "Keep its original source scope or use a separate project/collection for a reviewed replacement. "
                             "Existing mosaics and plan were not replaced.")
