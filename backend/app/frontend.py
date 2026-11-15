"""Serve the actual compiled SPA alongside the existing local API."""

from pathlib import Path

from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

# Exact page shells only. Entity/query validation belongs to ApplicationRouter
# and the real API; returning HTML never asserts that an entity exists.
V20_PAGE_ROUTES = (
    '/requirements/{requirement_id}/documents/{document_id}/code-tasks',
    '/code-tasks/{task_id}',
    '/settings/code',
    '/testing',
    '/testing/tasks/{testing_task_id}',
    '/testing/plans',
    '/settings/testing',
)


def install_frontend(app, directory):
    directory = Path(directory).resolve()
    index = directory / 'index.html'
    if not directory.is_dir() or not index.is_file() or not (directory / 'assets').is_dir():
        raise ValueError('Frontend build is missing; run npm run build in frontend first')
    # Only the assets subtree is public. No project files, source, env or DB.
    app.mount('/assets', StaticFiles(directory=directory / 'assets'), name='frontend-assets')

    async def shell():
        return FileResponse(index, media_type='text/html', headers={'Cache-Control': 'no-cache'})

    app.add_api_route('/', shell, methods=['GET', 'HEAD'], include_in_schema=False)
    app.add_api_route('/requirements', shell, methods=['GET', 'HEAD'], include_in_schema=False)

    for route in V20_PAGE_ROUTES:
        app.add_api_route(route, shell, methods=['GET', 'HEAD'], include_in_schema=False)

    async def requirement_shell(identity: str):
        # The SPA validates canonical positive internal IDs and handles missing
        # requirements through the real I03 error, never an empty document.
        return await shell()

    app.add_api_route(
        '/requirements/{identity}',
        requirement_shell,
        methods=['GET', 'HEAD'],
        include_in_schema=False,
    )
