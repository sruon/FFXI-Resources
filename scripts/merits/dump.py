import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import yaml
from loguru import logger

from xi_tinkerer import parse_dmsg_table
from scripts.base import DumpScript
from writers.json import write_ndjson_gz
from writers.parquet import write_parquet

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Devname placeholders that appear past the real merit range. Skip these.
_PLACEHOLDER = re.compile(r"^(MeripoName\d+|Meripo \d+ help text\.)$")


class MeritDumper(DumpScript):
    """FFXI merit dumper — paired (name, description) entries.

    The DAT stores name and description on consecutive IDs (even=name, odd=description).
    Real entries run from id 2 up to wherever the devname placeholders kick in
    (e.g. `MeripoName453`); placeholders are dropped.
    """
    produces = ["merits"]

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        return [self.spec["dat"]]

    def dump(self, version: str, base_path: str, output_dir: str):
        data = parse_dmsg_table(os.path.join(base_path, self.spec["dat"]))
        lists = data["lists"]

        def _str(k: int) -> str:
            entries = lists.get(str(k), [])
            if not entries or not isinstance(entries, list):
                return ""
            return entries[0].get("string", "") if isinstance(entries[0], dict) else ""

        rows = []
        # Walk even ids; paired description sits at id+1.
        for nid in range(2, max(int(k) for k in lists), 2):
            name = _str(nid)
            desc = _str(nid + 1)
            if not name or _PLACEHOLDER.match(name):
                continue
            rows.append({"id": nid, "name": name, "description": desc})

        rows.sort(key=lambda r: r["id"])
        logger.info("Parsed {} merits", len(rows))

        meta = {"version": version, "schema_version": 1}
        write_ndjson_gz(rows, os.path.join(output_dir, "merits.ndjson.gz"), meta=meta)
        write_parquet(
            rows, os.path.join(output_dir, "merits.parquet"),
            sort_by=["id"], row_group_size=1_000,
        )


if __name__ == "__main__":
    MeritDumper().run()
