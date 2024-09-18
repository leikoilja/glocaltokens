"""Token utilities."""

import random
import string


def is_aas_et(token: str) -> bool:
    """AAS type token."""
    return isinstance(token, str) and token.startswith("aas_et/") and len(token) == 223


def is_local_auth_token(token: str) -> bool:
    """Local authentication token."""
    return len(token) == 108


def generate(length: int, prefix: str = "", suffix: str = "") -> str:
    """Generate token."""
    return (
        prefix
        + "".join(random.choice(string.ascii_letters) for x in range(length))
        + suffix
    )
