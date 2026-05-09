import base64
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import yaml
from loguru import logger

from xi_tinkerer import parse_dmsg_table, parse_status_info
from parsers.bitmap import bitmap_a_to_png
from scripts.base import DumpScript
from writers.json import write_ndjson_gz
from writers.parquet import write_parquet

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _str(entry: dict) -> str:
    return entry.get("string", "") if isinstance(entry, dict) else ""


class StatusDumper(DumpScript):
    """FFXI status-effect dumper — joins StatusNames (display) and StatusInfo (description, flag, icon)."""
    produces = ["statuses"]

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        return [self.spec["info"], self.spec["names"]]

    def dump(self, version: str, base_path: str, output_dir: str):
        names_data = parse_dmsg_table(os.path.join(base_path, self.spec["names"]))
        info_data = parse_status_info(os.path.join(base_path, self.spec["info"]))

        names_by_id: dict[int, dict[str, str]] = {}
        for k, entries in names_data["lists"].items():
            if not entries or not isinstance(entries, list):
                continue
            name = _str(entries[0]) if len(entries) > 0 else ""
            name_passive = _str(entries[1]) if len(entries) > 1 else ""
            names_by_id[int(k)] = {"name": name, "name_passive": name_passive}

        # NDJSON gets icon as base64; Parquet gets raw bytes
        rows_ndjson: list[dict] = []
        rows_parquet: list[dict] = []
        for entry in info_data.get("status_infos", []):
            sid = entry.get("id", 0)
            name_rec = names_by_id.get(sid, {})
            icon_b64 = entry.get("icon_bytes") or ""
            # xi-tinkerer trims trailing '=' from base64 output; pad before decode
            bitmap = base64.b64decode(icon_b64 + "=" * (-len(icon_b64) % 4)) if icon_b64 else b""
            png = bitmap_a_to_png(bitmap) or b""
            png_b64 = base64.b64encode(png).decode("ascii") if png else ""
            common = {
                "id": sid,
                "name": name_rec.get("name", ""),
                "name_passive": name_rec.get("name_passive", ""),
                "description": entry.get("description", "") or "",
                "flag": entry.get("flag", 0),
            }
            rows_ndjson.append({**common, "icon": png_b64})
            rows_parquet.append({**common, "icon": png})

        rows_ndjson.sort(key=lambda r: r["id"])
        rows_parquet.sort(key=lambda r: r["id"])
        logger.info("Parsed {} statuses ({} with names)", len(rows_parquet), sum(1 for r in rows_parquet if r["name"]))

        meta = {"version": version, "schema_version": 1}
        write_ndjson_gz(rows_ndjson, os.path.join(output_dir, "statuses.ndjson.gz"), meta=meta)
        write_parquet(
            rows_parquet, os.path.join(output_dir, "statuses.parquet"),
            sort_by=["id"], row_group_size=500,
        )


if __name__ == "__main__":
    StatusDumper().run()
