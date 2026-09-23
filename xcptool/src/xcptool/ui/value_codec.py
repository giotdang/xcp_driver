"""Text <-> raw-bytes codec for A2L CHARACTERISTIC values — struct.pack
math only, no A2L types, no Qt. Shared by CalibrationView (live ECU
read/write) and HexView (dataset -> hex/s19 patch), so there is exactly one
place that decides how a value's text becomes the bytes written anywhere —
diverging encodings between "write to ECU" and "write to hex file" would be
a real correctness bug.
"""
from __future__ import annotations

import struct

__all__ = ["decode_value", "decode_value_precise", "encode_value"]

_ENDIAN: dict[str, str] = {"little": "<", "big": ">"}
_DTYPE_FMT: dict[str, str] = {
    "UBYTE": "B", "SBYTE": "b",
    "UWORD": "H", "SWORD": "h",
    "ULONG": "I", "SLONG": "i",
    "FLOAT32_IEEE": "f", "FLOAT64_IEEE": "d",
}


def decode_value(data: bytes, datatype: str, byte_order: str, radix: str = "DEC") -> str:
    """Giải mã bytes thành chuỗi đọc được.

    VAL_BLK / array: "v0, v1, v2, …".  VALUE scalar: "v".
    """
    fmt_char = _DTYPE_FMT.get(datatype, "B")
    endian = _ENDIAN.get(byte_order, "<")
    item_size = struct.calcsize(fmt_char)
    if item_size == 0 or len(data) < item_size:
        return "???"
    n = len(data) // item_size
    is_float = datatype.startswith("FLOAT")
    parts: list[str] = []

    for i in range(n):
        chunk = data[i * item_size : (i + 1) * item_size]
        if is_float:
            v = struct.unpack_from(endian + fmt_char, chunk)[0]
            if radix == "HEX":
                int_fmt = "I" if datatype == "FLOAT32_IEEE" else "Q"
                raw_int = struct.unpack_from(endian + int_fmt, chunk)[0]
                parts.append(f"0x{raw_int:0{item_size * 2}X}")
            elif radix == "BIN":
                int_fmt = "I" if datatype == "FLOAT32_IEEE" else "Q"
                raw_int = struct.unpack_from(endian + int_fmt, chunk)[0]
                parts.append(f"0b{raw_int:0{item_size * 8}b}")
            elif radix == "ASCII":
                chars = [chr(b) if 32 <= b <= 126 else "." for b in chunk]
                parts.append("".join(chars))
            else:
                parts.append(f"{v:.6g}")
        else:
            v = struct.unpack_from(endian + fmt_char, chunk)[0]
            if radix == "HEX":
                mask = (1 << (item_size * 8)) - 1
                parts.append(f"0x{v & mask:X}")
            elif radix == "BIN":
                mask = (1 << (item_size * 8)) - 1
                parts.append(f"0b{v & mask:b}")
            elif radix == "ASCII":
                try:
                    parts.append(chr(v) if 32 <= v <= 126 else ".")
                except ValueError:
                    parts.append(str(v))
            else:
                parts.append(str(v))
    return ", ".join(parts)


def decode_value_precise(data: bytes, datatype: str, byte_order: str) -> str:
    """Like `decode_value(data, datatype, byte_order, radix="DEC")` but with full
    round-trip precision for floats (`%.17g` for FLOAT64_IEEE, `%.9g` for
    FLOAT32_IEEE) instead of `decode_value`'s display-only `%.6g` rounding.
    Integer formatting is identical — only used for calibration-dataset export
    (`_gather_dataset_values`), never for on-screen display."""
    fmt_char = _DTYPE_FMT.get(datatype, "B")
    endian = _ENDIAN.get(byte_order, "<")
    item_size = struct.calcsize(fmt_char)
    if item_size == 0 or len(data) < item_size:
        return "???"
    n = len(data) // item_size
    float_fmt = "%.9g" if datatype == "FLOAT32_IEEE" else "%.17g"
    parts: list[str] = []
    for i in range(n):
        chunk = data[i * item_size:(i + 1) * item_size]
        v = struct.unpack_from(endian + fmt_char, chunk)[0]
        parts.append(float_fmt % v if datatype.startswith("FLOAT") else str(v))
    return ", ".join(parts)


def encode_value(text: str, datatype: str, byte_order: str, array_size: int) -> bytes:
    """Mã hoá chuỗi nhập từ người dùng thành bytes để ghi xuống ECU.

    Hỗ trợ cả định dạng số (DEC, HEX, BIN) lẫn ký tự/chuỗi ASCII.

    Raises:
        ValueError: chuỗi không parse được hoặc số lượng phần tử không khớp.
        struct.error: giá trị nằm ngoài khoảng kiểu dữ liệu.
    """
    fmt_char = _DTYPE_FMT.get(datatype)
    if fmt_char is None:
        raise ValueError(f"Unsupported datatype: {datatype}")
    endian = _ENDIAN.get(byte_order, "<")
    item_size = struct.calcsize(fmt_char)
    raw = [p.strip() for p in text.split(",")]
    if len(raw) == 1 and array_size > 1:
        raw = raw * array_size
    if len(raw) != array_size:
        raise ValueError(f"Expected {array_size} values, received {len(raw)}")
    is_float = datatype.startswith("FLOAT")
    buf = bytearray()

    for part in raw:
        if is_float:
            part_lower = part.lower()
            if part_lower.startswith("0x") or part_lower.startswith("0b"):
                int_fmt = "I" if datatype == "FLOAT32_IEEE" else "Q"
                raw_int = int(part, 0)
                buf += struct.pack(endian + int_fmt, raw_int)
            else:
                try:
                    v = float(part)
                    buf += struct.pack(endian + fmt_char, v)
                except ValueError:
                    encoded_bytes = part.encode("latin-1")
                    if len(encoded_bytes) > item_size:
                        raise ValueError(f"ASCII string '{part}' too long for {datatype} (max {item_size} bytes)")
                    padded = encoded_bytes.ljust(item_size, b"\x00") if endian == "<" else encoded_bytes.rjust(item_size, b"\x00")
                    buf += padded
        else:
            try:
                v = int(part, 0)
                buf += struct.pack(endian + fmt_char, v)
            except ValueError:
                # Không phải số (Dec/Hex/Bin) -> parse theo ký tự / chuỗi ASCII
                encoded_bytes = part.encode("latin-1")
                if len(encoded_bytes) > item_size:
                    raise ValueError(f"ASCII string '{part}' too long for {datatype} (max {item_size} bytes)")
                padded = encoded_bytes.ljust(item_size, b"\x00") if endian == "<" else encoded_bytes.rjust(item_size, b"\x00")
                buf += padded

    return bytes(buf)
