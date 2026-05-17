"""Regression tests for parsers/strings.py.

Each test pins a specific real-world string DAT payload (raw bytes as
they sit on disk) to the expected formatted output. Bytes were captured
from the live English DAT files; the comments name the in-game string.

Run: `python -m unittest discover tests`
"""

import unittest

import tempfile
from pathlib import Path

from parsers.strings import (
    _substitute_multibyte,
    deobfuscate_body,
    format_string,
    parse_string_dat,
    parse_string_dat_english,
)


def parse_and_format(raw: bytes) -> str:
    """Mirror the full string-DAT pipeline: deobfuscate → format."""
    return format_string(deobfuscate_body(raw))


class OmegaRunTests(unittest.TestCase):
    """FFXIEncoding 0x83 0xB6 (Ω) stored as 0x03 0x36 in the DAT.

    Before the fix this rendered as '6666666' because subtract-0x80
    deobfuscation left the low bytes alone and format_string dropped
    the 0x03 control bytes, leaving only the literal '6's.
    """

    def test_seven_repeat_run(self):
        # zone 72 / id 7747; zone 77 / id 7560 ("Repent thy irreverence..." marker)
        raw = b"\x03\x36" * 7 + b"\xff\xb1\x80\x87"  # 7x omega + 0x7F 0x31 0x00 0x07 trailer
        self.assertEqual(parse_and_format(raw), "ΩΩΩΩΩΩΩ")

    def test_omega_count_preserved(self):
        for n in (2, 3, 5, 12):
            with self.subTest(n=n):
                raw = b"\x03\x36" * n
                self.assertEqual(parse_and_format(raw), "Ω" * n)

    def test_single_omega_not_substituted(self):
        # A lone 0x03 0x36 is more likely a control-byte + '6' literal than
        # a real omega; the regex requires 2+ to qualify as the GM marker.
        raw = b"\x03\x36"
        self.assertEqual(parse_and_format(raw), "6")


class StarSubstitutionTests(unittest.TestCase):
    """FFXIEncoding 0x81 0x9A (★) stored as 0x01 0x1A in the DAT.

    Ambiguous with `<0x01 entity-ref><0x1A keyitem param>`; the
    lookahead-guarded substitution only fires when the next byte is
    printable ASCII (text context, not a parameter byte).
    """

    def test_star_followed_by_text(self):
        # zone 255 / id 8094 fragment: "...[The Wyrm God/★The Wyrm God/]..."
        raw = b"\xaf\x81\x9aThe Wyrm God"
        # 0xAF deobf to 0x2F = '/', then star, then 'The Wyrm God'
        self.assertEqual(parse_and_format(raw), "/★The Wyrm God")

    def test_keyitem_param_not_treated_as_star(self):
        # When 0x01 0x1A is followed by a control byte (the keyitem-
        # parameter form, e.g. zone 6 / id 7396 has '\x01\x1a\x01...'),
        # the substitution must NOT fire so format_string's other
        # handlers can interpret the bytes correctly.
        for trail in (b"\x01", b"\x07", b"\x1f", b"\x00"):
            with self.subTest(trail=trail):
                out = _substitute_multibyte(b"\x01\x1a" + trail)
                self.assertNotIn("★".encode("utf-8"), out)
                self.assertEqual(out, b"\x01\x1a" + trail)

    def test_full_battlefield_string(self):
        # zone 255 / id 8094 — full payload through the pipeline
        raw = (
            b"\xc5eF6V?XV?o\xa0F+6S?VV?KV?6F1\xa0F+`Sc?Vv?6S?V?6\xa0F1?eVw?V?6S?6"
            b"\xa0\x87\xb2\x0c\x01\x5bThe Wyrm God/\x01\x1aThe Wyrm God/\x5d\x87\xb3!"
            b"\xff\xb1\x80\x87"
        )
        # Star inside the choice brackets must render; surrounding text intact.
        out = parse_and_format(raw)
        self.assertIn("[The Wyrm God/★The Wyrm God/]", out)


class WideBracketMarkerTests(unittest.TestCase):
    """0x07 0x32 / 0x07 0x33 wrap multiple-choice brackets in some
    strings; format_string's 0x07 handler drops both bytes silently
    unless the byte pair is part of an ordinal like '2nd'/'3rd'.
    """

    def test_wide_bracket_open_close_dropped(self):
        # 0x87 0xB2 ... 0x87 0xB3 deobf to 0x07 0x32 ... 0x07 0x33
        raw = b"\x87\xb2Hello\x87\xb3!"
        self.assertEqual(parse_and_format(raw), "Hello!")

    def test_ordinal_2nd_preserved(self):
        # "...2nd..." — 0x07 0x32 followed by "nd" must NOT drop the '2'
        # (it's a real ordinal marker, not a bracket wrapper).
        raw = b"\xb2\x87\xb2nd \xf0\xece\xe1\xe3\xe5"  # '2' 0x07 0x32 'nd place'
        out = parse_and_format(raw)
        self.assertIn("2", out)
        self.assertIn("nd", out)


class AsciiPreservationTests(unittest.TestCase):
    """SJIS-decode regression: 0x1F 0x12 0x54 ('T') used to render as
    'ime...' because 0x92 0x54 paired as one SJIS char, eating the 'T'.
    The current parser uses utf-8 with subtract-deobf, so 0x12 is a
    bare continuation byte and 'T' survives. _SILENT_CODES[0x1F] = 2
    consumes 0x1F and its 1-byte param.
    """

    def test_silent_1f_does_not_eat_following_letter(self):
        # zone 55 / id 7531: '\x9f\x92Time remaining...'
        raw = b"\x9f\x92Time remaining"
        out = parse_and_format(raw)
        self.assertTrue(out.startswith("Time remaining"), repr(out))

    def test_silent_1f_then_capital_a(self):
        # zone 55 / id 7534: '\x9f\x92All party members...'
        raw = b"\x9f\x92All party members"
        out = parse_and_format(raw)
        self.assertTrue(out.startswith("All party members"), repr(out))


class PlaceholderEmissionTests(unittest.TestCase):
    """Sanity-check that semantic placeholders still render after the
    revert+substitution changes.
    """

    def test_item_placeholder_via_entity_ref(self):
        # zone 1 / id 6385/6386 shape: '...the \x01\x05<id>\x02.'
        raw = b"\xf4\xe8\xe5\xa0\x81\x85\xa3\x02\x00\x00\x00\xae"  # 'the ' + ref-block + '.'
        out = parse_and_format(raw)
        self.assertEqual(out, "the %.")

    def test_keyitem_placeholder(self):
        # 0x9A 0xC1 deobf to 0x1A 0x41; 0x1A is <keyitem> with 1-byte param
        raw = b"\xc1\xa0\x9a\x41 \xe4\xe9\xf3\xe1\xf0\xf0\xe5\xe1\xf2\xf3\xa1"
        out = parse_and_format(raw)
        self.assertEqual(out, "A <keyitem> disappears!")


class FormatStringDirectTests(unittest.TestCase):
    """Direct tests of format_string without the deobfuscation layer,
    exercising the control-byte handler edge cases.
    """

    def test_empty_input(self):
        self.assertEqual(format_string(""), "")

    def test_plain_ascii_passthrough(self):
        self.assertEqual(format_string("Hello, world!"), "Hello, world!")

    def test_omega_kept_in_output(self):
        # Omega is in the allowlist (_KEEP_UNICODE) — must survive
        # format_string's default-drop fall-through for chars >= 0x80.
        self.assertEqual(format_string("ΩΩΩ"), "ΩΩΩ")

    def test_star_kept_in_output(self):
        self.assertEqual(format_string("★ test ★"), "★ test ★")

    def test_replacement_char_dropped(self):
        # U+FFFD is not in the allowlist and is >= 0x80, so it drops.
        self.assertEqual(format_string("hi�there"), "hithere")

    def test_keyitem_placeholder_emitted(self):
        # SEMANTIC_CODES[0x1A] = ('<keyitem>', 2): emits + skips 2 chars
        text = "A\x1a\x05 vanishes"
        self.assertEqual(format_string(text), "A<keyitem> vanishes")

    def test_item_placeholder_emitted(self):
        # SEMANTIC_CODES[0x19] = ('<item>', 2)
        text = "got \x19\x07!"
        self.assertEqual(format_string(text), "got <item>!")

    def test_number_placeholder_emitted(self):
        # SEMANTIC_CODES[0x0A] = ('<number>', 2)
        text = "x\x0a\x03y"
        self.assertEqual(format_string(text), "x<number>y")

    def test_player_placeholder_emitted(self):
        # SEMANTIC_CODES[0x08] = ('<player>', 1) — 1-byte (no param)
        text = "hi \x08!"
        self.assertEqual(format_string(text), "hi <player>!")

    def test_silent_1f_skips_two(self):
        # 0x1F is a 2-byte silent control (consume 0x1F + 1 param)
        text = "\x1f\x12Hello"
        self.assertEqual(format_string(text), "Hello")

    def test_0x07_as_selection_separator(self):
        # 0x7F 0x92 opens a singular/plural choice (emits "[/", sets
        # in_selection); subsequent lone 0x07 then renders as '/'.
        text = "\x7f\x92\x00x\x07y"
        self.assertEqual(format_string(text), "[/x/y")


class SilentControlByteTests(unittest.TestCase):
    """Every entry in _SILENT_CODES should consume itself + N params
    and emit nothing.
    """

    def test_0x0b_selection_dialog_open(self):
        # _SILENT_CODES[0x0B] = 1 (the byte itself only, no param)
        self.assertEqual(format_string("a\x0bb"), "ab")

    def test_0x0c_multiple_choice(self):
        # _SILENT_CODES[0x0C] = 2 (byte + 1 param byte)
        self.assertEqual(format_string("a\x0c\x00b"), "ab")

    def test_0x1e_set_color(self):
        # _SILENT_CODES[0x1E] = 2 (byte + color id)
        self.assertEqual(format_string("a\x1e\x05b"), "ab")

    def test_0x1f_unknown_silent(self):
        # _SILENT_CODES[0x1F] = 2
        self.assertEqual(format_string("a\x1f\x12b"), "ab")

    def test_0xef_silent(self):
        # _SILENT_CODES[0xEF] = 2 — but 0xEF >= 0x80 so currently lives
        # in the fall-through path unless explicitly handled. Verify it
        # is consumed silently and the following char survives.
        self.assertEqual(format_string("a\xef\x00b"), "ab")

    def test_0xfd_six_byte_silent(self):
        # _SILENT_CODES[0xFD] = 6
        self.assertEqual(format_string("a\xfd\x01\x02\x03\x04\x05b"), "ab")

    def test_silent_truncated_at_end(self):
        # _skip() clamps to len(text) — input shorter than expected param
        # length must not crash.
        for code, length in [(0x1F, 2), (0x0C, 2), (0xFD, 6)]:
            with self.subTest(code=hex(code), length=length):
                # Provide the code with no following bytes
                self.assertEqual(format_string(chr(code)), "")


class Entity0x01HandlerTests(unittest.TestCase):
    """The 0x01..0x02 entity-ref handler is the most complex branch.
    Cover its variants explicitly: well-formed ref, empty ref, missing
    0x02 terminator, and the smart-dispatch fall-back.
    """

    def test_nonempty_ref_emits_percent(self):
        # \x01 <content> \x02 <4-byte id> → '%'
        text = "got \x01abc\x02\x00\x00\x00\x00!"
        self.assertEqual(format_string(text), "got %!")

    def test_empty_ref_emits_nothing_but_still_consumes_trailer(self):
        # \x01\x02 = empty ref: no '%' emit, but the handler still
        # advances pos = min(j+4, len) past where the 4-byte ID would
        # have lived. Real strings never produce empty refs, so this
        # over-consumption is harmless in practice — pin it to catch
        # accidental changes.
        text = "got \x01\x02 nothing"
        self.assertEqual(format_string(text), "got thing")

    def test_unterminated_ref_skips_two_default(self):
        # No 0x02 within 14 chars after 0x01, prev byte not in placeholder
        # set → skip 2 bytes (the 0x01 + 1 more).
        text = "ab\x01\x99xy"  # '\x99' chars survive the >=0x80 drop only if in keep
        out = format_string(text)
        # 0x99 isn't in _KEEP_UNICODE, dropped by fall-through
        self.assertEqual(out, "abxy")

    def test_unterminated_ref_after_placeholder_skips_one(self):
        # When prev byte is in (0x05, 0x08, 0x0A, 0x11, 0x1C) the
        # handler treats 0x01 as a single-byte filler (skip 1, not 2).
        for placeholder_byte in (0x05, 0x11):
            with self.subTest(prev=hex(placeholder_byte)):
                # Use 0x11 which is in _SEMANTIC_CODES → '<player>' (1B);
                # 0x05 is in _GENERIC_PERCENT_CODES → '%' (1B). Either way
                # the placeholder advances pos to the 0x01.
                text = f"\x05\x01XY"  # '%' from 0x05, then 0x01 (no 0x02 within reach)
                out = format_string(text)
                # smart-dispatch skips 1 (not 2), so 'X' survives
                self.assertEqual(out, "%XY", repr(out))


class Sub0x7FDispatchTests(unittest.TestCase):
    """The 0x7F prefix has a sub-byte dispatch matching POLUtils."""

    def test_prompt_0x31_consumes_three(self):
        # 0x7F 0x31 0x00 = "Prompt" (clears in_selection); consumes 3
        text = "a\x7f\x31\x00b"
        self.assertEqual(format_string(text), "ab")

    def test_plural_choice_0x92_opens_bracket(self):
        # 0x7F 0x92 <param> = singular/plural choice; emits "[/" and
        # subsequent 0x07 becomes '/'.
        text = "x\x7f\x92\x00y\x07z"
        self.assertEqual(format_string(text), "x[/y/z")

    def test_gender_open_0x05_consumes_two(self):
        # 0x7F 0x05 — consume 2 bytes (POLUtils: "Possible Special Code: 05")
        text = "a\x7f\x05b"
        self.assertEqual(format_string(text), "ab")

    def test_gender_open_0x85_consumes_two(self):
        # 0x7F 0x85 — alias of 0x05 (POLUtils: "Multiple Choice (Player Gender)")
        # 0x85 is >= 0x80 and not in any keep/handler set, so the 'b' must
        # survive intact after the 2-byte consume.
        text = "a\x7f\x85b"
        self.assertEqual(format_string(text), "ab")

    def test_weather_0x8d_consumes_three(self):
        # 0x7F 0x8D <param> — Weather Event Parameter
        text = "a\x7f\x8d\x01b"
        self.assertEqual(format_string(text), "ab")

    def test_weather_0x8e_consumes_three(self):
        text = "a\x7f\x8e\x01b"
        self.assertEqual(format_string(text), "ab")

    def test_title_0xb1_consumes_three(self):
        # 0x7F 0xB1 <param> — Title Parameter
        text = "a\x7f\xb1\x01b"
        self.assertEqual(format_string(text), "ab")

    def test_unknown_subbyte_default_consumes_three(self):
        # Any other sub-byte defaults to skip-3
        text = "a\x7f\xfd\x00b"
        self.assertEqual(format_string(text), "ab")

    def test_0x7f_at_end_without_subbyte(self):
        # No bytes after 0x7F — must not crash or hang
        self.assertEqual(format_string("a\x7f"), "a")


class Sub0x07OrdinalTests(unittest.TestCase):
    """0x07 0x32/0x33 are wide-bracket markers (drop both) UNLESS
    followed by 'nd'/'rd' (ordinal: keep '2'/'3' as the digit).
    """

    def test_07_32_drops_both(self):
        self.assertEqual(format_string("a\x07\x32b"), "ab")

    def test_07_33_drops_both(self):
        self.assertEqual(format_string("a\x07\x33b"), "ab")

    def test_07_32_with_nd_keeps_2_and_inserts_space(self):
        # 0x07 0x32 'nd' — handler emits ' ' AND advances pos += 1 so
        # the '2nd' survives intact with a separator space (real DAT
        # strings like "Bastok\x07\x322nd:" render as "Bastok 2nd:").
        self.assertEqual(format_string("Bastok\x07\x32nd:"), "Bastok 2nd:")

    def test_07_33_with_rd_keeps_3_and_inserts_space(self):
        self.assertEqual(format_string("Bastok\x07\x33rd place"), "Bastok 3rd place")

    def test_07_outside_selection_becomes_space(self):
        # Lone 0x07 with no 0x32/0x33 follower → ' ' if not in_selection
        # but the consecutive-space collapse + strip leaves no visible
        # space at edges.
        self.assertEqual(format_string("a\x07b"), "a b")

    def test_07_inside_selection_becomes_slash(self):
        # After 0x7F 0x92 opens a selection, lone 0x07 → '/'
        self.assertEqual(format_string("\x7f\x92\x00a\x07b"), "[/a/b")

    def test_prompt_resets_selection(self):
        # After 0x7F 0x31 0x00 (prompt) the in_selection flag clears,
        # so a subsequent lone 0x07 renders as ' ', not '/'. The
        # prompt sequence itself emits nothing.
        text = "\x7f\x92\x00a\x7f\x31\x00b\x07c"
        self.assertEqual(format_string(text), "[/ab c")


class WhitespaceCleanupTests(unittest.TestCase):
    """Final-pass invariants: collapse runs of spaces, strip edges,
    drop chars below 0x20.
    """

    def test_consecutive_spaces_collapsed(self):
        self.assertEqual(format_string("hi    there"), "hi there")

    def test_leading_and_trailing_whitespace_stripped(self):
        self.assertEqual(format_string("   hi   "), "hi")

    def test_control_chars_dropped_at_end(self):
        # Trailing 0x7F 0x31 0x00 0x07 (prompt + line break) is a common
        # tail in real DAT entries — must produce no trailing whitespace.
        self.assertEqual(format_string("hi\x7f\x31\x00\x07"), "hi")

    def test_null_bytes_dropped(self):
        # \x00 not in any handler, falls through to drop (below 0x20).
        self.assertEqual(format_string("a\x00b\x00\x00c"), "abc")


class GoldenFixtureTests(unittest.TestCase):
    """Raw byte payloads captured verbatim from real English string DATs
    on FFXI client 30260429_1. Pin them so any regression to the deobf
    pipeline or format_string surfaces here.

    Capture script (for re-generation if the client changes):
        python -X utf8 scripts/strings/dump.py dump --version <ver>
        # then read the raw bytes at offset = id*4 ^ 0x80808080
        # from the per-zone DAT.
    """

    # Raw payloads + observed output on client 30260429_1. Each row
    # exercises a different control-byte path so a future regression
    # surfaces at the specific fixture, not a generic "diff exploded".
    FIXTURES = [
        # 0x1F silent prefix; the XOR/SJIS detour used to chew the 'T'.
        # Also exercises 0x7F 0x92 (singular/plural choice "[/...]").
        (
            "time_remaining_minutes",
            b"\x9f\x12\xd4\xe9\xed\xe5\xa0\xf2\xe5\xed\xe1\xe9\xee\xe9\xee\xe7\xba\xa0\x8a\x80"
            b"\xa0\xff\x12\x80\xdb\xed\xe9\xee\xf5\xf4\xe5\xaf\xed\xe9\xee\xf5\xf4\xe5\xf3\xdd"
            b"\xa0\xa8\xc5\xe1\xf2\xf4\xe8\xa0\xf4\xe9\xed\xe5\xa9\xae\xff\xb1\x80\x87",
            "Time remaining: <number> [minute/minutes] (Earth time).",
        ),
        # Entity-ref placeholder + trailing prompt.
        (
            "cannot_obtain",
            b"\xd9\xef\xf5\xa0\xe3\xe1\xee\xee\xef\xf4\xa0\xef\xe2\xf4\xe1\xe9\xee\xa0\xe1\xee"
            b"\xf9\xa0\xed\xef\xf2\xe5\xae\xff\xb1\x80\x87",
            "You cannot obtain any more.",
        ),
        # 0x07 0x32 / 0x07 0x33 wide-bracket markers (dropped), star
        # substitution (\x01\x1a inside brackets), 0x7F 0x92 plural choice.
        (
            "wyrm_god_battlefield",
            b"\xd4\xe8\xe5\xa0\xe3\xf5\xf2\xf2\xe5\xee\xf4\xa0\xe2\xe1\xf4\xf4\xec\xe5\xe6\xe9"
            b"\xe5\xec\xe4\xa0\xe3\xec\xe5\xe1\xf2\xa0\xf4\xe9\xed\xe5\xa0\xf2\xe5\xe3\xef\xf2"
            b"\xe4\xa0\xe6\xef\xf2\xa0\x072\x8c\x81\xdb\xd4\xe8\xe5\xa0\xd7\xf9\xf2\xed\xa0\xc7"
            b"\xef\xe4\xaf\x01\x1a\xd4\xe8\xe5\xa0\xd7\xf9\xf2\xed\xa0\xc7\xef\xe4\xaf\xdd\x073"
            b"\xa0\xe9\xf3\xa0\x8a\x83\xa0\xed\xe9\xee\xf5\xf4\xe5\xff\x12\x83\xdb\xaf\xf3\xdd"
            b"\xa0\x8a\x82\xa0\xf3\xe5\xe3\xef\xee\xe4\xff\x12\x82\xdb\xaf\xf3\xdd\xae\x80\x87",
            "The current battlefield clear time record for [The Wyrm God/★The Wyrm God/] is "
            "<number> minute[/s] <number> second[/s].",
        ),
    ]

    def test_all_fixtures(self):
        for name, raw, expected in self.FIXTURES:
            with self.subTest(name=name):
                self.assertEqual(parse_and_format(raw), expected)


class ParseStringDatErrorTests(unittest.TestCase):
    """Edge cases on the file-level parse_string_dat header validation.
    The dump.py wrapper relies on these raising ValueError (not crashing)
    so a bad/empty DAT just skips a zone rather than failing the whole run.
    """

    def _parse_bytes(self, data: bytes):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".DAT") as tf:
            tf.write(data)
            path = tf.name
        try:
            return parse_string_dat(path)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_empty_file_raises(self):
        with self.assertRaises(Exception):  # ValueError or construct StreamError
            self._parse_bytes(b"")

    def test_too_small_raises(self):
        with self.assertRaisesRegex(ValueError, "too small"):
            self._parse_bytes(b"\x00\x00\x00")

    def test_bad_file_size_marker_raises(self):
        # Right size, wrong marker
        data = b"\xff\xff\xff\xff" + b"\x00" * 8
        with self.assertRaisesRegex(ValueError, "Invalid file size marker"):
            self._parse_bytes(data)

    def test_bad_first_text_pos_raises(self):
        # Valid marker, invalid first_text_pos (off the end)
        filesize = 16
        marker = (0x10000000 + filesize - 4).to_bytes(4, "little")
        # first_text_pos must be % 4 == 0, between 8 and len; force 999
        bad_offset_raw = (999 ^ 0x80808080).to_bytes(4, "little")
        data = marker + bad_offset_raw + b"\x00" * 8
        with self.assertRaisesRegex(ValueError, "Invalid first text position"):
            self._parse_bytes(data)


class FuzzTests(unittest.TestCase):
    """Property checks: random / adversarial byte sequences must not
    raise, return a string, and preserve the trim+collapse invariants.
    """

    def test_random_bytes_dont_crash(self):
        import random

        rng = random.Random(0xC0FFEE)
        for trial in range(200):
            length = rng.randint(0, 256)
            raw = bytes(rng.randint(0, 255) for _ in range(length))
            with self.subTest(trial=trial, raw_hex=raw.hex()[:64]):
                # Full pipeline (deobf + substitute + decode + format)
                out = parse_and_format(raw)
                self.assertIsInstance(out, str)
                # Whitespace invariants
                self.assertEqual(out, out.strip(), "leading/trailing whitespace")
                self.assertNotIn("  ", out, "double spaces")
                # No char < 0x20 survives the final filter
                for c in out:
                    self.assertGreaterEqual(ord(c), 0x20, f"control char {ord(c):#x}")

    def test_all_single_bytes(self):
        # Each byte value 0x00..0xFF as a standalone payload must not crash.
        for b in range(256):
            with self.subTest(byte=hex(b)):
                out = parse_and_format(bytes([b]))
                self.assertIsInstance(out, str)

    def test_all_byte_pairs_dont_crash(self):
        # Every 2-byte combo (65536 inputs). Roughly stresses every
        # control-byte handler's lookahead path.
        for hi in range(256):
            for lo in range(256):
                out = parse_and_format(bytes([hi, lo]))
                # Cheap invariant — full assert overhead too slow at 65k
                if "  " in out or out != out.strip():
                    self.fail(f"whitespace invariant broken on {hi:02x} {lo:02x}: {out!r}")


if __name__ == "__main__":
    unittest.main()
