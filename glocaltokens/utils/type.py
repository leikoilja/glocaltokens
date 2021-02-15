def is_numeric(variable):
    """Checks if a variable is numeric"""
    return is_integer(variable) or is_float(variable)


def is_integer(variable):
    """Checks if a variable is an integer value"""
    return type(variable) == int


def is_float(variable):
    """Checks if a variable is a floating point value"""
    return type(variable) == float
