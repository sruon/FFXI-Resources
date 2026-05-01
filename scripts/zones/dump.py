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


def _dmsg_to_dict(dmsg_data: dict) -> dict[int, str]:
    result = {}
    for k, entries in dmsg_data["lists"].items():
        if entries and isinstance(entries, list) and "string" in entries[0]:
            result[int(k)] = entries[0]["string"]
    return result


class ZoneDumper(DumpScript):
    """FFXI zone (area) name dumper — long, alt (abbreviated), and short forms."""
    produces = ["zones"]

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        return [self.spec["names"], self.spec["names_alt"], self.spec["names_short"]]

    def dump(self, version: str, base_path: str, output_dir: str):
        names = _dmsg_to_dict(parse_dmsg_table(os.path.join(base_path, self.spec["names"])))
        names_alt = _dmsg_to_dict(parse_dmsg_table(os.path.join(base_path, self.spec["names_alt"])))
        names_short = _dmsg_to_dict(parse_dmsg_table(os.path.join(base_path, self.spec["names_short"])))

        zone_ids = set(names) | set(names_alt) | set(names_short)
        rows = []
        for zid in sorted(zone_ids):
            rows.append({
                "id": zid,
                "name": names.get(zid, ""),
                "name_alt": names_alt.get(zid, ""),
                "name_short": names_short.get(zid, ""),
            })

        logger.info("Parsed {} zones", len(rows))

        meta = {"version": version, "schema_version": 1}
        write_ndjson_gz(rows, os.path.join(output_dir, "zones.ndjson.gz"), meta=meta)
        write_parquet(rows, os.path.join(output_dir, "zones.parquet"))


if __name__ == "__main__":
    ZoneDumper().run()
