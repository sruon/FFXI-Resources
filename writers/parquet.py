import os

import pyarrow as pa
import pyarrow.parquet as pq
from loguru import logger


def write_parquet(
    records: list[dict],
    path: str,
    schema: pa.Schema | None = None,
    *,
    sort_by: list[str] | None = None,
    row_group_size: int | None = None,
):
    """Write a list of dicts to a zstd Parquet.

    sort_by: column names to sort the table by before writing. Tight per-row-group
        min/max stats let DuckDB skip groups confidently for predicates on these columns.
    row_group_size: rows per group. Default = single group (fine for small tables);
        set explicitly on large files to enable group-level pruning.
    """
    if not records:
        logger.warning("No records to write to {}", path)
        return

    if schema is not None:
        table = pa.Table.from_pylist(records, schema=schema)
    else:
        table = pa.Table.from_pylist(records)

    if sort_by:
        table = table.sort_by([(c, "ascending") for c in sort_by])

    write_kwargs = {
        "compression": "zstd",
        "compression_level": 3,
        "write_statistics": True,
        "write_page_index": True,
    }
    if sort_by:
        write_kwargs["sorting_columns"] = [
            pq.SortingColumn(table.schema.get_field_index(c)) for c in sort_by
        ]
    if row_group_size is not None:
        write_kwargs["row_group_size"] = row_group_size

    pq.write_table(table, path, **write_kwargs)
    pf = pq.ParquetFile(path)
    logger.info(
        "Wrote {} ({} records, {} bytes, {} row groups)",
        path, len(records), os.path.getsize(path), pf.metadata.num_row_groups,
    )
