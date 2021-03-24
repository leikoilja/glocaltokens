def censor(text: str, char: str = "*") -> str:
    """
    Replaces all the characters in a str by the specified [replace]

    text: The text to censure.
    replace: The character to instead of the content.
    """
    text = text if text else ""
    censored_text = text[0] + (len(text) - 1) * char if len(text) else text
    return censored_text
