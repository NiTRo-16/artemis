"""Which network addresses Artemis may connect to on a user's behalf.

Used by the scanner and the headless browser so both apply the same rule: only public addresses.
"""
from __future__ import annotations

import ipaddress

# IPv6 prefixes that carry an IPv4 address inside them (RFC 6052 NAT64). On networks with NAT64,
# connecting to 64:ff9b::7f00:1 reaches 127.0.0.1, yet Python reports these prefixes as global.
NAT64_PREFIXES = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))


def embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address an IPv6 address stands for (mapped, NAT64, 6to4 or Teredo), if any."""
    if ip.ipv4_mapped:
        return ip.ipv4_mapped
    if any(ip in net for net in NAT64_PREFIXES):
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if ip.sixtofour:
        return ip.sixtofour
    if ip.teredo:
        return ip.teredo[1]
    return None


def is_public_ip(address: str) -> bool:
    """True only for globally routable addresses, including any IPv4 hidden inside an IPv6 one."""
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        inner = embedded_ipv4(ip)
        if inner is not None:
            return inner.is_global
    return ip.is_global
