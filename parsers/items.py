import base64
import os
import struct

import construct as cs
from loguru import logger

from constants import (
    ELEMENTS,
    JOBS,
    RACES,
    EQUIPMENT_SLOTS,
    WEAPON_SKILLS,
    TARGETS,
    ITEM_TYPES,
    ITEM_FLAGS,
    ITEM_CATEGORIES,
    decode_bitmask,
)
from models.items import (
    AnyItem,
    ItemName,
    ItemDescription,
    ChargeData,
    WeaponData,
    ArmorData,
    UsableData,
    FurnishingData,
    PuppetData,
    InstinctData,
    SlipData,
    MonipulatorData,
    WeaponItem,
    ArmorItem,
    UsableItem,
    FurnishingItem,
    PuppetItem,
    InstinctItem,
    SlipItem,
    MonipulatorItem,
    GeneralItem,
)

RECORD_SIZE = 0xC00
ICON_OFFSET = 0x280
FUD_FIRST_ENTRY = 0x170

FURNITURE_PLACEMENT = {0x01: "CanBeHung", 0x02: "CanBePut", 0x04: "CanPutOn"}

# Construct schemas

ItemHeader = cs.Struct(
    "id" / cs.Int16ul,
    cs.Padding(2),
    "flags" / cs.Int16ul,
    "stack_size" / cs.Int16ul,
    "item_type" / cs.Int16ul,
    "resource_id" / cs.Int16ul,
    "valid_targets" / cs.Int16ul,
)

WeaponFields = cs.Struct(
    "level" / cs.Int16ul,
    "slots" / cs.Int16ul,
    "races" / cs.Int16ul,
    "jobs" / cs.Int32ul,
    "superior_level" / cs.Int8ul,
    cs.Padding(1),
    "shield_size" / cs.Int16ul,
    "damage" / cs.Int16ul,
    "delay" / cs.Int16sl,
    "dps" / cs.Int16ul,
    "skill_type" / cs.Int8ul,
    "jug_size" / cs.Int8ul,
    "emote" / cs.Int32ul,
    "max_charges" / cs.Int8ul,
    "cast_time_raw" / cs.Int8ul,
    "cast_delay" / cs.Int16ul,
    "recast_delay" / cs.Int32ul,
    "unknown1" / cs.Int16ul,
    "item_level" / cs.Int8ul,
    "unknown2" / cs.Int8ul,
    "unknown3" / cs.Int32ul,
)

ArmorFields = cs.Struct(
    "level" / cs.Int16ul,
    "slots" / cs.Int16ul,
    "races" / cs.Int16ul,
    "jobs" / cs.Int32ul,
    "superior_level" / cs.Int8ul,
    cs.Padding(1),
    "shield_size" / cs.Int16ul,
    "max_charges" / cs.Int8ul,
    "cast_time_raw" / cs.Int8ul,
    "cast_delay" / cs.Int16ul,
    "recast_delay" / cs.Int32ul,
    "unknown1" / cs.Int16ul,
    "item_level" / cs.Int8ul,
    "unknown2" / cs.Int8ul,
    "unknown3" / cs.Int32ul,
)

FurnishingFields = cs.Struct(
    "element" / cs.Int16ul,
    "storage" / cs.Int32ul,
    "unknown3" / cs.Int32ul,
)

UsableFields = cs.Struct(
    "cast_time_raw" / cs.Int16ul,
    "unknown1" / cs.Int32ul,
    "unknown2" / cs.Int32ul,
    "unknown3" / cs.Int32ul,
)

PuppetFields = cs.Struct(
    "slot" / cs.Int16ul,
    "element_charge" / cs.Int32ul,
    "unknown1" / cs.Int32ul,
)

InstinctFields = cs.Struct(
    "unknown1" / cs.Int32ul,
    "unknown2" / cs.Int32ul,
    "unknown3" / cs.Int16ul,
    "instinct_cost" / cs.Int16ul,
    "unknown4" / cs.Int16ul,
    "unknown5" / cs.Int32ul,
    "unknown6" / cs.Int32ul,
    "unknown7" / cs.Int32ul,
)

SlipFields = cs.Struct(
    "unknown1" / cs.Int16ul,
    "unknowns" / cs.Array(17, cs.Int32ul),
)

MonipulatorFields = cs.Struct(
    "unknown1" / cs.Int16ul,
    "unknowns" / cs.Array(24, cs.Int32ul),
)

FudEntry = cs.Struct(
    "info" / cs.Int16ul,
    "model_no" / cs.Int16ul,
    "size_x" / cs.Int8ul,
    "size_z" / cs.Int8ul,
    "height" / cs.Int16ul,
)


def decrypt_record(data: bytes) -> bytes:
    return bytes(((b >> 5) | (b << 3)) & 0xFF for b in data)


def _read_cstring(dec: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(dec):
        return ""
    null_pos = dec.find(0, offset)
    end = null_pos if null_pos >= 0 else len(dec)
    try:
        return dec[offset:end].decode("shift_jis", errors="replace")
    except Exception:
        return dec[offset:end].decode("ascii", errors="replace")


def _clean_text(s: str) -> str:
    lines = [line.rstrip() for line in s.split("\n")]
    return "\n".join(line for line in lines if line)


def parse_string_table_en(dec: bytes) -> dict:
    result = {
        "name": "",
        "log_name_single": "",
        "log_name_plural": "",
        "description": "",
    }

    marker = struct.pack("<II", 5, 0x2C)
    pos = dec.find(marker)
    if pos < 0:
        marker2 = struct.pack("<II", 1, 0x05)
        pos2 = dec.find(marker2)
        if pos2 >= 0:
            result["name"] = _clean_text(_read_cstring(dec, pos2 + 4 + 8))
        return result

    table_base = pos + 4
    for idx, key in [
        (0, "name"),
        (2, "log_name_single"),
        (3, "log_name_plural"),
        (4, "description"),
    ]:
        entry_pos = table_base + idx * 8
        if entry_pos + 8 > len(dec):
            break
        str_offset, str_type = struct.unpack_from("<II", dec, entry_pos)
        abs_offset = table_base + str_offset - 4
        if str_type == 0 and abs_offset + 0x1C < len(dec):
            result[key] = _clean_text(_read_cstring(dec, abs_offset + 0x1C))

    return result


def parse_string_table_ja(dec: bytes) -> dict:
    result = {"name": "", "description": ""}
    marker = struct.pack("<II", 2, 0x14)
    pos = dec.find(marker)
    if pos < 0:
        return result
    table_base = pos + 4
    for idx, key in [(0, "name"), (1, "description")]:
        entry_pos = table_base + idx * 8
        if entry_pos + 8 > len(dec):
            break
        str_offset, str_type = struct.unpack_from("<II", dec, entry_pos)
        abs_offset = table_base + str_offset - 4
        if str_type == 0 and abs_offset + 0x1C < len(dec):
            result[key] = _clean_text(_read_cstring(dec, abs_offset + 0x1C))
    return result


def load_furniture_properties(base_path: str, fud_dat: str) -> dict:
    fud_path = os.path.join(base_path, fud_dat)
    if not os.path.exists(fud_path):
        return {}

    with open(fud_path, "rb") as f:
        data = f.read()

    result = {}
    max_entries = (len(data) - FUD_FIRST_ENTRY) // 8
    for idx in range(max_entries):
        off = FUD_FIRST_ENTRY + idx * 8
        entry = FudEntry.parse(data[off : off + 8])
        if entry.info == 0 and entry.model_no == 0 and entry.size_x == 0 and entry.size_z == 0 and entry.height == 0:
            continue

        item_id = idx if idx < 512 else idx + 3072
        result[item_id] = {
            "model_no": entry.model_no,
            "size_x": entry.size_x,
            "size_z": entry.size_z,
            "height": entry.height,
            "placement_flags": [name for bit, name in FURNITURE_PLACEMENT.items() if entry.info & bit],
        }

    return result


def get_category(item_id: int) -> str:
    for cat in (
        "weapon",
        "armor",
        "usable",
        "puppet",
        "slip",
        "instinct",
        "monipulator",
    ):
        if ITEM_CATEGORIES[cat](item_id):
            return cat
    return "general"


def _extract_icon(dec: bytes) -> str | None:
    if len(dec) < ICON_OFFSET + 4:
        return None
    size = int.from_bytes(dec[ICON_OFFSET : ICON_OFFSET + 4], "little")
    if size == 0 or ICON_OFFSET + 4 + size > len(dec):
        return None
    return base64.b64encode(dec[ICON_OFFSET + 4 : ICON_OFFSET + 4 + size]).decode("ascii")


def _build_charges(fields) -> ChargeData | None:
    if not fields.max_charges:
        return None
    return ChargeData(
        max_charges=fields.max_charges,
        cast_time=fields.cast_time_raw / 4.0,
        cast_delay=fields.cast_delay,
        recast_delay=fields.recast_delay,
    )


def _build_weapon(dec: bytes) -> WeaponData:
    f = WeaponFields.parse(dec[0x0E:])
    slots = decode_bitmask(f.slots, EQUIPMENT_SLOTS, 0, 16)
    races = decode_bitmask(f.races, RACES, 1, 9)
    jobs = decode_bitmask(f.jobs, JOBS, 1, 23)

    damage, delay, dps, skill = None, None, None, None
    if f.skill_type == 1:  # H2H: subtract base D3, add base delay 480
        damage, delay = f.damage - 3, f.delay + 240
        dps = f.dps or None
        skill = WEAPON_SKILLS.get(f.skill_type, str(f.skill_type))
    elif f.skill_type > 1:
        damage, delay = f.damage, f.delay
        dps = f.dps or None
        skill = WEAPON_SKILLS.get(f.skill_type, str(f.skill_type))

    return WeaponData(
        level=f.level,
        slots=slots,
        races=races,
        jobs=jobs,
        damage=damage,
        delay=delay,
        dps=dps,
        skill=skill,
        jug_size=f.jug_size or None,
        emote=f.emote or None,
        item_level=f.item_level or None,
        superior_level=f.superior_level or None,
        unknown1=f.unknown1 or None,
        unknown2=f.unknown2 or None,
        unknown3=f.unknown3 or None,
        charges=_build_charges(f),
    )


def _build_armor(dec: bytes) -> ArmorData:
    f = ArmorFields.parse(dec[0x0E:])
    return ArmorData(
        level=f.level,
        slots=decode_bitmask(f.slots, EQUIPMENT_SLOTS, 0, 16),
        races=decode_bitmask(f.races, RACES, 1, 9),
        jobs=decode_bitmask(f.jobs, JOBS, 1, 23),
        shield_size=f.shield_size or None,
        item_level=f.item_level or None,
        superior_level=f.superior_level or None,
        unknown1=f.unknown1 or None,
        unknown2=f.unknown2 or None,
        unknown3=f.unknown3 or None,
        charges=_build_charges(f),
    )


def _build_furnishing(dec: bytes, item_id: int, furniture_properties: dict) -> FurnishingData:
    f = FurnishingFields.parse(dec[0x0E:])
    props = furniture_properties.get(item_id, {})
    return FurnishingData(
        element=ELEMENTS.get(f.element, str(f.element)),
        storage=f.storage,
        unknown3=f.unknown3 or None,
        **props,
    )


def _build_usable(dec: bytes) -> UsableData:
    f = UsableFields.parse(dec[0x0E:])
    return UsableData(
        cast_time=f.cast_time_raw / 4.0 if f.cast_time_raw else None,
        unknown1=f.unknown1 or None,
        unknown2=f.unknown2 or None,
        unknown3=f.unknown3 or None,
    )


def _build_puppet(dec: bytes) -> PuppetData:
    f = PuppetFields.parse(dec[0x0E:])
    return PuppetData(
        slot=f.slot,
        element_charge=f.element_charge,
        unknown1=f.unknown1 or None,
    )


def _build_instinct(dec: bytes) -> InstinctData:
    f = InstinctFields.parse(dec[0x0E:])
    return InstinctData(
        instinct_cost=f.instinct_cost,
        unknown1=f.unknown1 or None,
        unknown2=f.unknown2 or None,
        unknown3=f.unknown3 or None,
        unknown4=f.unknown4 or None,
        unknown5=f.unknown5 or None,
        unknown6=f.unknown6 or None,
        unknown7=f.unknown7 or None,
    )


def _build_slip(dec: bytes) -> SlipData:
    f = SlipFields.parse(dec[0x0E:])
    return SlipData(unknown1=f.unknown1 or None, unknowns=list(f.unknowns))


def _build_monipulator(dec: bytes) -> MonipulatorData:
    f = MonipulatorFields.parse(dec[0x0E:])
    return MonipulatorData(unknown1=f.unknown1 or None, unknowns=list(f.unknowns))


def _build_names(dec: bytes, dec_ja: bytes | None) -> tuple[ItemName, ItemDescription]:
    en = parse_string_table_en(dec)
    ja = parse_string_table_ja(dec_ja) if dec_ja else {"name": "", "description": ""}
    return (
        ItemName(
            english=en["name"],
            english_log_single=en["log_name_single"],
            english_log_plural=en["log_name_plural"],
            japanese=ja["name"],
        ),
        ItemDescription(english=en["description"], japanese=ja["description"]),
    )


def parse_item(dec: bytes, dec_ja: bytes | None, furniture_properties: dict) -> AnyItem | None:
    header = ItemHeader.parse(dec)

    if header.id == 0:
        return None
    if header.item_type == 0 and not ITEM_CATEGORIES["puppet"](header.id):
        return None

    category = get_category(header.id)
    name, description = _build_names(dec, dec_ja)
    icon = _extract_icon(dec)

    base = dict(
        id=header.id,
        resource_id=header.resource_id,
        name=name,
        description=description,
        type=ITEM_TYPES.get(header.item_type, str(header.item_type)),
        stack_size=header.stack_size,
        flags=decode_bitmask(header.flags, ITEM_FLAGS, 0, 16),
        targets=decode_bitmask(header.valid_targets, TARGETS, 0, 8),
        icon=icon,
    )

    if category == "weapon":
        return WeaponItem(**base, category="weapon", weapon=_build_weapon(dec))
    if category == "armor":
        return ArmorItem(**base, category="armor", armor=_build_armor(dec))
    if header.item_type == 10:
        return FurnishingItem(
            **base,
            category="furnishing",
            furnishing=_build_furnishing(dec, header.id, furniture_properties),
        )
    if category == "puppet":
        return PuppetItem(**base, category="puppet", puppet=_build_puppet(dec))
    if category == "instinct":
        return InstinctItem(**base, category="instinct", instinct=_build_instinct(dec))
    if category == "slip":
        return SlipItem(**base, category="slip", slip=_build_slip(dec))
    if category == "monipulator":
        return MonipulatorItem(**base, category="monipulator", monipulator=_build_monipulator(dec))
    if category == "usable" or (header.flags & (1 << 9)):
        return UsableItem(**base, category="usable", usable=_build_usable(dec))

    return GeneralItem(**base, category="general")


def parse_all_items(base_path: str, dat_spec: dict) -> list[AnyItem]:
    fud_dat = dat_spec.get("furniture")
    if fud_dat:
        furniture_properties = load_furniture_properties(base_path, fud_dat)
    else:
        furniture_properties = {}

    items = []
    for entry in dat_spec["item_dats"]:
        dat_en_path = os.path.join(base_path, entry["en"])
        dat_ja_path = os.path.join(base_path, entry["ja"])
        max_count = entry["max_count"]

        if not os.path.exists(dat_en_path):
            logger.warning("{} not found, skipping", dat_en_path)
            continue

        file_size = os.path.getsize(dat_en_path)
        num_records = min(max_count, file_size // RECORD_SIZE)

        if not os.path.exists(dat_ja_path):
            raise FileNotFoundError(f"JP DAT not found: {dat_ja_path}")

        with open(dat_en_path, "rb") as f_en, open(dat_ja_path, "rb") as f_ja:
            for i in range(num_records):
                raw_en = f_en.read(RECORD_SIZE)
                raw_ja = f_ja.read(RECORD_SIZE)
                if len(raw_en) < RECORD_SIZE:
                    break

                dec_en = decrypt_record(raw_en)
                dec_ja = decrypt_record(raw_ja) if len(raw_ja) == RECORD_SIZE else None
                item = parse_item(dec_en, dec_ja, furniture_properties)
                if item:
                    items.append(item)

    items.sort(key=lambda x: x.id)
    return items
