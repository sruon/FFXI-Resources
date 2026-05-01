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


def write_ndjson_gz(records, path: str, meta: dict | None = None):
    """Write iterable of records as gzipped NDJSON. Optionally write a .meta.json sidecar.

    `meta` will be augmented with a `count` field. The sidecar is written at
    `<path>.meta.json` (i.e. for `events.ndjson.gz` -> `events.ndjson.gz.meta.json`)
    or, if the path ends in `.ndjson.gz`, at `<base>.meta.json` (more conventional).
    """
    count = 0
    with gzip.open(path, "wb") as f:
        for rec in records:
            line = json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n"
            f.write(line.encode("utf-8"))
            count += 1
    logger.info("Wrote {} ({} records, {} bytes)", path, count, os.path.getsize(path))

    if meta is not None:
        meta = dict(meta)
        meta["count"] = count
        if path.endswith(".ndjson.gz"):
            meta_path = path[: -len(".ndjson.gz")] + ".meta.json"
        else:
            meta_path = path + ".meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        logger.info("Wrote {}", meta_path)
