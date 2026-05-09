"""Parse FFXI string/dialog DAT files."""

import re
from pathlib import Path

import construct as cs
from loguru import logger

from models.strings import ParsedString, ParsedStringDat

StringDatHeader = cs.Struct(
    "file_size_marker" / cs.Int32ul,
    "first_offset_raw" / cs.Int32ul,
)

# Control codes that insert a placeholder character
_PLACEHOLDER_CODES = {
    0x08: "%",
    0x11: "%",
    0x1C: "%",
    0x05: "%",
}

# Control codes silently skipped (byte lengths including the code byte)
_SKIP_CODES = {
    0x09: 1,
    0x0B: 1,
    0x0C: 2,
    0x19: 2,
    0x1A: 2,
    0x1F: 2,
}


def parse_string_dat(file_path: str | Path, encoding: str = "utf-8") -> ParsedStringDat:
    with open(file_path, "rb") as f:
        raw_data = f.read()

    if len(raw_data) < 8:
        raise ValueError("File too small")

    header = StringDatHeader.parse(raw_data)

    expected_marker = 0x10000000 + len(raw_data) - 4
    if header.file_size_marker != expected_marker:
        raise ValueError(f"Invalid file size marker: {header.file_size_marker:08X}")

    first_text_pos = header.first_offset_raw ^ 0x80808080
    if first_text_pos % 4 != 0 or first_text_pos > len(raw_data) or first_text_pos < 8:
        raise ValueError(f"Invalid first text position: {first_text_pos}")

    entry_count = first_text_pos // 4

    raw_offsets = [first_text_pos]
    for i in range(1, entry_count):
        offset_pos = 4 + (i * 4)
        if offset_pos + 4 > len(raw_data):
            break
        raw_offsets.append(int.from_bytes(raw_data[offset_pos : offset_pos + 4], "little") ^ 0x80808080)

    sorted_offsets = sorted(set(raw_offsets))
    sorted_offsets.append(len(raw_data) - 4)

    def _string_end(offset: int) -> int:
        for s in sorted_offsets:
            if s > offset:
                return s
        return len(raw_data) - 4

    strings = []
    for i, offset in enumerate(raw_offsets):
        if offset < 4 * entry_count or offset >= len(raw_data) - 4:
            continue

        start_pos = offset + 4
        end_pos = _string_end(offset) + 4
        if start_pos >= len(raw_data) or end_pos > len(raw_data):
            continue

        try:
            raw_bytes = raw_data[start_pos:end_pos]
            decoded = bytes(b - 0x80 if b >= 0x80 else b for b in raw_bytes).rstrip(b"\x00")
            text = decoded.decode(encoding, errors="replace")
            strings.append(ParsedString(index=i, offset=offset, text=text))
        except Exception as e:
            logger.debug("Failed to decode string at offset {}: {}", offset, e)

    return ParsedStringDat(entry_count=entry_count, strings=strings)


def parse_string_dat_english(file_path: str | Path) -> ParsedStringDat:
    return parse_string_dat(file_path, encoding="utf-8")


def _skip(pos: int, text: str, n: int) -> int:
    return min(pos + n, len(text))


def format_string(text: str) -> str:
    """Strip FFXI control codes, insert readable placeholders."""
    result = []
    pos = 0
    in_selection = False

    while pos < len(text):
        b = ord(text[pos])

        if b == 0x07:
            if pos + 1 < len(text) and ord(text[pos + 1]) == 0x32:
                if pos + 3 < len(text) and text[pos + 2 : pos + 4] == "nd":
                    result.append(" ")
                    pos += 1
                else:
                    pos += 2
            elif pos + 1 < len(text) and ord(text[pos + 1]) == 0x33:
                if pos + 3 < len(text) and text[pos + 2 : pos + 4] == "rd":
                    result.append(" ")
                    pos += 1
                else:
                    pos += 2
            else:
                result.append("/" if in_selection else " ")
                pos += 1

        elif b == 0x0A:
            result.append("#")
            pos = _skip(pos, text, 2)

        elif b == 0x1E:
            pos = _skip(
                pos,
                text,
                3 if pos + 1 < len(text) and ord(text[pos + 1]) == 0x1F else 2,
            )

        elif b == 0x7F:
            if pos + 1 >= len(text):
                pos += 1
                continue
            sub = ord(text[pos + 1])
            if sub == 0x31:
                in_selection = False
                pos = _skip(pos, text, 3)
            elif sub == 0x92:
                result.append("[/")
                in_selection = True
                pos = _skip(pos, text, 3)
            elif sub in (0x05, 0x85):
                # 2-byte prefix; bytes that follow (incl. literal `[…]`) are content
                pos = _skip(pos, text, 2)
            else:
                pos = _skip(pos, text, 3)

        elif b == 0x01:
            found = False
            for j in range(pos + 1, min(pos + 14, len(text))):
                if ord(text[j]) == 0x02:
                    if j <= pos + 1 or ord(text[j - 1]) != 0x29:
                        result.append("%")
                    pos = min(j + 4, len(text))
                    found = True
                    break
            if not found:
                # 0x01 has two roles depending on what precedes it:
                #   - after a placeholder code (0x05/0x08/0x0A/0x11/0x1C):
                #     it's a 1-byte format marker; the next byte is a
                #     literal punctuation char to keep (e.g. "%!" comes
                #     from 0x11 0x01 0x21).
                #   - elsewhere: it's a 2-byte control prefix; the next
                #     byte is a parameter that must be consumed too (e.g.
                #     0x01 0x60 between two numbers, 0x01 0x1A before
                #     "The Wyrm God").
                prev = ord(text[pos - 1]) if pos > 0 else 0
                if prev in (0x05, 0x08, 0x0A, 0x11, 0x1C):
                    pos += 1
                else:
                    pos += 2

        elif b == 0x05:
            result.append("%")
            pos += 1
            while pos < len(text) and 0x20 <= ord(text[pos]) < 0x7F:
                pos += 1

        elif b in _PLACEHOLDER_CODES:
            result.append(_PLACEHOLDER_CODES[b])
            pos = _skip(pos, text, 2 if b == 0x1C else 1)

        elif b in _SKIP_CODES:
            pos = _skip(pos, text, _SKIP_CODES[b])

        elif b == 0xEF:
            pos = _skip(pos, text, 2)
        elif b == 0xFD:
            pos = _skip(pos, text, 6)
        elif 0x20 <= b < 0x7F:
            result.append(text[pos])
            pos += 1
        else:
            pos += 1

    raw = re.sub(r" +", " ", "".join(result))
    return "".join(c for c in raw if ord(c) >= 0x20).strip()
