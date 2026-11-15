"""Build a new dedicated installer package; never install or control a service."""

import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.windows_guard_installer_package import main as prepare

    return prepare()


if __name__ == '__main__':
    raise SystemExit(main())
