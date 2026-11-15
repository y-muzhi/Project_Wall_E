"""Forward browser traffic only to the held original Testing application roots."""

from dataclasses import dataclass
from urllib.parse import unquote_to_bytes

from backend.app.shared.validation import strict_integer

from .check_case_pack import CaseStep
from .check_case_values import byte_literal, header_value, relative_target, request_method
from .check_driver_bootstrap import BROWSER_RESPONSE_BODY_MAX_BYTES
from .check_runner_bundle import exact_record, reference, valid_sha256
from .owned_check_http import (
    OwnedHttpEndpoint,
    OwnedHttpUnavailable,
    OwnedHttpUnknown,
    _exchange_original_request,
    _original_request,
)
from .runtime_launch_journal import TestingLaunchScope
from .windows_process import NativeProcessIdentity, ObservedProcess

_REQUEST = frozenset(
    {
        'accept',
        'content-type',
        'content-language',
        'if-match',
        'if-none-match',
        'idempotency-key',
    }
)
_RESPONSE = frozenset(
    {
        'content-type',
        'content-language',
        'cache-control',
        'etag',
        'vary',
        'content-encoding',
        'content-security-policy',
        'content-security-policy-report-only',
        'x-content-type-options',
        'x-frame-options',
        'referrer-policy',
        'permissions-policy',
        'cross-origin-resource-policy',
        'cross-origin-opener-policy',
        'cross-origin-embedder-policy',
        'last-modified',
        'expires',
    }
)
_UNSUPPORTED_RESPONSE = frozenset(
    {
        'set-cookie',
        'location',
        'upgrade',
        'content-disposition',
        'refresh',
        'trailer',
        'access-control-allow-origin',
        'access-control-allow-credentials',
    }
)
_MAX_BYTES = 16 * 1024 * 1024


def _request_headers(values):
    if type(values) is not dict or not values.keys() <= _REQUEST:
        raise OwnedHttpUnavailable('ORIGINAL_BROWSER_REQUEST_HEADERS_UNSUPPORTED')
    return tuple(sorted((key, header_value(value)) for key, value in values.items()))


def _response_headers(status, values):
    if 300 <= status < 400 and status != 304:
        raise OwnedHttpUnknown('ORIGINAL_BROWSER_REDIRECT_UNSUPPORTED')
    kept = []
    seen = set()
    for raw, value in values:
        name = raw.lower()
        if name in _UNSUPPORTED_RESPONSE:
            raise OwnedHttpUnknown('ORIGINAL_BROWSER_RESPONSE_HEADERS_UNSUPPORTED')
        if name in _RESPONSE:
            if name in seen or name == 'content-encoding' and value.lower() != 'identity':
                raise OwnedHttpUnknown('ORIGINAL_BROWSER_RESPONSE_HEADERS_UNSUPPORTED')
            seen.add(name)
            kept.append((name, header_value(value)))
    return kept


@dataclass(frozen=True)
class BrowserApplication:
    scope: TestingLaunchScope
    endpoint: OwnedHttpEndpoint
    process: NativeProcessIdentity
    receipt_sha256: str
    verify_job: object

    def __post_init__(self):
        if (
            type(self.scope) is not TestingLaunchScope
            or type(self.endpoint) is not OwnedHttpEndpoint
            or type(self.process) is not NativeProcessIdentity
            or not valid_sha256(self.receipt_sha256)
            or not callable(self.verify_job)
        ):
            raise OwnedHttpUnavailable('ORIGINAL_BROWSER_APPLICATION_REQUIRED')


@dataclass(frozen=True)
class BrowserRoute:
    origin_ref: str
    prefix: str
    role: str
    application: BrowserApplication

    def __post_init__(self):
        reference(self.origin_ref)
        path = relative_target(self.prefix)
        if (
            not path.endswith('/')
            or '%' in path
            or '?' in path
            or self.role not in ('FRONTEND', 'BACKEND')
            or type(self.application) is not BrowserApplication
        ):
            raise OwnedHttpUnavailable('ORIGINAL_BROWSER_ROUTE_REQUIRED')


def _operation(scope):
    return scope.controller_ref, scope.owner_id, scope.control_generation, scope.operation_id


class OwnedBrowserRelay:
    """A single ordered relay. Persist intent before business bytes, including GET."""

    def __init__(self, scope, routes, *, request_limit, output_limit, count_limit, before_send):
        if (
            type(scope) is not TestingLaunchScope
            or type(routes) is not tuple
            or not 1 <= len(routes) <= 16
            or any(type(route) is not BrowserRoute for route in routes)
            or not callable(before_send)
        ):
            raise OwnedHttpUnavailable('ORIGINAL_BROWSER_RELAY_REQUIRED')
        seen = set()
        applications = {}
        roles = {}
        for route in routes:
            app = route.application
            key = (route.origin_ref, route.prefix)
            if key in seen or app.scope == scope or _operation(app.scope) != _operation(scope):
                raise OwnedHttpUnavailable('ORIGINAL_BROWSER_RELAY_SCOPE_DIFFERS')
            seen.add(key)
            prior = applications.setdefault(app.endpoint.address, app)
            if prior != app or roles.setdefault(app.scope, route.role) != route.role:
                raise OwnedHttpUnavailable('ORIGINAL_BROWSER_APPLICATION_AMBIGUOUS')
        if len({app.scope for app in applications.values()}) != len(applications):
            raise OwnedHttpUnavailable('ORIGINAL_BROWSER_APPLICATION_AMBIGUOUS')
        if len({app.process for app in applications.values()}) != len(applications):
            raise OwnedHttpUnavailable('ORIGINAL_BROWSER_APPLICATION_AMBIGUOUS')
        self.scope = scope
        self.origins = tuple(dict.fromkeys(route.origin_ref for route in routes))
        self._routes = tuple(sorted(routes, key=lambda route: -len(route.prefix)))
        self._request_limit = strict_integer(request_limit, 'request_limit', maximum=_MAX_BYTES)
        self._remaining = strict_integer(output_limit, 'output_limit', maximum=_MAX_BYTES)
        self._count_limit = strict_integer(count_limit, 'count_limit', maximum=1024)
        self._before_send = before_send
        self._sequence = 1
        self._closed = False
        self._traffic = []

    @property
    def traffic(self):
        return tuple(self._traffic)

    def _route(self, origin_ref, raw_target):
        target = relative_target(raw_target)
        path = unquote_to_bytes(target.partition('?')[0])
        for route in self._routes:
            if route.origin_ref == origin_ref and path.startswith(route.prefix.encode('ascii')):
                return route, target
        raise OwnedHttpUnavailable('ORIGINAL_BROWSER_DESTINATION_NOT_REGISTERED')

    def send(self, value, *, deadline, active):
        if self._closed:
            raise OwnedHttpUnknown('ORIGINAL_BROWSER_RELAY_CLOSED')
        dispatched = False
        try:
            row = exact_record(value, ('seq', 'origin_ref', 'path', 'method', 'headers', 'body'))
            sequence = strict_integer(row['seq'], 'seq', maximum=self._count_limit)
            if sequence != self._sequence:
                raise OwnedHttpUnavailable('ORIGINAL_BROWSER_REQUEST_SEQUENCE_DIFFERS')
            route, path = self._route(reference(row['origin_ref']), row['path'])
            app = route.application
            body = byte_literal(row['body'], self._request_limit)
            method = request_method(row['method'])
            step = CaseStep(
                'browser-' + str(sequence),
                'REQUEST',
                (app.endpoint.endpoint_ref, path, method, _request_headers(row['headers']), body),
            )
            _, raw = _original_request(
                step, app.endpoint, self._request_limit, headers_decoder=_request_headers
            )

            def record(_step_id, request_sha256):
                nonlocal dispatched
                self._before_send(sequence, route, request_sha256)
                dispatched = True

            with ObservedProcess(app.process.pid, expected=app.process) as process:
                observed = _exchange_original_request(
                    step,
                    app.endpoint,
                    process,
                    method,
                    raw,
                    deadline=deadline,
                    active=active,
                    verify_job=app.verify_job,
                    before_send=record,
                    remaining=min(self._remaining, BROWSER_RESPONSE_BODY_MAX_BYTES),
                    response_decoder=_response_headers,
                )
            self._remaining -= len(observed.body) + sum(
                len(k) + len(v) for k, v in observed.headers
            )
            self._sequence += 1
            self._traffic.append((sequence, route.role, app.scope, app.receipt_sha256))
            return observed
        except Exception as error:
            self._closed = True
            if dispatched or self._traffic:
                raise OwnedHttpUnknown('ORIGINAL_BROWSER_RELAY_RESULT_UNVERIFIED') from error
            raise OwnedHttpUnavailable('ORIGINAL_BROWSER_RELAY_UNAVAILABLE') from error
