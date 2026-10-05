"""D-003 one local process, no reload/workers or automatic DB initialization."""
import uvicorn
from .service import create_app


def main():
    uvicorn.run(create_app(), host='127.0.0.1', port=8000, workers=1, reload=False,
        timeout_graceful_shutdown=10, log_level='info')


if __name__ == '__main__': main()
