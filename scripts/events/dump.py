import gzip
import json
import multiprocessing as mp
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import xi_tinkerer
import yaml
from loguru import logger

from scripts.base import DumpScript
from writers.json import write_ndjson_gz
from writers.parquet import write_parquet

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(SCRIPT_DIR, "..", "..", "dist")


def _load_entities_lookup():
    path = os.path.join(DIST_DIR, "entities.ndjson.gz")
    if not os.path.exists(path):
        return {}
    lookup = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            lookup[rec["entity_id"]] = rec["name"]
    return lookup


def _signed16(val: int) -> int:
    return val - 0x10000 if val >= 0x8000 else val


def _strip_hex_prefix(s: str) -> str:
    return s[2:] if s.startswith("0x") else s


def _parse_zone(args):
    zone, base_path = args
    events_dat_path = zone.get("events_dat")
    if not events_dat_path:
        return None
    full_path = Path(base_path) / events_dat_path
    if not full_path.exists():
        return None
    try:
        result = xi_tinkerer.parse_events(str(full_path))
    except Exception as e:
        logger.error("Failed to parse events for {}: {}", zone["name"], e)
        return None
    return {"id": zone["id"], "name": zone["name"], "blocks": result["blocks"]}


class EventDumper(DumpScript):
    """FFXI event dumper — extracts per-event bytecode via xi-tinkerer."""
    produces = ["events", "events_actors"]
    consumes = ["entities"]  # entity_lookup for actor_name resolution

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        files = set()
        for zone in self.spec.get("zones", []):
            dat = zone.get("files", {}).get("events")
            if dat:
                files.add(dat)
        return list(files)

    def dump(self, version: str, base_path: str, output_dir: str):
        zone_list = []
        for zone in self.spec.get("zones", []):
            events_dat = zone.get("files", {}).get("events")
            if events_dat:
                zone_list.append({"id": zone["id"], "name": zone["name"], "events_dat": events_dat})

        entity_lookup = _load_entities_lookup()
        logger.info("Loaded {} entity names from dist", len(entity_lookup))

        work = [(zone, base_path) for zone in zone_list]
        with mp.Pool(os.cpu_count() or 4) as pool:
            results = pool.map(_parse_zone, work)

        # Merge spec entries that share zone_id (e.g. Aht Urhgan Whitegate phases). Same logical zone, multiple event DATs.
        merged: dict[int, dict] = {}
        for r in results:
            if not r:
                continue
            zid = r["id"]
            if zid not in merged:
                merged[zid] = {"id": zid, "name": r["name"], "blocks": []}
            merged[zid]["blocks"].extend(r["blocks"])
        zone_data = sorted(merged.values(), key=lambda z: z["id"])

        events_rows = []
        actors_rows = []
        for zone in zone_data:
            zid = zone["id"]
            block_counter: dict[int, int] = {}
            for block in sorted(zone["blocks"], key=lambda b: b["entity_id"]):
                actor_id = block["entity_id"]
                actor_name = entity_lookup.get(actor_id)
                block_idx = block_counter.get(actor_id, 0)
                block_counter[actor_id] = block_idx + 1
                actors_rows.append({
                    "zone_id": zid,
                    "actor_id": actor_id,
                    "actor_name": actor_name,
                    "block": block_idx,
                    "imed_data": list(block["data"]),
                })
                entrypoint = 0
                for idx, ev in enumerate(block["events"]):
                    byte_code = _strip_hex_prefix(ev["byte_code"])
                    events_rows.append({
                        "zone_id": zid,
                        "actor_id": actor_id,
                        "actor_name": actor_name,
                        "block": block_idx,
                        "idx": idx,
                        "event_id": _signed16(ev["id"]),
                        "entrypoint": entrypoint,
                        "byte_code": byte_code,
                    })
                    entrypoint += len(byte_code) // 2

        events_rows.sort(key=lambda r: (r["zone_id"], r["actor_id"], r["block"], r["idx"]))
        actors_rows.sort(key=lambda r: (r["zone_id"], r["actor_id"], r["block"]))

        logger.info("Parsed {} events / {} actors across {} zones", len(events_rows), len(actors_rows), len(zone_data))

        meta = {"version": version, "schema_version": 2}
        write_ndjson_gz(events_rows, os.path.join(output_dir, "events.ndjson.gz"), meta=meta)
        write_ndjson_gz(actors_rows, os.path.join(output_dir, "events_actors.ndjson.gz"), meta=meta)
        write_parquet(events_rows, os.path.join(output_dir, "events.parquet"))
        write_parquet(actors_rows, os.path.join(output_dir, "events_actors.parquet"))


if __name__ == "__main__":
    EventDumper().run()
