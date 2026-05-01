import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import yaml
from loguru import logger

from xi_tinkerer import parse_menu_table, parse_dmsg_table
from scripts.base import DumpScript
from writers.json import write_ndjson_gz
from writers.parquet import write_parquet

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _dmsg_to_dict(dmsg_data: dict) -> dict[int, str]:
    result = {}
    for k, entries in dmsg_data["lists"].items():
        if entries and isinstance(entries, list) and "string" in entries[0]:
            result[int(k)] = entries[0]["string"]
    return result


class AbilityDumper(DumpScript):
    """FFXI ability/weapon skill dumper"""
    produces = ["abilities"]

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        return [self.spec["menu_table"], self.spec["names"], self.spec["descriptions"]]

    def dump(self, version: str, base_path: str, output_dir: str):
        data = parse_menu_table(os.path.join(base_path, self.spec["menu_table"]))
        names = _dmsg_to_dict(parse_dmsg_table(os.path.join(base_path, self.spec["names"])))
        descs = _dmsg_to_dict(parse_dmsg_table(os.path.join(base_path, self.spec["descriptions"])))

        comm = next(s for s in data["sections"] if s["type"] == "Comm")

        rows = []
        for entry in comm["entries"]:
            ability_id = entry["id"]
            name = names.get(ability_id, "")
            if not name or name == "." or name == "(NULL)":
                continue

            rows.append({
                "id": ability_id,
                "name": name,
                "description": descs.get(ability_id, ""),
                "type": entry["ability_type"],
                "icon_id": entry["icon_id"],
                "mp_cost": entry["mp_cost"],
                "tp_cost": entry["tp_cost"],
                "range": entry["range"],
                "aoe_range": entry["aoe_range"],
                "area_shape": entry["area_shape"],
                "shared_timer_id": entry["shared_timer_id"],
                "valid_targets": entry["valid_targets"],
            })

        rows.sort(key=lambda x: x["id"])
        logger.info("Parsed {} abilities", len(rows))

        meta = {"version": version, "schema_version": 1}
        write_ndjson_gz(rows, os.path.join(output_dir, "abilities.ndjson.gz"), meta=meta)
        write_parquet(rows, os.path.join(output_dir, "abilities.parquet"))


if __name__ == "__main__":
    AbilityDumper().run()
