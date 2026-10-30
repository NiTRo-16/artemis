"""Reads public certificate logs in the tile format (static-ct-api): which names each new certificate covers.

Everything in a log is untrusted input: anyone can get a certificate logged. The reader never trusts a length,
and a malformed entry is counted and skipped, never fatal.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

TILE_ENTRIES = 256
USER_AGENT = "ArtemisDomainWatch/1.0 (+https://artemissecure.co.in; artemis_secure@gmail.com)"
SAN_OID = bytes.fromhex("551d11")   # 2.5.29.17, subjectAltName
MAX_NAMES = 200                     # a certificate listing more is cut off here

# Each log only takes certificates that expire within its period, so a new half-year needs adding as time
# passes (tests/test_watch_read.py fails when it's due): (name, monitoring URL, end of the period).
LOGS: list[tuple[str, str, str]] = [
    ("sycamore2026h2", "https://mon.sycamore.ct.letsencrypt.org/2026h2/", "2027-01-01"),
    ("sycamore2027h1", "https://mon.sycamore.ct.letsencrypt.org/2027h1/", "2027-07-01"),
    ("sycamore2027h2", "https://mon.sycamore.ct.letsencrypt.org/2027h2/", "2028-01-01"),
    ("willow2026h2", "https://mon.willow.ct.letsencrypt.org/2026h2/", "2027-01-01"),
    ("willow2027h1", "https://mon.willow.ct.letsencrypt.org/2027h1/", "2027-07-01"),
    ("willow2027h2", "https://mon.willow.ct.letsencrypt.org/2027h2/", "2028-01-01"),
]


@dataclass
class Entry:
    timestamp_ms: int
    names: list[str]


def tile_path(index: int) -> str:
    """005, x001/234, x004/x105/756: groups of three digits, all but the last prefixed with x."""
    digits = str(index)
    digits = digits.zfill(3 * ((len(digits) + 2) // 3))
    groups = [digits[i:i + 3] for i in range(0, len(digits), 3)]
    return "/".join(["x" + g for g in groups[:-1]] + [groups[-1]])


def parse_checkpoint(text: str) -> int:
    """The log's current size: the second line of its signed checkpoint."""
    return int(text.split("\n")[1])


def _read_der(buf: bytes, pos: int) -> tuple[int, int, int] | None:
    """(tag, start of content, end of content) of the element at pos, or None if it doesn't fit in buf."""
    if pos + 2 > len(buf):
        return None
    tag, first = buf[pos], buf[pos + 1]
    pos += 2
    if first < 0x80:
        length = first
    else:
        count = first & 0x7F
        if count == 0 or count > 4 or pos + count > len(buf):
            return None
        length = int.from_bytes(buf[pos:pos + count], "big")
        pos += count
    if pos + length > len(buf):
        return None
    return tag, pos, pos + length


def _children(buf: bytes, start: int, end: int) -> list[tuple[int, int, int]]:
    out, pos, view = [], start, buf[:end]
    while pos < end:
        element = _read_der(view, pos)
        if element is None:
            break
        out.append(element)
        pos = element[2]
    return out


def names_from_tbs(tbs: bytes) -> list[str]:
    """The DNS names in a TBSCertificate's subjectAltName extension."""
    top = _read_der(tbs, 0)
    if top is None or top[0] != 0x30:
        return []
    for tag, start, end in _children(tbs, top[1], top[2]):
        if tag != 0xA3:     # [3] extensions
            continue
        wrapper = _read_der(tbs[:end], start)
        if wrapper is None:
            return []
        for ext_tag, ext_start, ext_end in _children(tbs, wrapper[1], wrapper[2]):
            fields = _children(tbs, ext_start, ext_end) if ext_tag == 0x30 else []
            if len(fields) < 2 or tbs[fields[0][1]:fields[0][2]] != SAN_OID:
                continue
            value = fields[-1]   # an optional "critical" flag can sit between the name and the value
            inner = _read_der(tbs[:value[2]], value[1])
            if inner is None:
                return []
            names = []
            for name_tag, name_start, name_end in _children(tbs, inner[1], inner[2])[:MAX_NAMES]:
                if name_tag == 0x82:   # [2] dNSName
                    raw = tbs[name_start:name_end]
                    if raw.isascii():
                        names.append(raw.decode("ascii").lower())
            return names
    return []


def _tbs_of_certificate(cert: bytes) -> bytes:
    outer = _read_der(cert, 0)
    inner = outer and _read_der(cert[:outer[2]], outer[1])
    return cert[outer[1]:inner[2]] if inner else b""


def _u24(buf: bytes, pos: int) -> tuple[bytes, int]:
    size = int.from_bytes(buf[pos:pos + 3], "big")
    end = pos + 3 + size
    if pos + 3 > len(buf) or end > len(buf):
        raise ValueError("length runs past the end")
    return buf[pos + 3:end], end


def _u16(buf: bytes, pos: int) -> tuple[bytes, int]:
    if pos + 2 > len(buf):
        raise ValueError("length runs past the end")
    end = pos + 2 + struct.unpack_from(">H", buf, pos)[0]
    if end > len(buf):
        raise ValueError("length runs past the end")
    return buf[pos + 2:end], end


def parse_tile(data: bytes) -> tuple[list[Entry], int]:
    """(entries, malformed count). Entries sit end to end, so one bad length means the rest can't be found."""
    entries: list[Entry] = []
    pos = 0
    while pos < len(data):
        try:
            if pos + 10 > len(data):
                raise ValueError("too short")
            timestamp, kind = struct.unpack_from(">QH", data, pos)
            pos += 10
            if kind == 0:       # certificate
                cert, pos = _u24(data, pos)
                tbs = _tbs_of_certificate(cert)
                _, pos = _u16(data, pos)        # extensions
            elif kind == 1:     # precertificate
                if pos + 32 > len(data):
                    raise ValueError("too short")
                tbs, pos = _u24(data, pos + 32)
                _, pos = _u16(data, pos)        # extensions
                _, pos = _u24(data, pos)        # the precertificate itself
            else:
                raise ValueError("unknown entry type")
            _, pos = _u16(data, pos)            # fingerprints of the issuer chain
        except (ValueError, struct.error):
            return entries, 1
        entries.append(Entry(timestamp, names_from_tbs(tbs)))
    return entries, 0
