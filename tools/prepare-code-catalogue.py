"""Publish immutable nonsecret code option metadata; no model, install or execution."""

import argparse
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from backend.app.infrastructure.code_configuration_catalog import (
    load_code_catalogue,
    prepare_catalogue,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-id')
    parser.add_argument('--verify', action='store_true')
    arguments = parser.parse_args()
    if arguments.verify == bool(arguments.release_id):
        parser.error('Choose either --verify or an explicit new --release-id')
    if arguments.verify:
        loaded = load_code_catalogue()
        print('Code catalogue', loaded.release_id, loaded.manifest_sha256)
        return 0
    root = Path(__file__).resolve().parents[1]
    pin = root / 'backend/app/infrastructure/code_catalogue_admission.py'
    old = pin.read_bytes() if pin.exists() else None
    directory, sha = prepare_catalogue(arguments.release_id)
    content = (
        '"""Generated immutable code option catalogue pin; not runtime admission."""\n\n'
        + 'RELEASE_DIRECTORY = '
        + repr(directory.name)
        + '\n'
        + 'MANIFEST_SHA256 = '
        + repr(sha)
        + '\n'
    ).encode('utf-8')
    if old is not None and b'\r\n' in old:
        content = content.replace(b'\n', b'\r\n')
    temporary = None
    try:
        with NamedTemporaryFile(
            dir=pin.parent, prefix='.code-catalogue-pin-', delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if old is not None:
            os.chmod(temporary, pin.stat().st_mode)
        if (pin.read_bytes() if pin.exists() else None) != old:
            raise RuntimeError(
                'Original code catalogue pin changed; keep prepared release unadopted'
            )
        os.replace(temporary, pin)
        print('Code catalogue', directory.name, sha, 'runtime admission unchanged')
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
