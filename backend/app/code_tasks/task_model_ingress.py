"""Fail-closed model preflight for a single accepted OpenCode connection."""

import re
from dataclasses import dataclass
from threading import Event

from backend.app.infrastructure.guard_task_model_source import AcceptedModelConnection
from backend.app.infrastructure.opencode_model_credential import OpenCodeModelCredential
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.shared.validation import strict_integer, strict_json_object

from .repository_operations import _time
from .task_role_chain import RoleChainUnavailable, current_role_chain
from .task_runtime_launch import RuntimeTaskLaunch

_NATIVE_ID = re.compile(r'(ses|msg)_[0-9A-Za-z]{1,96}')


def _native_id(value, kind):
    if (
        type(value) is not str
        or not value.startswith(kind + '_')
        or not _NATIVE_ID.fullmatch(value)
    ):
        raise TaskExecutionError('ORIGINAL_MODEL_NATIVE_ASSOCIATION_REQUIRED')
    return value


@dataclass(frozen=True)
class ModelWindow:
    task_id: int
    instance_id: int
    generation: int
    execution_session_id: int
    native_session_id: str
    operation_id: int
    trigger_message_id: str

    def __post_init__(self):
        for key in ('task_id', 'instance_id', 'generation', 'execution_session_id', 'operation_id'):
            strict_integer(getattr(self, key), key)
        _native_id(self.native_session_id, 'ses')
        _native_id(self.trigger_message_id, 'msg')


@dataclass(frozen=True)
class ModelIngressProof:
    window: ModelWindow
    source_evidence_ref: str
    connection_sha256: str


def _native_response_queued(connection, window):
    # This is still the confirmed original model window. A pending native
    # response only queues while every open wait belongs to its claimed dispatch.
    return (
        connection.execute(
            """SELECT 1 FROM code_operations o
               JOIN code_operation_steps observation ON observation.operation_id=o.id AND observation.step_no=1
               JOIN code_operation_steps send ON send.operation_id=o.id AND send.step_no=2
               WHERE o.task_id=? AND o.session_id=? AND o.control_generation=?
               AND o.status='RUNNING' AND send.status='RUNNING' AND send.external_identity IS NOT NULL
               AND EXISTS(SELECT 1 FROM code_waiting_items w WHERE w.task_id=o.task_id AND w.status='OPEN')
               AND NOT EXISTS(
                   SELECT 1 FROM code_waiting_items w WHERE w.task_id=o.task_id AND w.status='OPEN'
                   AND NOT coalesce((
                     (o.operation_type='ANSWER_QUESTION' AND w.kind='QUESTION' AND w.source_kind='QUESTION'
                       AND w.id=json_extract(o.fixed_input,'$.waiting_item_id') AND EXISTS(
                         SELECT 1 FROM code_questions q WHERE q.id=w.source_id AND q.task_id=o.task_id
                         AND q.id=json_extract(o.fixed_input,'$.question_id') AND q.session_id=o.session_id
                         AND q.control_generation=o.control_generation AND q.status='ANSWERING'))
                     OR
                     (o.operation_type='DECIDE_PERMISSION' AND w.kind='PERMISSION' AND w.source_kind='PERMISSION'
                       AND EXISTS(SELECT 1 FROM json_each(observation.result_ref,'$.items') item
                         JOIN code_permissions p ON p.id=w.source_id AND p.task_id=o.task_id
                         WHERE w.id=json_extract(item.value,'$.waiting_id')
                         AND p.id=json_extract(item.value,'$.permission_id')
                         AND p.session_id=o.session_id AND p.control_generation=o.control_generation
                         AND p.status='ANSWERING'))
                   ),0)
               )
               AND o.operation_type IN ('ANSWER_QUESTION','DECIDE_PERMISSION')
               LIMIT 1""",
            (window.task_id, window.execution_session_id, window.generation),
        ).fetchone()
        is not None
    )


def read_original_window_state(connection, expected, credential_ref):
    row = connection.execute(
        """SELECT s.model_window,s.status AS session_status,t.status AS task_status,t.active_session_id,
                  a.status AS grant_status,o.status AS operation_status,o.operation_type,
                  i.control_generation AS instance_generation,t.phase,t.control_generation,
                  o.id AS original_operation_id,o.control_generation AS operation_generation,
                  o.session_id AS operation_session_id
           FROM code_sessions s
           JOIN code_tasks t ON t.id=s.task_id
           JOIN code_instances i ON i.id=s.instance_id AND i.task_id=s.task_id
           JOIN code_authorizations a ON a.id=t.authorization_id AND a.task_id=t.id
           JOIN code_operations o ON o.id=? AND o.task_id=t.id
           WHERE s.id=? AND t.id=? AND i.id=? AND t.control_generation=?
           AND s.control_generation=t.control_generation
           AND i.control_generation<=t.control_generation
           AND ((o.operation_type<>'HANDOFF_ROLE' AND o.control_generation=t.control_generation)
                OR (o.operation_type='REPAIR' AND o.control_generation+1=t.control_generation
                    AND EXISTS(SELECT 1 FROM code_operation_steps restore WHERE restore.operation_id=o.id
                        AND restore.step_no=1 AND restore.step_type='RESTORE_SOURCE' AND restore.status='SUCCEEDED'
                        AND json_extract(restore.external_identity,'$.replacement.target_session_id')=s.id
                        AND json_extract(restore.result_ref,'$.native_session_id')=s.native_session_id))
                OR (o.operation_type='HANDOFF_ROLE' AND o.control_generation+1=t.control_generation
                    AND o.session_id<>s.id AND EXISTS(
                      SELECT 1 FROM code_operation_steps creation
                      WHERE creation.operation_id=o.id AND creation.step_no=4
                        AND creation.step_type='CREATE_SESSION' AND creation.status='SUCCEEDED'
                        AND json_extract(creation.result_ref,'$.session_id')=s.id
                        AND json_extract(creation.result_ref,'$.native_session_id')=s.native_session_id)))
           AND s.native_session_id=? AND (o.operation_type IN ('RESUME','REPAIR') OR s.native_message_id=?)
           AND s.gateway_credential_ref=?
           AND i.status='READY' AND t.stop_requested_at IS NULL
           AND a.profile_version_id=t.execution_profile_version_id
           AND o.resource_kind='TASK' AND o.resource_id=t.id
           AND o.operation_type IN ('START','RESUME','REPAIR','HANDOFF_ROLE')
           AND (o.operation_type NOT IN ('RESUME','REPAIR') OR o.session_id=s.id OR
                (o.operation_type='REPAIR' AND EXISTS(SELECT 1 FROM code_operation_steps restore
                    WHERE restore.operation_id=o.id AND restore.step_no=1 AND restore.status='SUCCEEDED'
                    AND json_extract(restore.external_identity,'$.replacement.target_session_id')=s.id)))
           AND (o.status IN ('RUNNING','SUCCEEDED') OR (o.operation_type IN ('RESUME','REPAIR') AND o.status='UNKNOWN'))
           AND (o.operation_type<>'REPAIR' OR EXISTS(
               SELECT 1 FROM code_operation_steps repair WHERE repair.operation_id=o.id
               AND repair.step_no=2 AND repair.step_type='SEND_REPAIR'
               AND repair.status IN ('RUNNING','UNKNOWN','SUCCEEDED')
               AND json_extract(repair.external_identity,'$.payload.messageID')
                   =json_extract(s.model_window,'$.native_trigger_message_id')))
           AND NOT EXISTS(
               SELECT 1 FROM code_operations stage
               WHERE stage.task_id=t.id AND stage.id<>o.id
               AND stage.resource_kind='TASK' AND stage.resource_id=t.id
               AND stage.control_generation=t.control_generation
               AND stage.operation_type IN ('CAPTURE_AND_CHECK','VERIFY_CANDIDATE',
                   'HANDOFF_ROLE','APPLY_CONFIGURATION','REPAIR')
               AND stage.status IN ('PENDING','RUNNING','UNKNOWN')
           )""",
        (
            expected.operation_id,
            expected.execution_session_id,
            expected.task_id,
            expected.instance_id,
            expected.generation,
            expected.native_session_id,
            expected.trigger_message_id,
            credential_ref,
        ),
    ).fetchone()
    if row is None or row['model_window'] is None:
        return None
    try:
        from .task_configuration_effective import effective_control_application

        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (expected.task_id,)
        ).fetchone()
        instance = connection.execute(
            'SELECT effective_profile_version_id FROM code_instances WHERE id=?',
            (expected.instance_id,),
        ).fetchone()
        effective_control_application(
            connection,
            task,
            instance_id=expected.instance_id,
            launch_profile_id=instance['effective_profile_version_id'],
        )
        if row['operation_type'] == 'REPAIR' and (
            row['operation_generation'] != expected.generation
            or row['operation_session_id'] != expected.execution_session_id
        ):
            from .task_session_replacement import replacement_for_session

            replacement = replacement_for_session(
                connection, expected.task_id, expected.execution_session_id
            )
            if replacement is None or replacement.operation['id'] != expected.operation_id:
                return None
        window = strict_json_object(row['model_window'])
        if set(window) != {
            'operation_id',
            'native_trigger_message_id',
            'state',
            'opened_at',
            'closed_at',
        }:
            return None
        if (
            type(window['operation_id']) is not int
            or window['operation_id'] != expected.operation_id
            or window['native_trigger_message_id'] != expected.trigger_message_id
            or window['closed_at'] is not None
        ):
            return None
        if row['instance_generation'] != expected.generation and row['session_status'] == 'ACTIVE':
            try:
                chain = current_role_chain(
                    connection,
                    {
                        'id': expected.task_id,
                        'phase': row['phase'],
                        'active_session_id': row['active_session_id'],
                        'control_generation': row['control_generation'],
                    },
                )
            except RoleChainUnavailable:
                return None
            if chain.session_id != expected.execution_session_id:
                return None
            if not chain.operations:
                from .task_session_replacement import replacement_for_session

                if (
                    replacement_for_session(
                        connection, expected.task_id, expected.execution_session_id
                    )
                    is None
                ):
                    return None
        elif (
            row['instance_generation'] != expected.generation
            and row['operation_type'] != 'HANDOFF_ROLE'
        ):
            return None
        if window['state'] in ('OPEN', 'HELD'):
            if (
                row['operation_type'] in ('RESUME', 'HANDOFF_ROLE')
                and row['operation_status'] != 'SUCCEEDED'
            ):
                return None
            _time(window['opened_at'], nullable=False)
            if (
                window['opened_at'].endswith('Z')
                and row['active_session_id'] == expected.execution_session_id
                and row['session_status'] == 'ACTIVE'
                and row['task_status'] == ('WAITING' if window['state'] == 'HELD' else 'RUNNING')
                and row['grant_status'] == 'EFFECTIVE'
            ):
                return window['state']
            if (
                window['state'] == 'OPEN'
                and window['opened_at'].endswith('Z')
                and row['task_status'] == 'WAITING'
                and row['session_status'] == 'ACTIVE'
                and row['active_session_id'] == expected.execution_session_id
                and row['grant_status'] == 'EFFECTIVE'
                and _native_response_queued(connection, expected)
            ):
                return 'QUEUED'
        if row['operation_type'] in ('RESUME', 'REPAIR'):
            if (
                window['state'] == 'QUEUED'
                and window['opened_at'] is None
                and row['active_session_id'] == expected.execution_session_id
                and row['session_status'] == 'ACTIVE'
                and row['task_status'] == 'WAITING'
                and row['grant_status'] == 'EFFECTIVE'
                and row['operation_status'] in ('RUNNING', 'UNKNOWN')
            ):
                return 'QUEUED'
            return None
        if row['operation_type'] == 'HANDOFF_ROLE':
            if (
                window['state'] == 'QUEUED'
                and window['opened_at'] is None
                and row['active_session_id'] is None
                and row['session_status'] == 'PREPARING'
                and row['task_status'] == 'VERIFYING'
                and row['grant_status'] == 'EFFECTIVE'
                and row['operation_status'] == 'RUNNING'
            ):
                return 'QUEUED'
            return None
        if (
            window['state'] == 'QUEUED'
            and window['opened_at'] is None
            and row['active_session_id'] is None
            and row['session_status'] == 'PREPARING'
            and row['task_status'] == 'PENDING'
            and row['grant_status'] in ('BOUND_PENDING_APPLY', 'EFFECTIVE')
            and row['operation_status'] == 'RUNNING'
        ):
            return 'QUEUED'
    except (TypeError, ValueError):
        return None
    return None


def read_original_open_window(connection, expected, credential_ref):
    if read_original_window_state(connection, expected, credential_ref) == 'OPEN':
        return expected
    return None


class TaskModelIngress:
    """Only issues a source proof. The original LLMUse must consume it before a send."""

    def __init__(self, launch, window, read_window, credential, *, verify_source=None):
        if (
            type(launch) is not RuntimeTaskLaunch
            or type(window) is not ModelWindow
            or not callable(read_window)
            or type(credential) is not OpenCodeModelCredential
            or (verify_source is not None and not callable(verify_source))
        ):
            raise TaskExecutionError('ORIGINAL_MODEL_WINDOW_REQUIRED')
        self._window, self._read_window = window, read_window
        self._credential = credential
        self._source = launch.verify_model_source if verify_source is None else verify_source
        self._revoked = Event()

    @property
    def route(self):
        return self._credential.route

    @property
    def credential_ref(self):
        return self._credential.reference

    def revoke(self):
        self._revoked.set()

    def check_credential(self, authorization):
        if self._revoked.is_set():
            raise TaskExecutionError('ORIGINAL_MODEL_CREDENTIAL_UNVERIFIED')
        self._credential.verify(authorization)

    def _headers(self, headers):
        selected = {}
        fields = {
            'accept',
            'authorization',
            'content-type',
            'x-opencode-session-id',
            'x-opencode-parent-session-id',
            'x-parent-session-id',
        }
        for name, value in headers:
            if type(name) is not str or type(value) is not str:
                raise TaskExecutionError('ORIGINAL_MODEL_REQUEST_HEADERS_INVALID')
            key = name.lower()
            if key == 'origin' or key.startswith('sec-fetch-'):
                raise TaskExecutionError('ORIGINAL_MODEL_BROWSER_REQUEST_REJECTED')
            if key in fields:
                if key in selected:
                    raise TaskExecutionError('ORIGINAL_MODEL_REQUEST_HEADERS_INVALID')
                selected[key] = value
        if (
            selected.get('content-type') != 'application/json'
            or selected.get('accept') != 'text/event-stream'
            or 'x-opencode-parent-session-id' in selected
            or 'x-parent-session-id' in selected
            or selected.get('x-opencode-session-id') != self._window.native_session_id
        ):
            raise TaskExecutionError('ORIGINAL_MODEL_REQUEST_HEADERS_INVALID')
        return selected.get('authorization')

    def _check_window(self, checkpoint):
        checkpoint()
        actual = self._read_window(self._window, self.credential_ref)
        if type(actual) is not ModelWindow or actual != self._window:
            raise TaskExecutionError('ORIGINAL_MODEL_WINDOW_FENCED')

    def check_request(self, accepted, method, target, version, headers):
        connection = AcceptedModelConnection.from_accept(accepted)
        if (method, target, version) != ('POST', self.route, 'HTTP/1.1'):
            raise TaskExecutionError('ORIGINAL_MODEL_REQUEST_ROUTE_INVALID')
        authorization = self._headers(headers)
        self.check_credential(authorization)
        return connection, authorization

    def verify(
        self, accepted, method, target, version, headers, checkpoint, *, timeout_ms, cancelled
    ):
        connection, authorization = self.check_request(accepted, method, target, version, headers)
        self._check_window(checkpoint)
        verified = self._source(accepted, timeout_ms=timeout_ms, cancelled=cancelled)
        self._check_window(checkpoint)
        self.check_credential(authorization)
        if connection != AcceptedModelConnection.from_accept(accepted):
            raise TaskExecutionError('ORIGINAL_TASK_MODEL_CONNECTION_DIFFERS')
        return ModelIngressProof(
            self._window, verified['source_evidence_ref'], verified['connection_sha256']
        )
