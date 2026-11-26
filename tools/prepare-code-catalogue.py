"""Publish immutable nonsecret code option metadata; no model, install or execution."""

import argparse
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from backend.app.infrastructure.code_configuration_catalog import (
    OpenCodeCatalogueSources,
    load_code_catalogue,
    prepare_catalogue,
)
from backend.app.infrastructure.opencode_runtime_bundle import OpenCodeRuntimeBundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-id')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--opencode-archive', type=Path)
    parser.add_argument('--opencode-openapi', type=Path)
    parser.add_argument('--opencode-bundle-manifest', type=Path)
    parser.add_argument('--opencode-bundle-root', type=Path)
    parser.add_argument('--opencode-bundle-ref')
    arguments = parser.parse_args()
    if arguments.verify == bool(arguments.release_id):
        parser.error('Choose either --verify or an explicit new --release-id')
    opencode_fields = (
        arguments.opencode_archive,
        arguments.opencode_openapi,
        arguments.opencode_bundle_manifest,
        arguments.opencode_bundle_root,
        arguments.opencode_bundle_ref,
    )
    if any(opencode_fields) and (arguments.verify or not all(opencode_fields)):
        parser.error('Supply all OpenCode sources together with a new release ID')
    if arguments.verify:
        loaded = load_code_catalogue()
        print('Code catalogue', loaded.release_id, loaded.manifest_sha256)
        return 0
    root = Path(__file__).resolve().parents[1]
    pin = root / 'backend/app/infrastructure/code_catalogue_admission.py'
    old = pin.read_bytes() if pin.exists() else None
    opencode = None
    if all(opencode_fields):
        opencode = OpenCodeCatalogueSources(
            arguments.opencode_archive.absolute(),
            arguments.opencode_openapi.absolute(),
            OpenCodeRuntimeBundle(
                arguments.opencode_bundle_manifest.absolute(),
                arguments.opencode_bundle_root.absolute(),
            ),
            arguments.opencode_bundle_ref,
        )
    directory, sha = prepare_catalogue(arguments.release_id, opencode=opencode)
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
