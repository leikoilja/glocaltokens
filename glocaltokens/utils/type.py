def is_numeric(variable) -> bool:
    return is_integer(variable) or is_float(variable)


def is_integer(variable) -> bool:
    return type(variable) == int


def is_float(variable):
    return type(variable) == float
