# xi-events-py — required changes for new event schema

The producer (`sruon/FFXI-Resources`) is switching its event dump to a simpler per-event-bytecode model. This drops `offset`/`size`/`group`/`entities[]` from the event records — they were computed by an embedded opcode parser that's now removed. xi-events-py must adapt.

## Schema changes

### `events.ndjson.gz` / `events.parquet`

**Before** (schema_version 1):
```json
{
  "zone_id": 100, "zone_name": "West Ronfaure",
  "actor_id": 16785749, "actor_name": "Guilloud",
  "event_id": 33,
  "offset": 220, "size": 2560,
  "group": 5,
  "entities": [16785750, 16785789]
}
```

**After** (schema_version 2):
```json
{
  "zone_id": 100, "zone_name": "West Ronfaure",
  "actor_id": 16785749, "actor_name": "Guilloud",
  "block": 0,
  "idx": 3,
  "event_id": 33,
  "entrypoint": 220,
  "byte_code": "320045..."
}
```

Removed: `offset`, `size`, `group`, `entities[]`.
Added:
- `block` — zero-based block ordinal for this `(zone_id, actor_id)`. Almost always `0`. A handful of zones (e.g. Aht Urhgan Whitegate phases) ship two event DATs that share an `actor_id`; each block has its own bytecode region and `imed_data`. **Primary key includes block.**
- `idx` — zero-based position within this block's events list. Disambiguates events that share an `event_id` (~47% of actors have duplicates).
- `entrypoint` — byte offset within the actor block's concatenated bytecode region where this event starts. **Branch operands inside `byte_code` are absolute offsets in that frame, not slice-relative** — consumers must subtract `entrypoint` (or pass it as the starting position to the disassembler) to land at the right slice index. Computed as cumulative sum of preceding events' bytecode lengths within the block.
- `byte_code` — hex string, the full bytecode for this single event (no `0x` prefix).

### `events_actors.ndjson.gz` / `events_actors.parquet`

**Before**:
```json
{ "zone_id": 100, "actor_id": 16785749, "actor_name": "Guilloud",
  "bytecode": "...long hex...", "imed_data": [7481, 0, 1, ...] }
```

**After**:
```json
{ "zone_id": 100, "actor_id": 16785749, "actor_name": "Guilloud",
  "block": 0, "imed_data": [7481, 0, 1, ...] }
```

Removed: `bytecode` (now lives per-event in `events.ndjson.gz`).
Added: `block` — same semantics as on events. Primary key is `(zone_id, actor_id, block)`.

Sort: `(zone_id, actor_id, block)`.

### Why duplicate event_ids exist

About 47% of actors (10,477 / 22,407) have at least one duplicate event_id, accounting for ~128k duplicate entries. These are mostly fragments (`event_id == -1` / `0xFFFF`) representing scheduler-triggered code blocks, fall-through continuations of preceding events, or jump targets.

The new `idx` field disambiguates them. Primary key for an event row is `(zone_id, actor_id, idx)`.

## Required changes in xi-events-py

### 1. `Dataset.from_dist`

`actors[(zone_id, actor_id, block)]` no longer carries `bytecode`. Read bytecode from event records instead. Note the key now includes `block`.

`events` should key by `(zone_id, actor_id, block, idx)`. `(zone_id, actor_id, idx)` alone is **not unique** — same actor across blocks (Whitegate phases) can have the same idx.

Suggested API:
```python
ds.event(zone_id, actor_id, block, idx)            # canonical lookup
ds.events_for(zone_id, actor_id, event_id)         # may return >1 fragment, across blocks
ds.iter_events()                                    # yields (zone_id, actor_id, block, idx, event_id, zone_name)
```

### 2. `Fixture` construction

```python
@dataclass
class Fixture:
    zone_id: int
    actor_id: int
    block: int                  # NEW: per-actor block ordinal
    idx: int                    # per-block event index
    event_id: int
    bytecode: bytes             # per-event slice
    entrypoint: int             # the original starting offset in actor-block coordinates
    imed_data: list[int]         # from the matching actor row, keyed by (zone, actor, block)
    strings: dict[int, str]
    entities: dict[int, str]
    items: dict[int, str]
```

`fixture()` builds bytecode from the event row's `byte_code` hex (`bytes.fromhex(ev["byte_code"])`) and copies `entrypoint` from the event row.

**Branch operands are absolute in actor-block coordinates.** A branch with operand `0x6D` lands at slice index `0x6D - entrypoint`. The disassembler must rebase every jump target accordingly. Targets that fall outside `[entrypoint, entrypoint + len(bytecode))` are cross-event jumps into a sibling event in the same actor — those targets land in another event's slice; resolve via the actor's events list if you need to follow them, otherwise treat as out-of-slice (terminator/external).

### 3. Expose `entities` (required) — and optionally `group`

The producer no longer parses opcodes itself. xi-events-py already disassembles bytecode for decompilation, so this is the right place to compute the index — and the producer needs `entities[]` back to enrich its dump.

- **`entities[]`** — REQUIRED. Scan disassembled instructions, collect args of type `ENTITY_ID` from reachable instructions only (not data sections). Filter out sentinels (`0x7FFFFFC0..0x7FFFFFF9`). Sort ascending. Duplicates removed.

  Expose on `EventInfo` so the producer can call:
  ```python
  info = xi_events.analyze(ds.fixture(zone_id, actor_id, idx))
  entities_list = info.entities  # list[int], sorted, no sentinels
  ```

  The producer's `events_scripts/dump.py` will call `analyze()` per event and re-emit `entities[]` into a downstream output (likely `events_scripts.parquet` alongside the Lua, or as a new index file). Consumers querying "events involving NPC X" rely on this.

- **`group`** — OPTIONAL. The old `group` field was a connected-component ID within an actor block based on bytecode offset adjacency + CALL/GOTO targets. With per-event bytecode, events don't share an address space, so the old definition no longer applies. If you want to expose a similar concept, define it as "events that JUMP_TO_POSITION into another event in the same actor" (cross-event jump edges only) and put it on `EventInfo`. Skip if it doesn't fit cleanly.

### 4. CLI

`python -m xi_events.cli <zone> <actor> <event>` still works, but if `event_id` is ambiguous (multiple fragments), require `--idx N` or pick the first match with a warning.

## Migration path

The new producer release will bump `schema_version: 2` in the sidecar `.meta.json` for both `events.ndjson.gz` and `events_actors.ndjson.gz`. xi-events-py can branch on schema_version to support both old and new dumps during transition, or hard-cut once the new release is live.

## Sample records

```ndjson
{"zone_id":100,"zone_name":"West Ronfaure","actor_id":16785749,"actor_name":"Guilloud","idx":0,"event_id":-1,"byte_code":"00"}
{"zone_id":100,"zone_name":"West Ronfaure","actor_id":16785749,"actor_name":"Guilloud","idx":1,"event_id":33,"byte_code":"4220011EF0FFFF7F1D0080231D0180..."}
{"zone_id":100,"zone_name":"West Ronfaure","actor_id":16785749,"actor_name":"Guilloud","idx":2,"event_id":-1,"byte_code":"39038000"}
```
