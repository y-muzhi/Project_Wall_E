"""Compose the admitted original TASK preparation, launch, and readiness checks."""

import hashlib
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from time import monotonic, sleep

from backend.app.infrastructure.guard_control_git_transport import exchange_guard_task_files
from backend.app.infrastructure.guard_request_header import build_guard_request_header
from backend.app.infrastructure.guard_task_basis_protocol import _hex
from backend.app.infrastructure.guard_task_sources import TaskSourcePins
from backend.app.infrastructure.opencode_instance_control import (
    NativeTurnCompletion,
    native_json_equal,
    native_message_input,
)
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError, TaskExecutionPlan
from backend.app.infrastructure.runtime_launch_journal import (
    LaunchOutcomeUnknown,
    LaunchScope,
    _bytes,
)
from backend.app.infrastructure.windows_local_paths import (
    FileIdentity,
    LocalPathGuard,
    local_absolute_path,
)
from backend.app.infrastructure.windows_stdio import BackendStandardIO
from backend.app.infrastructure.windows_task_basis_group import BasisCopyPlan
from backend.app.shared.validation import strict_json_object

from .coding_model_gateway import _check_credentials
from .native_permission_objects import pin_permission_object
from .task_basis_package import runtime_basis_plan
from .task_initial_configuration import InitialConfigurationObservation, InitialNativeSession
from .task_initial_prompt import (
    MODEL,
    PROVIDER,
    NativeCodingPolicy,
    checked_coding_configuration,
    initial_texts,
    repair_texts,
)
from .task_model_ingress import ModelWindow
from .task_native_actions import TaskNativeActions
from .task_output_capture import TaskOutputCapture
from .task_records import safe_native_records
from .task_runtime_basis import RuntimeBasisTransfer
from .task_runtime_files import RuntimeFilesTransfer
from .task_runtime_launch import RuntimeTaskLaunch
from .task_runtime_recovery import RuntimeTaskRecovery, TaskRecoveryReceipt
from .task_runtime_workspace import RuntimeWorkspaceTransfer
from .task_start_instance import ReadyInstanceEvidence, StartInstanceClaim
from .task_start_session import SuccessorSessionScope
from .task_workspace_release import OriginalWorkspaceRelease


@dataclass(frozen=True)
class TaskLaunchInstallation:
    plan: TaskExecutionPlan
    configuration_sha256: str
    startup_timeout_ms: int
    coding: NativeCodingPolicy | None = None
    max_diagnostic_output_bytes: int = 256 * 1024

    def __post_init__(self):
        if (
            type(self.plan) is not TaskExecutionPlan
            or not _hex(self.configuration_sha256, 64)
            or type(self.startup_timeout_ms) is not int
            or not 1000 <= self.startup_timeout_ms <= 30000
            or (self.coding is not None and type(self.coding) is not NativeCodingPolicy)
            or type(self.max_diagnostic_output_bytes) is not int
            or not 1 <= self.max_diagnostic_output_bytes <= 4 * 1024 * 1024
        ):
            raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_INSTALLATION_REQUIRED')
        if self.plan != TaskExecutionPlan.parse(
            self.execution, self.network, self.plan.runtime_bundle_ref
        ):
            raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_INSTALLATION_DIFFERS')

    @property
    def execution(self):
        plan = self.plan
        return {
            'binary_ref': plan.binary_ref,
            'version': plan.executor['version'],
            'active_process_limit': plan.active_process_limit,
            'job_memory_limit_bytes': plan.job_memory_limit_bytes,
        }

    @property
    def network(self):
        return {
            role: [{'address': address, 'port': port} for address, port in endpoints]
            for role, endpoints in self.plan.endpoints
        }

    def matches(self, executor):
        return (
            type(executor) is dict
            and all(executor.get(key) == value for key, value in self.plan.executor.items())
            and executor.get('runtime_policy_version') == 'WIN20-ISOLATION-1'
            and executor.get('configuration_policy_version') == 'OC20-CONFIG-1'
        )


@dataclass(frozen=True)
class CaptureTurnEvidence:
    turn: NativeTurnCompletion
    guard_receipt_sha256: str
    active_process_count: int
    workspace: FileIdentity
    scratch: FileIdentity | None = None

    def scope_proof(self):
        return {
            'turn': self.turn.scope_proof(),
            'guard_receipt_sha256': self.guard_receipt_sha256,
            'active_process_count': self.active_process_count,
            'workspace': asdict(self.workspace),
        }


@dataclass(frozen=True)
class ControlConfigurationObservation:
    quiescence: CaptureTurnEvidence
    configuration: InitialConfigurationObservation
    permission_sha256: str


@dataclass(frozen=True)
class NativeConfigurationPreparation:
    observation: ControlConfigurationObservation
    policy_evidence_json: str
    target_permission_sha256: str
    session_scope: LaunchScope
    previous_applications: tuple[LaunchScope, ...]


@dataclass
class _Owner:
    launch: RuntimeTaskLaunch | None = None
    streams: BackendStandardIO | None = None
    credential: object = None
    workspace: FileIdentity | None = None
    scratch: FileIdentity | None = None
    basis: FileIdentity | None = None
    basis_plan: BasisCopyPlan | None = None
    claim: StartInstanceClaim | None = None
    gateway: object = None
    output: TaskOutputCapture | None = None
    fenced: bool = False
    configuration: InitialConfigurationObservation | None = None

    def close_local(self):
        if self.gateway is not None:
            self.gateway.revoke()
        if self.streams is not None:
            self.streams.close()
        if self.credential is not None:
            self.credential.close()


class TaskInstanceDriver:
    def __init__(
        self,
        installation,
        parent,
        controller,
        process_lock,
        connect,
        *,
        model_listener=None,
        database=None,
    ):
        if type(installation) is not TaskLaunchInstallation:
            raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_INSTALLATION_REQUIRED')
        self._installation, self._parent, self._connect = installation, parent, connect
        self._controller, self._lock = controller, process_lock
        self._model_listener, self._database = model_listener, database
        self._owners = {}
        self._workspace_releases = {}

    @property
    def has_owners(self):
        return bool(self._owners or self._workspace_releases)

    def start(self, original, checkpoint, *, cancelled):
        claim = original.claim
        if claim.operation_id in self._owners:
            raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_REQUIRES_OBSERVATION')
        deadline = monotonic() + self._installation.startup_timeout_ms / 1000

        def interrupted():
            return cancelled() or monotonic() >= deadline

        def active():
            if interrupted():
                raise TaskExecutionError('ORIGINAL_TASK_STARTUP_INTERRUPTED')
            checkpoint()

        def options():
            active()
            return {
                'timeout_ms': max(1, min(30000, int((deadline - monotonic()) * 1000))),
                'cancelled': interrupted,
            }

        owner = _Owner(claim=claim)
        self._owners[claim.operation_id] = owner
        with self._connect() as frames:
            return self._start(frames, owner, original, active, options)

    def _start(self, frames, owner, original, active, options):
        claim, parent = original.claim, self._parent
        installation = self._installation
        workspace = strict_json_object(original.workspace_receipt)
        source_plan = runtime_basis_plan(
            parent, original.basis_binding, original.basis_seal, active
        )
        with TaskSourcePins(
            original.allocation.parent,
            original.allocation.nonce,
            workspace=FileIdentity(**workspace['directory']),
            workspace_tree=FileIdentity(**workspace['tree_record']['file']),
            basis_seal=FileIdentity(**original.basis_seal['file']),
        ) as pins:
            source = pins.request_data(
                basis_plan_sha256=source_plan.sha256,
                reserve_files=True,
                workspace_manifest_sha256=workspace['content_sha256'],
                runtime_bundle_ref=installation.plan.runtime_bundle_ref,
                execution=installation.execution,
                network=installation.network,
            )
            reserved = self._reserve(frames, claim, 'PREPARE', source, options)
            request = reserved[0]
            if reserved[1].status != 'UNKNOWN':
                raise TaskExecutionError('ORIGINAL_TASK_RESERVATION_UNVERIFIED')
            _, observed = self._reserve(
                frames, claim, 'OBSERVE', {'observed_action': 'PREPARE'}, options
            )
            if (
                observed.status != 'OBSERVED'
                or observed.result['preparation'].get('directory_state') != 'HELD'
            ):
                raise TaskExecutionError('ORIGINAL_TASK_RESERVATION_UNVERIFIED')
            reference = observed.result['binding_ref']
            TaskRecoveryReceipt(parent, claim.operation_id, claim.nonce).remember_binding(reference)
            owner.streams = BackendStandardIO(request.scope)
            owner.launch = RuntimeTaskLaunch(
                frames, self._controller, self._lock, request, reference, owner.streams, parent
            )
            transfers = (frames, self._controller, self._lock, request, reference)
            basis = RuntimeBasisTransfer(*transfers).publish(
                parent, original.basis_binding, original.basis_seal, active, **options()
            )
            target = RuntimeWorkspaceTransfer(*transfers).publish(
                parent,
                original.allocation,
                original.workspace_receipt,
                active,
                original.limits,
                **options(),
            )
            transfer = RuntimeFilesTransfer(*transfers)
            files = transfer.prepare(basis, target, **options())
            transfer.prepare_execution(files, **options())
            profile = transfer.prepare_profile(files, **options())
            transfer.install_network(files, **options())
            owner.credential = transfer.issue_control_credential()
            transfer.bind_control_credential(files, owner.credential, **options())
            launch_input = transfer.verify_launch_input(files, **options())
            # Guard still owns the original directory pins, and the task has
            # not started. Retain its scratch identity for later repair writes.
            workspace_path = local_absolute_path(target.destination.directory.canonical_path)
            with (
                LocalPathGuard(workspace_path.with_name('scratch'), directory=True) as scratch,
                LocalPathGuard(workspace_path.with_name('basis'), directory=True) as fixed_basis,
            ):
                owner.scratch = scratch.verify()
                owner.basis = fixed_basis.verify()
            owner.launch.confirm(launch_input, **options())
            suspended = owner.launch.create(**options())
            owner.output = TaskOutputCapture(
                owner.streams,
                request.scope,
                parent,
                installation.max_diagnostic_output_bytes,
            )
            owner.launch.resume(suspended['receipt_sha256'], **options())
            running = owner.launch.running_receipt()

        with owner.launch.running_control(
            owner.credential, target.destination.directory
        ) as control:
            self._wait_ready(control, active, options)
            configuration = control.configuration(active, timeout_ms=options()['timeout_ms'])
        model_credential = None
        if installation.coding is not None:
            model_credential = owner.credential.model_credential(request.scope, installation.plan)
            configuration = checked_coding_configuration(
                configuration, model_credential, installation.coding
            )
        if hashlib.sha256(_bytes(configuration)).hexdigest() != installation.configuration_sha256:
            raise TaskExecutionError('ORIGINAL_TASK_EFFECTIVE_CONFIGURATION_DIFFERS')
        active()
        if installation.coding is not None:
            owner.configuration = InitialConfigurationObservation(
                runtime_bundle_ref=files['runtime_bundle_ref'],
                source_sha256=launch_input['file_evidence_sha256'],
                nonsecret_config_sha256=installation.configuration_sha256,
                agent_ref=installation.coding.agent,
            )
        if model_credential is not None and self._model_listener is not None:
            owner.gateway = self._model_listener.attach(
                owner.launch, model_credential, self._connect, self._database
            )
        owner.workspace, owner.basis_plan, owner.claim = (
            target.destination.directory,
            source_plan,
            claim,
        )
        return ReadyInstanceEvidence.from_running(
            running,
            launch_input=launch_input,
            profile=profile,
            credential_ref=owner.credential.reference,
            scope=request.scope,
        )

    def _reserve(self, frames, claim, action, source, options):
        request = build_guard_request_header(
            self._controller,
            self._lock,
            action=action,
            operation_id=claim.operation_id,
            step_no=4,
            nonce=claim.nonce,
            binding_ref=None,
            action_input=source,
        )
        if action == 'PREPARE':
            TaskRecoveryReceipt(self._parent, claim.operation_id, claim.nonce).remember(request)
        return request, exchange_guard_task_files(
            frames, self._controller, self._lock, request, **options()
        )

    def _wait_ready(self, control, checkpoint, options):
        while True:
            checkpoint()
            try:
                control.verify_ready(checkpoint, timeout_ms=options()['timeout_ms'])
            except TaskExecutionError as error:
                if str(error) != 'ORIGINAL_TASK_CONTROL_RESULT_UNVERIFIED':
                    raise
                sleep(0.025)
            else:
                return

    def session_available(self, operation_id):
        owner = self._owners.get(operation_id)
        return (
            self._installation.coding is not None
            and owner is not None
            and owner.workspace is not None
            and not owner.fenced
        )

    def _session_owner(self, scope):
        if not self.session_available(scope.operation_id):
            raise TaskExecutionError('ORIGINAL_TASK_NATIVE_CONTROL_UNAVAILABLE')
        owner = self._owners[scope.operation_id]
        claim = owner.claim
        if (
            claim.task_id != scope.task_id
            or claim.instance_id != scope.instance_id
            or claim.profile_id != scope.profile_id
            or claim.state_version != scope.state_version
            or claim.generation != scope.launch_generation
            or claim.nonce != scope.nonce
        ):
            raise TaskExecutionError('ORIGINAL_TASK_NATIVE_CONTROL_DIFFERS')
        return owner

    @contextmanager
    def _native_actions(self, owner, scope=None):
        launch = owner.launch._original.scope
        action = (
            LaunchScope(
                launch.controller_ref,
                scope.transition_operation_id,
                scope.transition_step_no,
                scope.transition_nonce,
            )
            if type(scope) is SuccessorSessionScope
            else None
        )
        history = ()
        if scope is not None and getattr(self, '_database', None) is not None:
            from .task_configuration_native import adopted_native_permission_scopes

            with self._database.transaction() as connection:
                history = adopted_native_permission_scopes(connection, scope, action or launch)
        with owner.launch.running_control(owner.credential, owner.workspace) as control:
            yield TaskNativeActions(
                self._parent, launch, control, action_scope=action, permission_history=history
            )

    def _observe_configuration(self, owner, control, checkpoint, *, timeout_ms):
        if (
            owner.configuration is None
            or owner.gateway is None
            or self._installation.coding is None
        ):
            raise TaskExecutionError('ORIGINAL_TASK_EFFECTIVE_CONFIGURATION_REQUIRED')
        actual = checked_coding_configuration(
            control.configuration(checkpoint, timeout_ms=timeout_ms),
            owner.gateway._credential,
            self._installation.coding,
        )
        if (
            hashlib.sha256(_bytes(actual)).hexdigest()
            != owner.configuration.nonsecret_config_sha256
        ):
            raise TaskExecutionError('ORIGINAL_CONTROL_NATIVE_CONFIGURATION_DIFFERS')

    def _observe_session_configuration(self, owner, actions, checkpoint, *, timeout_ms):
        """Compare live config/providers and bracket them with the original session policy."""
        session = actions.observe_session(checkpoint, timeout_ms=timeout_ms)
        self._observe_configuration(owner, actions._control, checkpoint, timeout_ms=timeout_ms)
        verified = actions.observe_session(checkpoint, timeout_ms=timeout_ms)
        fields = ('id', 'title', 'agent', 'model', 'metadata', 'permission')
        if any(not native_json_equal(session.get(key), verified.get(key)) for key in fields):
            raise TaskExecutionError('ORIGINAL_CONTROL_SESSION_POLICY_DIFFERS')
        return verified

    def _prepare_initial_delivery(self, owner, actions, scope, original, payload, checkpoint):
        payload = actions.prepare_initial(original['native_session_id'], payload)
        timeout = min(3000, scope.query_timeout_seconds * 1000)
        receipt = self._continuation_guard(owner, checkpoint, timeout)
        session = self._observe_session_configuration(
            owner, actions, checkpoint, timeout_ms=timeout
        )
        if session['id'] != original['native_session_id'] or not native_json_equal(
            session.get('metadata'), scope.metadata()
        ):
            raise TaskExecutionError('ORIGINAL_TASK_INITIAL_DELIVERY_DIFFERS')
        if self._continuation_guard(owner, checkpoint, timeout) != receipt:
            raise TaskExecutionError('ORIGINAL_TASK_INITIAL_GUARD_DIFFERS')
        checkpoint()
        return payload

    def _compile_session_policy(self, owner, scope, checkpoint):
        from backend.app.infrastructure.database import StorageUnavailable
        from backend.app.infrastructure.resources import ConfigInvalid
        from backend.app.shared.validation import InvalidInput

        from .task_native_policy import (
            NativePolicyCompilationError,
            compile_managed_native_policy,
            read_managed_session_policy_input,
        )

        if self._database is None or owner.basis is None or owner.workspace is None:
            raise TaskExecutionError('ORIGINAL_TASK_POLICY_SOURCE_REQUIRED')
        checkpoint()
        try:
            with self._database.transaction() as connection:
                profile, grant, provenance = read_managed_session_policy_input(connection, scope)
            compiled = compile_managed_native_policy(
                profile,
                grant,
                agent=self._installation.coding.agent,
                workspace=owner.workspace,
                basis=owner.basis,
                checkpoint=checkpoint,
            )
            checkpoint()
            with self._database.transaction() as connection:
                current = read_managed_session_policy_input(connection, scope)
            if current[2] != provenance:
                raise TaskExecutionError('ORIGINAL_TASK_POLICY_SOURCE_CHANGED')
        except (
            NativePolicyCompilationError,
            StorageUnavailable,
            ConfigInvalid,
            InvalidInput,
        ) as error:
            raise TaskExecutionError('ORIGINAL_TASK_POLICY_UNVERIFIED') from error
        checkpoint()
        return compiled.policy

    def create_session(self, scope, checkpoint):
        owner = self._session_owner(scope)
        coding = self._compile_session_policy(owner, scope, checkpoint)
        role = scope.role if type(scope) is SuccessorSessionScope else 'BACKEND'
        request = {
            'title': f'WALL-E Coding {scope.task_id} {role}',
            'agent': coding.agent,
            'model': {'id': MODEL, 'providerID': PROVIDER},
            'permission': coding.permission(),
            'metadata': scope.metadata(),
        }
        with self._native_actions(owner, scope) as actions:
            request = actions.prepare_session(request)
            timeout = min(3000, scope.query_timeout_seconds * 1000)
            receipt = self._continuation_guard(owner, checkpoint, timeout)
            self._observe_configuration(owner, actions._control, checkpoint, timeout_ms=timeout)
            if self._continuation_guard(owner, checkpoint, timeout) != receipt:
                raise TaskExecutionError('ORIGINAL_TASK_CREATE_GUARD_DIFFERS')
            checkpoint()
            prior = (
                actions._read('session', 'intent') if type(scope) is SuccessorSessionScope else None
            )
            if prior is None:
                try:
                    actions.create_session(
                        request,
                        checkpoint,
                        timeout_ms=min(30000, scope.send_timeout_seconds * 1000),
                    )
                except (LaunchOutcomeUnknown, OSError) as error:
                    if getattr(error, 'retained_owner', None) is not None:
                        raise
            elif actions._original('session')['input'] != request:
                raise TaskExecutionError('ORIGINAL_ROLE_SESSION_REQUEST_DIFFERS')
            session = self._observe_session_configuration(
                owner, actions, checkpoint, timeout_ms=timeout
            )
            if self._continuation_guard(owner, checkpoint, timeout) != receipt:
                raise TaskExecutionError('ORIGINAL_TASK_CREATE_GUARD_DIFFERS')
        fields = ('title', 'agent', 'model', 'permission', 'metadata')
        if any(session.get(key) != request[key] for key in fields):
            raise TaskExecutionError('ORIGINAL_TASK_NATIVE_SESSION_POLICY_DIFFERS')
        if owner.configuration is None:
            raise TaskExecutionError('ORIGINAL_TASK_EFFECTIVE_CONFIGURATION_REQUIRED')
        return InitialNativeSession(session['id'], owner.configuration)

    def observe_created_session(self, scope, checkpoint):
        """C38 never creates a missing session or replays the original POST."""
        owner = self._session_owner(scope)
        with self._native_actions(owner, scope) as actions:
            original = actions._original('session')['input']
            session = self._observe_session_configuration(
                owner,
                actions,
                checkpoint,
                timeout_ms=min(3000, scope.query_timeout_seconds * 1000),
            )
            if any(
                session.get(key) != original[key]
                for key in ('title', 'agent', 'model', 'permission', 'metadata')
            ):
                raise TaskExecutionError('ORIGINAL_TASK_NATIVE_SESSION_POLICY_DIFFERS')
        return session['id']

    def observe_control_configuration(self, scope, window, credential_ref, checkpoint):
        owner = self._continuation_owner(scope, credential_ref)
        quiet = self.observe_capture_turn(scope, window, credential_ref, checkpoint)
        timeout = min(3000, scope.query_timeout_seconds * 1000)
        with self._native_actions(owner, scope) as actions:
            session = self._observe_session_configuration(
                owner, actions, checkpoint, timeout_ms=timeout
            )
        if self._continuation_guard(owner, checkpoint, timeout) != quiet.guard_receipt_sha256:
            raise TaskExecutionError('ORIGINAL_CONTROL_GUARD_DIFFERS')
        return ControlConfigurationObservation(
            quiet,
            owner.configuration,
            hashlib.sha256(_bytes(session['permission'])).hexdigest(),
        )

    def prepare_native_configuration(
        self, scope, window, credential_ref, profile, grant, checkpoint
    ):
        from .task_native_policy import compile_managed_native_policy

        observation = self.observe_control_configuration(scope, window, credential_ref, checkpoint)
        owner = self._continuation_owner(scope, credential_ref)
        with self._native_actions(owner, scope) as actions:
            expected = actions.expected_session_policy(checkpoint)
            if (
                expected['id'] != window.native_session_id
                or expected['metadata'] != scope.metadata()
                or hashlib.sha256(_bytes(expected['permission'])).hexdigest()
                != observation.permission_sha256
            ):
                raise TaskExecutionError('ORIGINAL_NATIVE_CONFIGURATION_PREDECESSOR_DIFFERS')
            compiled = compile_managed_native_policy(
                profile,
                grant,
                agent=self._installation.coding.agent,
                workspace=owner.workspace,
                basis=owner.basis,
                checkpoint=checkpoint,
            )
            checkpoint()
            return NativeConfigurationPreparation(
                observation,
                _bytes(compiled.evidence()).decode('utf-8').strip(),
                hashlib.sha256(
                    _bytes(expected['permission'] + compiled.policy.permission())
                ).hexdigest(),
                actions._scope,
                actions._permission_history,
            )

    def apply_native_configuration(
        self, scope, window, credential_ref, profile, grant, identity, checkpoint, *, dispatch
    ):
        from .task_configuration_control import _digest
        from .task_native_policy import compile_managed_native_policy

        owner = self._continuation_owner(scope, credential_ref)
        if (
            window.task_id != scope.task_id
            or window.instance_id != scope.instance_id
            or window.generation != scope.control_generation
            or window.execution_session_id != scope.session_id
            or owner.gateway._window != window
        ):
            raise TaskExecutionError('ORIGINAL_NATIVE_CONFIGURATION_WINDOW_DIFFERS')
        compiled = compile_managed_native_policy(
            profile,
            grant,
            agent=self._installation.coding.agent,
            workspace=owner.workspace,
            basis=owner.basis,
            checkpoint=checkpoint,
        )
        timeout = min(3000, scope.query_timeout_seconds * 1000)
        receipt = self._continuation_guard(owner, checkpoint, timeout)
        with self._native_actions(owner, scope) as original:
            expected = original.expected_session_policy(checkpoint)
            if (
                expected['id'] != window.native_session_id
                or expected['metadata'] != scope.metadata()
                or identity['session_scope'] != asdict(original._scope)
                or identity['previous_applications']
                != [asdict(previous) for previous in original._permission_history]
                or not native_json_equal(identity['target_policy'], compiled.evidence())
                or identity['permission_sha256']
                != hashlib.sha256(_bytes(expected['permission'])).hexdigest()
                or identity['target_permission_sha256']
                != hashlib.sha256(
                    _bytes(expected['permission'] + compiled.policy.permission())
                ).hexdigest()
                or identity['configuration_sha256'] != _digest(asdict(owner.configuration))
            ):
                raise TaskExecutionError('ORIGINAL_NATIVE_CONFIGURATION_TARGET_DIFFERS')
            application_scope = LaunchScope(
                original._scope.controller_ref, identity['operation_id'], 3, identity['nonce']
            )
            actions = TaskNativeActions(
                self._parent,
                owner.launch._original.scope,
                original._control,
                action_scope=application_scope,
            )
            self._observe_configuration(owner, original._control, checkpoint, timeout_ms=timeout)
            if dispatch:
                self._observe_session_configuration(owner, original, checkpoint, timeout_ms=timeout)
                original._control.capture_turn_completion(
                    window.native_session_id,
                    window.trigger_message_id,
                    checkpoint,
                    timeout_ms=timeout,
                )
                if self._continuation_guard(owner, checkpoint, timeout) != receipt:
                    raise TaskExecutionError('ORIGINAL_NATIVE_CONFIGURATION_GUARD_DIFFERS')
                actions.apply_permission(
                    expected,
                    compiled.policy.permission(),
                    checkpoint,
                    timeout_ms=timeout,
                    session_scope=original._scope,
                    previous_applications=original._permission_history,
                )
            else:
                actions.observe_permission(checkpoint, timeout_ms=timeout)
            self._observe_configuration(owner, original._control, checkpoint, timeout_ms=timeout)
            session = actions.observe_permission(checkpoint, timeout_ms=timeout)
            if (
                hashlib.sha256(_bytes(session['permission'])).hexdigest()
                != identity['target_permission_sha256']
            ):
                raise TaskExecutionError('ORIGINAL_NATIVE_CONFIGURATION_EFFECTIVE_DIFFERS')
            turn = original._control.capture_turn_completion(
                window.native_session_id, window.trigger_message_id, checkpoint, timeout_ms=timeout
            )
        if self._continuation_guard(owner, checkpoint, timeout) != receipt:
            raise TaskExecutionError('ORIGINAL_NATIVE_CONFIGURATION_GUARD_DIFFERS')
        safe_turn = safe_native_records(
            turn, (owner.credential._password, owner.gateway._credential._secret)
        )
        quiet = CaptureTurnEvidence(safe_turn, receipt, 1, owner.workspace, owner.scratch)
        return ControlConfigurationObservation(
            quiet, owner.configuration, identity['target_permission_sha256']
        )

    def gateway_reference(self, scope):
        gateway = self._session_owner(scope).gateway
        if gateway is None or not gateway.accepting:
            return None
        return gateway.credential_ref

    def initial_payload(self, scope, context):
        owner = self._session_owner(scope)
        texts = initial_texts(scope, context, owner.basis_plan, owner.workspace)
        with self._native_actions(owner) as actions:
            return actions.initial_payload(self._installation.coding.agent, PROVIDER, MODEL, texts)

    def send_initial(self, scope, original, payload, checkpoint):
        payload = native_message_input(payload)
        original = strict_json_object(_bytes(original))
        owner = self._session_owner(scope)
        if (
            self.gateway_reference(scope) != original['gateway_credential_ref']
            or hashlib.sha256(_bytes(payload)).hexdigest() != original['payload_sha256']
        ):
            raise TaskExecutionError('ORIGINAL_TASK_INITIAL_DELIVERY_DIFFERS')
        with self._native_actions(owner) as actions:
            payload = self._prepare_initial_delivery(
                owner, actions, scope, original, payload, checkpoint
            )
            owner.gateway.queue(scope, original)
            try:
                actions.send_initial(
                    original['native_session_id'],
                    payload,
                    checkpoint,
                    timeout_ms=min(30000, scope.send_timeout_seconds * 1000),
                )
            except (LaunchOutcomeUnknown, OSError) as error:
                if getattr(error, 'retained_owner', None) is not None:
                    raise
            deadline = monotonic() + min(scope.query_timeout_seconds, 30)
            while True:
                checkpoint()
                remaining = max(1, int((deadline - monotonic()) * 1000))
                try:
                    message = actions.observe_initial(checkpoint, timeout_ms=remaining)
                except TaskExecutionError as error:
                    if (
                        str(error) != 'ORIGINAL_OPENCODE_RESPONSE_UNVERIFIED'
                        or monotonic() >= deadline
                    ):
                        raise
                    sleep(0.025)
                else:
                    return message['info']['id']

    def revoke_session_source(self, scope, previous, credential_ref, checkpoint):
        owner = self._continuation_owner(scope, credential_ref)
        checkpoint()
        owner.gateway.revoke_session_source(previous)
        checkpoint()

    def role_payload(self, scope, context, handoff, checkpoint):
        owner = self._session_owner(scope)
        texts = initial_texts(scope, context, owner.basis_plan, owner.workspace, handoff=handoff)
        with self._native_actions(owner, scope) as actions:
            checkpoint()
            return actions.plan_initial_payload(
                self._installation.coding.agent, PROVIDER, MODEL, texts
            )

    def send_successor(self, scope, previous, original, payload, checkpoint):
        payload = native_message_input(payload)
        original = strict_json_object(_bytes(original))
        owner = self._session_owner(scope)
        if (
            type(scope) is not SuccessorSessionScope
            or self.gateway_reference(scope) != original['gateway_credential_ref']
            or hashlib.sha256(_bytes(payload)).hexdigest() != original['payload_sha256']
        ):
            raise TaskExecutionError('ORIGINAL_ROLE_DELIVERY_DIFFERS')
        with self._native_actions(owner, scope) as actions:
            prior = actions._read('initial', 'intent')
            if prior is not None and actions._original('initial')['input'] != {
                'session_id': original['native_session_id'],
                'payload': payload,
            }:
                raise TaskExecutionError('ORIGINAL_ROLE_MESSAGE_INTENT_DIFFERS')
            payload = self._prepare_initial_delivery(
                owner, actions, scope, original, payload, checkpoint
            )
            owner.gateway.queue_successor(previous, scope, original)
            timeout = min(30000, scope.send_timeout_seconds * 1000)
            try:
                if prior is None:
                    actions.send_initial(
                        original['native_session_id'], payload, checkpoint, timeout_ms=timeout
                    )
            except (LaunchOutcomeUnknown, OSError) as error:
                if getattr(error, 'retained_owner', None) is not None:
                    raise
            deadline = monotonic() + min(scope.query_timeout_seconds, 30)
            while True:
                checkpoint()
                try:
                    message = actions.observe_initial(
                        checkpoint, timeout_ms=max(1, int((deadline - monotonic()) * 1000))
                    )
                except TaskExecutionError as error:
                    if (
                        str(error) != 'ORIGINAL_OPENCODE_RESPONSE_UNVERIFIED'
                        or monotonic() >= deadline
                    ):
                        raise
                    sleep(0.025)
                else:
                    return message['info']['id']

    def observe_successor_message(self, scope, original, checkpoint):
        owner = self._session_owner(scope)
        window = ModelWindow(
            scope.task_id,
            scope.instance_id,
            scope.control_generation,
            scope.session_id,
            original['native_session_id'],
            scope.transition_operation_id,
            original['native_message_id'],
        )
        if self.gateway_reference(scope) != original[
            'gateway_credential_ref'
        ] or not owner.gateway.owns_successor_window(window):
            raise TaskExecutionError('ORIGINAL_ROLE_GATEWAY_WINDOW_UNAVAILABLE')
        timeout = min(3000, scope.query_timeout_seconds * 1000)
        with self._native_actions(owner, scope) as actions:
            record = actions._original('initial')
            if (
                record['input']['session_id'] != original['native_session_id']
                or hashlib.sha256(_bytes(record['input']['payload'])).hexdigest()
                != original['payload_sha256']
            ):
                raise TaskExecutionError('ORIGINAL_ROLE_MESSAGE_INTENT_DIFFERS')
            checkpoint()
            found = actions.observe_initial(checkpoint, timeout_ms=timeout)
        return found['info']['id']

    def send_question_response(self, scope, native, request_id, answers, checkpoint):
        answers = strict_json_object(_bytes({'answers': answers}))['answers']
        owner = self._session_owner(scope)
        secrets = [owner.credential._password]
        if owner.gateway is not None:
            secrets.append(owner.gateway._credential._secret)
        _check_credentials(answers, tuple(secrets))
        with ExitStack() as opened:
            actions = opened.enter_context(self._native_actions(owner, scope))
            control = actions._control
            send_timeout = min(30000, scope.send_timeout_seconds * 1000)
            query_timeout = min(3000, scope.query_timeout_seconds * 1000)
            session = self._observe_session_configuration(
                owner, actions, checkpoint, timeout_ms=query_timeout
            )
            if session['id'] != native:
                raise TaskExecutionError('ORIGINAL_QUESTION_SESSION_DIFFERS')
            try:
                events = opened.enter_context(
                    control.reply_events(
                        checkpoint,
                        timeout_ms=min(30000, send_timeout + 2 * query_timeout),
                        ready_timeout_ms=query_timeout,
                    )
                )
            except TaskExecutionError:
                events = None
            try:
                control.reply_question(request_id, answers, checkpoint, timeout_ms=send_timeout)
            except TaskExecutionError:
                if events is None:
                    raise
                while True:
                    event = events.next()
                    if event['type'] == 'question.replied' and event['properties'] == {
                        'sessionID': native,
                        'requestID': request_id,
                        'answers': answers,
                    }:
                        checkpoint()
                        return {'source': 'NATIVE_EVENT', 'event_id': event['id']}
            return {'source': 'HTTP_200'}

    def decide_native_permission(self, scope, response, checkpoint, claim, record):
        owner = self._session_owner(scope)
        native, original, candidates, reply = response
        frozen = strict_json_object(_bytes({'original': original, 'candidates': list(candidates)}))
        original, candidates = frozen['original'], tuple(frozen['candidates'])
        selected = original['id']
        send_timeout = min(30000, scope.send_timeout_seconds * 1000)
        query_timeout = min(3000, scope.query_timeout_seconds * 1000)
        with ExitStack() as opened:
            actions = opened.enter_context(self._native_actions(owner, scope))
            control = actions._control
            checked = checkpoint
            if reply == 'once':
                session = self._observe_session_configuration(
                    owner, actions, checkpoint, timeout_ms=query_timeout
                )
                if session['id'] != native:
                    raise TaskExecutionError('ORIGINAL_PERMISSION_SESSION_DIFFERS')
                checked = opened.enter_context(
                    pin_permission_object(
                        control, owner.workspace, original, checkpoint, timeout_ms=query_timeout
                    )
                )
            try:
                events = opened.enter_context(
                    control.reply_events(
                        checked,
                        timeout_ms=min(30000, send_timeout + 2 * query_timeout),
                        ready_timeout_ms=query_timeout,
                    )
                )
            except TaskExecutionError:
                if reply == 'reject':
                    raise
                events = None

            # The write-ahead claim occurs after the original event subscription is ready
            # for a rejection, with every concrete path pin still held for an allow.
            checked()
            claim()
            try:
                control.reply_permission(selected, reply, checked, timeout_ms=send_timeout)
            except TaskExecutionError:
                if events is None:
                    raise
            else:
                if reply == 'once':
                    record(selected, {'source': 'HTTP_200'})
                    return

            outstanding = set(candidates)
            while outstanding:
                event = events.next()
                values = event['properties']
                if (
                    event['type'] != 'permission.replied'
                    or set(values) != {'sessionID', 'requestID', 'reply'}
                    or values['sessionID'] != native
                    or values['reply'] != reply
                    or type(values['requestID']) is not str
                    or values['requestID'] not in outstanding
                ):
                    continue
                checked()
                request = values['requestID']
                record(request, {'source': 'NATIVE_EVENT', 'event_id': event['id']})
                outstanding.remove(request)

    def observe_native_issues(self, scope, native, checkpoint):
        owner = self._session_owner(scope)
        timeout = min(1000, scope.query_timeout_seconds * 1000)
        with self._native_actions(owner, scope) as actions:
            observed = actions.observe_session(checkpoint, timeout_ms=timeout)
            if observed['id'] != native or observed.get('metadata') != scope.metadata():
                raise TaskExecutionError('ORIGINAL_TASK_ISSUE_SESSION_DIFFERS')
            questions = actions._control.pending(native, 'question', checkpoint, timeout_ms=timeout)
            permissions = actions._control.pending(
                native, 'permission', checkpoint, timeout_ms=timeout
            )
        secrets = [owner.credential._password]
        if owner.gateway is not None:
            secrets.append(owner.gateway._credential._secret)
        _check_credentials([*questions, *permissions], tuple(secrets))
        return questions, permissions

    def _continuation_owner(self, scope, credential_ref):
        owner = self._session_owner(scope)
        if (
            owner.gateway is None
            or not owner.gateway.accepting
            or owner.gateway.credential_ref != credential_ref
        ):
            raise TaskExecutionError('ORIGINAL_TASK_CONTINUATION_GATEWAY_DIFFERS')
        return owner

    def _continuation_guard(self, owner, checkpoint, timeout):
        checkpoint()
        with self._connect() as frames:
            owner.launch.reconnect(frames)
            observed = owner.launch.observe('RESUME', timeout_ms=timeout, cancelled=lambda: False)
        checkpoint()
        resource, job, fence = (observed[name] for name in ('resource', 'job_activity', 'fence'))
        receipt = owner.launch.running_receipt()
        if (
            resource is None
            or job is None
            or fence is None
            or observed['acknowledgement'] is None
            or resource['receipt_sha256'] != receipt['receipt_sha256']
            or resource['process_identity'] != receipt['process_identity']
            or resource['process_state'] != 'RUNNING'
            or fence['stop_closed']
            or job['complete'] is not True
            or job['assigned_count'] != 1
            or job['process_ids'] != [receipt['process_identity']['pid']]
        ):
            raise TaskExecutionError('ORIGINAL_TASK_CONTINUATION_ACTIVITY_UNVERIFIED')
        return receipt['receipt_sha256']

    def observe_capture_turn(self, scope, window, credential_ref, checkpoint):
        """Compare the exact native turn inside independently observed original Job facts."""
        owner = self._continuation_owner(scope, credential_ref)
        if (
            window.task_id != scope.task_id
            or window.instance_id != scope.instance_id
            or window.generation != scope.control_generation
            or window.execution_session_id != scope.session_id
            or owner.gateway._window != window
        ):
            raise TaskExecutionError('ORIGINAL_CAPTURE_NATIVE_WINDOW_DIFFERS')
        timeout = min(3000, scope.query_timeout_seconds * 1000)
        receipt = self._continuation_guard(owner, checkpoint, timeout)
        with self._native_actions(owner, scope) as actions:
            session = self._observe_session_configuration(
                owner, actions, checkpoint, timeout_ms=timeout
            )
            if (
                session['id'] != window.native_session_id
                or session.get('metadata') != scope.metadata()
            ):
                raise TaskExecutionError('ORIGINAL_CAPTURE_NATIVE_SESSION_DIFFERS')
            turn = actions._control.capture_turn_completion(
                window.native_session_id, window.trigger_message_id, checkpoint, timeout_ms=timeout
            )
        if self._continuation_guard(owner, checkpoint, timeout) != receipt:
            raise TaskExecutionError('ORIGINAL_CAPTURE_GUARD_RECEIPT_DIFFERS')
        safe_turn = safe_native_records(
            turn, (owner.credential._password, owner.gateway._credential._secret)
        )
        return CaptureTurnEvidence(safe_turn, receipt, 1, owner.workspace, owner.scratch)

    def repair_session_archived_at(self, scope, previous, credential_ref, checkpoint):
        """An archived session is replaceable only after its exact settled turn."""
        owner = self._continuation_owner(scope, credential_ref)
        timeout = min(3000, scope.query_timeout_seconds * 1000)
        receipt = self._continuation_guard(owner, checkpoint, timeout)
        with self._native_actions(owner, scope) as actions:
            session = self._observe_session_configuration(
                owner, actions, checkpoint, timeout_ms=timeout
            )
            if (
                session['id'] != previous.native_session_id
                or session.get('metadata') != scope.metadata()
            ):
                raise TaskExecutionError('ORIGINAL_REPAIR_SESSION_DIFFERS')
            times = session.get('time', {})
            if type(times) is not dict:
                raise TaskExecutionError('ORIGINAL_REPAIR_ARCHIVE_UNVERIFIED')
            archived = times.get('archived')
            if archived is None:
                if self._continuation_guard(owner, checkpoint, timeout) != receipt:
                    raise TaskExecutionError('ORIGINAL_REPAIR_GUARD_DIFFERS')
                return None
            from backend.app.shared.validation import strict_integer

            strict_integer(archived, 'archived')
            control = actions._control
            control.settled_turn(
                previous.native_session_id,
                previous.trigger_message_id,
                checkpoint,
                timeout_ms=timeout,
            )
            if (
                not control.original_turn_idle(
                    previous.native_session_id, checkpoint, timeout_ms=timeout
                )
                or control.pending(
                    previous.native_session_id, 'question', checkpoint, timeout_ms=timeout
                )
                or control.pending(
                    previous.native_session_id, 'permission', checkpoint, timeout_ms=timeout
                )
            ):
                raise TaskExecutionError('ORIGINAL_REPAIR_SOURCE_NOT_SETTLED')
        if self._continuation_guard(owner, checkpoint, timeout) != receipt:
            raise TaskExecutionError('ORIGINAL_REPAIR_GUARD_DIFFERS')
        return archived

    def observe_replacement_source(self, scope, expected, credential_ref, checkpoint):
        """No successor prompt is queued while the retired source is rechecked."""
        owner = self._continuation_owner(scope, credential_ref)
        timeout = min(3000, scope.query_timeout_seconds * 1000)
        receipt = self._continuation_guard(owner, checkpoint, timeout)
        original = expected['turn']
        with self._native_actions(owner, scope) as actions:
            actions._control.session(original['session_id'], checkpoint, timeout_ms=timeout)
            turn = actions._control.capture_turn_completion(
                original['session_id'],
                original['trigger_message_id'],
                checkpoint,
                timeout_ms=timeout,
            )
        if (
            turn.scope_proof() != original
            or receipt != expected['guard_receipt_sha256']
            or asdict(owner.workspace) != expected['workspace']
            or self._continuation_guard(owner, checkpoint, timeout) != receipt
        ):
            raise TaskExecutionError('ORIGINAL_REPAIR_REPLACEMENT_SOURCE_DIFFERS')
        safe_turn = safe_native_records(
            turn, (owner.credential._password, owner.gateway._credential._secret)
        )
        return CaptureTurnEvidence(safe_turn, receipt, 1, owner.workspace, owner.scratch)

    def replacement_repair_payload(self, scope, context, source, defects, checkpoint):
        owner = self._session_owner(scope)
        parts = repair_texts(scope, context, owner.basis_plan, owner.workspace, source, defects)
        with self._native_actions(owner, scope) as actions:
            checkpoint()
            return actions.plan_initial_payload(
                self._installation.coding.agent, PROVIDER, MODEL, parts
            )

    def repair_payload(
        self, scope, previous, credential_ref, checkpoint, *, context, source, defects
    ):
        owner = self._continuation_owner(scope, credential_ref)
        if context.native_session_id != previous.native_session_id:
            raise TaskExecutionError('ORIGINAL_REPAIR_PROMPT_SESSION_DIFFERS')
        parts = repair_texts(scope, context, owner.basis_plan, owner.workspace, source, defects)
        return self.continuation_payload(scope, previous, credential_ref, checkpoint, parts=parts)

    def continuation_payload(self, scope, previous, credential_ref, checkpoint, *, parts=None):
        owner = self._continuation_owner(scope, credential_ref)
        timeout = min(3000, scope.query_timeout_seconds * 1000)
        receipt = self._continuation_guard(owner, checkpoint, timeout)
        with self._native_actions(owner, scope) as actions:
            session = self._observe_session_configuration(
                owner, actions, checkpoint, timeout_ms=timeout
            )
            native = previous.native_session_id
            if session['id'] != native or session.get('metadata') != scope.metadata():
                raise TaskExecutionError('ORIGINAL_TASK_CONTINUATION_SESSION_DIFFERS')
            control = actions._control
            control.settled_turn(
                native, previous.trigger_message_id, checkpoint, timeout_ms=timeout
            )
            if (
                not control.original_turn_idle(native, checkpoint, timeout_ms=timeout)
                or control.pending(native, 'question', checkpoint, timeout_ms=timeout)
                or control.pending(native, 'permission', checkpoint, timeout_ms=timeout)
            ):
                raise TaskExecutionError('ORIGINAL_TASK_CONTINUATION_ACTIVITY_UNVERIFIED')
            payload = actions.initial_payload(
                self._installation.coding.agent,
                PROVIDER,
                MODEL,
                parts
                if parts is not None
                else (
                    '用户已明确继续当前后端阶段。请从本会话的现有工作继续，沿用原固定依据、任务范围及授权。',
                ),
            )
        if self._continuation_guard(owner, checkpoint, timeout) != receipt:
            raise TaskExecutionError('ORIGINAL_TASK_CONTINUATION_GUARD_DIFFERS')
        return payload

    def dispatch_continuation(self, scope, previous, window, credential_ref, payload, checkpoint):
        payload = native_message_input(payload)
        if payload['messageID'] != window.trigger_message_id:
            raise TaskExecutionError('ORIGINAL_TASK_CONTINUATION_MESSAGE_DIFFERS')
        owner = self._continuation_owner(scope, credential_ref)
        timeout = min(3000, scope.query_timeout_seconds * 1000)
        receipt = self._continuation_guard(owner, checkpoint, timeout)
        with self._native_actions(owner, scope) as actions:
            session = self._observe_session_configuration(
                owner, actions, checkpoint, timeout_ms=timeout
            )
            if session['id'] != window.native_session_id or not native_json_equal(
                session.get('metadata'), scope.metadata()
            ):
                raise TaskExecutionError('ORIGINAL_TASK_CONTINUATION_SESSION_DIFFERS')
            if self._continuation_guard(owner, checkpoint, timeout) != receipt:
                raise TaskExecutionError('ORIGINAL_TASK_CONTINUATION_GUARD_DIFFERS')
            checkpoint()
            owner.gateway.queue_continuation(previous, window)
            actions._control.send_message(
                window.native_session_id,
                payload,
                checkpoint,
                timeout_ms=min(30000, scope.send_timeout_seconds * 1000),
            )

    def observe_continuation(self, scope, window, credential_ref, payload, checkpoint):
        owner = self._continuation_owner(scope, credential_ref)
        # A restarted backend cannot reconstruct a live route or recover
        # permission to send from SQLite alone.
        if owner.gateway._window != window:
            raise TaskExecutionError('ORIGINAL_TASK_CONTINUATION_GATEWAY_DIFFERS')
        with owner.launch.running_control(owner.credential, owner.workspace) as control:
            result = control.verify_message(
                window.native_session_id,
                payload,
                checkpoint,
                timeout_ms=min(3000, scope.query_timeout_seconds * 1000),
            )
        return result['info']['id']

    def revoke_original_gateway(self, original):
        owner = self._stop_owner(original)
        if owner is not None and owner.gateway is not None:
            owner.gateway.revoke()

    def abort_original(self, original, checkpoint, *, timeout_ms):
        owner = self._stop_owner(original)
        if owner is None:
            return 'CONTROL_UNAVAILABLE'
        if original.native_session_id is None:
            return 'NO_VERIFIED_SESSION'
        if owner.fenced or owner.credential is None or owner.workspace is None:
            return 'CONTROL_UNAVAILABLE'
        with owner.launch.running_control(owner.credential, owner.workspace) as control:
            control.abort_session(original.native_session_id, checkpoint, timeout_ms=timeout_ms)
        return 'ACKNOWLEDGED'

    def _stop_owner(self, original):
        owner = self._owners.get(original.claim.operation_id)
        if owner is not None and (owner.claim != original.claim or owner.launch is None):
            raise TaskExecutionError('ORIGINAL_TASK_STOP_OWNER_DIFFERS')
        return owner

    @contextmanager
    def _stop_target(self, original):
        with self._connect() as frames:
            owner = self._stop_owner(original)
            if owner is not None and owner.launch._input is not None:
                owner.launch.reconnect(frames)
                yield owner, owner.launch
            else:
                receipt = TaskRecoveryReceipt(
                    self._parent, original.claim.operation_id, original.claim.nonce
                )
                yield None, RuntimeTaskRecovery(frames, self._controller, self._lock, receipt)

    def stop_original(self, original, *, timeout_ms, cancelled):
        with self._stop_target(original) as (owner, launch):
            if owner is None and launch._reference is None:
                launch.observe('PREPARE', timeout_ms=timeout_ms, cancelled=cancelled)
            before = launch.observe('STOP', timeout_ms=timeout_ms, cancelled=cancelled)
            if before['acknowledgement'] is None:
                launch.stop(timeout_ms=timeout_ms, cancelled=cancelled)
            stopped = launch.observe('STOP', timeout_ms=timeout_ms, cancelled=cancelled)
            if owner is not None and stopped['acknowledgement'] is not None:
                # Recover the exact ACK locally before allowing RELEASE.
                if owner.launch._evidence.read_ack('STOP') is None:
                    owner.launch.stop(timeout_ms=timeout_ms, cancelled=cancelled)
                owner.fenced = True
                if owner.output is not None:
                    owner.output.finish_after_stop(stopped['resource'], timeout_ms=1000)
            return stopped

    def release_original(self, original, *, timeout_ms, cancelled):
        with self._stop_target(original) as (_, launch):
            if isinstance(launch, RuntimeTaskRecovery) and launch._reference is None:
                launch.observe('PREPARE', timeout_ms=timeout_ms, cancelled=cancelled)
            previous = launch.observe('RELEASE', timeout_ms=timeout_ms, cancelled=cancelled)
            if previous['preparation']['cleanup_state'] != 'COMPLETE':
                launch.release(timeout_ms=timeout_ms, cancelled=cancelled)
            return launch.observe('RELEASE', timeout_ms=timeout_ms, cancelled=cancelled)

    def release_workspace_original(self, original, operation_id, guard_ref, checkpoint):
        identity = original.claim.operation_id
        release = self._workspace_releases.get(identity)
        if release is None:
            release = OriginalWorkspaceRelease(self._parent, original, operation_id, guard_ref)
            self._workspace_releases[identity] = release
        elif (
            release._scope['operation_id'] != operation_id
            or release._scope['guard_cleanup_sha256'] != guard_ref
        ):
            raise TaskExecutionError('ORIGINAL_TASK_WORKSPACE_RELEASE_SCOPE_DIFFERS')
        return release.release(checkpoint)

    def retire_original(self, original):
        identity = original.claim.operation_id
        owner = self._stop_owner(original)
        if owner is not None:
            if not owner.fenced:
                raise TaskExecutionError('ORIGINAL_TASK_LOCAL_RETIREMENT_REQUIRES_STOP')
            owner.close_local()
            del self._owners[identity]
        self._close_workspace_release(identity)

    def _close_workspace_release(self, identity):
        release = self._workspace_releases.get(identity)
        if release is not None:
            release.close()
            del self._workspace_releases[identity]

    def fence_failed(self, operation_id):
        owner = self._owners.get(operation_id)
        if owner is None or owner.launch is None or owner.launch._input is None:
            return False
        if owner.fenced:
            return True
        if owner.gateway is not None:
            owner.gateway.revoke()
        try:
            with self._connect() as frames:
                owner.launch.reconnect(frames)
                native = owner.launch.stop(timeout_ms=5000, cancelled=lambda: False)
                if native['process_state'] not in ('NOT_CREATED', 'EXITED'):
                    return False
                if owner.output is not None:
                    owner.output.finish_after_stop(native, timeout_ms=1000)
        except (LaunchOutcomeUnknown, OSError) as error:
            if getattr(error, 'retained_owner', None) is not None:
                raise
            return False
        owner.fenced = True
        return True

    def close(self):
        # Fence through the original Guard owner before retiring local handles.
        # The controller watch remains responsible if Guard cannot confirm.
        for operation_id, owner in tuple(self._owners.items()):
            if (
                owner.launch is not None
                and owner.launch._input is not None
                and not self.fence_failed(operation_id)
            ):
                error = TaskExecutionError('ORIGINAL_TASK_SHUTDOWN_FENCE_UNVERIFIED')
                error.retained_owner = owner
                raise error
            owner.close_local()
            del self._owners[operation_id]
        for operation_id in tuple(self._workspace_releases):
            self._close_workspace_release(operation_id)
