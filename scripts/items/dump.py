import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import yaml
from loguru import logger

from models.items import AnyItem
from parsers.items import parse_all_items
from scripts.base import DumpScript
from writers.json import write_ndjson_gz
from writers.parquet import write_parquet
from writers.schema import write_schema

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class ItemDumper(DumpScript):
    """FFXI item dumper"""
    produces = ["items"]

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        files = set()
        if self.spec.get("furniture"):
            files.add(self.spec["furniture"])
        for entry in self.spec.get("item_dats", []):
            files.add(entry["en"])
            files.add(entry["ja"])
        return list(files)

    def dump(self, version: str, base_path: str, output_dir: str):
        import base64

        items = parse_all_items(base_path, self.spec)
        items.sort(key=lambda x: x.id)
        logger.info("Parsed {} items", len(items))

        meta = {"version": version, "schema_version": 1}

        # NDJSON: icon as base64 string (kept on items, sortable last so consumers can skip it cheaply)
        rows = [item.model_dump(exclude_none=True) for item in items]
        write_ndjson_gz(rows, os.path.join(output_dir, "items.ndjson.gz"), meta=meta)

        # Parquet: wide schema with all category keys present (null when unused).
        # Icon stored as raw PNG bytes (binary column, no base64 overhead).
        category_keys = ["weapon", "armor", "usable", "furnishing", "puppet", "instinct", "slip", "monipulator"]
        wide_rows = []
        for item in items:
            full = item.model_dump()
            for key in category_keys:
                full.setdefault(key, None)
            # Convert base64 icon -> raw bytes for Parquet
            icon_b64 = full.get("icon")
            full["icon"] = base64.b64decode(icon_b64) if icon_b64 else None
            wide_rows.append(full)
        write_parquet(
            wide_rows, os.path.join(output_dir, "items.parquet"),
            sort_by=["id"], row_group_size=5_000,
        )

        write_schema(AnyItem, os.path.join(output_dir, "items.schema.json"))


if __name__ == "__main__":
    ItemDumper().run()
