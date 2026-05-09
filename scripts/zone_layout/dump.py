import multiprocessing as mp
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import yaml
from loguru import logger

from parsers.zone_layout import model_file_id, parse_rid_entries
from scripts.base import DumpScript
from writers.json import write_ndjson_gz
from writers.parquet import write_parquet

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


_TYPES = {
    "Z": "ZoneLine",
    "_": "Door",
    "F": "FishingArea",
    "@": "Elevator",
    "E": "Event",
    "M": "Model",
}


def _type_of(id_str: str) -> str:
    if not id_str:
        return ""
    return _TYPES.get(id_str[0].upper(), "Unknown")


def _parse_zone(args):
    zone, base_path = args
    full = Path(base_path) / zone["dat"]
    if not full.exists():
        return None
    try:
        entries = parse_rid_entries(full.read_bytes())
    except Exception as e:
        logger.error("Failed to parse zone {}: {}", zone["name"], e)
        return None
    return {"id": zone["id"], "name": zone["name"], "entries": entries}


class ZoneLayoutDumper(DumpScript):
    """RID sub-region dumper — fishing areas, doors, zonelines, models, elevators, events."""
    produces = ["zone_layout"]

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        return [z["dat"] for z in self.spec.get("zones", [])]

    def dump(self, version: str, base_path: str, output_dir: str):
        zones = self.spec.get("zones", [])

        with mp.Pool(os.cpu_count() or 4) as pool:
            results = pool.map(_parse_zone, [(z, base_path) for z in zones])

        rows = []
        for r in results:
            if not r:
                continue
            zid = r["id"]
            for idx, e in enumerate(r["entries"]):
                rows.append({
                    "zone_id": zid,
                    "idx": idx,
                    "type": _type_of(e.id_str),
                    "id_str": e.id_str,
                    "target_id_str": e.target_id_str,
                    "id": e.id,
                    "target_id": e.target_id,
                    "pos_x": e.pos[0], "pos_y": e.pos[1], "pos_z": e.pos[2],
                    "tex_map_no": e.tex_map_no,
                    "ry": e.ry,
                    "scale_x": e.scale[0], "scale_y": e.scale[1], "scale_z": e.scale[2],
                    "zone_no": e.zone_no,
                    "arrow_flag": e.arrow_flag,
                    "lift_height_0": e.lift_height[0],
                    "lift_height_1": e.lift_height[1],
                    "lift_current_height": e.lift_current_height,
                    "flag": e.flag,
                    "file_id": model_file_id(e),
                })

        rows.sort(key=lambda r: (r["zone_id"], r["idx"]))
        logger.info("Parsed {} RID entries across {} zones", len(rows), sum(1 for r in results if r))

        meta = {"version": version, "schema_version": 1}
        write_ndjson_gz(rows, os.path.join(output_dir, "zone_layout.ndjson.gz"), meta=meta)
        write_parquet(
            rows, os.path.join(output_dir, "zone_layout.parquet"),
            sort_by=["zone_id", "idx"],
            row_group_size=10_000,
        )


if __name__ == "__main__":
    ZoneLayoutDumper().run()
