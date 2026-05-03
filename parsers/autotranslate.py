"""Parse FFXI auto-translate DAT files."""

import struct


CATEGORY_MARKER_OPEN = b"\x81\x79"
CATEGORY_MARKER_CLOSE = b"\x81\x7a"
ENTRY_MARKER = b"\x02\x02"


def parse_autotranslate(file_path: str) -> list[dict]:
    with open(file_path, "rb") as f:
        data = f.read()

    if len(data) < 4:
        raise ValueError("File too small")

    # Find all category markers
    categories = []
    pos = 4  # skip 4-byte header

    while pos < len(data) - 2:
        # Look for category marker
        marker_pos = data.find(CATEGORY_MARKER_OPEN, pos)
        if marker_pos < 0:
            break

        end = data.find(CATEGORY_MARKER_CLOSE, marker_pos + 2)
        if end < 0:
            break

        try:
            cat_name = data[marker_pos + 2 : end].decode("shift_jis")
        except Exception:
            cat_name = data[marker_pos + 2 : end].decode("ascii", errors="replace")

        # After the closing marker, skip padding + plaintext name repeat + padding
        # The metadata (entry_count u32, byte_size u32) is at the end of this block,
        # right before the first 0x0202 entry
        entry_start = data.find(ENTRY_MARKER, end + 2)
        if entry_start < 0:
            # Last category with no entries
            categories.append({"name": cat_name, "entries": {}})
            break

        # Read metadata: last 8 bytes before entry_start
        meta_pos = entry_start - 8
        if meta_pos >= end + 2:
            entry_count, _ = struct.unpack_from("<II", data, meta_pos)
        else:
            entry_count = 0

        # Parse entries
        entries = []
        p = entry_start
        for _ in range(entry_count):
            if p + 5 > len(data) or data[p] != 0x02 or data[p + 1] != 0x02:
                break
            cat_id = data[p + 2]
            entry_id = data[p + 3]
            str_len = data[p + 4]
            p += 5

            if p + str_len > len(data):
                break
            try:
                text = data[p : p + str_len].rstrip(b"\x00").decode("shift_jis")
            except Exception:
                text = data[p : p + str_len].rstrip(b"\x00").decode("ascii", errors="replace")
            if not text.strip():
                p += str_len
                while p < len(data) and data[p] == 0:
                    p += 1
                continue
            key_bytes = bytes([0x02, 0x02, cat_id, entry_id])
            entries.append({"id": entry_id, "text": text, "key": key_bytes.hex()})
            p += str_len

            # Skip null padding
            while p < len(data) and data[p] == 0:
                p += 1

        entries.sort(key=lambda x: x["id"])
        categories.append({"name": cat_name, "entries": entries})
        pos = p

    return categories
