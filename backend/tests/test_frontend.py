"""Actual lifespan/SQLite and isolated build assets; no model calls."""
from pathlib import Path
import tempfile
import unittest
import httpx
from backend.app.service import create_app
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.resources import ResourceCatalog


class FrontendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='walle-spa-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = Database(self.root / 'real.sqlite')
        self.database.initialize()
        self.dist = self.root / 'dist'
        (self.dist / 'assets').mkdir(parents=True)
        (self.dist / 'index.html').write_text('<!doctype html><div id="root"></div>', encoding='utf8')
        (self.dist / 'assets' / 'app.js').write_text('console.log("asset")', encoding='utf8')

    async def test_real_shell_routes_assets_head_and_api_are_separate(self):
        app = create_app(database=self.database, catalog=ResourceCatalog(), frontend_directory=self.dist)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local') as client:
                for path in ('/', '/requirements', '/requirements/1', '/requirements/01'):
                    response = await client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('text/html', response.headers['content-type'])
                    self.assertEqual(response.headers['cache-control'], 'no-cache')
                    self.assertIn('id="root"', response.text)
                    head = await client.head(path)
                    self.assertEqual(head.status_code, 200)
                    self.assertEqual(head.content, b'')
                asset = await client.get('/assets/app.js')
                self.assertEqual(asset.status_code, 200)
                self.assertEqual(asset.text, 'console.log("asset")')
                actual = await client.get('/api/v1/requirements')
                self.assertEqual(actual.status_code, 200)
                self.assertEqual(actual.json()['data']['items'], [])
                for path in ('/api/not-a-binding', '/assets/not-found.js', '/.env', '/real.sqlite', '/src/main.tsx'):
                    self.assertEqual((await client.get(path)).status_code, 404)

    async def test_missing_build_refused_before_starting_service(self):
        with self.assertRaisesRegex(ValueError, 'Frontend build is missing'):
            create_app(database=self.database, frontend_directory=self.root / 'absent')

    async def test_api_only_factory_has_no_fake_product_shell(self):
        app = create_app(database=self.database, catalog=ResourceCatalog())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local') as client:
                self.assertEqual((await client.get('/requirements')).status_code, 404)
                self.assertEqual((await client.get('/api/v1/requirements')).status_code, 200)
