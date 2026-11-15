"""Prepare a manifest for an existing offline runtime; no install or runtime admission."""

import argparse
import sys
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.infrastructure.opencode_runtime_preparation import publish_runtime_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle-root', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    arguments = parser.parse_args()
    prepared = publish_runtime_manifest(
        arguments.bundle_root.absolute(),
        arguments.manifest.absolute(),
        deadline=monotonic() + 120,
        cancelled=lambda: False,
    )
    print(
        'Offline OpenCode runtime manifest',
        prepared.file_count,
        'files',
        prepared.reference,
        'runtime admission unchanged',
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
