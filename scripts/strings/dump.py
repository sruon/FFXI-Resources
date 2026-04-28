import multiprocessing as mp
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import yaml
from loguru import logger

from parsers.strings import parse_string_dat_english, format_string
from scripts.base import DumpScript
from writers.json import write_json_gz

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

    strings = {}
    for s in parsed.strings:
        text = format_string(s.text)
        if len(text) <= 1:
            continue
        strings[s.index] = text

    if not strings:
        return None

    return {
        "id": zone["id"],
        "name": zone["name"],
        "strings": strings,
    }


class StringDumper(DumpScript):
    """FFXI zone dialog string dumper"""

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        return [z["dat"] for z in self.spec.get("zones", []) if z.get("dat")]

    def dump(self, version: str, base_path: str, output_dir: str):
        zones = self.spec.get("zones", [])

        work = [(zone, base_path) for zone in zones]
        with mp.Pool(os.cpu_count() or 4) as pool:
            results = pool.map(_parse_zone, work)

        zone_data = sorted([r for r in results if r], key=lambda z: z["id"])
        total = sum(len(z["strings"]) for z in zone_data)
        logger.info("Parsed {} strings across {} zones", total, len(zone_data))

        payload = {"version": version, "zones": zone_data}
        write_json_gz(payload, os.path.join(output_dir, "strings.json.gz"))


if __name__ == "__main__":
    StringDumper().run()
