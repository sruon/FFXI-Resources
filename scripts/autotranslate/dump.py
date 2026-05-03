import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import yaml
from loguru import logger

from xi_tinkerer import parse_auto_translate
from scripts.base import DumpScript
from writers.json import write_ndjson_gz
from writers.parquet import write_parquet

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class AutoTranslateDumper(DumpScript):
    """FFXI auto-translate dumper"""
    produces = ["autotranslate"]

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        return [self.spec[k] for k in ("en", "ja") if k in self.spec]

    def dump(self, version: str, base_path: str, output_dir: str):
        data = parse_auto_translate(os.path.join(base_path, self.spec["en"]))

        rows = []
        for cat in data["categories"]:
            cat_id = cat["id"]
            for entry in cat.get("entries", []):
                entry_id = entry["id"]
                rows.append({
                    "category_name": cat["name"],
                    "entry_id": entry_id,
                    "text": entry["text"],
                    "key": f"0202{cat_id:02x}{entry_id:02x}",
                })

        logger.info("Parsed {} auto-translate entries across {} categories", len(rows), len(data["categories"]))

        meta = {"version": version, "schema_version": 1}
        write_ndjson_gz(rows, os.path.join(output_dir, "autotranslate.ndjson.gz"), meta=meta)
        write_parquet(rows, os.path.join(output_dir, "autotranslate.parquet"))


if __name__ == "__main__":
    AutoTranslateDumper().run()
