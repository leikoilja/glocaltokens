"""Network utilities."""

from __future__ import annotations

from ipaddress import IPv4Address


def is_valid_ipv4_address(address: str) -> bool:
    """Check if ip address is ipv4."""
    try:
        IPv4Address(address)
    except ValueError:
        return False
    return True
