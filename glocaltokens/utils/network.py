"""Network utilities"""
from __future__ import annotations

import socket


def is_valid_ipv4_address(address: str) -> bool:
    """Check if ip address is ipv4"""
    try:
        socket.inet_pton(socket.AF_INET, address)
    except AttributeError:  # no inet_pton here, sorry
        try:
            socket.inet_aton(address)
        except OSError:
            return False
        return address.count(".") == 3
    except OSError:  # not a valid address
        return False

    return True


def is_valid_ipv6_address(address: str) -> bool:
    """Check if ip address is ipv6"""
    try:
        socket.inet_pton(socket.AF_INET6, address)
    except OSError:  # not a valid address
        return False
    return True


def is_valid_port(port: int) -> bool:
    """Check if port is valid"""
    return 0 <= port <= 65535
