# Output Formats

Every dump ships in two formats — pick whichever fits your pipeline:

- **`.ndjson.gz`** — gzipped newline-delimited JSON, one record per line. Streamable, jq-friendly, no schema upfront.
- **`.parquet`** — zstd-compressed columnar Parquet. DuckDB-native, predicate pushdown, smaller for repetitive data.

Both contain the same data. NDJSON has a sidecar `<name>.meta.json` with `version`/`schema_version`/`count`. Parquet embeds typing in the file itself.

## Conventions

- **One record per line/row**. No ID-keyed maps anywhere in record data.
- **Sorted output** for deterministic diffs and binary-searchable files.
- **Explicit nullability**: `null` for absent scalars, `[]` for absent arrays. Never omit.
- **Stable field order** within each record.
- **Sentinels left raw**: pseudo-entity IDs in `0x7FFFFFC0–0x7FFFFFF9` (e.g. `0x7FFFFFF0` LocalPlayer) appear as their integer values, not translated names. Consumers translate as needed.
- **Signed 16-bit interpretation** for event IDs: `-1` means `0xFFFF`, `-2` means `0xFFFE`. These are continuation/fragment markers in the FFXI event system.

## File index

| File | Description |
|---|---|
| `items.{ndjson.gz,parquet}` | Item records (one per item). Parquet uses wide schema with all category sub-objects nullable. |
| `items.schema.json` | JSON Schema for items |
| `strings.{ndjson.gz,parquet}` | Zone dialog strings (one string per row) |
| `entities.{ndjson.gz,parquet}` | Entity names (one entity per row) |
| `zones.{ndjson.gz,parquet}` | Zone names — long, alt (abbreviated), short (one zone per row) |
| `autotranslate.{ndjson.gz,parquet}` | Auto-translate phrases (one entry per row) |
| `events.{ndjson.gz,parquet}` | Event records (one event per row) |
| `events_actors.{ndjson.gz,parquet}` | Actor blocks with bytecode + imed_data |
| `spells.{ndjson.gz,parquet}` | Spells (one spell per row) |
| `abilities.{ndjson.gz,parquet}` | Abilities + weapon skills (one per row) |
| `events_scripts.parquet` | Event bytecode decompiled to Lua (one per event) |

Plus a `<name>.meta.json` for each `.ndjson.gz`:

```json
{
  "version": "30260203_0",
  "schema_version": 1,
  "count": 28862
}
```

---

## items.ndjson.gz

Discriminated union via `category`. Sort: `(id)`. Schema also published as `items.schema.json` (Pydantic-generated JSON Schema).

```json
{
  "id": 16777,
  "resource_id": 12345,
  "name": {"english": "Death Scythe", "english_log_single": "...", "english_log_plural": "...", "japanese": "..."},
  "description": {"english": "...", "japanese": "..."},
  "type": "Weapon",
  "stack_size": 1,
  "flags": ["MysteryBox", "CanEquip"],
  "targets": [],
  "category": "weapon",
  "weapon": {
    "level": 73,
    "slots": ["Main"],
    "races": [...],
    "jobs": ["DRK"],
    "damage": 97,
    "delay": 528,
    "skill": "Scythe",
    ...
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | int | Item ID |
| `resource_id` | int | Icon/model resource reference |
| `name.*`, `description.*` | string | Empty string `""` if absent |
| `type` | string | `Weapon`, `Armor`, `General`, `Furnishing`, etc. |
| `stack_size` | int | |
| `flags` | string[] | Decoded bitflags |
| `targets` | string[] | Valid target types |
| `category` | enum | `weapon` \| `armor` \| `usable` \| `furnishing` \| `puppet` \| `instinct` \| `slip` \| `monipulator` \| `general` |
| `<category>` | object | Category-specific fields (see schema) |

---

## strings.ndjson.gz

One row per zone string. Sort: `(zone_id, string_id)`.

```json
{
  "zone_id": 100,
  "zone_name": "West Ronfaure",
  "string_id": 42,
  "content": "Welcome, traveler."
}
```

| Field | Type | Notes |
|---|---|---|
| `zone_id` | int | |
| `zone_name` | string | |
| `string_id` | int | Index within the zone's string DAT |
| `content` | string | Cleaned text (control codes resolved) |

---

## entities.ndjson.gz

One row per entity. Sort: `(zone_id, entity_id)`.

```json
{
  "zone_id": 230,
  "zone_name": "Southern San d'Oria",
  "entity_id": 17104897,
  "name": "Valaineral R Davilles"
}
```

| Field | Type | Notes |
|---|---|---|
| `zone_id` | int | |
| `zone_name` | string | |
| `entity_id` | int | Server-side entity ID |
| `name` | string | Empty string preserved as-is |

---

## zones.ndjson.gz

One row per zone. Sort: `(id)`.

```json
{
  "id": 100,
  "name": "West Ronfaure",
  "name_alt": "W.Ronfaure",
  "name_short": "WRonfaure"
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | int | Zone ID |
| `name` | string | Full name (from `ROM/165/84.DAT`) |
| `name_alt` | string | Abbreviated name (from `ROM/165/83.DAT`) |
| `name_short` | string | Short name (from `ROM/165/85.DAT`) |

---

## autotranslate.ndjson.gz

One row per phrase. Sort: `(category_name, entry_id)`.

```json
{
  "category_name": "Greetings",
  "entry_id": 1,
  "text": "Nice to meet you.",
  "key": "02020101"
}
```

| Field | Type | Notes |
|---|---|---|
| `category_name` | string | `Greetings`, `Spells`, `Job Abilities`, etc. |
| `entry_id` | int | Index within category |
| `text` | string | Resolved text (job/zone refs replaced) |
| `key` | string | 4-byte hex sequence for the wire-format reference |

---

## events.ndjson.gz

One row per event. Sort: `(zone_id, actor_id, idx)`. Schema version 2.

```json
{
  "zone_id": 100,
  "zone_name": "West Ronfaure",
  "actor_id": 16785749,
  "actor_name": "Guilloud",
  "block": 0,
  "idx": 3,
  "event_id": 33,
  "entrypoint": 220,
  "byte_code": "4220011EF0FFFF7F1D0080231D0180..."
}
```

| Field | Type | Notes |
|---|---|---|
| `zone_id` | int | |
| `zone_name` | string | |
| `actor_id` | int | Owning entity. Sentinels (`0x7FFFFFC0–0x7FFFFFF9`) kept raw |
| `actor_name` | string \| null | `null` for sentinels and zone-level scripts |
| `block` | int | Zero-based block ordinal for this `(zone_id, actor_id)`. Most actors have one block (`0`). A few zones (e.g. Aht Urhgan Whitegate phases) ship multiple event DATs that share an `actor_id` — each block has its own bytecode/imed |
| `idx` | int | Zero-based position within this block's events list. Disambiguates events that share an `event_id` (~47% of actors have duplicates) |
| `event_id` | int | Signed 16-bit. `-1` = `0xFFFF` fragment, `-2` = `0xFFFE`, etc. **Not unique within a block.** |
| `entrypoint` | int | Byte offset within the actor block's concatenated bytecode region where this event's `byte_code` starts. Branch operands inside `byte_code` are absolute in that frame — disassemblers must rebase via `entrypoint` |
| `byte_code` | string | Hex string. The full bytecode slice for this single event (no `0x` prefix) |

Primary key: `(zone_id, actor_id, block, idx)`.

Primary key: `(zone_id, actor_id, idx)`.

---

## events_actors.ndjson.gz

One row per actor block. Sort: `(zone_id, actor_id)`. Schema version 2.

```json
{
  "zone_id": 100,
  "zone_name": "West Ronfaure",
  "actor_id": 16785749,
  "actor_name": "Guilloud",
  "block": 0,
  "imed_data": [7481, 0, 1, 2, 3, 4, 5, 6]
}
```

| Field | Type | Notes |
|---|---|---|
| `zone_id` | int | |
| `zone_name` | string | |
| `actor_id` | int | |
| `actor_name` | string \| null | Resolved from entities lookup |
| `block` | int | Zero-based block ordinal for this `(zone_id, actor_id)`. Same semantics as on `events` |
| `imed_data` | int[] | Immediate data table for this block. Opcode args in `0x8000–0x8FFF` index into this |

Primary key: `(zone_id, actor_id, block)`.

---

---

## spells.ndjson.gz / spells.parquet

One row per spell. Sort: `(id)`.

```json
{
  "id": 1,
  "index": 1,
  "name": "Cure",
  "description": "Restores target's HP. Afflatus Solace: Grants the effect of \"Stoneskin.\"",
  "type": "WhiteMagic",
  "element": "Light",
  "skill": "HealingMagic",
  "mp_cost": 8,
  "cast_time": 8,
  "recast_time": 20,
  "range": "D20",
  "aoe_range": "None",
  "area_shape": "Single",
  "icon_id": 6,
  "valid_targets": ["SelfTarget", "Player", "PartyMember", "Ally", "NPC", "Enemy"],
  "level_required": {"WHM": 1, "RDM": 3, "PLD": 5, "SCH": 5, "MON": 1}
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | int | Spell ID |
| `index` | int | Index in MenuTable's Mgc_ section (used for name lookup) |
| `name` / `description` | string | From DmsgTable (ROM/181/73.DAT, ROM/181/75.DAT) |
| `type` | string | WhiteMagic, BlackMagic, BardSong, Geomancy, Ninjutsu, SummonerPact, BlueMagic, etc. |
| `element` | string | Fire, Ice, Wind, Earth, Lightning, Water, Light, Dark |
| `skill` | string | HealingMagic, ElementalMagic, etc. |
| `mp_cost` / `cast_time` / `recast_time` | int | |
| `range` / `aoe_range` | string | Distance enum (e.g. `D20`, `None`) |
| `area_shape` | string | Single, Sphere, Cone, CasterSphere, etc. |
| `icon_id` | int | |
| `valid_targets` | string[] | |
| `level_required` | object | Job → level map |

---

## abilities.ndjson.gz / abilities.parquet

One row per ability or weapon skill. Sort: `(id)`.

```json
{
  "id": 1,
  "name": "Combo",
  "description": "Delivers a threefold attack...",
  "type": "Weapon",
  "icon_id": 46,
  "mp_cost": 0,
  "tp_cost": -1,
  "range": "None",
  "aoe_range": "None",
  "area_shape": "Single",
  "shared_timer_id": 900,
  "valid_targets": ["Enemy"]
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | int | Ability ID |
| `name` / `description` | string | From DmsgTable (ROM/181/72.DAT, ROM/181/74.DAT) |
| `type` | string | Weapon (weaponskill), Job, Trait, Monster, BloodPactRage, BloodPactWard, Corsair, Pet, Scholar, Waltz, Step, Samba, Jig, Flourish1/2/3, Effusion, Rune, etc. |
| `icon_id` | int | |
| `mp_cost` / `tp_cost` | int | `tp_cost: -1` means N/A |
| `range` / `aoe_range` / `area_shape` | string | Same enum types as spells |
| `shared_timer_id` | int | |
| `valid_targets` | string[] | |

---

## events_scripts.parquet

One row per event. The `lua` column holds decompiled Lua source, and `entities` is the reverse-index list of entity IDs referenced by reachable instructions. Both produced via [xi-events-py](https://github.com/sruon/xi-events-py). Sort: `(zone_id, actor_id, block, idx)`.

```
zone_id, zone_name, actor_id, actor_name, block, idx, event_id, entities, lua
```

| Field | Type | Notes |
|---|---|---|
| `block`, `idx`, `event_id` | int | Same semantics as `events.parquet`. Primary key: `(zone_id, actor_id, block, idx)` |
| `entities` | int[] | Entity IDs referenced by reachable instructions (sentinels filtered, sorted ascending). Useful as a reverse index — `WHERE list_contains(entities, X)` |
| `lua` | string | Decompiled Lua source |

```lua
function event_2(npc, player, params)
    npc:lookAtAndTalk(player)
    npc:say(7428)  -- This barge is currently en route to [South Landing via Newtpool/...
    player:waitForKeypress()
    ...
end
```

Parquet-only — Lua text is too verbose for NDJSON to be practical.

---

## DuckDB usage

Parquet is preferred — typed columns, predicate pushdown, no parsing overhead:

```sql
-- Load Parquet directly
CREATE TABLE events AS SELECT * FROM 'events.parquet';
CREATE TABLE actors AS SELECT * FROM 'events_actors.parquet';

-- Reverse lookup: events involving a specific entity
SELECT * FROM events WHERE list_contains(entities, 16785750) OR actor_id = 16785750;

-- Get bytecode for a specific event
SELECT a.bytecode, e.offset, e.size
FROM events e JOIN actors a USING (zone_id, actor_id)
WHERE e.zone_id = 100 AND e.actor_id = 16785749 AND e.event_id = 33;

-- Items: query into category-specific fields (struct columns)
SELECT id, name.english, weapon.damage, weapon.delay
FROM 'items.parquet'
WHERE category = 'weapon' AND weapon.damage > 50;
```

Or use NDJSON if you want streaming/scripting:

```sql
CREATE TABLE events AS SELECT * FROM read_ndjson_auto('events.ndjson.gz');
```
