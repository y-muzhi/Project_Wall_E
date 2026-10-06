"""D-003 one local process, no reload/workers or automatic DB initialization."""
import uvicorn
from pathlib import Path
import os
from .service import create_app
from .infrastructure.database import ROOT


def main():
    frontend = Path(os.environ.get('WALLE_FRONTEND_DIST', str(ROOT / 'frontend' / 'dist')))
    uvicorn.run(create_app(frontend_directory=frontend), host='127.0.0.1', port=8000, workers=1, reload=False,
        timeout_graceful_shutdown=10, log_level='info')


if __name__ == '__main__': main()
