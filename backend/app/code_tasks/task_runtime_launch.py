"""Backend side of one original TASK I/O and launch exchange."""

from contextlib import contextmanager

from backend.app.infrastructure.guard_action_records import mutation_input_sha256
from backend.app.infrastructure.guard_control_git_transport import (
    _endpoint,
    exchange_guard_task_files,
)
from backend.app.infrastructure.guard_request_header import (
    GuardRequestHeader,
    build_guard_request_header,
)
from backend.app.infrastructure.guard_task_basis_protocol import _hex
from backend.app.infrastructure.guard_task_execution_protocol import EXECUTION_PREPARATION_STATUS
from backend.app.infrastructure.guard_task_files import _publish_original, _read_original
from backend.app.infrastructure.guard_task_launch_protocol import (
    CONFIRM_LAUNCH,
    STDIO_FIELDS,
    check_task_prepare_ack,
    task_launch_fence,
)
from backend.app.infrastructure.guard_task_model_source import (
    MODEL_SOURCE_STATUS,
    VERIFY_MODEL_SOURCE,
    AcceptedModelConnection,
)
from backend.app.infrastructure.opencode_control import OpenCodeControlCredential
from backend.app.infrastructure.opencode_instance_control import OpenCodeInstanceControl
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.infrastructure.windows_guard_pipe import GuardPipeClient
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.infrastructure.windows_process import NativeProcessIdentity, ObservedProcess
from backend.app.infrastructure.windows_stdio import BackendStandardIO
from backend.app.shared.validation import strict_json_object

_LIMIT = 16384


class _BackendLaunchEvidence:
    def __init__(self, package, original, reference):
        if type(package) is not PrivatePackageGuard or package.is_control_git_read_package:
            raise TaskExecutionError('ORIGINAL_BACKEND_TASK_RECEIPT_PACKAGE_REQUIRED')
        self._package = package
        self._directory = package.verify()
        expected = original.input.get('sources', {}).get('parent', {})
        if self._directory.file_id != expected.get(
            'file_id'
        ) or self._directory.volume_serial != expected.get('volume_serial'):
            raise TaskExecutionError('ORIGINAL_BACKEND_TASK_RECEIPT_PACKAGE_DIFFERS')
        self._original, self._reference = original, reference

    def _name(self, action, phase):
        return (
            self._original.scope.key
            + '.task-backend-'
            + action.lower().replace('_', '-')
            + '-'
            + phase
            + '.json'
        )

    def _read(self, action, phase):
        if self._package.verify() != self._directory:
            raise TaskExecutionError('ORIGINAL_BACKEND_TASK_RECEIPT_PACKAGE_DIFFERS')
        return _read_original(self._package, self._name(action, phase), _LIMIT)

    def _identity(self, action):
        return {
            'schema_version': 1,
            'scope': self._original.scope.key,
            'owner_epoch': self._original.owner_epoch,
            'prepare_input_sha256': mutation_input_sha256(self._original),
            'binding_ref': self._reference,
            'action': action,
        }

    def _append(self, action, phase, value):
        raw = _bytes(value)
        prior = self._read(action, phase)
        if prior is None:
            _publish_original(self._package, self._name(action, phase), raw, _LIMIT)
        if self._read(action, phase) != raw:
            raise TaskExecutionError('ORIGINAL_BACKEND_TASK_RECEIPT_DIFFERS')

    def intent(self, action, digest, *, repeat=False):
        if self._read(action, 'intent') is not None and not repeat:
            raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_REQUIRES_OBSERVATION')
        self._append(action, 'intent', {**self._identity(action), 'input_sha256': digest})

    def _known_intent(self, action):
        raw = self._read(action, 'intent')
        if raw is None:
            return None
        value = strict_json_object(raw)
        digest = value.get('input_sha256')
        if not _hex(digest, 64) or value != {**self._identity(action), 'input_sha256': digest}:
            raise TaskExecutionError('ORIGINAL_BACKEND_TASK_RECEIPT_DIFFERS')
        return value

    def acknowledge(self, action, result):
        intent = self._known_intent(action)
        if intent is None:
            raise TaskExecutionError('ORIGINAL_BACKEND_TASK_INTENT_REQUIRED')
        self._append(action, 'ack', {**intent, 'result': result})

    def read_ack(self, action):
        intent = self._known_intent(action)
        raw = self._read(action, 'ack')
        if raw is None:
            return None
        value = strict_json_object(raw)
        if intent is None or value != {**intent, 'result': value.get('result')}:
            raise TaskExecutionError('ORIGINAL_BACKEND_TASK_RECEIPT_DIFFERS')
        return value['result']


class RuntimeTaskLaunch:
    def __init__(self, frames, controller, process_lock, original, binding_ref, streams, package):
        if (
            type(original) is not GuardRequestHeader
            or original.scope.step_no != 4
            or original.action != 'PREPARE'
            or original.input.get('run_kind') != 'TASK'
            or original.input.get('reserve_files') is not True
            or type(streams) is not BackendStandardIO
            or streams._scope != original.scope
            or streams.owner != controller.controller
        ):
            raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_OWNER_REQUIRED')
        self._frames, self._controller, self._lock = frames, controller, process_lock
        self._original, self._reference, self._streams = original, binding_ref, streams
        self._evidence = _BackendLaunchEvidence(package, original, binding_ref)
        self._input = self._receipt = None
        self._attempted = {}
        self._confirmed = False

    def reconnect(self, frames):
        if not self._frames._failed:
            raise TaskExecutionError('ORIGINAL_TASK_PIPE_STILL_ACTIVE')
        self._controller.assert_backend(self._lock)
        _endpoint(frames, GuardPipeClient, self._controller.installation_ref).verify()
        self._frames = frames

    def _request(self, action, payload, *, binding=None):
        scope = self._original.scope
        request = build_guard_request_header(
            self._controller,
            self._lock,
            action=action,
            operation_id=scope.operation_id,
            step_no=scope.step_no,
            nonce=scope.nonce,
            binding_ref=binding,
            action_input=payload,
        )
        if request.scope != scope or request.owner_epoch != self._original.owner_epoch:
            raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_SCOPE_DIFFERS')
        return request

    def _exchange(self, request, *, timeout_ms, cancelled, frames=None):
        return exchange_guard_task_files(
            self._frames if frames is None else frames,
            self._controller,
            self._lock,
            request,
            timeout_ms=timeout_ms,
            cancelled=cancelled,
        )

    def _confirm_copy(self, result):
        scope = self._original.scope
        binding = check_task_prepare_ack(scope, self._reference, result)
        if self._input != result['launch_input_sha256']:
            raise TaskExecutionError('ORIGINAL_TASK_CONFIRMATION_ACK_DIFFERS')
        self._evidence.acknowledge('PREPARE', result)
        self._streams.acknowledge_copy(binding)
        if not self._confirmed:
            self._streams.release_child_copies()
            self._streams.close_input()
            self._confirmed = True
        return result

    def confirm(self, verified, *, timeout_ms, cancelled):
        if self._input is not None:
            raise TaskExecutionError('ORIGINAL_TASK_CONFIRMATION_REQUIRES_OBSERVATION')
        if (
            type(verified) is not dict
            or verified.get('binding_ref') != self._reference
            or verified.get('policy_state') != 'NO_EXTERNAL_BYPASS_SEEN'
        ):
            raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_EVIDENCE_REQUIRED')
        descriptor = self._streams.descriptor()
        digest = verified['launch_input_sha256']
        request = self._request(
            'PREPARE',
            {
                'run_kind': 'TASK',
                'execution_stage': CONFIRM_LAUNCH,
                'execution_binding_ref': self._reference,
                'prepare_input_sha256': mutation_input_sha256(self._original),
                'launch_input_sha256': digest,
                'stdio': {key: getattr(descriptor, key) for key in STDIO_FIELDS},
            },
        )
        self._evidence.intent('PREPARE', mutation_input_sha256(request))
        self._streams.begin_handoff()
        self._input = digest
        reply = self._exchange(request, timeout_ms=timeout_ms, cancelled=cancelled)
        if reply.status != EXECUTION_PREPARATION_STATUS:
            raise TaskExecutionError('ORIGINAL_TASK_CONFIRMATION_REQUIRES_OBSERVATION')
        return self._confirm_copy(reply.result)

    def _mutation(self, action, payload, *, timeout_ms, cancelled):
        if action in self._attempted and action not in ('STOP', 'RELEASE'):
            raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_REQUIRES_OBSERVATION')
        request = self._request(action, payload, binding=self._reference)
        digest = mutation_input_sha256(request)
        self._evidence.intent(action, digest, repeat=action in ('STOP', 'RELEASE'))
        self._attempted[action] = digest
        reply = self._exchange(request, timeout_ms=timeout_ms, cancelled=cancelled)
        if reply.status != 'ACKNOWLEDGED':
            raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_REQUIRES_OBSERVATION')
        self._evidence.acknowledge(action, reply.result)
        return reply.result

    def create(self, *, timeout_ms, cancelled):
        if not self._confirmed or self._evidence._known_intent('STOP') is not None:
            raise TaskExecutionError('ORIGINAL_TASK_CONFIRMATION_REQUIRED')
        receipt = self._mutation(
            'CREATE_SUSPENDED',
            {'launch_input_sha256': self._input},
            timeout_ms=timeout_ms,
            cancelled=cancelled,
        )
        native = receipt['native']
        self._receipt = native['receipt_sha256']
        return native

    def resume(self, durable_receipt_sha256, *, timeout_ms, cancelled):
        original = self._evidence.read_ack('CREATE_SUSPENDED')
        if (
            self._receipt is None
            or durable_receipt_sha256 != self._receipt
            or original is None
            or original['native']['receipt_sha256'] != durable_receipt_sha256
            or self._evidence._known_intent('STOP') is not None
        ):
            raise TaskExecutionError('ORIGINAL_TASK_DURABLE_RECEIPT_REQUIRED')
        return self._mutation(
            'RESUME',
            {'receipt_sha256': durable_receipt_sha256},
            timeout_ms=timeout_ms,
            cancelled=cancelled,
        )['native']

    def running_receipt(self):
        created = self._evidence.read_ack('CREATE_SUSPENDED')
        resumed = self._evidence.read_ack('RESUME')
        if self._evidence._known_intent('STOP') is not None or created is None or resumed is None:
            raise TaskExecutionError('ORIGINAL_TASK_RUNNING_RECEIPT_REQUIRED')
        original, current = created['native'], resumed['native']
        identity_fields = ('resource_ref', 'job_ref', 'receipt_sha256', 'process_identity')
        if (
            original['process_state'] != 'SUSPENDED'
            or current['process_state'] != 'RUNNING'
            or any(
                current.get(key) is None or current[key] != original.get(key)
                for key in identity_fields
            )
            or current['job_ref'] != self._reference
        ):
            raise TaskExecutionError('ORIGINAL_TASK_RUNNING_RECEIPT_DIFFERS')
        return current

    @contextmanager
    def running_control(self, credential, workspace):
        current = self.running_receipt()
        if (
            type(credential) is not OpenCodeControlCredential
            or credential._scope != self._original.scope
        ):
            raise TaskExecutionError('ORIGINAL_TASK_CONTROL_CREDENTIAL_REQUIRED')
        identity = NativeProcessIdentity(**current['process_identity'])
        with ObservedProcess(identity.pid) as process:
            if process.identity != identity:
                raise TaskExecutionError('ORIGINAL_OPENCODE_PROCESS_DIFFERS')
            yield OpenCodeInstanceControl(credential, process, identity, workspace)

    def verify_model_source(self, accepted, *, timeout_ms, cancelled, frames=None):
        current = self.running_receipt()
        connection = AcceptedModelConnection.from_accept(accepted)
        request = self._request(VERIFY_MODEL_SOURCE, connection.wire(), binding=self._reference)
        reply = self._exchange(request, timeout_ms=timeout_ms, cancelled=cancelled, frames=frames)
        if (
            reply.status != MODEL_SOURCE_STATUS
            or reply.result['resource_ref'] != current['resource_ref']
            or connection != AcceptedModelConnection.from_accept(accepted)
            or self.running_receipt() != current
        ):
            raise TaskExecutionError('ORIGINAL_TASK_MODEL_SOURCE_UNVERIFIED')
        return reply.result

    def stop(self, *, timeout_ms, cancelled):
        native = self._mutation('STOP', {}, timeout_ms=timeout_ms, cancelled=cancelled)['native']
        self._streams.acknowledge_closed_scope(
            task_launch_fence(native['fence'], self._original.scope)
        )
        return native

    def release(self, *, timeout_ms, cancelled):
        if self._evidence.read_ack('STOP') is None:
            raise TaskExecutionError('ORIGINAL_TASK_RELEASE_STOP_REQUIRED')
        return self._mutation('RELEASE', {}, timeout_ms=timeout_ms, cancelled=cancelled)

    def observe(self, action, *, timeout_ms, cancelled):
        request = self._request('OBSERVE', {'observed_action': action}, binding=self._reference)
        reply = self._exchange(request, timeout_ms=timeout_ms, cancelled=cancelled)
        if reply.status != 'OBSERVED':
            raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_OBSERVATION_UNKNOWN')
        result = reply.result
        expected = (
            mutation_input_sha256(self._original)
            if action == 'PREPARE'
            else self._attempted.get(action)
        )
        if expected is not None and result['input_sha256'] not in (None, expected):
            raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_OBSERVATION_DIFFERS')
        acknowledgement = result['acknowledgement']
        if acknowledgement is not None:
            if action == 'PREPARE' and acknowledgement.get('run_kind') == 'TASK':
                self._confirm_copy(acknowledgement)
            elif action in self._attempted:
                self._evidence.acknowledge(action, acknowledgement)
                if action == 'CREATE_SUSPENDED':
                    self._receipt = acknowledgement['native']['receipt_sha256']
        fence = result['fence']
        if fence is not None and fence['stop_closed'] is True:
            self._streams.acknowledge_closed_scope(task_launch_fence(fence, self._original.scope))
        return result
