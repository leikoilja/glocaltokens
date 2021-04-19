"""Log utilities"""
from __future__ import annotations


def censor(text: str | None) -> str:
    """
    Replaces characters in a str with the asterisks

    text: The text to censure.
    """
    char = "*"
    text = text if text else ""
    return text[0] + (len(text) - 1) * char if text else text
