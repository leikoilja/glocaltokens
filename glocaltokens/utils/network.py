"""Network utilities."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv6Address


def is_valid_ipv4_address(address: str) -> bool:
    """Check if ip address is ipv4."""
    try:
        IPv4Address(address)
    except ValueError:
        return False
    return True


def is_valid_ipv6_address(address: str) -> bool:
    """Check if ip address is ipv6."""
    try:
        IPv6Address(address)
    except ValueError:
        return False
    return True


def is_valid_port(port: int) -> bool:
    """Check if port is valid."""
    return 0 <= port <= 65535
