"""Explicit preparation of a new dedicated Guard package; no service installation."""

import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.windows_guard_package import main as prepare

    return prepare()


if __name__ == '__main__':
    raise SystemExit(main())
