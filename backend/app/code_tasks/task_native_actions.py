"""One-shot native session and message actions in the original backend package."""

from dataclasses import asdict

from backend.app.infrastructure.guard_task_files import _publish_original, _read_original
from backend.app.infrastructure.opencode_identifiers import OpenCodeMessageIds
from backend.app.infrastructure.opencode_instance_control import (
    OpenCodeInstanceControl,
    _identifier,
    native_json_equal,
    native_message_input,
    native_permission_rules,
    native_request_bytes,
    native_session_input,
)
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchScope, _bytes
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.infrastructure.windows_private_record import PrivateRecordError
from backend.app.shared.validation import MAX_SAFE_INTEGER, InvalidInput, strict_json_object

_LIMIT = 4 * 1024 * 1024


def _permission_input(expected, rules):
    fields = ('id', 'title', 'agent', 'model', 'metadata', 'permission')
    if type(expected) is not dict or set(expected) != set(fields):
        raise TaskExecutionError('ORIGINAL_PERMISSION_SESSION_POLICY_REQUIRED')
    value = strict_json_object(native_request_bytes({'before': expected, 'rules': rules}))
    before = value['before']
    _identifier(before['id'], 'ses')
    native_session_input({key: before[key] for key in fields if key != 'id'})
    checked = native_permission_rules(value['rules'])
    if checked[0] != {'permission': '*', 'pattern': '*', 'action': 'deny'}:
        raise TaskExecutionError('ORIGINAL_PERMISSION_EXPLICIT_RESET_REQUIRED')
    return value


def _record_bytes(value):
    raw = _bytes(value)
    if len(raw) > _LIMIT:
        raise TaskExecutionError('ORIGINAL_NATIVE_ACTION_RECORD_TOO_LARGE')
    return raw


class TaskNativeActions:
    def __init__(self, package, scope, control, *, action_scope=None, permission_history=()):
        if (
            type(package) is not PrivatePackageGuard
            or package.is_control_git_read_package
            or type(scope) is not LaunchScope
            or type(control) is not OpenCodeInstanceControl
            or control._credential._scope != scope
            or action_scope is not None
            and (
                type(action_scope) is not LaunchScope
                or action_scope.controller_ref != scope.controller_ref
                or action_scope.operation_id == scope.operation_id
                or action_scope.step_no not in (1, 3, 4)
            )
        ):
            raise TaskExecutionError('ORIGINAL_NATIVE_ACTION_OWNER_REQUIRED')
        self._package, self._identity = package, package.verify()
        self._scope, self._control = action_scope or scope, control
        self._launch_scope = scope
        if type(permission_history) is not tuple or any(
            type(item) is not LaunchScope for item in permission_history
        ):
            raise TaskExecutionError('ORIGINAL_PERMISSION_PREDECESSORS_REQUIRED')
        self._permission_history = permission_history
        self._permission_predecessors([asdict(item) for item in permission_history])
        self._ids = OpenCodeMessageIds()

    def _name(self, action, phase):
        return f'{self._scope.key}.task-opencode-{action}-{phase}.json'

    def _read(self, action, phase):
        if self._package.verify() != self._identity:
            raise TaskExecutionError('ORIGINAL_NATIVE_ACTION_PACKAGE_DIFFERS')
        return _read_original(self._package, self._name(action, phase), _LIMIT)

    def _write(self, action, phase, record):
        raw = _record_bytes(record)
        prior = self._read(action, phase)
        if prior is None:
            _publish_original(self._package, self._name(action, phase), raw, _LIMIT)
        if self._read(action, phase) != raw:
            raise TaskExecutionError('ORIGINAL_NATIVE_ACTION_RECORD_DIFFERS')

    def _begin(self, action, payload, checkpoint):
        checkpoint()
        if self._read(action, 'intent') is not None:
            raise TaskExecutionError('ORIGINAL_NATIVE_ACTION_REQUIRES_OBSERVATION')
        record = {'scope': self._scope.key, 'action': action, 'input': payload}
        # Only the original CREATE_NEW/no-replace publisher may dispatch.
        # Observing identical existing bytes never acquires another send slot.
        raw = _record_bytes(record)
        if self._package.verify() != self._identity:
            raise TaskExecutionError('ORIGINAL_NATIVE_ACTION_PACKAGE_DIFFERS')
        try:
            _publish_original(self._package, self._name(action, 'intent'), raw, _LIMIT)
        except PrivateRecordError as error:
            if getattr(error, 'retained_owner', None) is not None:
                raise
            raise TaskExecutionError('ORIGINAL_NATIVE_ACTION_PUBLICATION_UNKNOWN') from error
        checkpoint()
        return record

    def _original(self, action):
        raw = self._read(action, 'intent')
        try:
            value = {} if raw is None else strict_json_object(raw)
        except InvalidInput as error:
            raise TaskExecutionError('ORIGINAL_NATIVE_ACTION_INTENT_REQUIRED') from error
        if (
            set(value) != {'scope', 'action', 'input'}
            or value['scope'] != self._scope.key
            or value['action'] != action
            or type(value['input']) is not dict
        ):
            raise TaskExecutionError('ORIGINAL_NATIVE_ACTION_INTENT_REQUIRED')
        return value

    def _check_ack_capacity(self, action, payload, result):
        _record_bytes(
            {
                'scope': self._scope.key,
                'action': action,
                'input': payload,
                'result': result,
            }
        )

    def _ack(self, record, result):
        self._write(record['action'], 'ack', {**record, 'result': result})

    def _acknowledgement(self, record):
        raw = self._read(record['action'], 'ack')
        if raw is None:
            return None
        try:
            value = strict_json_object(raw)
        except InvalidInput as error:
            raise TaskExecutionError('ORIGINAL_NATIVE_ACTION_ACK_DIFFERS') from error
        result = value.get('result')
        if type(result) is not dict or not native_json_equal(value, {**record, 'result': result}):
            raise TaskExecutionError('ORIGINAL_NATIVE_ACTION_ACK_DIFFERS')
        action = record['action']
        if action == 'session':
            if set(result) != {'native_session_id'}:
                raise TaskExecutionError('ORIGINAL_NATIVE_SESSION_ACK_REQUIRED')
            _identifier(result['native_session_id'], 'ses')
        elif action == 'initial':
            expected = {
                'native_message_id': record['input']['payload']['messageID'],
                'accepted': True,
            }
            if not native_json_equal(result, expected):
                raise TaskExecutionError('ORIGINAL_NATIVE_MESSAGE_ACK_DIFFERS')
        elif action == 'permission':
            payload = _permission_input(record['input']['before'], record['input']['rules'])
            expected = {
                'native_session_id': payload['before']['id'],
                'permission': payload['before']['permission'] + payload['rules'],
            }
            if not native_json_equal(result, expected):
                raise TaskExecutionError('ORIGINAL_PERMISSION_ACK_DIFFERS')
        else:
            raise TaskExecutionError('ORIGINAL_NATIVE_ACTION_ACK_DIFFERS')
        return result

    def _created_session_record(self):
        record = self._original('session')
        native_session_input(record['input'])
        self._metadata(record['input'])
        return record

    def _require_session_ack(self, native):
        if self._read('session', 'ack') is None:
            raise TaskExecutionError('ORIGINAL_NATIVE_SESSION_ACK_REQUIRED')
        session = self._acknowledgement(self._created_session_record())
        if session != {'native_session_id': native}:
            raise TaskExecutionError('ORIGINAL_NATIVE_SESSION_ACK_REQUIRED')

    def _initial_input(self, record):
        value = record['input']
        if set(value) != {'session_id', 'payload'}:
            raise TaskExecutionError('ORIGINAL_NATIVE_MESSAGE_INTENT_DIFFERS')
        _identifier(value['session_id'], 'ses')
        native_message_input(value['payload'])
        self._require_session_ack(value['session_id'])
        return value

    def _metadata(self, payload):
        fields = (
            'task_id',
            'execution_session_id',
            'instance_id',
            'operation_id',
            'control_generation',
        )
        metadata = payload.get('metadata')
        original = metadata.get('walle') if type(metadata) is dict else None
        if (
            type(original) is not dict
            or set(metadata) != {'walle'}
            or set(original) != {*fields, 'nonce'}
            or any(
                type(original[key]) is not int or not 1 <= original[key] <= MAX_SAFE_INTEGER
                for key in fields
            )
            or original['operation_id'] != self._scope.operation_id
            or original['nonce'] != self._scope.nonce
        ):
            raise TaskExecutionError('ORIGINAL_NATIVE_SESSION_ASSOCIATION_REQUIRED')
        return metadata

    def prepare_session(self, payload):
        if self._permission_history:
            raise TaskExecutionError('ORIGINAL_NATIVE_SESSION_ALREADY_HAS_PERMISSION_HISTORY')
        payload = native_session_input(payload)
        self._metadata(payload)
        self._check_ack_capacity('session', payload, {'native_session_id': 'ses_' + 'X' * 96})
        return payload

    def create_session(self, payload, checkpoint, *, timeout_ms):
        payload = self.prepare_session(payload)
        record = self._begin('session', payload, checkpoint)
        result = self._control.create_session(payload, checkpoint, timeout_ms=timeout_ms)
        self._ack(record, {'native_session_id': result['id']})
        return result

    def observe_session(self, checkpoint, *, timeout_ms):
        record = self._created_session_record()
        metadata = self._metadata(record['input'])
        acknowledged = self._acknowledgement(record)
        expected = (
            self.expected_session_policy(checkpoint)
            if self._permission_history
            else record['input']
        )
        if acknowledged is None:
            result = self._control.find_session(metadata, checkpoint, timeout_ms=timeout_ms)
        else:
            result = self._control.session(
                acknowledged['native_session_id'], checkpoint, timeout_ms=timeout_ms
            )
            if not native_json_equal(result.get('metadata'), metadata):
                raise TaskExecutionError('ORIGINAL_NATIVE_SESSION_ASSOCIATION_REQUIRED')
        if any(
            not native_json_equal(result.get(key), expected[key])
            for key in ('title', 'agent', 'model', 'permission')
        ):
            raise TaskExecutionError('ORIGINAL_NATIVE_SESSION_POLICY_DIFFERS')
        self._ack(record, {'native_session_id': result['id']})
        return result

    def initial_payload(self, agent, provider, model, texts):
        payload = {
            'messageID': self._ids.allocate('msg'),
            'model': {'providerID': provider, 'modelID': model},
            'agent': agent,
            'parts': [
                {'id': self._ids.allocate('prt'), 'type': 'text', 'text': text} for text in texts
            ],
        }
        return native_message_input(payload)

    def plan_initial_payload(self, agent, provider, model, texts):
        raw = self._read('initial', 'planned')
        if raw is None:
            payload = self.initial_payload(agent, provider, model, texts)
            self._write('initial', 'planned', {'scope': self._scope.key, 'payload': payload})
            return payload
        try:
            planned = strict_json_object(raw)
        except InvalidInput as error:
            raise TaskExecutionError('ORIGINAL_ROLE_MESSAGE_PLAN_DIFFERS') from error
        if set(planned) != {'scope', 'payload'} or planned['scope'] != self._scope.key:
            raise TaskExecutionError('ORIGINAL_ROLE_MESSAGE_PLAN_DIFFERS')
        payload = native_message_input(planned['payload'])
        if (
            payload['agent'] != agent
            or payload['model'] != {'providerID': provider, 'modelID': model}
            or [part['text'] for part in payload['parts']] != list(texts)
        ):
            raise TaskExecutionError('ORIGINAL_ROLE_MESSAGE_PLAN_DIFFERS')
        return payload

    def prepare_initial(self, native, payload):
        payload = native_message_input(payload)
        _identifier(native, 'ses')
        self._check_ack_capacity(
            'initial',
            {'session_id': native, 'payload': payload},
            {'native_message_id': payload['messageID'], 'accepted': True},
        )
        self._require_session_ack(native)
        return payload

    def send_initial(self, native, payload, checkpoint, *, timeout_ms):
        payload = self.prepare_initial(native, payload)
        session = self.observe_session(checkpoint, timeout_ms=min(3000, timeout_ms))
        if session['id'] != native:
            raise TaskExecutionError('ORIGINAL_NATIVE_SESSION_ACK_REQUIRED')
        record = self._begin('initial', {'session_id': native, 'payload': payload}, checkpoint)
        self._control.send_message(native, payload, checkpoint, timeout_ms=timeout_ms)
        self._ack(record, {'native_message_id': payload['messageID'], 'accepted': True})
        return payload['messageID']

    def observe_initial(self, checkpoint, *, timeout_ms):
        record = self._original('initial')
        value = self._initial_input(record)
        self._acknowledgement(record)
        native, payload = value['session_id'], value['payload']
        result = self._control.verify_message(native, payload, checkpoint, timeout_ms=timeout_ms)
        self._ack(record, {'native_message_id': payload['messageID'], 'accepted': True})
        return result

    def _permission_session_scope(self, value):
        if value is None:
            return self._launch_scope
        try:
            if type(value) is not dict or set(value) != {
                'controller_ref',
                'operation_id',
                'step_no',
                'nonce',
            }:
                raise ValueError('Invalid source')
            scope = LaunchScope(**value)
        except (TypeError, ValueError, RuntimeError) as error:
            raise TaskExecutionError('ORIGINAL_PERMISSION_SESSION_SOURCE_REQUIRED') from error
        if (
            scope.controller_ref != self._launch_scope.controller_ref
            or self._scope.step_no == 3
            and scope.operation_id == self._scope.operation_id
            or scope != self._launch_scope
            and scope.step_no not in (1, 4)
        ):
            raise TaskExecutionError('ORIGINAL_PERMISSION_SESSION_SOURCE_DIFFERS')
        return scope

    def _permission_payload(self, value):
        if (
            type(value) is not dict
            or not {'before', 'rules'} <= set(value)
            or (set(value) - {'before', 'rules', 'session_scope', 'previous_applications'})
        ):
            raise TaskExecutionError('ORIGINAL_PERMISSION_INTENT_INVALID')
        payload = _permission_input(value['before'], value['rules'])
        for key in ('session_scope', 'previous_applications'):
            if key in value:
                if value[key] is None:
                    raise TaskExecutionError('ORIGINAL_PERMISSION_SESSION_SOURCE_REQUIRED')
                payload[key] = value[key]
        return payload

    def _permission_predecessors(self, values):
        if type(values) is not list:
            raise TaskExecutionError('ORIGINAL_PERMISSION_PREDECESSORS_REQUIRED')
        scopes = []
        operations = {self._scope.operation_id, self._launch_scope.operation_id}
        for value in values:
            try:
                if type(value) is not dict or set(value) != {
                    'controller_ref',
                    'operation_id',
                    'step_no',
                    'nonce',
                }:
                    raise ValueError('Invalid predecessor')
                scope = LaunchScope(**value)
            except (TypeError, ValueError, RuntimeError) as error:
                raise TaskExecutionError('ORIGINAL_PERMISSION_PREDECESSORS_REQUIRED') from error
            if (
                scope.controller_ref != self._launch_scope.controller_ref
                or scope.step_no != 3
                or scope.operation_id in operations
            ):
                raise TaskExecutionError('ORIGINAL_PERMISSION_PREDECESSORS_DIFFER')
            operations.add(scope.operation_id)
            scopes.append(scope)
        return scopes

    def _permission_expected(self, payload, checkpoint):
        """Rebuild one exact native predecessor chain; business adoption stays with the caller."""
        checkpoint()
        launch = TaskNativeActions(self._package, self._launch_scope, self._control)
        source = self._permission_session_scope(payload.get('session_scope'))
        original = (
            launch
            if source == self._launch_scope
            else TaskNativeActions(
                self._package, self._launch_scope, self._control, action_scope=source
            )
        )
        created = original._created_session_record()
        root = launch._created_session_record()
        if launch._acknowledgement(root) is None:
            raise TaskExecutionError('ORIGINAL_NATIVE_SESSION_ACK_REQUIRED')
        association = created['input']['metadata']['walle']
        root_association = root['input']['metadata']['walle']
        if any(association[key] != root_association[key] for key in ('task_id', 'instance_id')):
            raise TaskExecutionError('ORIGINAL_PERMISSION_SESSION_SOURCE_DIFFERS')
        acknowledgement = original._acknowledgement(created)
        if acknowledgement is None:
            raise TaskExecutionError('ORIGINAL_NATIVE_SESSION_ACK_REQUIRED')
        expected = {'id': acknowledgement['native_session_id'], **created['input']}
        prefix = []
        scopes = self._permission_predecessors(payload.get('previous_applications', []))
        if source.operation_id in {scope.operation_id for scope in scopes}:
            raise TaskExecutionError('ORIGINAL_PERMISSION_PREDECESSORS_DIFFER')
        for scope in scopes:
            checkpoint()
            prior = TaskNativeActions(
                self._package, self._launch_scope, self._control, action_scope=scope
            )
            record = prior._original('permission')
            previous = self._permission_payload(record['input'])
            if (
                self._permission_session_scope(previous.get('session_scope')) != source
                or not native_json_equal(previous.get('previous_applications', []), prefix)
                or not native_json_equal(previous['before'], expected)
            ):
                raise TaskExecutionError('ORIGINAL_PERMISSION_PREDECESSORS_DIFFER')
            if prior._acknowledgement(record) is None:
                raise TaskExecutionError('ORIGINAL_PERMISSION_PREDECESSOR_ACK_REQUIRED')
            expected = {**expected, 'permission': expected['permission'] + previous['rules']}
            prefix.append(asdict(scope))
            checkpoint()
        checkpoint()
        return expected

    def _permission_origin(self, payload, checkpoint):
        expected = self._permission_expected(payload, checkpoint)
        if not native_json_equal(payload['before'], expected):
            raise TaskExecutionError('ORIGINAL_PERMISSION_SESSION_POLICY_DIFFERS')

    def expected_session_policy(self, checkpoint):
        if self._scope.step_no == 3:
            raise TaskExecutionError('ORIGINAL_NATIVE_SESSION_CREATION_SCOPE_REQUIRED')
        return self._permission_expected(
            {
                'session_scope': asdict(self._scope),
                'previous_applications': [asdict(scope) for scope in self._permission_history],
            },
            checkpoint,
        )

    def apply_permission(
        self,
        expected,
        rules,
        checkpoint,
        *,
        timeout_ms,
        session_scope=None,
        previous_applications=(),
    ):
        """One original C39 APPLY_PAIR intent; policy authorization stays with its caller."""
        if self._scope.step_no != 3:
            raise TaskExecutionError('ORIGINAL_PERMISSION_APPLICATION_SCOPE_REQUIRED')
        payload = _permission_input(expected, rules)
        if session_scope is not None:
            if type(session_scope) is not LaunchScope:
                raise TaskExecutionError('ORIGINAL_PERMISSION_SESSION_SOURCE_REQUIRED')
            payload['session_scope'] = asdict(session_scope)
        if type(previous_applications) is not tuple or any(
            type(scope) is not LaunchScope for scope in previous_applications
        ):
            raise TaskExecutionError('ORIGINAL_PERMISSION_PREDECESSORS_REQUIRED')
        if previous_applications:
            payload['previous_applications'] = [asdict(scope) for scope in previous_applications]
        self._permission_origin(payload, checkpoint)
        fields = ('id', 'title', 'agent', 'model', 'metadata', 'permission')
        # Reserve enough room for the final positive receipt before any mutation.
        _record_bytes(
            {
                'scope': self._scope.key,
                'action': 'permission',
                'input': payload,
                'result': {
                    'native_session_id': payload['before']['id'],
                    'permission': payload['before']['permission'] + payload['rules'],
                },
            }
        )
        before = payload['before']
        checkpoint()
        if self._read('permission', 'intent') is not None:
            raise TaskExecutionError('ORIGINAL_NATIVE_ACTION_REQUIRES_OBSERVATION')
        observed = self._control.session(before['id'], checkpoint, timeout_ms=timeout_ms)
        if any(not native_json_equal(observed.get(key), before[key]) for key in fields):
            raise TaskExecutionError('ORIGINAL_PERMISSION_SESSION_POLICY_DIFFERS')
        record = self._begin('permission', payload, checkpoint)
        self._control.update_session_permission(
            before['id'], payload['rules'], checkpoint, timeout_ms=timeout_ms
        )
        return self._observe_permission(record, checkpoint, timeout_ms=timeout_ms)

    def _observe_permission(self, record, checkpoint, *, timeout_ms):
        payload = self._permission_payload(record['input'])
        before, rules = payload['before'], payload['rules']
        self._permission_origin(payload, checkpoint)
        self._acknowledgement(record)
        result = self._control.session(before['id'], checkpoint, timeout_ms=timeout_ms)
        fields = ('id', 'title', 'agent', 'model', 'metadata')
        if any(
            not native_json_equal(result.get(key), before[key]) for key in fields
        ) or not native_json_equal(result.get('permission'), before['permission'] + rules):
            raise TaskExecutionError('ORIGINAL_PERMISSION_EFFECTIVE_POLICY_UNKNOWN')
        checkpoint()
        self._ack(record, {'native_session_id': before['id'], 'permission': result['permission']})
        return result

    def observe_permission(self, checkpoint, *, timeout_ms):
        if self._scope.step_no != 3:
            raise TaskExecutionError('ORIGINAL_PERMISSION_APPLICATION_SCOPE_REQUIRED')
        return self._observe_permission(
            self._original('permission'), checkpoint, timeout_ms=timeout_ms
        )
