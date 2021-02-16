import random
import string
from typing import Optional


def is_aas_et(token: str) -> bool:
    return type(token) == str and token.startswith("aas_et/") and len(token) == 223


def is_local_auth_token(token: str) -> bool:
    return len(token) == 108


def generate(length: int, prefix: Optional[str] = None, suffix: Optional[str] = None) -> str:
    return prefix if prefix else "" + \
           "".join(random.choice(string.ascii_letters) for x in range(length)) + \
           suffix if suffix else ""
