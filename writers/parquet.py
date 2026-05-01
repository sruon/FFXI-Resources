import os

import pyarrow as pa
import pyarrow.parquet as pq
from loguru import logger


def write_parquet(records: list[dict], path: str, schema: pa.Schema | None = None):
    """Write a list of dicts to Parquet (snappy compressed by default).

    If `schema` is None, pyarrow infers it from the records. Pass an explicit
    schema for unions / heavily-nullable structures where inference might miss types.
    """
    if not records:
        logger.warning("No records to write to {}", path)
        return

    if schema is not None:
        table = pa.Table.from_pylist(records, schema=schema)
    else:
        table = pa.Table.from_pylist(records)

    pq.write_table(table, path, compression="zstd", compression_level=3)
    logger.info("Wrote {} ({} records, {} bytes)", path, len(records), os.path.getsize(path))
