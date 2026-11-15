"""Read an explicit deployment source without starting any application or service."""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.infrastructure.deployment_manifest import absolute_path, digest
from backend.app.infrastructure.windows_config_source import LockedFileSource


def main(arguments=None):
    parser = argparse.ArgumentParser(
        description='Inspect an existing pinned local deployment source.'
    )
    parser.add_argument('--kind', choices=('backend', 'guard'), required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--sha256', required=True)
    values = parser.parse_args(arguments)
    try:
        path, expected = absolute_path(values.manifest), digest(values.sha256)
        if values.kind == 'backend':
            from backend.app.code_tasks.local_deployment import (
                DIGEST_ENV,
                MANIFEST_ENV,
                hold_configured_deployment,
            )

            environment = {**os.environ, MANIFEST_ENV: str(path), DIGEST_ENV: expected}
            with hold_configured_deployment(environment):
                pass
            print(
                'BACKEND_SOURCE_RESOURCES_CHECKED; no application, runtime admission or API call.'
            )
        else:
            from backend.app.infrastructure.guard_deployment_configuration import (
                MAX_BYTES,
                decode_guard_deployment,
            )

            with LockedFileSource(path, max_file_bytes=MAX_BYTES) as source:
                if source.snapshot.sha256 != expected:
                    print('DEPLOYMENT_SOURCE_REJECTED', file=sys.stderr)
                    return 1
                decode_guard_deployment(source.snapshot.raw)
            print(
                'GUARD_SOURCE_SHAPE_CHECKED; SYSTEM/runtime evidence, journal and pipe not opened.'
            )
    except (OSError, ValueError, TypeError, RuntimeError):
        print('DEPLOYMENT_SOURCE_REJECTED', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
