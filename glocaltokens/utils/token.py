def is_aas_et(token: str) -> bool:
    return type(token) == str and token.startswith("aas_et/") and len(token) == 223


def is_local_auth_token(token: str) -> bool:
    return len(token) == 108
