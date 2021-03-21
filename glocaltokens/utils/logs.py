def censure(text: str, replace: str = "*") -> str:
    """
    Replaces all the characters in a str by the specified [replace]

    text: The text to censure.
    replace: The character to instead of the content.
    """
    return replace * len(text)
