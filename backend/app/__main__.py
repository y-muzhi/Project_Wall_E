"""One local process, fixed SQLite and explicit existing Schema200/210; never initializes a DB."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(*, port=8000, schema_version=200):
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('An explicit local HTTP port between 1024 and 65535 is required')
    if type(schema_version) is not int or schema_version not in (200, 210):
        raise ValueError('An explicit supported database schema version is required')
    # Activate the approved native library before uvicorn/FastAPI/database imports.
    from .infrastructure.sqlite_runtime import activate

    activate()
    import uvicorn

    from .code_tasks.local_deployment import hold_configured_deployment
    from .service import create_app

    frontend = Path(os.environ.get('WALLE_FRONTEND_DIST', str(ROOT / 'frontend' / 'dist')))
    with hold_configured_deployment() as installation:
        uvicorn.run(
            create_app(
                frontend_directory=frontend,
                registration_installation=installation,
                schema_version=schema_version,
            ),
            host='127.0.0.1',
            port=port,
            workers=1,
            reload=False,
            timeout_graceful_shutdown=10,
            log_level='info',
        )


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema-version', type=int, choices=(200, 210), default=200)
    parser.add_argument('--port', type=int, default=8000)
    arguments = parser.parse_args()
    main(port=arguments.port, schema_version=arguments.schema_version)
