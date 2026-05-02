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


def _num(entry: dict) -> int:
    return entry.get("number", 0) if isinstance(entry, dict) else 0


class KeyItemDumper(DumpScript):
    """FFXI key item dumper — name, plural, description, icon and category numbers."""
    produces = ["keyitems"]

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        return [self.spec["dat"]]

    def dump(self, version: str, base_path: str, output_dir: str):
        data = parse_dmsg_table(os.path.join(base_path, self.spec["dat"]))
        rows = []
        for k, entries in data["lists"].items():
            kid = int(k)
            if not isinstance(entries, list) or len(entries) < 7:
                continue
            name = _str(entries[4])
            if not name:
                continue
            rows.append({
                "id": kid,
                "icon_id": _num(entries[0]),
                "category": _num(entries[1]),
                "name": name,
                "name_plural": _str(entries[5]),
                "description": _str(entries[6]),
            })

        rows.sort(key=lambda r: r["id"])
        logger.info("Parsed {} key items", len(rows))

        meta = {"version": version, "schema_version": 1}
        write_ndjson_gz(rows, os.path.join(output_dir, "keyitems.ndjson.gz"), meta=meta)
        write_parquet(
            rows, os.path.join(output_dir, "keyitems.parquet"),
            sort_by=["id"], row_group_size=1_000,
        )


if __name__ == "__main__":
    KeyItemDumper().run()
