"""Explicit offline package preparation; never installs or starts the backend."""

import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.windows_backend_package import main as build

    return build()


if __name__ == '__main__':
    raise SystemExit(main())
