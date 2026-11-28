"""Materialize independent build inputs from an explicit V2.2 integration commit."""

import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend.app.management.release_source import main as prepare_source

    return prepare_source()


if __name__ == '__main__':
    raise SystemExit(main())
