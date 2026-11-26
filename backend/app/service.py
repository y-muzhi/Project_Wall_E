"""Production API lifespan: verified existing Schema200 -> lock/recovery -> registered document/V2 routes.

No paid compatibility/effect claim and no placeholder product page. Initialization
is the separate native database CLI. This factory never creates or repairs a DB.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.comments.api import comment_router
from backend.app.documents.api import doc_router
from backend.app.guide.orchestrator import _native
from backend.app.infrastructure.execution_lease import ExecutionLease, LeasedDatabase
from backend.app.infrastructure.resources import DocumentResources, ResourceCatalog
from backend.app.messages.api import message_router
from backend.app.requirements.api import req_router
from backend.app.revisions.api import rev_router
from backend.app.shared.http_boundary import HttpRuntime


def _build_app(lifespan, routers, frontend_directory):
    app = FastAPI(
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
    )
    for router in routers:
        app.include_router(router)
    if frontend_directory is not None:
        from .frontend import install_frontend

        install_frontend(app, frontend_directory)
    return app


def _recovery_app(recovery, catalog, frontend_directory):
    from backend.app.infrastructure.environment_http import api_admission
    from backend.app.requirements.discussion import discussion_resources

    def load_document_resources():
        return DocumentResources(default_collaboration=discussion_resources())

    @asynccontextmanager
    async def lifespan(app):
        resources = await _native(load_document_resources) if catalog is None else catalog
        lease = ExecutionLease()
        await _native(recovery.start)
        app.state.walle_runtime = HttpRuntime(LeasedDatabase(recovery.database, lease), resources)
        try:
            yield
        finally:
            recovery.drain()
            try:
                await _native(lease.retire_and_wait)
            finally:
                app.state.walle_runtime = None

    app = _build_app(
        lifespan,
        (req_router, doc_router, rev_router, comment_router, message_router),
        frontend_directory,
    )

    @app.middleware('http')
    async def admission(request, call_next):
        return await api_admission(request, call_next, recovery, recovery=True)

    return app


def create_app(
    *,
    database=None,
    catalog=None,
    worker_factory=None,
    frontend_directory=None,
    registration_installation=None,
    ordinary=None,
    recovery=None,
):
    """Private process startup dependencies. Installation input is never HTTP data."""
    if ordinary is not None and recovery is not None:
        raise TypeError('Only one installed scope may be bound to the application')
    if ordinary is not None or recovery is not None:
        if any(
            input_value is not None
            for input_value in (database, worker_factory, registration_installation)
        ):
            raise TypeError('Installed execution must use its own admitted database and worker')
    if recovery is not None:
        return _recovery_app(recovery, catalog, frontend_directory)

    from backend.app.code_tasks.authorization_api import authorization_router
    from backend.app.code_tasks.check_set_api import check_set_router
    from backend.app.code_tasks.command_api import COMMAND_CONTROL_PATHS, command_router
    from backend.app.code_tasks.configuration_api import (
        configuration_router,
        is_configuration_path,
    )
    from backend.app.code_tasks.design_revisions import (
        design_revision_router,
        is_design_revision_path,
    )
    from backend.app.code_tasks.execution_profile_api import execution_profile_router
    from backend.app.code_tasks.repository_observations import (
        is_repository_observation_path,
        repository_observation_router,
    )
    from backend.app.code_tasks.repository_operations import (
        is_repository_operation_path,
        repository_operation_router,
    )
    from backend.app.code_tasks.repository_reads import (
        is_repository_read_path,
        repository_read_router,
    )
    from backend.app.code_tasks.repository_registration_api import (
        is_repository_write_path,
        repository_registration_router,
    )
    from backend.app.code_tasks.repository_snapshot_reads import (
        is_repository_snapshot_path,
        repository_snapshot_router,
    )
    from backend.app.code_tasks.task_creation_api import (
        is_document_code_tasks_path,
        task_creation_router,
    )
    from backend.app.code_tasks.task_defects import defect_router
    from backend.app.code_tasks.task_delivery_api import delivery_command_router
    from backend.app.code_tasks.task_delivery_reads import delivery_reads_router
    from backend.app.code_tasks.task_read_api import is_code_task_detail_path, task_read_router
    from backend.app.code_tasks.task_repairs import repair_router
    from backend.app.code_tasks.task_start_api import is_task_start_path, task_start_router
    from backend.app.code_tasks.task_start_workspace import recover_workspace_starts
    from backend.app.code_tasks.task_stop import serve_task_stops
    from backend.app.code_tasks.task_stop_api import is_task_stop_path, task_stop_router
    from starlette.responses import JSONResponse
    from backend.app.guide.api import guide_router
    from backend.app.guide.worker import GuideWorker
    from backend.app.infrastructure.database import Database, configured_path
    from backend.app.infrastructure.idempotency import Idempotency
    from backend.app.infrastructure.schema_v20_release import load_release
    from backend.app.shared.http_errors import error_response, new_request_id
    from backend.app.suggestions.api import batch_router
    from backend.app.testing.plan_api import TEST_PLAN_ROUTER, is_testing_plan_path
    from backend.app.testing.planning_worker import recover_drafts, serve_testing_plans
    from backend.app.testing.policy_api import is_testing_policy_path, testing_policy_router

    if registration_installation is not None:
        from backend.app.code_tasks.repository_registration_worker import RegistrationInstallation

        if type(registration_installation) is not RegistrationInstallation:
            raise TypeError('Trusted registration installation inputs required')

    @asynccontextmanager
    async def lifespan(app):
        if ordinary is not None:
            actual_database = ordinary.database
        else:
            actual_database = (
                Database(configured_path(), schema_release=load_release())
                if database is None
                else database
            )
        resources = await _native(ResourceCatalog) if catalog is None else catalog
        if ordinary is not None:
            worker = GuideWorker(actual_database, catalog=resources, ordinary=ordinary)
        elif worker_factory is not None:
            worker = worker_factory(actual_database, resources)
        else:
            from backend.app.infrastructure.production_ai import production_options

            worker = GuideWorker(
                actual_database, catalog=resources, orchestrator_options=production_options()
            )
        if (
            not isinstance(worker, GuideWorker)
            or worker.database is not actual_database
            or worker.catalog is not resources
        ):
            raise ValueError('The startup owner must bind this actual database and catalog')
        http_lease = ExecutionLease()
        registration = None
        stop_service = planning_service = None
        planning_wake = asyncio.Event()
        stop_wake = asyncio.Event()
        stop_closing = asyncio.Event()
        try:
            await worker.start()
            internal_runtime = HttpRuntime(actual_database, resources, worker.executor, worker)
            recover = ordinary is None or getattr(ordinary, 'recover_on_start', True)
            if actual_database.schema_release is not None and recover:
                await _native(recover_workspace_starts, internal_runtime)
                await _native(recover_drafts, internal_runtime)
            if registration_installation is not None:
                from backend.app.code_tasks.repository_registration_worker import (
                    RepositoryRegistrationWorker,
                )

                registration = RepositoryRegistrationWorker(
                    internal_runtime, registration_installation
                )
                app.state.walle_repository_registration = registration
                await _native(registration.start)
            http_database = LeasedDatabase(actual_database, http_lease)
            executor = Idempotency(http_database, worker.process_lock, clock=worker.clock)
            app.state.walle_runtime = HttpRuntime(http_database, resources, executor, worker)
            app.state.walle_worker = worker
            app.state.walle_http_lease = http_lease
            if ordinary is None and actual_database.schema_release is not None:
                app.state.walle_stop_wake = stop_wake
                app.state.walle_planning_wake = planning_wake
                planning_service = asyncio.create_task(
                    serve_testing_plans(internal_runtime, planning_wake, stop_closing)
                )
                stop_service = asyncio.create_task(
                    serve_task_stops(
                        internal_runtime,
                        stop_wake,
                        stop_closing,
                        testing_native=lambda: (
                            registration is not None
                            and registration.testing_cli_resources is not None
                        ),
                    )
                )
            if ordinary is not None:
                await _native(ordinary.start)
                worker.accepting = True
            yield
        finally:
            worker.accepting = False

            # Every public command/read uses this HTTP transaction fence.
            # Retirement protects against threadpool work outliving ASGI drain.
            # Worker and recovery use the underlying actual DB independently.
            async def close():
                try:
                    if ordinary is None:
                        await asyncio.to_thread(http_lease.retire)
                    else:
                        try:
                            await _native(ordinary.drain)
                        finally:
                            await asyncio.to_thread(http_lease.retire_and_wait)
                finally:
                    try:
                        try:
                            if stop_service is not None:
                                stop_closing.set()
                                stop_wake.set()
                                planning_wake.set()
                                await asyncio.gather(stop_service, planning_service)
                        finally:
                            if registration is not None:
                                await _native(registration.close)
                    finally:
                        await worker.close()

            closing = asyncio.create_task(close())
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                while not closing.done():
                    try:
                        await asyncio.shield(closing)
                    except asyncio.CancelledError:
                        continue
                raise
            finally:
                app.state.walle_runtime = None

    app = _build_app(
        lifespan,
        (
            req_router,
            doc_router,
            rev_router,
            comment_router,
            batch_router,
            guide_router,
            message_router,
            command_router,
            configuration_router,
            check_set_router,
            execution_profile_router,
            authorization_router,
            repository_observation_router,
            repository_operation_router,
            repository_read_router,
            repository_registration_router,
            repository_snapshot_router,
            design_revision_router,
            task_creation_router,
            task_read_router,
            defect_router,
            delivery_command_router,
            delivery_reads_router,
            repair_router,
            task_start_router,
            task_stop_router,
            testing_policy_router,
            TEST_PLAN_ROUTER,
        ),
        frontend_directory,
    )

    if ordinary is not None:
        from backend.app.infrastructure.environment_http import api_admission

    @app.middleware('http')
    async def admission(request, call_next):
        if ordinary is not None:
            return await api_admission(request, call_next, ordinary)
        runtime = getattr(request.app.state, 'walle_runtime', None)
        if not isinstance(runtime, HttpRuntime) or not runtime.worker.accepting:
            request_id = new_request_id()
            request.state.request_id = request_id
            code_contract = (
                request.url.path in COMMAND_CONTROL_PATHS
                or is_configuration_path(request.url.path)
                or is_repository_observation_path(request.url.path)
                or is_repository_operation_path(request.url.path)
                or is_repository_read_path(request.url.path)
                or is_repository_write_path(request.url.path)
                or is_repository_snapshot_path(request.url.path)
                or is_design_revision_path(request.url.path)
                or is_document_code_tasks_path(request.url.path)
                or is_code_task_detail_path(request.url.path)
                or is_task_start_path(request.url.path)
                or is_task_stop_path(request.url.path)
                or is_testing_policy_path(request.url.path)
                or is_testing_plan_path(request.url.path)
            )
            failure = error_response(
                'STORAGE_UNAVAILABLE',
                {'capability_codes': ['DATABASE']} if code_contract else None,
                allowed_errors={'STORAGE_UNAVAILABLE'},
                request_id=request_id,
                contract='code' if code_contract else 'document',
            )
            return JSONResponse(failure.body, status_code=failure.status)
        return await call_next(request)

    return app
