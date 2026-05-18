import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import yaml
from loguru import logger

from xi_tinkerer import parse_entity_names
from scripts.base import DumpScript
from writers.json import write_ndjson_gz
from writers.parquet import write_parquet

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _parse(dat_path: Path) -> list[dict] | None:
    if not dat_path.exists():
        return None
    try:
        data = parse_entity_names(str(dat_path))
    except Exception as e:
        logger.error("Failed to parse {}: {}", dat_path, e)
        return None
    return sorted(
        ({"id": e["id"], "name": e["name"]} for e in data["names"]),
        key=lambda x: x["id"],
    )


class EntityDumper(DumpScript):
    """FFXI entity name dumper (per zone)"""
    produces = ["entities"]

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        files = []
        for z in self.spec.get("zones", []):
            if z.get("dat"):
                files.append(z["dat"])
            for ph in z.get("layers") or []:
                if ph.get("dat"):
                    files.append(ph["dat"])
        return files

    def dump(self, version: str, base_path: str, output_dir: str):
        rows = []
        layer_zone_count = 0

        for zone in sorted(self.spec.get("zones", []), key=lambda z: z["id"]):
            base = _parse(Path(base_path) / zone["dat"])
            if base:
                for e in base:
                    rows.append({
                        "zone_id": zone["id"],
                        "block": 0,
                        "entity_id": e["id"],
                        "layer": None,
                        "name": e["name"],
                    })

            for block_idx, ph in enumerate(zone.get("layers") or [], start=1):
                entities = _parse(Path(base_path) / ph["dat"])
                if not entities:
                    continue
                layer_zone_count += 1
                for e in entities:
                    rows.append({
                        "zone_id": zone["id"],
                        "block": block_idx,
                        "entity_id": e["id"],
                        "layer": ph["label"],
                        "name": e["name"],
                    })

        zone_count = len({(r["zone_id"], r["block"]) for r in rows})
        logger.info(
            "Parsed {} entities across {} zone-blocks ({} are layer overlays)",
            len(rows), zone_count, layer_zone_count,
        )

        meta = {"version": version, "schema_version": 2}
        write_ndjson_gz(rows, os.path.join(output_dir, "entities.ndjson.gz"), meta=meta)
        write_parquet(
            rows, os.path.join(output_dir, "entities.parquet"),
            sort_by=["zone_id", "block", "entity_id"],
        )


if __name__ == "__main__":
    EntityDumper().run()
