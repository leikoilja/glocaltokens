"""Types utilities"""


def is_numeric(variable) -> bool:
    """Checks if a variable is numeric"""
    return is_integer(variable) or is_float(variable)


def is_integer(variable):
    """Checks if a variable is an integer value"""
    return isinstance(variable, int)


def is_float(variable):
    """Checks if a variable is a floating point value"""
    return isinstance(variable, float)


# pylint: disable=too-few-public-methods
class Struct:
    """Structure type"""

    def __init__(self, **entries):
        """Initialization"""
        self.__dict__.update(entries)
