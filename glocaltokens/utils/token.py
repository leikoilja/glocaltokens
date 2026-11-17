"""Token utilities."""

from .. import const
from ..const import LOCAL_AUTH_TOKEN_LENGTH

MASTER_TOKEN_LENGTH = const.MASTER_TOKEN_LENGTH  # Keep the existing import path.


def is_aas_et(token: str) -> bool:
    """Check the master token's local shape after trimming outer whitespace."""
    token = token.strip() if isinstance(token, str) else ""
    return (
        len(token) >= 200
        and token.startswith("aas_et/")
        and all("!" <= char <= "~" for char in token)
    )


def is_local_auth_token(token: str) -> bool:
    """Local authentication token."""
    return len(token) == LOCAL_AUTH_TOKEN_LENGTH
