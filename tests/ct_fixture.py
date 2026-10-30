"""Certificate log entries built by hand, for the Domain watch tests."""
import struct


def der(tag, body):
    n = len(body)
    if n < 0x80:
        return bytes([tag, n]) + body
    size = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(size)]) + size + body


def tbs(names, extra_ext=b""):
    san = der(0x30, b"".join(der(0x82, n.encode()) for n in names))
    ext = der(0x30, der(0x06, bytes.fromhex("551d11")) + der(0x04, san))
    other = der(0x30, der(0x06, bytes.fromhex("551d13")) + der(0x04, der(0x30, b"")))
    junk = der(0x30, b"")
    return der(0x30, der(0xA0, der(0x02, b"\x02")) + der(0x02, b"\x01") + junk + junk + junk + junk + junk
               + der(0xA3, der(0x30, other + extra_ext + ext)))


def u24(b):
    return len(b).to_bytes(3, "big") + b


def leaf(names, ts=1_800_000_000_000, precert=True):
    body = tbs(names)
    out = struct.pack(">QH", ts, 1 if precert else 0)
    if precert:
        out += b"\x11" * 32 + u24(body) + b"\x00\x00" + u24(b"fake-precert") + struct.pack(">H", 32) + b"\x22" * 32
    else:
        out += u24(der(0x30, body + der(0x30, b"") + der(0x03, b"\x00"))) + b"\x00\x00" + struct.pack(">H", 0)
    return out
