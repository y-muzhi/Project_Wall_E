"""Durable private browser case and per-request intent evidence."""

from dataclasses import asdict, dataclass

from backend.app.infrastructure.check_runner_bundle import exact_record, valid_sha256
from backend.app.infrastructure.guard_control_git_reply import _check_task_mutation
from backend.app.infrastructure.guard_task_files import _publish_original, _read_original
from backend.app.infrastructure.guard_task_launch_protocol import check_task_prepare_ack
from backend.app.infrastructure.runtime_launch_journal import (
    LaunchOutcomeUnknown,
    _bytes,
    decode_launch_scope,
)
from backend.app.shared.validation import strict_json_object

_MAX = 4 * 1024 * 1024
_TERMINAL = ('PASSED', 'FAILED', 'UNAVAILABLE', 'UNKNOWN', 'CANCELLED', 'INPUT_CHANGED')


@dataclass(frozen=True)
class ClosedBrowserCase:
    status: str
    assertions: tuple
    traffic: tuple
    prepared: dict | None
    created: dict | None
    stopped: dict | None
    released: dict | None


class BrowserCaseJournal:
    def __init__(self, evidence, case):
        if evidence._scope != case.scope or evidence._epoch != case.epoch or not case.applications:
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_JOURNAL_SCOPE_REQUIRED')
        self._evidence, self._case = evidence, case
        self._package = evidence._journal._package
        self._scope = case.scope
        self._applications = {item.scope: item for item in case.applications}
        self._name = case.scope.key + '.browser-case-result.json'

    def intent(self, sequence, route, request_sha256):
        application = self._applications.get(route.application.scope)
        if (
            type(sequence) is not int
            or not 1 <= sequence <= 1024
            or application is None
            or route.role != application.fixed['role']
            or route.prefix != application.fixed['prefix']
            or route.origin_ref != application.fixed['origin_ref']
            or not valid_sha256(request_sha256)
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_REQUEST_SCOPE_DIFFERS')
        payload = self._record(
            sequence, route.role, application.scope, route.application.receipt_sha256
        )
        payload['request_sha256'] = request_sha256
        raw = _bytes(payload)
        with self._evidence._journal._scope(self._scope):
            self._evidence._active()
            name = self._intent_name(sequence)
            if _read_original(self._package, name, 8192) is not None:
                raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_REQUEST_ALREADY_DISPATCHED')
            _publish_original(self._package, name, raw, 8192)
            if _read_original(self._package, name, 8192) != raw:
                raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_REQUEST_INTENT_UNVERIFIED')

    def _intent_name(self, number):
        return f'{self._scope.key}.browser-request-{number}.json'

    def _record(self, number, role, app_scope, receipt):
        return {
            'scope': asdict(self._scope),
            'owner_epoch': self._case.epoch,
            'sequence': number,
            'role': role,
            'application_scope': asdict(app_scope),
            'application_receipt_sha256': receipt,
        }

    def _traffic(self, values):
        traffic = []
        if type(values) is not list or len(values) > 1024:
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_TRAFFIC_DIFFERS')
        for number, row in enumerate(values, 1):
            if type(row) is not list or len(row) != 4:
                raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_TRAFFIC_DIFFERS')
            sequence, role, stored_scope, receipt = row
            scope = decode_launch_scope(stored_scope)
            original = self._applications.get(scope)
            if (
                type(sequence) is not int
                or sequence != number
                or original is None
                or original.fixed['role'] != role
                or not valid_sha256(receipt)
            ):
                raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_TRAFFIC_DIFFERS')
            raw = _read_original(self._package, self._intent_name(number), 8192)
            if raw is None:
                raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_REQUEST_INTENT_MISSING')
            fact = strict_json_object(raw)
            request = fact.pop('request_sha256', None)
            if not valid_sha256(request) or fact != self._record(number, role, scope, receipt):
                raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_REQUEST_INTENT_DIFFERS')
            traffic.append((number, role, scope, receipt))
        return tuple(traffic)

    def _decode(self, data):
        value = exact_record(data, ('scope', 'epoch', 'case_sha256', 'status', 'cases', 'traffic'))
        if (
            value['scope'] != asdict(self._scope)
            or value['epoch'] != self._case.epoch
            or value['case_sha256'] != self._case.fixed['case_pack_sha256']
            or value['status'] not in _TERMINAL
            or type(value['cases']) is not list
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_RESULT_SCOPE_DIFFERS')
        prepared, created, resumed, stopped, released = (
            self._evidence.original_ack(action)
            for action in ('PREPARE', 'CREATE_SUSPENDED', 'RESUME', 'STOP', 'RELEASE')
        )
        if stopped is None or released is None:
            self._evidence.require_no_dispatch()
            if any(item is not None for item in (prepared, created, resumed, stopped, released)):
                raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_RESULT_CLEANUP_REQUIRED')
        else:
            reference = released['binding_ref']
            for action, ack in (
                ('CREATE_SUSPENDED', created),
                ('RESUME', resumed),
                ('STOP', stopped),
                ('RELEASE', released),
            ):
                if ack is not None:
                    _check_task_mutation(
                        self._scope, reference, action, ack, run_kind='CHECK_DRIVER'
                    )
            if prepared is not None:
                check_task_prepare_ack(self._scope, reference, prepared, run_kind='CHECK_DRIVER')
            if stopped['native'] != released['native']:
                raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_RESULT_ROOT_DIFFERS')
        if value['status'] in ('PASSED', 'FAILED'):
            if not all(
                item is not None for item in (prepared, created, resumed, stopped, released)
            ):
                raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_RESULT_NATIVE_REQUIRED')
            check = released['check']
            exit = check['exit']
            if (
                check['check'] != asdict(self._case.check)
                or check['source_integrity'] != 'VERIFIED'
                or exit is None
                or exit['terminated']
                or exit['exit_code'] != 0
                or any(
                    ack['native'][field] != released['native'][field]
                    for ack in (created, resumed)
                    for field in ('process_identity', 'resource_ref', 'receipt_sha256')
                )
                or len(value['cases']) != 1
                or value['cases'][0]['case_id'] != self._case.case_id
                or value['cases'][0]['result'] != value['status']
            ):
                raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_RESULT_NATIVE_DIFFERS')
        elif value['cases']:
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_UNKNOWN_WITH_ASSERTIONS')
        return ClosedBrowserCase(
            value['status'],
            tuple(value['cases']),
            self._traffic(value['traffic']),
            prepared,
            created,
            stopped,
            released,
        )

    def read(self):
        with self._evidence._journal._scope(self._scope):
            raw = _read_original(self._package, self._name, _MAX)
            if raw is None:
                return None
            value = strict_json_object(raw)
            if raw != _bytes(value):
                raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_RESULT_BYTES_DIFFERS')
            return self._decode(value)

    def save(self, status, cases=(), traffic=()):
        value = {
            'scope': asdict(self._scope),
            'epoch': self._case.epoch,
            'case_sha256': self._case.fixed['case_pack_sha256'],
            'status': status,
            'cases': list(cases),
            'traffic': [[n, role, asdict(scope), receipt] for n, role, scope, receipt in traffic],
        }
        raw = _bytes(value)
        with self._evidence._journal._scope(self._scope):
            observed = self._decode(value)
            original = _read_original(self._package, self._name, _MAX)
            if original is None:
                _publish_original(self._package, self._name, raw, _MAX)
                original = _read_original(self._package, self._name, _MAX)
            if original != raw:
                raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_RESULT_BYTES_DIFFERS')
            return observed
