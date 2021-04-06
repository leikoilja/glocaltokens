"""Log utilities"""

from typing import Optional


def censor(text: Optional[str]) -> str:
    """
    Replaces characters in a str by the asteriks

    text: The text to censure.
    """
    char = "*"
    text = text if text else ""
    return text[0] + (len(text) - 1) * char if text else text
