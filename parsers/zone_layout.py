"""FFXI zone DAT walker — extracts RID (Resource ID) sub-region entries.

Per-entry layout (64 bytes, matches xiregiondump field names):
    0x00..0x0B  pos       (3 f32: x, y, z)
    0x0C..0x0F  tex_map_no (u32)
    0x10..0x13  ry         (f32) — rotation around Y axis
    0x14..0x17  padding    (u32, always 0 in known data; not preserved)
    0x18..0x23  scale      (3 f32: x, y, z) — OBB half-extents
    0x24..0x27  id         (u32) — 4-byte ASCII identifier ("f025", "@090", "m0x4", ...)
    0x28..0x2B  target_id  (u32) — 4-byte ASCII secondary identifier
    0x2C..0x2F  zone_no    (u32) — Model: raw file id (raw<600 ? raw+100 : raw+83191);
                                   ZoneLine: dest zone; otherwise unused
    0x30..0x33  arrow_flag (u32)
    0x34..0x35  lift_height[0] (i16)
    0x36..0x37  lift_height[1] (i16)
    0x38..0x3B  lift_current_height (f32)
    0x3C..0x3F  flag       (u32)

Verified byte-for-byte against xiregiondump.exe's all_zones.json.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


RID_RESOURCE_TYPE = 0x36
END_RESOURCE_TYPE = 0x00


@dataclass
class RidEntry:
    pos: tuple[float, float, float]
    tex_map_no: int
    ry: float
    scale: tuple[float, float, float]
    id: int
    id_str: str
    target_id: int
    target_id_str: str
    zone_no: int
    arrow_flag: int
    lift_height: tuple[int, int]
    lift_current_height: float
    flag: int


def _ascii4(buf: bytes) -> str:
    return buf.decode("ascii", errors="replace").split("\x00", 1)[0]


def _walk_rid_chunks(data: bytes):
    pos = 0
    while pos + 16 <= len(data):
        value = struct.unpack_from("<I", data, pos + 4)[0]
        resource_type = value & 0x7F
        size = 16 * ((value >> 7) & 0x7FFFF) - 16

        if resource_type == END_RESOURCE_TYPE:
            pos += 16
            continue
        if size <= 0 or pos + 16 + size > len(data):
            break

        if resource_type == RID_RESOURCE_TYPE:
            yield data[pos + 16 : pos + 16 + size]

        pos += 16 + size


def _parse_one_rid_chunk(chunk: bytes) -> list[RidEntry]:
    if len(chunk) < 0x40:
        return []
    count = struct.unpack_from("<I", chunk, 0x30)[0]
    out: list[RidEntry] = []
    for i in range(count):
        b = 0x40 + i * 0x40
        if b + 0x40 > len(chunk):
            break

        pos_x, pos_y, pos_z = struct.unpack_from("<3f", chunk, b + 0x00)
        tex_map_no = struct.unpack_from("<I", chunk, b + 0x0C)[0]
        ry = struct.unpack_from("<f", chunk, b + 0x10)[0]
        scale_x, scale_y, scale_z = struct.unpack_from("<3f", chunk, b + 0x18)

        id_bytes = chunk[b + 0x24 : b + 0x28]
        target_id_bytes = chunk[b + 0x28 : b + 0x2C]

        out.append(RidEntry(
            pos=(pos_x, pos_y, pos_z),
            tex_map_no=tex_map_no,
            ry=ry,
            scale=(scale_x, scale_y, scale_z),
            id=struct.unpack_from("<I", id_bytes)[0],
            id_str=_ascii4(id_bytes),
            target_id=struct.unpack_from("<I", target_id_bytes)[0],
            target_id_str=_ascii4(target_id_bytes),
            zone_no=struct.unpack_from("<I", chunk, b + 0x2C)[0],
            arrow_flag=struct.unpack_from("<I", chunk, b + 0x30)[0],
            lift_height=(
                struct.unpack_from("<h", chunk, b + 0x34)[0],
                struct.unpack_from("<h", chunk, b + 0x36)[0],
            ),
            lift_current_height=struct.unpack_from("<f", chunk, b + 0x38)[0],
            flag=struct.unpack_from("<I", chunk, b + 0x3C)[0],
        ))
    return out


def parse_rid_entries(data: bytes) -> list[RidEntry]:
    out: list[RidEntry] = []
    for chunk in _walk_rid_chunks(data):
        out.extend(_parse_one_rid_chunk(chunk))
    return out


def model_file_id(entry: RidEntry) -> int | None:
    if not entry.id_str or entry.id_str[0].lower() != "m":
        return None
    raw = entry.zone_no
    return raw + 100 if raw < 600 else raw + 83191
