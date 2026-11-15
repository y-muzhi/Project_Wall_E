"""Prepare only the pinned project-local MinGit package; no system installation."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.infrastructure.git_bundle import prepare_bundle, verify_bundle_bytes, VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--download', action='store_true')
    action.add_argument('--verify', action='store_true')
    arguments = parser.parse_args()
    if arguments.download:
        prepare_bundle()
    count, size, sha256 = verify_bundle_bytes()
    print(
        f'MinGit {VERSION}: {count} files / {size} bytes; manifest SHA256 {sha256}; runtime admission pending'
    )


if __name__ == '__main__':
    main()
