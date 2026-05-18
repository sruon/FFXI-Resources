import gzip
import json
import multiprocessing as mp
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pyarrow as pa
import xi_tinkerer
import yaml
from loguru import logger

from scripts.base import DumpScript
from writers.json import write_ndjson_gz
from writers.parquet import write_parquet
from xi_events import Fixture, analyze, decompile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(SCRIPT_DIR, "..", "..", "dist")


def _load_entities_by_zone() -> dict[int, dict[int, str]]:
    """Per-zone entity lookup — used by xi-events for in-Lua name resolution."""
    path = os.path.join(DIST_DIR, "entities.ndjson.gz")
    if not os.path.exists(path):
        return {}
    by_zone: dict[int, dict[int, str]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            by_zone.setdefault(rec["zone_id"], {})[rec["entity_id"]] = rec["name"]
    return by_zone


def _load_items() -> dict[int, str]:
    path = os.path.join(DIST_DIR, "items.ndjson.gz")
    if not os.path.exists(path):
        return {}
    items: dict[int, str] = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            name = rec.get("name")
            if isinstance(name, dict):
                name = name.get("english") or name.get("english_log_single")
            if name:
                items[rec["id"]] = name
    return items


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
    return {
        "id": zone["id"],
        "name": zone["name"],
        "phase": zone.get("phase"),
        "blocks": result["blocks"],
    }


def _is_fragment(event_id: int) -> bool:
    return event_id < 0


class EventDumper(DumpScript):
    """FFXI event dumper — bytecode + decompiled Lua + static analysis in one pass."""
    produces = ["events"]
    consumes = ["entities", "items"]

    def __init__(self):
        with open(os.path.join(SCRIPT_DIR, "dats.yaml")) as f:
            self.spec = yaml.safe_load(f)

    def list_files(self) -> list[str]:
        files = set()
        for zone in self.spec.get("zones", []):
            dat = zone.get("files", {}).get("events")
            if dat:
                files.add(dat)
            for ph in zone.get("phases") or []:
                if ph.get("dat"):
                    files.add(ph["dat"])
        return list(files)

    def dump(self, version: str, base_path: str, output_dir: str):
        zone_list = []
        for zone in self.spec.get("zones", []):
            events_dat = zone.get("files", {}).get("events")
            if events_dat:
                zone_list.append({
                    "id": zone["id"], "name": zone["name"],
                    "events_dat": events_dat, "phase": None,
                })
            for ph in zone.get("phases") or []:
                if ph.get("dat"):
                    zone_list.append({
                        "id": zone["id"], "name": zone["name"],
                        "events_dat": ph["dat"], "phase": ph["label"],
                    })

        entities_by_zone = _load_entities_by_zone()
        items_lookup = _load_items()
        logger.info(
            "Loaded {} zones of entities / {} items",
            len(entities_by_zone), len(items_lookup),
        )

        work = [(zone, base_path) for zone in zone_list]
        with mp.Pool(os.cpu_count() or 4) as pool:
            results = pool.map(_parse_zone, work)

        # Group results by (zone_id, phase) so phase events stay separately
        # tagged. The legacy Aht Urhgan Whitegate two-DAT case still merges
        # cleanly because both entries share phase=None.
        merged: dict[tuple, dict] = {}
        for r in results:
            if not r:
                continue
            key = (r["id"], r.get("phase"))
            if key not in merged:
                merged[key] = {"id": r["id"], "name": r["name"],
                               "phase": r.get("phase"), "blocks": []}
            merged[key]["blocks"].extend(r["blocks"])
        zone_data = sorted(merged.values(), key=lambda z: (z["id"], z.get("phase") or ""))

        events_rows: list[dict] = []
        decompile_failures = 0
        analyze_failures = 0

        for zone in zone_data:
            zid = zone["id"]
            phase_label = zone.get("phase")
            zone_entities = entities_by_zone.get(zid, {})
            block_counter: dict[int, int] = {}
            for block in sorted(zone["blocks"], key=lambda b: b["entity_id"]):
                actor_id = block["entity_id"]
                block_idx = block_counter.get(actor_id, 0)
                block_counter[actor_id] = block_idx + 1
                imed_data = list(block["data"])
                # Concat all event slices in source order — the decompiler uses this to
                # resolve JUMP_TO_POSITION targets that land in sibling events.
                block_bytecode = bytes.fromhex("".join(_strip_hex_prefix(e["byte_code"]) for e in block["events"]))
                entrypoint = 0
                for idx, ev in enumerate(block["events"]):
                    byte_code = _strip_hex_prefix(ev["byte_code"])
                    event_id = _signed16(ev["id"])

                    lua = None
                    params: list[int] = []
                    state: list[int] = []
                    scratch: list[int] = []
                    string_refs: list[int] = []
                    referenced_entities: list[int] = []
                    uses_result = False
                    uses_result2 = False
                    # parquet MAP requires list-of-tuples shape: [(slot_idx, {kind, value}), ...]
                    imed_pairs: list[tuple[int, dict]] = []

                    if not _is_fragment(event_id):
                        fix = Fixture(
                            zone_id=zid,
                            actor_id=actor_id,
                            block=block_idx,
                            idx=idx,
                            event_id=event_id,
                            bytecode=bytes.fromhex(byte_code),
                            entrypoint=entrypoint,
                            imed_data=imed_data,
                            strings={},
                            entities=zone_entities,
                            items=items_lookup,
                            block_bytecode=block_bytecode,
                        )
                        try:
                            lua = decompile(fix, comments=False)
                        except Exception as e:
                            decompile_failures += 1
                            logger.debug(
                                "decompile failed for ({}, {}, {}, {}): {}",
                                zid, actor_id, block_idx, idx, e,
                            )
                        try:
                            info = analyze(fix)
                            params = list(info.params)
                            state = list(info.state)
                            scratch = list(info.scratch)
                            string_refs = list(info.string_refs)
                            referenced_entities = list(info.entities)
                            uses_result = bool(info.uses_result)
                            uses_result2 = bool(info.uses_result2)
                            imed_pairs = sorted(info.imed.items())
                        except Exception as e:
                            analyze_failures += 1
                            logger.debug(
                                "analyze failed for ({}, {}, {}, {}): {}",
                                zid, actor_id, block_idx, idx, e,
                            )

                    events_rows.append({
                        "zone_id": zid,
                        "actor_id": actor_id,
                        "block": block_idx,
                        "phase": phase_label,
                        "idx": idx,
                        "event_id": event_id,
                        "entrypoint": entrypoint,
                        "byte_code": byte_code,
                        "lua": lua,
                        "params": params,
                        "state": state,
                        "scratch": scratch,
                        "string_refs": string_refs,
                        "entities": referenced_entities,
                        "uses_result": uses_result,
                        "uses_result2": uses_result2,
                        "imed": imed_pairs,
                    })
                    entrypoint += len(byte_code) // 2

        events_rows.sort(key=lambda r: (r["zone_id"], r["phase"] or "", r["actor_id"], r["block"], r["idx"]))

        decompiled = sum(1 for r in events_rows if r["lua"] is not None)
        phase_rows = sum(1 for r in events_rows if r["phase"] is not None)
        logger.info(
            "Parsed {} events ({} phase-tagged, {} decompiled, {} decompile failures, {} analyze failures) across {} zone-phase groups",
            len(events_rows), phase_rows, decompiled, decompile_failures, analyze_failures, len(zone_data),
        )

        meta = {"version": version, "schema_version": 4}

        # NDJSON wants regular dicts; parquet wants list-of-tuples for MAP. Convert both views.
        ndjson_rows = []
        for r in events_rows:
            ndjson_rows.append({**r, "imed": {str(k): v for k, v in r["imed"]}})
        write_ndjson_gz(ndjson_rows, os.path.join(output_dir, "events.ndjson.gz"), meta=meta)

        # Explicit schema so pyarrow emits MAP<int, struct<kind,value>> instead of inferring a wide STRUCT.
        imed_value_struct = pa.struct([
            pa.field("kind", pa.string()),
            pa.field("value", pa.int64()),
        ])
        events_schema = pa.schema([
            pa.field("zone_id", pa.int32()),
            pa.field("actor_id", pa.int64()),
            pa.field("block", pa.int32()),
            pa.field("phase", pa.string()),
            pa.field("idx", pa.int32()),
            pa.field("event_id", pa.int32()),
            pa.field("entrypoint", pa.int32()),
            pa.field("byte_code", pa.string()),
            pa.field("lua", pa.string()),
            pa.field("params", pa.list_(pa.int32())),
            pa.field("state", pa.list_(pa.int32())),
            pa.field("scratch", pa.list_(pa.int32())),
            pa.field("string_refs", pa.list_(pa.int64())),
            pa.field("entities", pa.list_(pa.int64())),
            pa.field("uses_result", pa.bool_()),
            pa.field("uses_result2", pa.bool_()),
            pa.field("imed", pa.map_(pa.int32(), imed_value_struct)),
        ])
        write_parquet(
            events_rows, os.path.join(output_dir, "events.parquet"),
            schema=events_schema,
            sort_by=["zone_id", "actor_id", "block", "idx"],
            row_group_size=5_000,
        )


if __name__ == "__main__":
    EventDumper().run()
