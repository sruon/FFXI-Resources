import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import yaml
from loguru import logger

from models.items import AnyItem
from parsers.items import parse_all_items
from scripts.base import DumpScript
from writers.json import write_json_gz
from writers.schema import write_schema

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class ItemDumper(DumpScript):
    """FFXI item dumper"""

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
        items = parse_all_items(base_path, self.spec)
        logger.info("Parsed {} items", len(items))

        data = [item.model_dump(exclude_none=True, exclude={"icon"}) for item in items]
        payload = {"version": version, "items": data}

        write_json_gz(payload, os.path.join(output_dir, "items.json.gz"))
        write_schema(AnyItem, os.path.join(output_dir, "items.schema.json"))


if __name__ == "__main__":
    ItemDumper().run()
