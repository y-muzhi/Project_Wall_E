"""Prepare a pinned Guard installation request without changing the system."""

import argparse
import sys
from pathlib import Path


def main(arguments=None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.windows_guard_installation import prepare_request

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--installer-package', type=Path, required=True)
    parser.add_argument('--installer-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    values = parser.parse_args(arguments)
    try:
        request_sha = prepare_request(
            values.prepared,
            values.plan_sha256,
            values.installer_package,
            values.installer_sha256,
            values.output,
        )
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        if getattr(error, 'retained_owner', None) is not None:
            raise
        print('GUARD_INSTALLATION_REQUEST_PREPARATION_REJECTED', file=sys.stderr)
        return 1
    print(f'GUARD_INSTALLATION_REQUEST_PREPARED request={request_sha}', flush=True)
    print('NO_INSTALLATION_SERVICE_ACL_WFP_OR_MODEL_ACTION', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
