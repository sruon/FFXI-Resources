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


class SpellDumper(DumpScript):
    """FFXI spell dumper"""
    produces = ["spells"]

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        return [self.spec["menu_table"], self.spec["names"], self.spec["descriptions"]]

    def dump(self, version: str, base_path: str, output_dir: str):
        data = parse_menu_table(os.path.join(base_path, self.spec["menu_table"]))
        names = _dmsg_to_dict(parse_dmsg_table(os.path.join(base_path, self.spec["names"])))
        descs = _dmsg_to_dict(parse_dmsg_table(os.path.join(base_path, self.spec["descriptions"])))

        mgc = next(s for s in data["sections"] if s["type"] == "Mgc_")

        rows = []
        for spell in mgc["entries"]:
            spell_id = spell["id"]
            if spell_id == 0 and spell["mp_cost"] == 0:
                continue

            spell_index = spell["index"]
            name = names.get(spell_index, "")
            if not name or name == "(NULL)":
                continue

            rows.append({
                "id": spell_id,
                "index": spell_index,
                "name": name,
                "description": descs.get(spell_index, ""),
                "type": str(spell["magic_type"]),
                "element": spell["element"],
                "skill": spell["skill_type"],
                "mp_cost": spell["mp_cost"],
                "cast_time": spell["cast_time"],
                "recast_time": spell["recast_time"],
                "range": spell["range"],
                "aoe_range": spell["aoe_range"],
                "area_shape": spell["area_shape"],
                "icon_id": spell["icon_id"],
                "valid_targets": spell["valid_targets"],
                "level_required": spell["level_required"],
            })

        rows.sort(key=lambda x: x["id"])
        logger.info("Parsed {} spells", len(rows))

        meta = {"version": version, "schema_version": 1}
        write_ndjson_gz(rows, os.path.join(output_dir, "spells.ndjson.gz"), meta=meta)
        write_parquet(rows, os.path.join(output_dir, "spells.parquet"))


if __name__ == "__main__":
    SpellDumper().run()
