import multiprocessing as mp
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import yaml
from loguru import logger

from parsers.strings import parse_string_dat_english, format_string
from scripts.base import DumpScript
from writers.json import write_ndjson_gz
from writers.parquet import write_parquet

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _parse_zone(args):
    zone, base_path = args
    strings_path = zone.get("dat")
    if not strings_path:
        return None

    full_path = Path(base_path) / strings_path
    if not full_path.exists():
        return None

    try:
        parsed = parse_string_dat_english(full_path)
    except Exception as e:
        logger.error("Failed to parse {}: {}", zone["name"], e)
        return None

    strings = []
    for s in parsed.strings:
        text = format_string(s.text)
        if len(text) <= 1:
            continue
        strings.append({"id": s.index, "content": text})

    if not strings:
        return None

    strings.sort(key=lambda x: x["id"])
    return {
        "id": zone["id"],
        "name": zone["name"],
        "layer": zone.get("layer"),
        "strings": strings,
    }


class StringDumper(DumpScript):
    """FFXI zone dialog string dumper"""
    produces = ["strings"]

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        files = []
        for z in self.spec.get("zones", []):
            if z.get("dat"):
                files.append(z["dat"])
            for ly in z.get("layers") or []:
                if ly.get("dat"):
                    files.append(ly["dat"])
        return files

    def dump(self, version: str, base_path: str, output_dir: str):
        zones = self.spec.get("zones", [])
        work = []
        for z in zones:
            work.append(({"id": z["id"], "name": z["name"], "dat": z.get("dat"), "layer": None}, base_path))
            for ly in z.get("layers") or []:
                if ly.get("dat"):
                    work.append((
                        {"id": z["id"], "name": z["name"], "dat": ly["dat"], "layer": ly["label"]},
                        base_path,
                    ))

        with mp.Pool(os.cpu_count() or 4) as pool:
            results = pool.map(_parse_zone, work)

        # Group by (zone_id, layer) so layer strings stay tagged. The legacy
        # Aht Urhgan Whitegate two-DAT case still merges (both layer=None).
        groups: dict[tuple, list] = {}
        order: list[tuple] = []
        for r in results:
            if not r:
                continue
            key = (r["id"], r.get("layer"))
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(r)

        rows = []
        # Sort: base zone first (layer=None), then layers alphabetically, per zone_id.
        for key in sorted(order, key=lambda k: (k[0], k[1] or "")):
            zid, layer = key
            for block_idx, zone in enumerate(groups[key]):
                for s in zone["strings"]:
                    rows.append({
                        "zone_id": zid,
                        "block": block_idx,
                        "string_id": s["id"],
                        "layer": layer,
                        "content": s["content"],
                    })

        layer_rows = sum(1 for r in rows if r["layer"] is not None)
        logger.info(
            "Parsed {} strings ({} layer-tagged) across {} zone-layer groups",
            len(rows), layer_rows, len(groups),
        )

        meta = {"version": version, "schema_version": 3}
        write_ndjson_gz(rows, os.path.join(output_dir, "strings.ndjson.gz"), meta=meta)
        write_parquet(
            rows, os.path.join(output_dir, "strings.parquet"),
            sort_by=["zone_id", "block", "string_id"], row_group_size=25_000,
        )

        # Note: primary key is (zone_id, block, string_id, layer) — layer
        # disambiguates same-zone overlays from the base zone strings.


if __name__ == "__main__":
    StringDumper().run()
