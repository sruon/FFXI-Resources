import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import yaml
from loguru import logger

from xi_tinkerer import parse_dmsg_table
from scripts.base import DumpScript
from writers.json import write_ndjson_gz
from writers.parquet import write_parquet

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _str(entry: dict) -> str:
    return entry.get("string", "") if isinstance(entry, dict) else ""


class MonsterFamilyDumper(DumpScript):
    """FFXI monster family dumper — singular and plural display names."""
    produces = ["monster_families"]

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        return [self.spec["dat"]]

    def dump(self, version: str, base_path: str, output_dir: str):
        data = parse_dmsg_table(os.path.join(base_path, self.spec["dat"]))
        rows = []
        for k, entries in data["lists"].items():
            if not entries or not isinstance(entries, list):
                continue
            name = _str(entries[0]) if len(entries) > 0 else ""
            name_plural = _str(entries[1]) if len(entries) > 1 else ""
            if not name:
                continue
            rows.append({"id": int(k), "name": name, "name_plural": name_plural})

        rows.sort(key=lambda r: r["id"])
        logger.info("Parsed {} monster families", len(rows))

        meta = {"version": version, "schema_version": 1}
        write_ndjson_gz(rows, os.path.join(output_dir, "monster_families.ndjson.gz"), meta=meta)
        write_parquet(
            rows, os.path.join(output_dir, "monster_families.parquet"),
            sort_by=["id"], row_group_size=1_000,
        )


if __name__ == "__main__":
    MonsterFamilyDumper().run()
