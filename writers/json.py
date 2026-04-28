import gzip
import json
import os

from loguru import logger


def write_json_gz(data: dict, path: str):
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(path, "wb") as f:
        f.write(blob)
    logger.info("Wrote {} ({} -> {} bytes)", path, len(blob), os.path.getsize(path))


def write_json(data: dict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
