"""FFXI BitmapA → PNG converter, shared by items and statuses."""

import io
import struct


def bitmap_a_to_png(raw: bytes) -> bytes | None:
    """Convert a FFXI BitmapA-tagged blob to PNG bytes.

    Tagged BitmapA layout:
        1 byte image_type (0x91 = BitmapA)
        8 bytes category text (e.g. "iconst00", "sts_icon")
        8 bytes id text
        40 bytes BITMAPINFOHEADER
        — 8 bpp:  256 * 4 bytes palette (BGRA) + width*height paletted pixels
        — 32 bpp: width*height*4 bytes BGRA pixels (no palette)
        Pixels stored bottom-up.

    For 8 bpp icons palette index 0 is FFXI's transparent color by convention.

    Returns the encoded PNG, or None if the input isn't recognizable BitmapA.
    """
    if not raw or raw[0] != 0x91 or len(raw) < 57:
        return None

    width = struct.unpack_from("<I", raw, 21)[0]
    height = struct.unpack_from("<I", raw, 25)[0]
    bit_count = struct.unpack_from("<H", raw, 31)[0]

    if width == 0 or height == 0:
        return None

    from PIL import Image

    if bit_count == 8:
        palette_offset = 57
        palette_bytes = raw[palette_offset : palette_offset + 256 * 4]
        pixel_offset = palette_offset + 256 * 4
        pixel_bytes = raw[pixel_offset : pixel_offset + width * height]
        if len(pixel_bytes) != width * height or len(palette_bytes) != 1024:
            return None

        rgb_palette = bytearray(256 * 3)
        for i in range(256):
            b, g, r, _ = palette_bytes[i * 4 : i * 4 + 4]
            rgb_palette[i * 3 : i * 3 + 3] = bytes([r, g, b])

        img = Image.frombytes("P", (width, height), pixel_bytes)
        img.putpalette(bytes(rgb_palette))
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
        img.info["transparency"] = 0

    elif bit_count == 32:
        pixel_offset = 57
        pixel_bytes = raw[pixel_offset : pixel_offset + width * height * 4]
        if len(pixel_bytes) != width * height * 4:
            return None
        # Stored as BGRA; PIL wants RGBA. Swap channels.
        rgba = bytearray(len(pixel_bytes))
        for i in range(0, len(pixel_bytes), 4):
            b, g, r, a = pixel_bytes[i : i + 4]
            rgba[i : i + 4] = bytes([r, g, b, a])
        img = Image.frombytes("RGBA", (width, height), bytes(rgba))
        img = img.transpose(Image.FLIP_TOP_BOTTOM)

    else:
        return None

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
