"""Defines greet; greet calls shout from c."""
from c import shout


def greet(name: str) -> str:
    return shout(f"hello {name}")
