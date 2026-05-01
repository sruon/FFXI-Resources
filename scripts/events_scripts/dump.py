import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from loguru import logger

from scripts.base import DumpScript
from writers.parquet import write_parquet
from xi_events import Dataset, decompile


class EventScriptDumper(DumpScript):
    """FFXI event bytecode -> Lua decompiler. Reads from dist/ produced by other dumpers."""

    def list_files(self) -> list[str]:
        return []

    def dump(self, version: str, base_path: str, output_dir: str):
        ds = Dataset.from_dist(output_dir)
        rows = []
        failed = 0

        for zone_id, actor_id, event_id, zone_name in ds.iter_events():
            ev_rec = ds.events.get((zone_id, actor_id, event_id), {})
            actor_name = ev_rec.get("actor_name")
            lua = None
            try:
                fx = ds.fixture(zone_id, actor_id, event_id)
                lua = decompile(fx)
            except Exception as e:
                failed += 1
                logger.debug("decompile failed for ({}, {}, {}): {}", zone_id, actor_id, event_id, e)

            rows.append({
                "zone_id": zone_id,
                "zone_name": zone_name,
                "actor_id": actor_id,
                "actor_name": actor_name,
                "event_id": event_id,
                "lua": lua,
            })

        rows.sort(key=lambda r: (r["zone_id"], r["actor_id"], r["event_id"]))
        logger.info("Decompiled {} events ({} failed)", len(rows) - failed, failed)

        write_parquet(rows, os.path.join(output_dir, "events_scripts.parquet"))


if __name__ == "__main__":
    EventScriptDumper().run()
