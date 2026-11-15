"""Retain the original program, LPAC Job and WFP plan before full TASK admission."""

import hashlib
from dataclasses import asdict
from time import monotonic
from uuid import uuid4

from .guard_action_journal import GuardActionJournal
from .guard_request_header import parse_guard_request_header
from .guard_task_execution_protocol import ExecutionPreparationResult, decode_task_execution_stage
from .guard_task_files import (
    _publish_original,
    _read_original,
    _verify_held_directories,
    find_task_file_reservation,
)
from .guard_task_launch_protocol import CONFIRM_LAUNCH, launch_stdio_descriptor
from .guard_task_network import (
    WfpObservationError,
    _sealed_task_plan,
    install_original_task_network,
    seal_original_task_network,
    verify_installed_task_network,
)
from .opencode_binary import OpenCodeBinaryError
from .opencode_control import OpenCodeControlCredential
from .opencode_runtime_bundle import OpenCodeRuntimeBundleError
from .opencode_task_launch import TaskExecutionError, TaskExecutionPlan, TaskProgramOwner
from .runtime_launch_journal import LaunchFenceError, _bytes
from .windows_config_source import ConfigReadError
from .windows_executable_pin import ExecutablePinError
from .windows_job import JobBoundaryError, JobMembers, OwnedJob
from .windows_local_paths import PathBoundaryError
from .windows_lpac_profile import TaskLpacProfile
from .windows_private_package import PackageSecurityError
from .windows_private_record import PrivateRecordError
from .windows_process import ProcessObservationError
from .windows_stdio import GuardStandardIO, StdioBoundaryError
from .windows_task_endpoints import observe_task_endpoints
from .windows_task_native_launch import TaskNativeLaunch

_MAX_RECORD_BYTES = 16384


class _ExecutionPreparation:
    def __init__(self, directories, owner, program_source, network):
        self._dirs, self._owner, self._network = directories, owner, network
        self._request = directories._prepare_request
        self._actions = directories._actions
        self._journal = self._actions._journal
        data = self._request.input
        self._plan = TaskExecutionPlan.parse(
            data.get('execution'), data.get('network'), directories._runtime_bundle_ref
        )
        declared = self._plan.network
        if (
            declared['model'] != (network.model_listener,)
            or declared['forward'] != network.forward_listeners
        ):
            raise TaskExecutionError('ORIGINAL_TASK_ENDPOINT_DEPLOYMENT_DIFFERS')
        self._program = TaskProgramOwner(program_source, self._plan)
        self._job = None
        self._profile = None
        self._credential = None
        self._streams = self._native = self._confirmation = None
        self._directory_release = None
        self._job_ref = uuid4().hex
        self._name = directories.scope.key + '.task-execution-prepared.json'
        self._credential_name = directories.scope.key + '.task-control-credential.json'

    def _files_digest(self, checkpoint):
        files = self._dirs._runtime_preparation
        if files is None:
            raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_FILE_EVIDENCE_REQUIRED')
        return hashlib.sha256(_bytes(files.verify(checkpoint))).hexdigest()

    def _endpoints(self, checkpoint):
        return observe_task_endpoints(
            self._plan, self._owner._source, self._owner.binding.controller, checkpoint
        )

    def _job_verified(self):
        if self._job is None or self._job.observe_members() != JobMembers((), 0, True):
            raise TaskExecutionError('ORIGINAL_TASK_JOB_EMPTY_SCOPE_UNVERIFIED')
        with self._job.process_creation_attributes(lpac_profile=self._dirs.profile):
            pass

    def _facts(self, files, endpoints, network_ref):
        return {
            'binding_ref': self._dirs.binding_ref,
            'job_ref': self._job_ref,
            'file_evidence_sha256': files,
            'program_sha256': self._program.verify(),
            'endpoints_sha256': endpoints,
            'network_plan_ref': network_ref,
        }

    def _record(self, facts):
        return _bytes(
            {
                'schema_version': 1,
                'scope': self._dirs.scope.key,
                'prepare_input_sha256': self._dirs._original.input_sha256,
                'owner_epoch': self._dirs._original.owner_epoch,
                'lpac_sid': self._dirs.package_sid,
                'active_process_limit': self._plan.active_process_limit,
                'job_memory_limit_bytes': self._plan.job_memory_limit_bytes,
                'evidence': facts,
            }
        )

    def prepare(self, checkpoint, *, deadline, cancelled):
        files = self._files_digest(checkpoint)
        endpoints = self._endpoints(checkpoint)
        self._program.prepare(deadline=deadline, cancelled=cancelled)
        checkpoint()
        self._job = OwnedJob(
            active_process_limit=self._plan.active_process_limit,
            job_memory_limit_bytes=self._plan.job_memory_limit_bytes,
        )
        self._job_verified()
        if self._endpoints(checkpoint) != endpoints:
            raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_ENDPOINTS_DIFFERS')
        provider, sublayer = self._network.provider, self._network.sublayer
        checkpoint()
        network_ref = seal_original_task_network(
            self._actions,
            self._request,
            provider=provider,
            sublayer=sublayer,
        )
        facts = self._facts(files, endpoints, network_ref)
        with self._journal._gate:
            checkpoint()
            _publish_original(
                self._journal._package, self._name, self._record(facts), _MAX_RECORD_BYTES
            )
        return self.verify(checkpoint)

    def verify(self, checkpoint):
        scope = self._dirs.scope
        files = self._files_digest(checkpoint)
        endpoints = self._endpoints(checkpoint)
        self._job_verified()
        provider, sublayer = self._network.provider, self._network.sublayer
        with _sealed_task_plan(
            self._actions, scope, self._request.owner_epoch, provider, sublayer
        ) as (_, marker, _, _):
            facts = self._facts(files, endpoints, marker.hex())
        if _read_original(self._journal._package, self._name, _MAX_RECORD_BYTES) != self._record(
            facts
        ):
            raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_EVIDENCE_UNVERIFIED')
        try:
            count = verify_installed_task_network(
                self._actions,
                scope,
                self._request.owner_epoch,
                provider=provider,
                sublayer=sublayer,
            )
        except WfpObservationError as error:
            if getattr(error, 'retained_owner', None) is not None:
                raise
            count = 0
        checkpoint()
        return {**facts, 'network_state': 'RULES_VERIFIED' if count else 'UNKNOWN'}

    def prepare_profile(self, checkpoint, cancelled):
        facts = self.verify(checkpoint)
        scope = self._dirs.scope.key
        if self._profile is not None or scope in self._owner._task_profiles:
            raise TaskExecutionError('ORIGINAL_LPAC_PROFILE_ALREADY_DISPATCHED')
        self._profile = TaskLpacProfile(self._dirs, self._job)
        self._owner._task_profiles[scope] = self
        identity = self._profile.prepare(cancelled)
        return self._profile_facts(facts, identity)

    def _profile_facts(self, facts, identity):
        raw = _bytes(
            {
                'scope': self._dirs.scope.key,
                'prepare_input_sha256': self._dirs._original.input_sha256,
                'job_ref': self._job_ref,
                'sid': self._dirs.package_sid,
                'folder': asdict(identity),
            }
        )
        return {**facts, 'profile_sha256': hashlib.sha256(raw).hexdigest()}

    def verify_profile(self, checkpoint, cancelled):
        facts = self.verify(checkpoint)
        if self._profile is None:
            raise TaskExecutionError('ORIGINAL_LPAC_PROFILE_EVIDENCE_REQUIRED')
        return self._profile_facts(facts, self._profile.verify(cancelled))

    def verify_profile_network(self, checkpoint, cancelled):
        facts = self.verify_profile(checkpoint, cancelled)
        if facts['network_state'] != 'RULES_VERIFIED':
            raise TaskExecutionError('ORIGINAL_TASK_INSTALLED_NETWORK_EVIDENCE_REQUIRED')
        return facts

    def install_network(self, checkpoint, cancelled):
        self.verify_profile(checkpoint, cancelled)
        install_original_task_network(
            self._actions,
            self._request,
            provider=self._network.provider,
            sublayer=self._network.sublayer,
            cancelled=cancelled,
        )
        return self.verify_profile_network(checkpoint, cancelled)

    def verify_network_policy(self, checkpoint, cancelled):
        facts = self.verify_profile_network(checkpoint, cancelled)
        count = verify_installed_task_network(
            self._actions,
            self._dirs.scope,
            self._request.owner_epoch,
            provider=self._network.provider,
            sublayer=self._network.sublayer,
            policy_checkpoint=checkpoint,
        )
        if not count:
            raise TaskExecutionError('ORIGINAL_TASK_NETWORK_POLICY_UNVERIFIED')
        return {**facts, 'policy_state': 'NO_EXTERNAL_BYPASS_SEEN'}

    def _credential_record(self, facts):
        return _bytes(
            {
                'schema_version': 1,
                'scope': self._dirs.scope.key,
                'prepare_input_sha256': self._dirs._original.input_sha256,
                'binding_ref': self._dirs.binding_ref,
                'job_ref': self._job_ref,
                **facts,
            }
        )

    def bind_credential(self, payload, checkpoint):
        self.verify(checkpoint)
        credential = OpenCodeControlCredential.from_pipe(self._dirs.scope, self._plan, payload)
        with self._journal._gate:
            checkpoint()
            if (
                self._credential is not None
                or _read_original(self._journal._package, self._credential_name, _MAX_RECORD_BYTES)
                is not None
            ):
                raise TaskExecutionError('ORIGINAL_TASK_CONTROL_CREDENTIAL_ALREADY_BOUND')
            self._credential = credential
            _publish_original(
                self._journal._package,
                self._credential_name,
                self._credential_record(credential.facts(self._dirs.scope, self._plan)),
                _MAX_RECORD_BYTES,
            )
        return self.verify_credential(checkpoint)

    def verify_credential(self, checkpoint):
        facts = self.verify(checkpoint)
        if self._credential is None:
            raise TaskExecutionError('ORIGINAL_TASK_CONTROL_CREDENTIAL_UNVERIFIED')
        credential = self._credential.facts(self._dirs.scope, self._plan)
        if _read_original(
            self._journal._package, self._credential_name, _MAX_RECORD_BYTES
        ) != self._credential_record(credential):
            raise TaskExecutionError('ORIGINAL_TASK_CONTROL_CREDENTIAL_UNVERIFIED')
        checkpoint()
        return {**facts, **credential}

    def verify_launch_input(self, checkpoint, cancelled):
        admission = self._network.admission
        if admission is None:
            raise TaskExecutionError('ORIGINAL_TASK_DEPLOYMENT_EVIDENCE_REQUIRED')
        with self._dirs._workspace_publication.hold_launch_tree(checkpoint) as tree:
            facts = self.verify_network_policy(checkpoint, cancelled)
            credential = self.verify_credential(checkpoint)
            credential = {key: credential[key] for key in ('credential_ref', 'credential_sha256')}
            deployment = admission.verify(
                installation_ref=self._owner.binding.installation_ref,
                backend_program_ref=self._owner.registration.backend_program_ref,
                plan=self._plan,
                program_sha256=self._program._image.verify().sha256,
                network=self._network,
                checkpoint=checkpoint,
            )
            launch_input = hashlib.sha256(
                _bytes(
                    {
                        'scope': self._dirs.scope.key,
                        'prepare_input_sha256': self._dirs._original.input_sha256,
                        'workspace_tree_sha256': tree,
                        'deployment_sha256': deployment,
                        'execution': facts,
                        'credential': credential,
                    }
                )
            ).hexdigest()
        return {
            **facts,
            **credential,
            'deployment_sha256': deployment,
            'launch_input_sha256': launch_input,
        }

    def confirm_launch(self, request, checkpoint, cancelled):
        scope = self._dirs.scope
        descriptor = launch_stdio_descriptor(request, self._owner.binding)
        digest = request.input['launch_input_sha256']
        intent = _bytes(
            {
                'scope': scope.key,
                'prepare_input_sha256': self._dirs._original.input_sha256,
                'launch_input_sha256': digest,
                'stdio_descriptor_sha256': hashlib.sha256(_bytes(asdict(descriptor))).hexdigest(),
            }
        )
        package = self._journal._package
        name = scope.key + '.task-launch-confirm-intent.json'
        existing = _read_original(package, name, _MAX_RECORD_BYTES)
        if existing is not None:
            confirmed = self._actions.find(scope, 'PREPARE')
            if existing != intent or confirmed != self._confirmation or confirmed is None:
                raise TaskExecutionError('ORIGINAL_TASK_CONFIRMATION_REQUIRES_OBSERVATION')
            fence = self._journal.inspect(scope)
            if fence is None or fence.stop_closed or cancelled():
                raise TaskExecutionError('ORIGINAL_TASK_CONFIRMATION_CLOSED')
            return confirmed.result
        facts = self.verify_launch_input(checkpoint, cancelled)
        if facts['launch_input_sha256'] != digest:
            raise TaskExecutionError('ORIGINAL_TASK_CONFIRMATION_INPUT_DIFFERS')
        with self._journal._gate:
            checkpoint()
            _publish_original(package, name, intent, _MAX_RECORD_BYTES)
            if _read_original(package, name, _MAX_RECORD_BYTES) != intent:
                raise TaskExecutionError('ORIGINAL_TASK_CONFIRMATION_INTENT_UNVERIFIED')
        try:
            self._streams = GuardStandardIO(self._dirs._controller, descriptor, scope=scope)
        except StdioBoundaryError as error:
            retained = getattr(error, 'retained_owner', None)
            if type(retained) is GuardStandardIO:
                self._streams = retained
                error.retained_owner = self
            raise
        self._native = TaskNativeLaunch(
            self._dirs, self._job, self._profile, self._program, streams=self._streams
        )
        self._owner.registry.register_task_stop(scope, self.stop_native)
        with self._journal._gate:
            checkpoint()
            fence = self._journal.prepare(scope, digest)
            if fence.stop_closed or fence.create_state != 'NONE':
                raise TaskExecutionError('ORIGINAL_TASK_CONFIRMATION_CLOSED')
            result = {
                'binding_ref': self._dirs.binding_ref,
                'run_kind': 'TASK',
                'launch_input_sha256': digest,
                'stdio_binding': asdict(self._streams.binding),
            }
            self._confirmation = self._actions.acknowledge(self._dirs._original, result)
        return self._confirmation.result

    def _protected_sources(self):
        root = self._owner._task_source_parent
        admission = self._network.admission
        if root is None or admission is None:
            raise TaskExecutionError('ORIGINAL_TASK_PROTECTED_SOURCES_REQUIRED')
        return root, admission.directory

    def create_native(self, digest, checkpoint, cancelled):
        facts = self.verify_launch_input(checkpoint, cancelled)
        if facts['launch_input_sha256'] != digest:
            raise TaskExecutionError('ORIGINAL_TASK_CREATE_INPUT_DIFFERS')
        directories = self._dirs
        runtime = directories._runtime_preparation
        workspace = directories._workspace_publication._receipt()
        members = {
            'basis': tuple(receipt.file for receipt in directories._basis_group._receipts.values()),
            'config': tuple(
                child.verify().file
                for (role, _), child in runtime._environment._children.items()
                if role == 'config'
            ),
            'runtime': tuple(runtime._bundle._members.values()),
        }
        result = self._native.create(
            digest,
            runtime._environment,
            self._credential,
            members,
            self._protected_sources(),
            checkpoint,
            workspace_tree_sha256=workspace['tree_identity_sha256'],
        )
        self._streams.close()
        return result

    def resume_native(self, digest, checkpoint, active):
        self._files_digest(checkpoint)
        self._program.verify()
        self._endpoints(checkpoint)
        self._profile.verify_identity()
        self._credential.facts(self._dirs.scope, self._plan)
        admission = self._network.admission
        admission.verify(
            installation_ref=self._owner.binding.installation_ref,
            backend_program_ref=self._owner.registration.backend_program_ref,
            plan=self._plan,
            program_sha256=self._program._image.verify().sha256,
            network=self._network,
            checkpoint=checkpoint,
        )
        count = verify_installed_task_network(
            self._actions,
            self._dirs.scope,
            self._request.owner_epoch,
            provider=self._network.provider,
            sublayer=self._network.sublayer,
            policy_checkpoint=checkpoint,
        )
        if not count:
            raise TaskExecutionError('ORIGINAL_TASK_RESUME_NETWORK_UNVERIFIED')
        return self._native.resume(digest, active)

    def stop_native(self, checkpoint, deadline):
        if self._credential is not None:
            self._credential.close()
        result = self._native.stop(checkpoint, deadline=deadline)
        if self._streams is not None:
            self._streams.close()
        return result

    def release_profile(self):
        self._profile.release()
        self.close_job()

    def close_job(self):
        if self._job is None:
            return
        if self._job.observe_members() != JobMembers((), 0, True):
            raise TaskExecutionError('ORIGINAL_TASK_JOB_EMPTY_SCOPE_UNVERIFIED')
        self._job.close()
        self._job = None

    def close(self):
        if self._credential is not None:
            self._credential.close()
        try:
            if self._native is not None:
                fence = self._journal.inspect(self._dirs.scope)
                if fence is not None and fence.create_state != 'NONE':
                    self.stop_native(lambda: None, monotonic() + 5)
                self._native.close()
                self._native = None
            if self._streams is not None:
                self._streams.close()
                self._streams = None
            if self._profile is None:
                self.close_job()
            elif self._job.observe_members() != JobMembers((), 0, True):
                raise TaskExecutionError('ORIGINAL_TASK_JOB_EMPTY_SCOPE_UNVERIFIED')
            self._program.close()
        except (JobBoundaryError, ExecutablePinError, PathBoundaryError, OSError) as error:
            raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_CLOSE_UNVERIFIED') from error


def run_guard_task_execution(
    owner, request, program_source, network, *, peer, program, timeout_ms, cancelled
):
    binding = owner.binding
    if parse_guard_request_header(request.wire, binding, peer=peer) != request:
        raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_REQUEST_DIFFERS')
    stage, reference, original_digest = decode_task_execution_stage(request)
    if program_source is None or network is None:
        raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_DEPLOYMENT_REQUIRED')
    deadline = monotonic() + timeout_ms / 1000

    def interrupted():
        return cancelled() or monotonic() >= deadline

    with owner.current_registry(
        binding, peer=peer, program=program, timeout_ms=timeout_ms, cancelled=interrupted
    ) as registry:
        journal = registry._journal
        scope = request.target_scope
        with journal._scope(scope):
            reservation = find_task_file_reservation(GuardActionJournal(journal), scope)
            if reservation is None:
                raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_RESERVATION_REQUIRED')
            original, basis_digest = reservation
            if (
                reference != original.allocated_binding_ref
                or original_digest != original.input_sha256
                or original.owner_epoch != request.owner_epoch
            ):
                raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_BINDING_DIFFERS')
            directories = owner._task_directories.get(scope.key)
            try:
                if stage == CONFIRM_LAUNCH and original.phase == 'ACKNOWLEDGED':
                    preparation = (
                        None if directories is None else directories._execution_preparation
                    )
                    if preparation is None:
                        raise TaskExecutionError('ORIGINAL_TASK_CONFIRMATION_REQUIRES_OBSERVATION')
                    facts = preparation.confirm_launch(request, lambda: None, interrupted)
                    return ExecutionPreparationResult(facts)
                _verify_held_directories(journal, original, basis_digest, directories, interrupted)

                def checkpoint():
                    directories._require_open(interrupted)

                preparation = directories._execution_preparation
                if stage == 'PREPARE_EXECUTION':
                    if preparation is not None:
                        raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_ALREADY_DISPATCHED')
                    if directories._runtime_preparation is None:
                        raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_FILE_EVIDENCE_REQUIRED')
                    directories._runtime_preparation.verify(checkpoint)
                    preparation = _ExecutionPreparation(directories, owner, program_source, network)
                    directories._execution_preparation = preparation
                    facts = preparation.prepare(
                        checkpoint, deadline=deadline, cancelled=interrupted
                    )
                elif preparation is None:
                    raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_EVIDENCE_UNVERIFIED')
                elif stage == 'PREPARE_PROFILE':
                    facts = preparation.prepare_profile(checkpoint, interrupted)
                elif stage == 'VERIFY_PROFILE':
                    facts = preparation.verify_profile(checkpoint, interrupted)
                elif stage == 'INSTALL_NETWORK':
                    facts = preparation.install_network(checkpoint, interrupted)
                elif stage == 'VERIFY_PROFILE_NETWORK':
                    facts = preparation.verify_profile_network(checkpoint, interrupted)
                elif stage == 'VERIFY_NETWORK_POLICY':
                    facts = preparation.verify_network_policy(checkpoint, interrupted)
                elif stage == 'VERIFY_LAUNCH_INPUT':
                    facts = preparation.verify_launch_input(checkpoint, interrupted)
                elif stage == CONFIRM_LAUNCH:
                    facts = preparation.confirm_launch(request, checkpoint, interrupted)
                elif stage == 'BIND_CONTROL_CREDENTIAL':
                    facts = preparation.bind_credential(
                        request.input['control_credential'], checkpoint
                    )
                elif stage == 'VERIFY_CONTROL_CREDENTIAL':
                    facts = preparation.verify_credential(checkpoint)
                else:
                    facts = preparation.verify(checkpoint)
                return ExecutionPreparationResult(facts)
            except (
                LaunchFenceError,
                WfpObservationError,
                OpenCodeBinaryError,
                OpenCodeRuntimeBundleError,
                ConfigReadError,
                ExecutablePinError,
                JobBoundaryError,
                OSError,
                PackageSecurityError,
                PathBoundaryError,
                PrivateRecordError,
                ProcessObservationError,
                StdioBoundaryError,
            ) as error:
                if getattr(error, 'retained_owner', None) is not None:
                    raise
                raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_EVIDENCE_UNVERIFIED') from error
