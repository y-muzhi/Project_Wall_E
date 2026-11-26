"""Dedicated onedir backend entry. Runtime probe never opens a business database."""

import sys


def verify_runtime(schema_version):
    from backend.app.infrastructure.sqlite_runtime import activate

    runtime = activate()
    from backend.app.infrastructure.git_bundle import verify_bundle_bytes
    from backend.app.infrastructure.resources import ResourceCatalog

    if schema_version == 210:
        from backend.app.infrastructure.formation_schema_release import load_release

        release = load_release()
    else:
        from backend.app.infrastructure.schema_v20_release import load_release

        release = load_release()
    ResourceCatalog()
    verify_bundle_bytes()
    print(
        f'BACKEND_RUNTIME_VERIFIED schema={schema_version} sqlite={runtime.version} '
        f'release={release.release_id}'
    )
    return 0


def main():
    sys.dont_write_bytecode = True
    if any(mode in sys.argv[1:] for mode in ('--hold-installation-reader', '--verify-guard')):
        from tools.windows_backend_guard_probe import main as run_probe

        return run_probe(sys.argv[1:])
    import argparse

    parser = argparse.ArgumentParser(description='Run the local WALL-E backend.')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--schema-version', type=int, choices=(200, 210), default=200)
    parser.add_argument('--verify-runtime', action='store_true')
    values = parser.parse_args()
    if values.verify_runtime:
        return verify_runtime(values.schema_version)
    if not 1024 <= values.port <= 65535:
        parser.error('The local HTTP port must be between 1024 and 65535')
    from backend.app.__main__ import main as run_backend

    run_backend(port=values.port, schema_version=values.schema_version)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
