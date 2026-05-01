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


class EntityDumper(DumpScript):
    """FFXI entity name dumper (per zone)"""
    produces = ["entities"]

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        return [z["dat"] for z in self.spec.get("zones", []) if z.get("dat")]

    def dump(self, version: str, base_path: str, output_dir: str):
        zones = self.spec.get("zones", [])
        results = []

        for zone in zones:
            dat_path = Path(base_path) / zone["dat"]
            if not dat_path.exists():
                continue

            try:
                data = parse_entity_names(str(dat_path))
            except Exception as e:
                logger.error("Failed to parse {}: {}", zone["name"], e)
                continue

            entities = sorted(
                ({"id": e["id"], "name": e["name"]} for e in data["names"]),
                key=lambda x: x["id"],
            )

            if entities:
                results.append({
                    "id": zone["id"],
                    "name": zone["name"],
                    "entities": entities,
                })

        results.sort(key=lambda z: z["id"])

        rows = []
        for zone in results:
            for e in zone["entities"]:
                rows.append({
                    "zone_id": zone["id"],
                    "entity_id": e["id"],
                    "name": e["name"],
                })

        logger.info("Parsed {} entities across {} zones", len(rows), len(results))

        meta = {"version": version, "schema_version": 1}
        write_ndjson_gz(rows, os.path.join(output_dir, "entities.ndjson.gz"), meta=meta)
        write_parquet(
            rows, os.path.join(output_dir, "entities.parquet"),
            sort_by=["zone_id", "entity_id"], row_group_size=10_000,
        )


if __name__ == "__main__":
    EntityDumper().run()
