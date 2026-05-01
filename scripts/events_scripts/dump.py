import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from loguru import logger

from scripts.base import DumpScript
from writers.parquet import write_parquet
from xi_events import Dataset, analyze, decompile


class EventScriptDumper(DumpScript):
    """FFXI event bytecode -> Lua decompiler. Reads from dist/ produced by other dumpers."""
    produces = ["events_scripts"]
    consumes = ["events", "events_actors", "strings", "entities", "items", "spells", "abilities"]

    def list_files(self) -> list[str]:
        return []

    def dump(self, version: str, base_path: str, output_dir: str):
        ds = Dataset.from_dist(output_dir)
        rows = []
        failed = 0

        for zone_id, actor_id, block, idx, event_id, zone_name in ds.iter_events():
            ev_rec = ds.events.get((zone_id, actor_id, block, idx), {})
            actor_name = ev_rec.get("actor_name")
            lua = None
            entities_list: list[int] = []
            try:
                fx = ds.fixture(zone_id, actor_id, idx, block=block)
                lua = decompile(fx)
                info = analyze(fx)
                entities_list = list(info.entities) if info.entities else []
            except Exception as e:
                failed += 1
                logger.debug("decompile failed for ({}, {}, {}, {}): {}", zone_id, actor_id, block, idx, e)

            rows.append({
                "zone_id": zone_id,
                "zone_name": zone_name,
                "actor_id": actor_id,
                "actor_name": actor_name,
                "block": block,
                "idx": idx,
                "event_id": event_id,
                "entities": entities_list,
                "lua": lua,
            })

        rows.sort(key=lambda r: (r["zone_id"], r["actor_id"], r["block"], r["idx"]))
        logger.info("Decompiled {} events ({} failed)", len(rows) - failed, failed)

        write_parquet(rows, os.path.join(output_dir, "events_scripts.parquet"))


if __name__ == "__main__":
    EventScriptDumper().run()
