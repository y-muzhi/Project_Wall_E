"""Independent management authentication, bindings and scoped API."""

from asyncio import timeout
from dataclasses import dataclass
from contextlib import contextmanager
import re
import signal
import sqlite3
from urllib.parse import urlsplit
from uuid import uuid4

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse
from starlette.routing import Route

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    exact,
    require,
)
from backend.app.infrastructure.environment_http import (
    gateway_headers_match,
    single,
    source_matches,
)
from backend.app.infrastructure.environment_installation import uuid_value
from backend.app.infrastructure.environment_lock import NativeEnvironmentFiles
from backend.app.shared.validation import InvalidInput, strict_json_object

from .attachment_observation import now
from .management_query import (
    available_actions,
    capacity,
    catalog_projection,
    environment_backups,
    environment_detail,
    environments,
    operation_detail,
    visible_filter,
    operations,
)
from .operation_contract import (
    Catalog,
    CONFLICT,
    DENIED,
    INVALID,
    MISSING,
    RESOURCE,
    SCOPE,
    UNAVAILABLE,
    VERSION,
)
from .operation_store import KEY_CONFLICT, execute_operation
from .registry import read_registry, verify_registered_data
from .registry_dispatch import PAUSED, require_dispatch_open
from .release_configuration import CHANGED, INCOMPATIBLE
from .runtime_controls import lookup_control
from .registry_installation import RegistryInstallation
from .web_installation import ManagementWeb, listening_socket

PUBLIC_PATH = '/.well-known/walle-management.json'
API_BASE = '/management/api/v1'
PREFIX = API_BASE + '/'
AUTH = 'REQUEST_SOURCE_REJECTED'
NOT_READY = 'MANAGEMENT_NOT_READY'
MAX_COMMAND_BYTES = 64 * 1024
WRITE_ACTIONS = frozenset(
    {'ATTACH', 'REGISTER_DELIVERY', 'START', 'STOP', 'RELEASE', 'BACKUP', 'RESTORE'}
)
CONTROL_SUBMISSION = re.compile(re.escape(PREFIX) + r'operations/([^/]+)/commands')
JSON_CONTENT = re.compile(r'application/json(?:\s*;\s*charset=utf-8)?', re.IGNORECASE)
REASONS = {
    INVALID: (400, '管理请求格式无效。'),
    'BACKUP_ASSET_UNSUPPORTED': (409, '当前备份资产或核验方式尚未准入。'),
    'MAINTENANCE_DRAIN_BLOCKED': (409, '尚未核实源环境已经正常停止。'),
    DENIED: (403, '当前身份无权执行此管理请求。'),
    AUTH: (403, '管理请求来源无法核实。'),
    SCOPE: (409, '管理入口或登记代次已变化，请重新核对入口。'),
    RESOURCE: (409, '实际管理资源暂无法核实。'),
    CONFLICT: (409, '目标资源或原操作已有占用。'),
    KEY_CONFLICT: (409, '原请求键已绑定另一份输入。'),
    VERSION: (409, '环境或分配版本已变化，请重新读取。'),
    CHANGED: (409, '维护计划或源部署已变化，请重新确认。'),
    INCOMPATIBLE: (409, '固定候选的兼容或验证证据不足。'),
    UNAVAILABLE: (409, '当前管理入口尚未开放这项操作。'),
    NOT_READY: (503, '管理登记暂不可读。'),
    PAUSED: (503, '管理登记当前只读，写入暂不可用。'),
    'MANAGEMENT_PRIOR_REGISTRY_RESULT_UNVERIFIED': (409, '原登记回执尚无法核实。'),
    MISSING: (404, '当前管理范围内未找到此记录。'),
}


@dataclass
class ManagementScope:
    web: ManagementWeb
    catalog: Catalog
    run_id: str
    observed_at: str
    native: NativeEnvironmentFiles
    installation: RegistryInstallation
    runtime_sha: str

    def headers(self, principal=None):
        return {
            'X-WALL-E-Manager-ID': self.catalog.scope['manager_id'],
            'X-WALL-E-Registry-Generation': self.catalog.scope['registry_generation'],
            'X-WALL-E-Manager-Run-ID': self.run_id,
            'Cache-Control': 'no-store',
            **({'X-WALL-E-Manager-Principal': principal.id} if principal is not None else {}),
        }

    def config(self):
        return {
            'format_version': 1,
            'management_protocol': 1,
            **self.catalog.scope,
            'display_name': self.web.display_name,
            'public_origin': self.web.origin,
            'api_base': API_BASE,
        }

    def dispatch_phase(self, pending):
        try:
            require_dispatch_open(self.installation)
        except (EnvironmentFailure, OSError):
            return 'BLOCKED'
        return 'RECOVERING' if pending else 'READY'

    def identify(self, connection, principal, kind):
        visible, values = visible_filter(principal, 'env', ownership=True)
        pending = connection.execute(
            'SELECT 1 FROM management_operations AS op JOIN managed_environments AS env USING(environment_id) '
            "WHERE op.registry_generation=? AND op.status IN ('RUNNING','UNKNOWN') AND "
            + visible
            + ' LIMIT 1',
            (self.catalog.scope['registry_generation'], *values),
        ).fetchone()
        phase = self.dispatch_phase(pending)
        actions = available_actions(principal, candidates=bool(self.catalog.candidates))
        if phase == 'BLOCKED':
            actions = [
                {**action, 'enabled': False, 'reason_code': PAUSED} if action['enabled'] else action
                for action in actions
            ]
        return {
            **self.config(),
            'manager_run_id': self.run_id,
            'phase': phase,
            'observed_at': self.observed_at,
            'access': {
                'principal_id': principal.id,
                'client_kind': kind,
                'role': principal.role,
                'visible_environment_ids': list(principal.visible),
            },
            'available_actions': actions,
        }

    def authorize(self, request):
        principal = single(request, 'x-wall-e-auth-principal')
        require(
            gateway_headers_match(request)
            and single(request, 'host') == urlsplit(self.web.origin).netloc
            and principal in self.web.identities,
            DENIED,
        )
        kind = self.web.identities[principal]
        require(
            len(request.headers.getlist('origin')) <= 1
            and (kind != 'AUTOMATION' or 'origin' not in request.headers)
            and source_matches(request, {'client_kind': kind}, self.web.origin),
            AUTH,
        )
        return self.catalog.access(principal), kind

    def validate_scope(self, request):
        manager = single(request, 'x-wall-e-manager-id')
        generation = single(request, 'x-wall-e-registry-generation')
        protocol = single(request, 'x-wall-e-management-protocol')
        require(
            uuid_value(manager)
            and uuid_value(generation)
            and bool(protocol and protocol.isascii() and protocol.isdigit()),
            INVALID,
        )
        require(
            manager == self.catalog.scope['manager_id']
            and generation == self.catalog.scope['registry_generation']
            and protocol == '1',
            SCOPE,
        )

    def query(self, connection, request, principal, kind):
        path, parameters = request.url.path, request.query_params
        require(request.method == 'GET', UNAVAILABLE)
        require(
            single(request, 'content-length') in (None, '0')
            and not request.headers.get('transfer-encoding'),
            INVALID,
        )
        if path == API_BASE + '/identity':
            require(not parameters, INVALID)
            return self.identify(connection, principal, kind)
        self.validate_scope(request)
        catalog = self.catalog
        if path == PREFIX + 'environments':
            return environments(connection, catalog, principal, parameters)
        if path == PREFIX + 'operations':
            return operations(connection, catalog, principal, parameters)
        fields = path.removeprefix(PREFIX).split('/')
        if (
            path.startswith(PREFIX)
            and len(fields) == 3
            and (fields[0], fields[2]) == ('environments', 'backups')
        ):
            return environment_backups(connection, catalog, principal, fields[1], parameters)
        if (
            path.startswith(PREFIX)
            and len(fields) == 3
            and (fields[0], fields[2]) == ('environments', 'prior-command-results')
        ):
            from .prior_result_view import prior_command_result, prior_command_scopes

            if not parameters:
                return prior_command_scopes(connection, catalog, principal, fields[1])
            return prior_command_result(connection, catalog, principal, fields[1], parameters)
        if path == PREFIX + 'catalog' and parameters:
            from .release_catalog_view import release_choices

            pairs = list(parameters.multi_items())
            filters = dict(pairs)
            require(len(pairs) == len(filters) and 'environment_id' in filters, INVALID)
            target = filters['environment_id']
            if set(filters) == {'environment_id', 'kind'} and filters['kind'] == 'BACKUP':
                from .backup_catalog_view import backup_choices

                return backup_choices(connection, catalog, principal, target)
            if set(filters) == {'environment_id', 'kind'} and filters['kind'] == 'RESTORE':
                from .restore_catalog_view import restore_choices

                return restore_choices(connection, catalog, principal, target)
            require(set(filters) == {'environment_id'}, INVALID)
            return release_choices(connection, catalog, principal, target, self.runtime_sha)
        require(not parameters, INVALID)
        if (
            path.startswith(PREFIX)
            and len(fields) == 3
            and (fields[0], fields[2]) == ('environments', 'maintenance')
        ):
            from .release_maintenance_view import environment_maintenance

            return environment_maintenance(connection, catalog, principal, fields[1])
        if path == PREFIX + 'catalog':
            return catalog_projection(connection, catalog, principal, self.runtime_sha)
        if path == PREFIX + 'capacity':
            return capacity(connection, catalog, principal)
        if (
            path.startswith(PREFIX)
            and len(fields) == 4
            and fields[0] == 'operations'
            and fields[2] == 'commands'
        ):
            operation_id, control_key = fields[1], fields[3]
            require(uuid_value(operation_id) and uuid_value(control_key), INVALID)
            return lookup_control(
                connection,
                catalog,
                principal,
                control_key,
                {'action': 'LOOKUP_CONTROL', 'operation_id': operation_id},
            )
        if path.startswith(PREFIX) and len(fields) == 2:
            section, identity_value = fields
            if section == 'environments':
                return environment_detail(connection, catalog, principal, identity_value)
            if section == 'operations':
                return operation_detail(
                    connection, catalog, principal, identity_value, by_key=False
                )
        if path.startswith(PREFIX) and len(fields) == 3 and fields[:2] == ['operations', 'by-key']:
            return operation_detail(connection, catalog, principal, fields[2], by_key=True)
        if (
            path.startswith(PREFIX)
            and len(fields) >= 4
            and (fields[0], fields[2]) == ('prior-registry', 'operations')
        ):
            from .registry_recovery_history import prior_result

            if len(fields) == 5 and fields[3] == 'by-key':
                return prior_result(
                    self.native,
                    self.installation,
                    connection,
                    principal,
                    fields[1],
                    fields[4],
                    self.runtime_sha,
                )
            if len(fields) == 6 and fields[4] == 'commands':
                return prior_result(
                    self.native,
                    self.installation,
                    connection,
                    principal,
                    fields[1],
                    fields[5],
                    self.runtime_sha,
                    operation=fields[3],
                )
        raise EnvironmentFailure(MISSING)

    async def submit(self, request, principal, operation_id=None, *, preview=False):
        self.validate_scope(request)
        require(not request.query_params, INVALID)
        roles = ('MANAGER',) if preview else ('MANAGER', 'DEVELOPER')
        require(principal.role in roles, DENIED)
        expected_principals = request.headers.getlist('x-wall-e-expected-principal')
        require(not expected_principals or expected_principals == [principal.id], DENIED)
        key = single(request, 'idempotency-key')
        content_type = single(request, 'content-type')
        lengths = request.headers.getlist('content-length')
        require(
            (uuid_value(key) or (preview and key is None))
            and content_type is not None
            and JSON_CONTENT.fullmatch(content_type)
            and not request.headers.getlist('content-encoding')
            and len(lengths) <= 1,
            INVALID,
        )
        if lengths:
            length = lengths[0]
            require(
                len(length) <= 5
                and length.isascii()
                and length.isdigit()
                and 0 < int(length) <= MAX_COMMAND_BYTES,
                INVALID,
            )
        raw = bytearray()
        try:
            async with timeout(10):
                async for chunk in request.stream():
                    require(len(raw) + len(chunk) <= MAX_COMMAND_BYTES, INVALID)
                    raw.extend(chunk)
            require(not lengths or len(raw) == int(lengths[0]), INVALID)
            intent = strict_json_object(bytes(raw))
            # SQLite stores the original UTF-8 intent; JSON escapes can decode to lone surrogates.
            canonical(intent)
        except (ClientDisconnect, InvalidInput, TimeoutError, UnicodeError) as error:
            raise EnvironmentFailure(INVALID) from error
        if preview:
            if intent.get('kind') == 'BACKUP':
                from .backup_operations import plan_backup

                planner = plan_backup
            elif intent.get('kind') == 'RESTORE':
                from .restore_operations import plan_restore

                planner = plan_restore
            else:
                from .release_operations import plan_release

                planner = plan_release
            planned = await run_in_threadpool(
                planner,
                self.native,
                self.installation,
                self.catalog,
                principal,
                intent,
                self.runtime_sha,
            )
            return planned, 201
        if operation_id is None:
            action = intent.get('action')
            require(type(action) is str, INVALID)
            require(action in WRITE_ACTIONS, UNAVAILABLE)
        else:
            exact(intent, ('command', 'expected_revision'), INVALID)
            require(intent['command'] in ('RECONCILE', 'CANCEL', 'CONTINUE'), UNAVAILABLE)
            intent = {'action': 'CONTROL', 'operation_id': operation_id, **intent}
        payload = {
            'format_version': 1,
            **self.catalog.scope,
            'principal': principal.id,
            'request_key': key,
            'input': intent,
        }
        result, existing = await run_in_threadpool(
            execute_operation,
            self.native,
            self.installation,
            self.catalog,
            payload,
            self.runtime_sha,
        )
        return result, 200 if existing else 202

    async def respond(self, request):
        request_id = str(uuid4())
        principal = None
        try:
            principal, kind = self.authorize(request)
            request_path = request.url.path
            control = CONTROL_SUBMISSION.fullmatch(request_path)
            preview = request_path == PREFIX + 'plans'
            if request.method == 'POST' and (
                request_path == PREFIX + 'operations' or control or preview
            ):
                verify_registered_data(self.native, self.installation, self.runtime_sha)
                result, status = await self.submit(
                    request, principal, control[1] if control else None, preview=preview
                )
                verify_registered_data(self.native, self.installation, self.runtime_sha)
            else:
                with read_registry(self.native, self.installation, self.runtime_sha) as connection:
                    if request.url.path == PUBLIC_PATH:
                        require(request.method == 'GET' and not request.query_params, INVALID)
                        return JSONResponse(self.config(), headers=self.headers(principal))
                    result = self.query(connection, request, principal, kind)
                status = 200
            message = None
        except (
            EnvironmentFailure,
            sqlite3.Error,
            OSError,
            KeyError,
            ValueError,
            TypeError,
        ) as error:
            code = getattr(error, 'code', NOT_READY)
            if code not in REASONS:
                code = NOT_READY
            status, detail = REASONS[code]
            message = {'code': code, 'message': detail, 'details': None}
            result = None
        return JSONResponse(
            {
                'success': status in (200, 201, 202),
                'data': result,
                'error': message,
                'meta': {'request_id': request_id},
            },
            status_code=status,
            headers=self.headers(principal),
        )


def serve(native, installation, catalog, web, runtime_sha):
    from uvicorn import Config, Server

    class ManagementServer(Server):
        @contextmanager
        def capture_signals(self):
            # Keep the owned socket cleanup on the normal shutdown path.
            events = (signal.SIGINT, signal.SIGTERM)
            previous = {event: signal.signal(event, self.handle_exit) for event in events}
            try:
                yield
            finally:
                for event, handler in previous.items():
                    signal.signal(event, handler)

    with read_registry(native, installation, runtime_sha, integrity=True):
        pass
    with listening_socket(web, installation) as sock:
        scope = ManagementScope(
            web, catalog, str(uuid4()), now(), native, installation, runtime_sha
        )
        methods = ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']
        app = Starlette(routes=[Route('/{path:path}', scope.respond, methods=methods)])
        server = ManagementServer(
            Config(app, proxy_headers=False, access_log=False, log_config=None)
        )
        server.run(sockets=[sock])
        return 0 if server.started else 2
