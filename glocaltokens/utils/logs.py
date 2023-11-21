"""Log utilities"""
from __future__ import annotations


def censor(
    text: str | None, hide_length: bool = False, hide_first_letter: bool = False
) -> str:
    """
    Replaces characters in a str with the asterisks

    text: The text to censure.
    """
    if not text:
        # 'None' for None, '' for ''.
        return str(text)
    char = "*"
    prefix = text[0] if not hide_first_letter else ""
    suffix = "<redacted>" if hide_length else char * (len(text) - len(prefix))
    return prefix + suffix
