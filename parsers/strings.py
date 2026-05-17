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

# Control byte → semantic placeholder. Mapping mirrors POLUtils'
# SimpleStringTableEntry / DialogTableEntry parsers, which is the canonical
# definition of FFXI's text format (see github.com/Windower/POLUtils).
#
# value = (placeholder_text, total_byte_length_including_control_byte)
_SEMANTIC_CODES = {
    0x08: ("<player>", 1),     # Player Name
    0x09: ("<name>", 1),       # Speaker Name (NPC)
    0x0A: ("<number>", 2),     # Numeric Parameter (+ 1B param)
    0x0E: ("<number>", 1),     # Variant numeric placeholder
    0x11: ("<player>", 1),     # Possible Special Code: 11 — used for player/trust names
    0x19: ("<item>", 2),       # Item Parameter (+ 1B param)
    0x1A: ("<keyitem>", 2),    # Key Item Parameter (+ 1B param)
    0x1C: ("<player>", 2),     # Player/Chocobo Parameter (+ 1B param)
}

# Control bytes that consume a fixed number of bytes and emit nothing.
_SILENT_CODES = {
    0x0B: 1,    # Selection Dialog open marker
    0x0C: 2,    # Multiple Choice (Parameter) — literal '[…]' follows
    0x1E: 2,    # Set Color
    0x1F: 2,    # Unknown
    0xEF: 2,
    0xFD: 6,
}

# Generic '%' placeholder for control bytes whose semantics POLUtils labels
# as "Possible Special Code" — these become a generic substitution after
# UpdateExtractor's sanitization, and we follow suit.
_GENERIC_PERCENT_CODES = {0x05}

# 0x7F sub-byte → (bytes_to_consume_including_0x7F, opens_selection)
# Mirrors POLUtils' DialogTableEntry / SimpleStringTableEntry handling
# of the 0x7F prefix family. The default (unknown sub-byte) consumes 3.
_SUB_7F_DISPATCH: dict[int, tuple[int, bool]] = {
    0x31: (3, False),  # Prompt / N-second delay — clears in_selection
    0x92: (3, True),   # Singular/Plural Choice — emits "[/", opens selection
    0x05: (2, False),  # Possible Special Code: 05
    0x85: (2, False),  # Multiple Choice (Player Gender)
    0x8D: (3, False),  # Weather Event Parameter
    0x8E: (3, False),  # Weather Type Parameter
    0xB1: (3, False),  # Title Parameter
}
_SUB_7F_DEFAULT = (3, False)

# 0x07 sub-byte → ordinal suffix that must match for the digit to be
# preserved. When the suffix matches, the handler only advances past
# 0x07 itself (pos+=1) so the literal digit survives.
_ORDINAL_07 = {0x32: "nd", 0x33: "rd"}

# FFXIEncoding multi-byte chars whose obfuscated (raw DAT) form is
# entirely low-byte, so simple subtract-deobfuscation leaves them intact
# and format_string then mis-handles them (eats them as control codes or
# emits a literal second byte). Substitute the known ones at the byte
# level *before* utf-8 decoding so format_string sees real codepoints.
#
# Each pair is the raw DAT byte sequence (FFXIEncoding `table off` byte
# pair XOR'd with 0x80, since the DAT stores text obfuscated). The 0x03
# 0x36 (Ω) case is handled separately because the GM placeholder spam
# uses runs of 7+ omegas and we want to preserve the repeat count.
_OMEGA_RUN = re.compile(rb"(?:\x03\x36){2,}")
# The byte pair \x01\x1a is ambiguous: it can be the obfuscated form of
# FFXIEncoding 0x81 0x9A (★, a decorative char) OR the bytes
# `<0x01 entity-ref><0x1A keyitem param>`. Disambiguate by lookahead:
# when followed by printable ASCII text it's the star, when followed by
# a control byte it's the keyitem-parameter prefix. (7396 has
# \x01\x1a\x01... = keyitem; 8094 has \x01\x1aThe = star.)
_STAR_PATTERN = re.compile(rb"\x01\x1a(?=[\x20-\x7e])")


def _substitute_multibyte(b: bytes) -> bytes:
    b = _OMEGA_RUN.sub(lambda m: "Ω".encode("utf-8") * (len(m.group(0)) // 2), b)
    b = _STAR_PATTERN.sub("★".encode("utf-8"), b)
    return b


def deobfuscate_body(raw_bytes: bytes, encoding: str = "utf-8") -> str:
    """Deobfuscate a raw string payload from a string DAT into unicode.

    Subtracts 0x80 from high bytes (matches the DAT obfuscation for
    standard ASCII text), substitutes known FFXIEncoding multi-byte
    chars (Ω, ★) at the byte level since their obfuscated forms are
    low bytes that subtract leaves untouched, then UTF-8 decodes.
    """
    sub = bytes(b - 0x80 if b >= 0x80 else b for b in raw_bytes).rstrip(b"\x00")
    sub = _substitute_multibyte(sub)
    return sub.decode(encoding, errors="replace")


# Codepoints above ASCII that format_string keeps in the decoded text
# (everything else >= 0x80 falls through to the drop branch).
_KEEP_UNICODE = {ord("Ω"), ord("★")}


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
            text = deobfuscate_body(raw_data[start_pos:end_pos], encoding=encoding)
            strings.append(ParsedString(index=i, offset=offset, text=text))
        except Exception as e:
            logger.debug("Failed to decode string at offset {}: {}", offset, e)

    return ParsedStringDat(entry_count=entry_count, strings=strings)


def parse_string_dat_english(file_path: str | Path) -> ParsedStringDat:
    return parse_string_dat(file_path, encoding="utf-8")


def _skip(pos: int, text: str, n: int) -> int:
    return min(pos + n, len(text))


def format_string(text: str) -> str:
    """Strip FFXI control codes, insert LSB-style placeholders.

    Byte→annotation mapping replicates POLUtils SimpleStringTableEntry.cs.
    Output uses the same placeholder vocabulary as LSB IDs.lua text comments
    (`<item>`, `<keyitem>`, `<player>`, `<name>`, `<number>`).

    The 0x7F 0x00 0x01 0x01 0x05 <id4> 0x00 substitution sequence (used in
    "Obtained: <item>." style strings) doesn't tag item-vs-keyitem in the
    bytes — POLUtils itself can't distinguish — so it falls through to '%'.
    LSB's curated tag for those rows is recoverable only via context.
    """
    result = []
    pos = 0
    in_selection = False

    while pos < len(text):
        b = ord(text[pos])

        if b == 0x07:
            # 0x07 is line-break / wide-bracket marker / selection
            # separator / ordinal marker depending on the next byte.
            nxt = ord(text[pos + 1]) if pos + 1 < len(text) else None
            if nxt in _ORDINAL_07 and text[pos + 2 : pos + 4] == _ORDINAL_07[nxt]:
                # Real ordinal ('2nd', '3rd'): emit a separator space
                # (the 0x07 sits between the previous content and the
                # ordinal so the rendered text reads "X 2nd Y") and
                # consume only the 0x07 itself — the digit follows.
                result.append(" ")
                pos += 1
            elif nxt in _ORDINAL_07:
                # Wide-bracket marker (0x07 0x32 / 0x07 0x33): drop both.
                pos += 2
            else:
                # Lone 0x07 — '/' inside a selection block, ' ' otherwise.
                result.append("/" if in_selection else " ")
                pos += 1

        elif b == 0x7F:
            # POLUtils 0x7F dispatch (DialogTableEntry / SimpleStringTableEntry).
            if pos + 1 >= len(text):
                pos += 1
                continue
            sub = ord(text[pos + 1])
            consume, opens = _SUB_7F_DISPATCH.get(sub, _SUB_7F_DEFAULT)
            if opens:
                result.append("[/")
                in_selection = True
            elif sub == 0x31:
                in_selection = False
            pos = _skip(pos, text, consume)

        elif b == 0x01:
            # 0x01..0x02 is a generic entity-ref substitution. The actual
            # semantic type at this byte sequence varies by game context
            # (LSB tags it as <item>, <keyitem>, <player>, or <name> case
            # by case) — not derivable from bytes alone. Emit '%' as the
            # ambiguous placeholder.
            found = False
            for j in range(pos + 1, min(pos + 14, len(text))):
                if ord(text[j]) == 0x02:
                    if j > pos + 1:
                        # Always emit a placeholder for non-empty entity refs.
                        # (Old code skipped emit when the prior byte was 0x29
                        # which dropped the '%' for item-with-quantity refs
                        # like 'You obtain <number> <item>!')
                        result.append("%")
                    pos = min(j + 4, len(text))
                    found = True
                    break
            if not found:
                prev = ord(text[pos - 1]) if pos > 0 else 0
                if prev in (0x05, 0x08, 0x0A, 0x11, 0x1C):
                    pos += 1
                else:
                    pos += 2

        elif b in _SEMANTIC_CODES:
            placeholder, length = _SEMANTIC_CODES[b]
            result.append(placeholder)
            pos = _skip(pos, text, length)

        elif b in _GENERIC_PERCENT_CODES:
            result.append("%")
            pos += 1

        elif b in _SILENT_CODES:
            pos = _skip(pos, text, _SILENT_CODES[b])

        elif 0x20 <= b < 0x7F or b in _KEEP_UNICODE:
            result.append(text[pos])
            pos += 1

        else:
            pos += 1

    raw = re.sub(r" +", " ", "".join(result))
    return "".join(c for c in raw if ord(c) >= 0x20).strip()
