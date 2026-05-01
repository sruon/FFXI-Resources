import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import yaml
from loguru import logger

from parsers.autotranslate import parse_autotranslate
from scripts.base import DumpScript
from writers.json import write_ndjson_gz
from writers.parquet import write_parquet

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class AutoTranslateDumper(DumpScript):
    """FFXI auto-translate dumper"""

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        return [self.spec[k] for k in ("en", "ja") if k in self.spec]

    def dump(self, version: str, base_path: str, output_dir: str):
        en_path = os.path.join(base_path, self.spec["en"])
        categories = parse_autotranslate(en_path)

        rows = []
        for cat in categories:
            for entry in cat.get("entries", []):
                rows.append({
                    "category_name": cat["name"],
                    "entry_id": entry["id"],
                    "text": entry["text"],
                    "key": entry["key"],
                })

        logger.info("Parsed {} auto-translate entries across {} categories", len(rows), len(categories))

        meta = {"version": version, "schema_version": 1}
        write_ndjson_gz(rows, os.path.join(output_dir, "autotranslate.ndjson.gz"), meta=meta)
        write_parquet(rows, os.path.join(output_dir, "autotranslate.parquet"))


if __name__ == "__main__":
    AutoTranslateDumper().run()
