"""Private Unix-channel authentication and P1 application action admission."""

import re
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from backend.app.shared.http_errors import new_request_id

from .environment_files import EnvironmentFailure
from .environment_installation import read_access_policy, uuid_value

DOCUMENT_READ = re.compile(
    r'/api/v1/(?:requirements(?:/[^/]+(?:/(?:current-document|manual-draft|revisions|'
    r'comments|comment-index|messages))?)?|(?:revisions|comments|conversation-messages)/[^/]+)'
)
ORDINARY_RECEIPT_READ = re.compile(r'/api/v1/(?:code|testing)-command-receipts')
RECOVERY_REASON = 'RECOVERY_RECONCILIATION_REQUIRED'
WRITE = {
    'POST': re.compile(
        r'/api/v1/requirements(?:/[^/]+/(?:documents|manual-draft(?:/complete)?|'
        r'complete-initialization))?'
    ),
    'PUT': re.compile(r'/api/v1/requirements/[^/]+/manual-draft'),
    'DELETE': re.compile(r'/api/v1/requirements/[^/]+/manual-draft'),
}
CAPABILITIES = (
    'DOCUMENT_READ',
    'DOCUMENT_WRITE',
    'DOCUMENT_AI',
    'TEST_PLAN_AI',
    'INTERNAL_EXECUTION',
    'INDEPENDENT_CHECK',
)
ERRORS = {
    'ENVIRONMENT_ACCESS_DENIED': (403, '当前访问身份无权执行此操作'),
    'REQUEST_SOURCE_REJECTED': (403, '请求来源不符合当前环境要求'),
    'ENVIRONMENT_BINDING_INVALID': (400, '环境绑定信息缺失或不合法'),
    'ENVIRONMENT_MISMATCH': (409, '当前入口与请求所属环境不一致'),
    'DATA_GENERATION_MISMATCH': (409, '数据已更换，请先核对原操作和草稿'),
    'BINDING_PROTOCOL_MISMATCH': (409, '客户端与服务的环境协议不兼容'),
    'ENVIRONMENT_CAPABILITY_DISABLED': (403, '此环境未启用该操作所需能力'),
    'ENVIRONMENT_NOT_READY': (503, '环境尚未就绪，请稍后查看状态'),
    'RECOVERY_READ_ONLY': (403, '恢复核对期间仅可读取已核验资料'),
}


def single(request, name):
    raw = request.headers.getlist(name)
    if not raw:
        return None
    if len(raw) != 1 or ',' in raw[0]:
        return ''
    return raw[0]


def identity_headers(scope):
    return {
        'X-WALL-E-Environment-ID': scope.installation.environment_id,
        'X-WALL-E-Data-Generation': scope.installation.data_generation,
        'X-WALL-E-Run-ID': scope.run_id,
        'Cache-Control': 'no-store',
    }


def reject(scope, code):
    status, message = ERRORS[code]
    return JSONResponse(
        {
            'success': False,
            'data': None,
            'error': {'code': code, 'message': message, 'details': None},
            'meta': {'request_id': new_request_id()},
        },
        status_code=status,
        headers=identity_headers(scope),
    )


def installed_identities(installation):
    contents = read_access_policy(installation)
    return contents['public_origin'], {
        item['principal_id']: item for item in contents['principals']
    }


def source_matches(request, access, origin):
    shape = single(request, 'x-wall-e-client')
    source = single(request, 'origin')
    if access['client_kind'] == 'AUTOMATION':
        return (
            shape == 'automation-v1'
            and source is None
            and not any(key.startswith('sec-fetch-') for key in request.headers)
        )
    safe_read = request.method == 'GET'
    return (
        shape == 'web-v1'
        and single(request, 'sec-fetch-site') == 'same-origin'
        and (source == origin or safe_read and source is None)
    )


def binding_error(request, scope):
    environment = single(request, 'x-wall-e-environment-id')
    generation = single(request, 'x-wall-e-data-generation')
    protocol = single(request, 'x-wall-e-binding-protocol')
    if (
        not uuid_value(environment)
        or not uuid_value(generation)
        or not protocol
        or not protocol.isascii()
        or not protocol.isdigit()
    ):
        return 'ENVIRONMENT_BINDING_INVALID'
    if protocol != '1':
        return 'BINDING_PROTOCOL_MISMATCH'
    if environment != scope.installation.environment_id:
        return 'ENVIRONMENT_MISMATCH'
    if generation != scope.installation.data_generation:
        return 'DATA_GENERATION_MISMATCH'
    return None


def handshake(scope, access, *, recovery=False):
    installation = scope.installation
    revision = scope.control['control_revision']
    access_view = {key: access[key] for key in ('client_kind', 'permission')}
    maintenance = {
        'contract_version': 1,
        'admission': 'OPEN',
        'maintenance_id': None,
        'stage': None,
        'control_revision': revision,
        'reason_code': None,
        'allowed_drain_actions': [],
        'recovery_read': {
            'status': 'NOT_APPLICABLE',
            'observed_at': scope.observed_at,
            'deployment_id': installation.deployment_id,
            'data_generation': installation.data_generation,
            'control_revision': revision,
            'verification_ref': None,
            'verified_scopes': [],
            'blockers': [],
        },
    }
    capability_reasons = dict.fromkeys(CAPABILITIES, 'CONFIG_DISABLED')
    capability_reasons['DOCUMENT_READ'] = None
    capability_reasons['DOCUMENT_WRITE'] = None
    if recovery:
        access_view['permission'] = 'READ_ONLY'
        capability_reasons['DOCUMENT_WRITE'] = 'RECOVERY_READ_ONLY'
        maintenance.update(
            admission='CLOSED',
            maintenance_id=scope.control['maintenance_id'],
            stage='BLOCKED',
            reason_code=RECOVERY_REASON,
        )
        maintenance['recovery_read'].update(
            status='AVAILABLE',
            verification_ref=scope.policy_sha256,
            verified_scopes=scope.plan['verified_scopes'],
            blockers=[RECOVERY_REASON],
        )
    return {
        'environment_id': installation.environment_id,
        'data_generation': installation.data_generation,
        'purpose': installation.description['purpose'],
        'run_id': scope.run_id,
        'phase': 'READY',
        'observed_at': scope.observed_at,
        'configuration_sha256': installation.configuration_sha256,
        'binding_protocol': 1,
        'access': access_view,
        'maintenance': maintenance,
        'capabilities': [
            {
                'code': code,
                'state': 'READY' if reason is None else 'DISABLED',
                'reason_code': reason,
            }
            for code, reason in capability_reasons.items()
        ],
    }


def gateway_headers_match(request):
    private = {'authorization', 'proxy-authorization', 'cookie', 'forwarded'}
    return not any(
        key in private or (key.startswith('x-wall-e-auth-') and key != 'x-wall-e-auth-principal')
        for key in request.headers
    )


async def recovery_available(scope):
    try:
        await run_in_threadpool(scope.check_current)
    except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError):
        return False
    return True


async def api_admission(request, call_next, scope, *, recovery=False):
    """The listener is reachable only through its owner-protected Unix directory."""
    try:
        origin, identities = await run_in_threadpool(installed_identities, scope.installation)
    except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError):
        return reject(scope, 'ENVIRONMENT_NOT_READY')
    principal = single(request, 'x-wall-e-auth-principal')
    access = identities.get(principal)
    if (
        access is None
        or not gateway_headers_match(request)
        or single(request, 'host') != urlsplit(origin).netloc
    ):
        return reject(scope, 'ENVIRONMENT_ACCESS_DENIED')
    route = request.url.path
    if recovery and not await recovery_available(scope):
        return reject(scope, 'ENVIRONMENT_NOT_READY')
    if not route.startswith('/api/'):
        if recovery and request.method not in ('GET', 'HEAD'):
            return reject(scope, 'RECOVERY_READ_ONLY')
        return await call_next(request)
    if not source_matches(request, access, origin):
        return reject(scope, 'REQUEST_SOURCE_REJECTED')
    is_handshake = route == '/api/v1/environment' and request.method == 'GET'
    if not is_handshake:
        error = binding_error(request, scope)
        if error:
            return reject(scope, error)
    if not scope.active or (not recovery and not request.app.state.walle_worker.accepting):
        return reject(scope, 'ENVIRONMENT_NOT_READY')
    if is_handshake:
        return JSONResponse(
            {
                'success': True,
                'data': handshake(scope, access, recovery=recovery),
                'error': None,
                'meta': {'request_id': new_request_id()},
            },
            headers=identity_headers(scope),
        )
    read = request.method == 'GET' and (
        DOCUMENT_READ.fullmatch(route) or (not recovery and ORDINARY_RECEIPT_READ.fullmatch(route))
    )
    if recovery and not read:
        return reject(scope, 'RECOVERY_READ_ONLY')
    writable = WRITE.get(request.method)
    write = writable is not None and writable.fullmatch(route)
    if not read and not write:
        return reject(scope, 'ENVIRONMENT_CAPABILITY_DISABLED')
    if write and access['permission'] != 'DEVELOP':
        return reject(scope, 'ENVIRONMENT_ACCESS_DENIED')
    response = await call_next(request)
    if recovery and not await recovery_available(scope):
        return reject(scope, 'ENVIRONMENT_NOT_READY')
    response.headers.update(identity_headers(scope))
    return response
