"""One local process, fixed SQLite and existing Schema200; never initializes a DB."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(*, port=8000):
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('An explicit local HTTP port between 1024 and 65535 is required')
    # Activate the approved native library before uvicorn/FastAPI/database imports.
    from .infrastructure.sqlite_runtime import activate

    activate()
    import uvicorn

    from .code_tasks.local_deployment import hold_configured_deployment
    from .service import create_app

    frontend = Path(os.environ.get('WALLE_FRONTEND_DIST', str(ROOT / 'frontend' / 'dist')))
    with hold_configured_deployment() as installation:
        uvicorn.run(
            create_app(frontend_directory=frontend, registration_installation=installation),
            host='127.0.0.1',
            port=port,
            workers=1,
            reload=False,
            timeout_graceful_shutdown=10,
            log_level='info',
        )


if __name__ == '__main__':
    main()
