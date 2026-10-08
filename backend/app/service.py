"""Production API lifespan: verified existing DB -> lock/recovery ->37 routes.

No paid compatibility/effect claim and no placeholder product page. Initialization
is the separate native database CLI. This factory never creates or repairs a DB.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.responses import JSONResponse

from backend.app.infrastructure.database import Database, configured_path
from backend.app.infrastructure.execution_lease import ExecutionLease, LeasedDatabase
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.infrastructure.production_ai import production_options
from backend.app.guide.worker import GuideWorker
from backend.app.guide.orchestrator import _native
from backend.app.shared.http_boundary import HttpRuntime
from backend.app.shared.http_errors import error_response, new_request_id
from backend.app.requirements.api import req_router
from backend.app.documents.api import doc_router
from backend.app.revisions.api import rev_router
from backend.app.comments.api import comment_router
from backend.app.suggestions.api import batch_router
from backend.app.guide.api import guide_router
from backend.app.messages.api import message_router


def create_app(*, database=None, catalog=None, worker_factory=None, frontend_directory=None):
    """Dependencies are private native test injection, never request arguments."""
    @asynccontextmanager
    async def lifespan(app):
        actual_database = Database(configured_path()) if database is None else database
        resources = await _native(ResourceCatalog) if catalog is None else catalog
        worker = GuideWorker(actual_database, catalog=resources, orchestrator_options=production_options()) if worker_factory is None else worker_factory(actual_database, resources)
        if not isinstance(worker, GuideWorker) or worker.database is not actual_database or worker.catalog is not resources:
            raise ValueError('The startup owner must bind this actual database and catalog')
        await worker.start()
        http_lease = ExecutionLease()
        try:
            http_database = LeasedDatabase(actual_database, http_lease)
            executor = Idempotency(http_database, worker.process_lock, clock=worker.clock)
            app.state.walle_runtime = HttpRuntime(http_database, resources, executor, worker)
            app.state.walle_worker = worker
            app.state.walle_http_lease = http_lease
            yield
        finally:
            worker.accepting = False
            # Every public command/read uses this HTTP transaction fence.
            # Retirement protects against threadpool work outliving ASGI drain.
            # Worker and recovery use the underlying actual DB independently.
            async def close():
                try: await asyncio.to_thread(http_lease.retire)
                finally: await worker.close()
            closing = asyncio.create_task(close())
            try: await asyncio.shield(closing)
            except asyncio.CancelledError:
                while not closing.done():
                    try: await asyncio.shield(closing)
                    except asyncio.CancelledError: continue
                raise
            finally:
                app.state.walle_runtime = None

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    for router in (req_router, doc_router, rev_router, comment_router, batch_router, guide_router, message_router):
        app.include_router(router)
    if frontend_directory is not None:
        from .frontend import install_frontend
        install_frontend(app, frontend_directory)

    @app.middleware('http')
    async def admission(request, call_next):
        runtime = getattr(request.app.state, 'walle_runtime', None)
        if not isinstance(runtime, HttpRuntime) or not runtime.worker.accepting:
            request_id = new_request_id(); request.state.request_id = request_id
            failure = error_response('STORAGE_UNAVAILABLE', None, allowed_errors={'STORAGE_UNAVAILABLE'}, request_id=request_id)
            return JSONResponse(failure.body, status_code=failure.status)
        return await call_next(request)
    return app
