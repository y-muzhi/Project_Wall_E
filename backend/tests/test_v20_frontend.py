"""Seven explicit V2 GET/HEAD shells: no catch-all, entity claims or private files."""

from pathlib import Path
import tempfile
import unittest

import httpx

from backend.app.frontend import V20_PAGE_ROUTES
from backend.app.service import create_app
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.resources import ResourceCatalog


class V20FrontendRoutes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='w2-spa-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = Database(self.root / 'actual.sqlite')
        self.database.initialize()
        self.directory = self.root / 'dist'
        (self.directory / 'assets').mkdir(parents=True)
        with (self.directory / 'index.html').open('x', encoding='utf-8') as stream:
            stream.write('<!doctype html><div id="root">isolated build marker</div>')
        with (self.directory / 'assets' / 'app.js').open('x', encoding='utf-8') as stream:
            stream.write('/* isolated asset marker */')

    async def test_exact_get_head_and_query_are_shells_not_resource_facts(self):
        app = create_app(
            database=self.database, catalog=ResourceCatalog(), frontend_directory=self.directory
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://owned'
            ) as client:
                self.assertEqual(len(V20_PAGE_ROUTES), 7)
                paths = (
                    '/requirements/1/documents/2/code-tasks',
                    '/code-tasks/3',
                    '/settings/code?section=execution',
                    '/testing',
                    '/testing/tasks/4',
                    '/testing/plans',
                    '/settings/testing',
                    '/code-tasks/01',
                    '/testing/tasks/not-an-id',
                    '/settings/code?section=invalid',
                    '/requirements/9/documents/10/code-tasks',
                )
                for path in paths:
                    with self.subTest(path=path):
                        got = await client.get(path)
                        head = await client.head(path)
                        self.assertEqual(got.status_code, 200)
                        self.assertEqual(head.status_code, 200)
                        self.assertIn('text/html', got.headers['content-type'])
                        self.assertEqual(got.headers['cache-control'], 'no-cache')
                        self.assertIn('isolated build marker', got.text)
                        self.assertEqual(head.content, b'')
                        self.assertEqual(
                            head.headers['content-length'], got.headers['content-length']
                        )
                        self.assertEqual((await client.post(path, json={})).status_code, 405)
                self.assertEqual(
                    (await client.get('/api/v1/requirements')).json()['data']['items'], []
                )
                self.assertIn('isolated asset marker', (await client.get('/assets/app.js')).text)
                for path in (
                    '/api/v1/code-tasks/3/not-a-binding',
                    '/api/v1/testing/not-a-binding',
                    '/api/no-binding',
                    '/settings/other',
                    '/settings/code/private',
                    '/testing/other',
                    '/testing/tasks/4/files',
                    '/testing/plans/other',
                    '/code-tasks/3/secret',
                    '/.env.local',
                    '/actual.sqlite',
                    '/src/main.tsx',
                    '/backend/app/service.py',
                    '/assets/../actual.sqlite',
                    '/assets/missing.js',
                ):
                    with self.subTest(not_shell=path):
                        got = await client.get(path)
                        self.assertEqual(got.status_code, 404)
                        self.assertNotIn('isolated build marker', got.text)

    async def test_api_only_startup_does_not_register_pages(self):
        app = create_app(database=self.database, catalog=ResourceCatalog())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://owned'
            ) as client:
                for path in ('/code-tasks/1', '/testing', '/settings/code', '/settings/testing'):
                    self.assertEqual((await client.get(path)).status_code, 404)
