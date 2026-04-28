import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import yaml
from loguru import logger

from parsers.autotranslate import parse_autotranslate
from scripts.base import DumpScript
from writers.json import write_json_gz
from writers.yaml import write_yaml

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

        total = sum(len(c.get("entries", {})) for c in categories)
        logger.info(
            "Parsed {} auto-translate entries across {} categories",
            total,
            len(categories),
        )

        payload = {"version": version, "categories": categories}

        write_yaml(payload, os.path.join(output_dir, "autotranslate.yaml"))
        write_json_gz(payload, os.path.join(output_dir, "autotranslate.json.gz"))


if __name__ == "__main__":
    AutoTranslateDumper().run()
