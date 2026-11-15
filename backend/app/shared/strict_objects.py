"""Exact object fields shared by metadata, protocol and HTTP boundaries."""


def exact(value: object, fields) -> dict:
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError('Response fields differ from the registered schema')
    return dict(value)
