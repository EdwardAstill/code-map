"""Caller module: imports b and calls b.greet."""
from b import greet


def main() -> None:
    print(greet("world"))


if __name__ == "__main__":
    main()
