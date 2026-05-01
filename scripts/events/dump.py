import gzip
import json
import multiprocessing as mp
import os
import sys
from pathlib import Path

# Events parser modules need to be found first (before repo-level models/parsers)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

import yaml
from loguru import logger

from event_parser.eventcode import EventCodeParser
from event_parser.eventdat import EventDatParser
from event_parser.opcodes.base import ArgType, OpcodeContext
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
    """Convert u16 to signed (65535 -> -1)."""
    return val - 0x10000 if val >= 0x8000 else val


def _is_real_entity(entity_id: int) -> bool:
    if not entity_id or entity_id <= 0:
        return False
    if 0x7FFFFFC0 <= entity_id <= 0x7FFFFFF9:
        return False
    return True


def _collect_entity_refs(instructions, context, entry_offset, reachable_offsets):
    """Collect entity refs only from reachable instructions (skip data sections)."""
    refs = set()
    cur = entry_offset
    for inst in instructions:
        if reachable_offsets is not None and cur not in reachable_offsets:
            cur += len(inst.raw_bytes)
            continue
        if inst.opcode_impl:
            opcode_args = inst.opcode_impl.get_args() if hasattr(inst.opcode_impl, "get_args") else []
            for arg_def in opcode_args:
                if arg_def.arg_type != ArgType.ENTITY_ID:
                    continue
                val = inst.args.get(arg_def.name)
                if val is None:
                    continue
                resolved, _ = inst.opcode_impl.resolve_reference_value(val, context)
                if _is_real_entity(resolved):
                    refs.add(resolved)
        cur += len(inst.raw_bytes)
    return sorted(refs)


def _build_groups(parsed_events):
    """Compute connected-component group IDs for events in a block.

    Two events are connected when:
    1. CALL/GOTO from event A targets event B's offset (jump edge)
    2. Event A ends non-terminally and is offset-adjacent to event B (fall-through edge)

    parsed_events: list of dicts with keys: offset, size, instructions
    Returns: dict mapping offset -> group_id
    """
    offsets = sorted(e["offset"] for e in parsed_events)
    by_offset = {e["offset"]: e for e in parsed_events}

    # Union-find
    parent = {off: off for off in offsets}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Jump edges — use opcode's own get_jump_targets()
    for ev in parsed_events:
        for inst in ev["instructions"]:
            if not inst.opcode_impl or not hasattr(inst.opcode_impl, "get_jump_targets"):
                continue
            try:
                targets = inst.opcode_impl.get_jump_targets(inst.args)
            except Exception:
                targets = []
            for target in targets or []:
                if target in by_offset:
                    union(ev["offset"], target)

    # Fall-through edges — use opcode's is_terminal()
    for i, off in enumerate(offsets[:-1]):
        next_off = offsets[i + 1]
        ev = by_offset[off]
        if not ev["instructions"]:
            continue
        last_inst = ev["instructions"][-1]
        is_terminal = False
        if last_inst.opcode_impl and hasattr(last_inst.opcode_impl, "is_terminal"):
            try:
                is_terminal = last_inst.opcode_impl.is_terminal()
            except Exception:
                pass
        if is_terminal:
            continue
        if off + ev["size"] == next_off:
            union(off, next_off)

    # Assign sequential group IDs based on root
    roots = {}
    next_id = 0
    result = {}
    for off in offsets:
        r = find(off)
        if r not in roots:
            roots[r] = next_id
            next_id += 1
        result[off] = roots[r]
    return result


def _parse_zone(args):
    zone, base_path, entity_lookup = args
    events_dat_path = zone.get("events_dat")
    if not events_dat_path:
        return None

    full_path = Path(base_path) / events_dat_path
    if not full_path.exists():
        return None

    try:
        event_dat = EventDatParser.parse_file(full_path)
    except Exception as e:
        logger.error("Failed to parse events for {}: {}", zone["name"], e)
        return None

    opcode_parser = EventCodeParser(use_control_flow=True)
    actors = []

    for block in event_dat.blocks:
        context = OpcodeContext(imed_data=block.imed_data)
        all_events = block.get_all_events()

        # First pass: parse instructions and collect entities
        parsed = []
        for event_id, offset, event_data in all_events:
            instructions = []
            entities = []
            if len(event_data) >= 1:
                try:
                    instructions, cf_data = opcode_parser.parse_event_data(event_data, offset)
                    reachable = cf_data.get("reachable_offsets") if cf_data else None
                    entities = _collect_entity_refs(instructions, context, offset, reachable)
                except Exception as e:
                    logger.error("Failed to parse event {} in zone {}: {}", event_id, zone["name"], e)
            parsed.append({
                "id": _signed16(event_id),
                "offset": offset,
                "size": len(event_data),
                "entities": entities,
                "instructions": instructions,
            })

        # Second pass: compute group IDs
        groups = _build_groups(parsed)

        events = []
        for ev in parsed:
            events.append({
                "id": ev["id"],
                "offset": ev["offset"],
                "size": ev["size"],
                "group": groups[ev["offset"]],
                "entities": ev["entities"],
            })

        actors.append({
            "actor_id": block.actor_number,
            "imed_data": block.imed_data,
            "bytecode": block.event_data.hex(),
            "events": events,
        })

    return {
        "id": zone["id"],
        "name": zone["name"],
        "actors": actors,
    }


class EventDumper(DumpScript):
    """FFXI event dumper"""

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
        zones = self.spec.get("zones", [])

        zone_list = []
        for zone in zones:
            events_dat = zone.get("files", {}).get("events")
            if events_dat:
                zone_list.append({
                    "id": zone["id"],
                    "name": zone["name"],
                    "events_dat": events_dat,
                })

        entity_lookup = _load_entities_lookup()
        logger.info("Loaded {} entity names from dist", len(entity_lookup))

        work = [(zone, base_path, entity_lookup) for zone in zone_list]
        with mp.Pool(os.cpu_count() or 4) as pool:
            results = pool.map(_parse_zone, work)

        zone_data = sorted([r for r in results if r], key=lambda z: z["id"])

        # Sort: (zone_id, actor_id, event_id, offset)
        events_rows = []
        actors_rows = []
        for zone in zone_data:
            zid, zname = zone["id"], zone["name"]
            for actor in sorted(zone["actors"], key=lambda a: a["actor_id"]):
                actor_id = actor["actor_id"]
                actor_name = entity_lookup.get(actor_id)
                actors_rows.append({
                    "zone_id": zid,
                    "zone_name": zname,
                    "actor_id": actor_id,
                    "actor_name": actor_name,
                    "bytecode": actor["bytecode"],
                    "imed_data": actor["imed_data"],
                })
                for ev in sorted(actor["events"], key=lambda e: (e["id"], e["offset"])):
                    events_rows.append({
                        "zone_id": zid,
                        "zone_name": zname,
                        "actor_id": actor_id,
                        "actor_name": actor_name,
                        "event_id": ev["id"],
                        "offset": ev["offset"],
                        "size": ev["size"],
                        "group": ev["group"],
                        "entities": ev["entities"],
                    })

        logger.info("Parsed {} events / {} actors across {} zones", len(events_rows), len(actors_rows), len(zone_data))

        meta = {"version": version, "schema_version": 1}
        write_ndjson_gz(events_rows, os.path.join(output_dir, "events.ndjson.gz"), meta=meta)
        write_ndjson_gz(actors_rows, os.path.join(output_dir, "events_actors.ndjson.gz"), meta=meta)
        write_parquet(events_rows, os.path.join(output_dir, "events.parquet"))
        write_parquet(actors_rows, os.path.join(output_dir, "events_actors.parquet"))


if __name__ == "__main__":
    EventDumper().run()
