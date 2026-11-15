"""Protected, scope-bound HTTP write intent and sanitized case evidence."""

from dataclasses import asdict

from backend.app.shared.validation import strict_json_object

from .check_runner_bundle import reference, valid_sha256
from .guard_task_files import _publish_original, _read_original
from .runtime_launch_journal import LaunchOutcomeUnknown, TestingLaunchScope, _bytes

_LIMIT = 128 * 1024


class ProjectCheckHttpJournal:
    def __init__(self, journal, scope, epoch, active):
        if type(scope) is not TestingLaunchScope:
            raise LaunchOutcomeUnknown('ORIGINAL_TESTING_HTTP_SCOPE_REQUIRED')
        self._journal, self._scope, self._epoch, self._active = journal, scope, epoch, active

    def _record(self, value):
        return {'scope': asdict(self._scope), 'owner_epoch': self._epoch, 'http': value}

    def _name(self, kind):
        return f'{self._scope.key}.testing-http-{kind}.json'

    def _read(self, kind):
        raw = _read_original(self._journal._package, self._name(kind), _LIMIT)
        if raw is None:
            return None
        record = strict_json_object(raw)
        value = record.get('http')
        if type(value) is not dict or self._record(value) != record or _bytes(record) != raw:
            raise LaunchOutcomeUnknown('ORIGINAL_TESTING_HTTP_RECORD_DIFFERS')
        return value

    def intent(self, sequence, step_id, request_sha256, native_receipt):
        if (
            type(sequence) is not int
            or not 1 <= sequence <= 256
            or not valid_sha256(request_sha256)
            or not valid_sha256(native_receipt)
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_TESTING_HTTP_INTENT_DIFFERS')
        value = {
            'sequence': sequence,
            'step_id': reference(step_id),
            'request_sha256': request_sha256,
            'native_receipt': native_receipt,
        }
        self._active()
        with self._journal._scope(self._scope):
            kind = 'request-' + str(sequence)
            if (
                self._read(kind) is not None
                or self._read('outcome') is not None
                or sequence > 1
                and self._read('request-' + str(sequence - 1)) is None
            ):
                raise LaunchOutcomeUnknown('ORIGINAL_TESTING_HTTP_REQUEST_MAY_EXIST')
            self._publish(kind, value)

    def _publish(self, kind, value):
        _publish_original(
            self._journal._package, self._name(kind), _bytes(self._record(value)), _LIMIT
        )
        if self._read(kind) != value:
            raise LaunchOutcomeUnknown('ORIGINAL_TESTING_HTTP_RECORD_UNVERIFIED')

    def finish(self, native_receipt, status, steps, outcome):
        value = {
            'native_receipt': native_receipt,
            'status': status,
            'steps': list(steps),
            'outcome': outcome,
        }
        with self._journal._scope(self._scope):
            self._verify(value, native_receipt)
            self._publish('outcome', value)

    def _verify(self, value, native_receipt):
        if (
            set(value) != {'native_receipt', 'status', 'steps', 'outcome'}
            or not valid_sha256(native_receipt)
            or value['native_receipt'] != native_receipt
            or value['status'] not in ('OBSERVED', 'UNAVAILABLE', 'UNKNOWN')
            or type(value['steps']) is not list
            or len(value['steps']) > 256
            or any(reference(step) != step for step in value['steps'])
            or len(set(value['steps'])) != len(value['steps'])
            or (type(value['outcome']) is dict) != (value['status'] == 'OBSERVED')
            or value['status'] == 'UNAVAILABLE'
            and value['steps']
            or value['status'] == 'OBSERVED'
            and not value['steps']
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_TESTING_HTTP_OUTCOME_DIFFERS')
        for index, step in enumerate(value['steps'], 1):
            original = self._read('request-' + str(index))
            if (
                original is None
                or set(original) != {'sequence', 'step_id', 'request_sha256', 'native_receipt'}
                or original['sequence'] != index
                or original['step_id'] != step
                or original['native_receipt'] != native_receipt
                or not valid_sha256(original['request_sha256'])
            ):
                raise LaunchOutcomeUnknown('ORIGINAL_TESTING_HTTP_INTENT_DIFFERS')
        if self._read('request-' + str(len(value['steps']) + 1)) is not None:
            raise LaunchOutcomeUnknown('ORIGINAL_TESTING_HTTP_INTENT_DIFFERS')

    def original_outcome(self, native_receipt):
        with self._journal._scope(self._scope):
            value = self._read('outcome')
            if value is not None:
                self._verify(value, native_receipt)
            return value
