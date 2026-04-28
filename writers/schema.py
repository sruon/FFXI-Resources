import json

from loguru import logger
from pydantic import TypeAdapter


def write_schema(type_hint, path: str):
    ta = TypeAdapter(type_hint)
    schema = ta.json_schema()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)
    logger.info("Wrote schema to {}", path)
