"""Serve the explicitly selected Schema210 document review layout."""

import os
from pathlib import Path


def serve_review(*, port):
    from .infrastructure.sqlite_runtime import activate

    activate()
    import uvicorn

    from .__main__ import ROOT
    from .code_tasks.local_deployment import hold_configured_deployment
    from .infrastructure.database import SchemaMismatch, configured_path
    from .infrastructure.formation_database import FormationDatabase
    from .infrastructure.review_schema import LAYOUT_NAME, load_configured_release
    from .service import create_app

    release = load_configured_release()
    if release.release_id != LAYOUT_NAME:
        raise SchemaMismatch('The explicit document review layout is required')

    database = FormationDatabase(configured_path(), formation_release=release)
    frontend = Path(os.environ.get('WALLE_FRONTEND_DIST', str(ROOT / 'frontend' / 'dist')))
    with hold_configured_deployment() as installation:
        uvicorn.run(
            create_app(
                database=database,
                frontend_directory=frontend,
                registration_installation=installation,
                schema_version=210,
            ),
            host='127.0.0.1',
            port=port,
            workers=1,
            reload=False,
            timeout_graceful_shutdown=10,
            log_level='info',
        )
