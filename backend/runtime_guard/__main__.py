"""Run only an explicitly registered RuntimeGuard Windows service."""

import argparse
import os

from backend.app.infrastructure.deployment_manifest import absolute_path, digest
from backend.app.infrastructure.windows_guard_service import GuardServiceError, guard_service_name
from backend.app.infrastructure.windows_guard_service_host import GuardServiceHost


def parse_arguments(arguments=None):
    parser = argparse.ArgumentParser(description='Run the registered WALL-E RuntimeGuard service.')
    parser.add_argument('--installation-ref', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--sha256', required=True)
    values = parser.parse_args(arguments)
    try:
        guard_service_name(values.installation_ref)
        values.manifest = str(absolute_path(values.manifest))
        values.sha256 = digest(values.sha256)
    except (TypeError, ValueError, RuntimeError):
        parser.error(
            'A fixed installation reference, absolute local manifest and SHA256 are required.'
        )
    return values


def main(arguments=None):
    values = parse_arguments(arguments)
    try:
        outcome = GuardServiceHost(values.installation_ref, values.manifest, values.sha256).run()
    except GuardServiceError as error:
        if getattr(error, 'retained_owner', None) is not None:
            os._exit(1)
        return 1
    if outcome.retained_owner is not None:
        # End only this Guard process: its original Job handles must not stay alive
        # behind a failed SCM callback. This is no business cleanup acknowledgement.
        os._exit(1)
    return outcome.exit_code


if __name__ == '__main__':
    raise SystemExit(main())
