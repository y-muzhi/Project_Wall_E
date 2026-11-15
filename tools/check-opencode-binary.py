"""Read and verify fixed OpenCode Windows installation sources."""

import argparse
import sys
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.infrastructure.opencode_binary import VERSION, verify_opencode_archive
from backend.app.infrastructure.opencode_protocol_source import verify_opencode_protocol_source
from backend.app.infrastructure.opencode_runtime_bundle import (
    OpenCodeRuntimeBundle,
    verify_opencode_runtime_bundle,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--openapi', type=Path)
    parser.add_argument('--bundle-manifest', type=Path)
    parser.add_argument('--bundle-root', type=Path)
    parser.add_argument('--bundle-ref')
    options = parser.parse_args()
    bundle_fields = (options.bundle_manifest, options.bundle_root, options.bundle_ref)
    if any(bundle_fields) and not all(bundle_fields):
        parser.error('provide --bundle-manifest, --bundle-root and --bundle-ref together')
    if options.archive is None and options.openapi is None and not all(bundle_fields):
        parser.error('provide --archive, --openapi or the bundle arguments')
    if options.archive is not None:
        image = verify_opencode_archive(
            options.archive.absolute(), deadline=monotonic() + 120, cancelled=lambda: False
        )
        print(f'OpenCode {VERSION} Windows x64 | {image.byte_count} bytes | SHA256 {image.sha256}')
    if options.openapi is not None:
        protocol = verify_opencode_protocol_source(
            options.openapi.absolute(), deadline=monotonic() + 15, cancelled=lambda: False
        )
        print(f'OpenCode SDK | {protocol.byte_count} bytes | Git blob {protocol.blob}')
    if options.bundle_manifest is not None:
        source = OpenCodeRuntimeBundle(
            options.bundle_manifest.absolute(), options.bundle_root.absolute()
        )
        count = verify_opencode_runtime_bundle(
            source, options.bundle_ref, deadline=monotonic() + 120, cancelled=lambda: False
        )
        print(f'OpenCode runtime bundle | {count} files | {options.bundle_ref}')


if __name__ == '__main__':
    main()
