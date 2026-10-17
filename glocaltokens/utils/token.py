"""Token utilities."""

from ..const import LOCAL_AUTH_TOKEN_LENGTH, MASTER_TOKEN_LENGTH


def is_aas_et(token: str) -> bool:
    """AAS type token."""
    return (
        isinstance(token, str)
        and token.startswith("aas_et/")
        and len(token) == len("aas_et/") + MASTER_TOKEN_LENGTH
    )


def is_local_auth_token(token: str) -> bool:
    """Local authentication token."""
    return len(token) == LOCAL_AUTH_TOKEN_LENGTH
