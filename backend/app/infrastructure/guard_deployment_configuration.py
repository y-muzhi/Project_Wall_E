"""Compose an existing trusted SYSTEM Guard deployment; no install or business database."""

import os
import re
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from uuid import UUID

from backend.app.shared.strict_objects import exact
from backend.app.shared.validation import strict_integer, strict_json_object

from .check_deployment_sources import (
    CheckDeploymentSources,
    decode_check_deployment_sources,
    verify_guard_check_deployments,
)
from .deployment_manifest import absolute_path, digest, file_identity
from .guard_backend_program import MAX_MANIFEST_BYTES, decode_backend_program_manifest
from .guard_control_git_host import GuardControlGitHost
from .guard_controller_records import GuardControllerRecords
from .guard_service_diagnostics import GuardFailureStage, diagnostic_for_failure
from .guard_task_actions import TaskNetworkDeployment
from .guard_task_deployment import TaskRuntimeAdmission
from .guard_task_sources import validate_task_source_parent
from .opencode_runtime_bundle import TaskRuntimeBundleDeployment
from .runtime_launch_journal import LaunchJournal, LaunchOutcomeUnknown
from .task_deployment_sources import (
    TaskDeploymentSources,
    decode_task_deployment_sources,
    hold_task_deployment_sources,
)
from .windows_config_source import LockedFileSource
from .windows_guard_pipe import pipe_name
from .windows_local_paths import FileIdentity, LocalDirectoryPin, LocalPathGuard
from .windows_private_package import current_operator_sid
from .windows_process import ObservedProcess
from .windows_task_directories import TaskRuntimeRoot

PROTOCOL = 'DEPLOY20-GUARD-1'
PROTOCOL_V2 = 'DEPLOY20-GUARD-2'
MAX_BYTES = 2 * 1024 * 1024
_SYSTEM = 'S-1-5-18'
_BACKEND_SID = re.compile(r'S-1-(?:5-21(?:-[0-9]+){4}|12-1(?:-[0-9]+){4})')


class GuardDeploymentError(LaunchOutcomeUnknown):
    pass


@dataclass(frozen=True)
class GuardTaskDeployment:
    sources: TaskDeploymentSources
    source_parent: FileIdentity
    runtime_base: FileIdentity
    runtime_root: FileIdentity
    network: TaskNetworkDeployment


@dataclass(frozen=True)
class GuardRuntimeDeployment:
    source_parent: FileIdentity
    runtime_base: FileIdentity
    runtime_root: FileIdentity


@dataclass(frozen=True)
class GuardDeployment:
    installation_ref: str
    backend_sid: str
    backend_program_root: Path
    backend_manifest_sha256: str
    journal_root: Path
    task: GuardTaskDeployment | None
    runtime: GuardRuntimeDeployment | None
    checks: CheckDeploymentSources | None
    connection_timeout_ms: int
    request_timeout_ms: int
    shutdown_timeout_ms: int


def _uuid(value):
    if type(value) is not str:
        raise GuardDeploymentError('GUARD_DEPLOYMENT_NETWORK_IDENTITY_REQUIRED')
    result = UUID(value)
    if str(result) != value or result.int == 0:
        raise GuardDeploymentError('GUARD_DEPLOYMENT_NETWORK_IDENTITY_REQUIRED')
    return result


def _task(value):
    value = exact(value, ('program', 'source_parent', 'runtime_base', 'runtime_root', 'network'))
    sources = decode_task_deployment_sources(value['program'])
    source_parent = file_identity(value['source_parent'], directory=True)
    validate_task_source_parent(source_parent)
    base = file_identity(value['runtime_base'], directory=True)
    root = file_identity(value['runtime_root'], directory=True)
    network = exact(
        value['network'],
        ('provider', 'sublayer', 'model_listener', 'forward_listeners', 'admission'),
    )
    if (
        type(network['model_listener']) is not list
        or type(network['forward_listeners']) is not list
        or len(network['forward_listeners']) > 16
        or any(type(endpoint) is not list for endpoint in network['forward_listeners'])
    ):
        raise GuardDeploymentError('GUARD_DEPLOYMENT_NETWORK_LISTENERS_REQUIRED')
    admission = exact(network['admission'], ('directory', 'evidence_sha256'))
    network = TaskNetworkDeployment(
        _uuid(network['provider']),
        _uuid(network['sublayer']),
        tuple(network['model_listener']),
        tuple(tuple(endpoint) for endpoint in network['forward_listeners']),
        TaskRuntimeAdmission(
            file_identity(admission['directory'], directory=True),
            digest(admission['evidence_sha256']),
        ),
    )
    if (
        sources.plan.network['model'] != (network.model_listener,)
        or sources.plan.network['forward'] != network.forward_listeners
    ):
        raise GuardDeploymentError('GUARD_DEPLOYMENT_NETWORK_PLAN_DIFFERS')
    return GuardTaskDeployment(sources, source_parent, base, root, network)


def decode_guard_deployment(raw):
    try:
        if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES:
            raise GuardDeploymentError('GUARD_DEPLOYMENT_SIZE_REQUIRED')
        value = strict_json_object(raw)
        version = value.get('schema_version')
        if (
            type(version) is not int
            or version not in (1, 2)
            or value.get('protocol_version') != (PROTOCOL if version == 1 else PROTOCOL_V2)
        ):
            raise GuardDeploymentError('GUARD_DEPLOYMENT_VERSION_DIFFERS')
        names = (
            'schema_version',
            'protocol_version',
            'installation_ref',
            'backend_sid',
            'backend_program',
            'journal_root',
            'task',
            'connection_timeout_ms',
            'request_timeout_ms',
            'shutdown_timeout_ms',
        )
        exact(value, names if version == 1 else (*names, 'runtime', 'checks'))
        checks = None
        if version == 1:
            task = None if value['task'] is None else _task(value['task'])
            runtime = (
                None
                if task is None
                else GuardRuntimeDeployment(
                    task.source_parent, task.runtime_base, task.runtime_root
                )
            )
        else:
            raw_runtime = value['runtime']
            runtime = None
            if raw_runtime is not None:
                raw_runtime = exact(raw_runtime, ('source_parent', 'runtime_base', 'runtime_root'))
                runtime = GuardRuntimeDeployment(
                    *(
                        file_identity(raw_runtime[name], directory=True)
                        for name in ('source_parent', 'runtime_base', 'runtime_root')
                    )
                )
                validate_task_source_parent(runtime.source_parent)
            task = None
            if value['task'] is not None:
                if runtime is None:
                    raise GuardDeploymentError('GUARD_DEPLOYMENT_RUNTIME_REQUIRED')
                task = _task({**exact(value['task'], ('program', 'network')), **raw_runtime})
            if value['checks'] is not None:
                checks = decode_check_deployment_sources(value['checks'])
                if checks.guard_deployments and runtime is None:
                    raise GuardDeploymentError('GUARD_DEPLOYMENT_CHECK_RUNTIME_REQUIRED')
        pipe_name(value['installation_ref'])
        if (
            type(value['backend_sid']) is not str
            or _BACKEND_SID.fullmatch(value['backend_sid']) is None
        ):
            raise GuardDeploymentError('GUARD_DEPLOYMENT_ORDINARY_BACKEND_REQUIRED')
        program = exact(value['backend_program'], ('root', 'manifest_sha256'))
        return GuardDeployment(
            value['installation_ref'],
            value['backend_sid'],
            absolute_path(program['root']),
            digest(program['manifest_sha256']),
            absolute_path(value['journal_root']),
            task,
            runtime,
            checks,
            strict_integer(
                value['connection_timeout_ms'], 'connection_timeout_ms', minimum=100, maximum=5000
            ),
            strict_integer(
                value['request_timeout_ms'], 'request_timeout_ms', minimum=500, maximum=300000
            ),
            strict_integer(
                value['shutdown_timeout_ms'], 'shutdown_timeout_ms', minimum=1000, maximum=300000
            ),
        )
    except GuardDeploymentError:
        raise
    except (TypeError, ValueError, RuntimeError) as error:
        if getattr(error, 'retained_owner', None) is not None:
            raise
        raise GuardDeploymentError('GUARD_DEPLOYMENT_INVALID') from None


def require_guard_identity():
    with ObservedProcess(os.getpid()) as process:
        observed = process.observe()
        identity = observed.identity
        if (
            observed.state != 'RUNNING'
            or identity.user_sid != _SYSTEM
            or current_operator_sid() != _SYSTEM
            or identity.is_appcontainer
            or identity.appcontainer_sid is not None
            or identity.is_lpac is not False
        ):
            raise GuardDeploymentError('GUARD_DEPLOYMENT_SYSTEM_REQUIRED')


class GuardDeploymentOwner:
    """Keep the original local configuration and native host until verified shutdown."""

    def __init__(self, manifest, expected_sha256, *, cancelled):
        self.spec = None
        self.host = None
        self._held = ExitStack()
        self._orphans = []
        self._closed = False
        self._close_failed = False
        stage = GuardFailureStage.SYSTEM_IDENTITY
        try:
            require_guard_identity()
            deadline = monotonic() + 120

            def checkpoint():
                if cancelled() or monotonic() >= deadline:
                    raise GuardDeploymentError('GUARD_DEPLOYMENT_PREPARATION_INTERRUPTED')

            stage = GuardFailureStage.DEPLOYMENT_SOURCE
            source = self._held.enter_context(
                LockedFileSource(
                    absolute_path(manifest), max_file_bytes=MAX_BYTES, checkpoint=checkpoint
                )
            )
            if source.snapshot.sha256 != digest(expected_sha256):
                raise GuardDeploymentError('GUARD_DEPLOYMENT_SOURCE_DIGEST_DIFFERS')
            stage = GuardFailureStage.DEPLOYMENT_CONTRACT
            self.spec = decode_guard_deployment(source.snapshot.raw)
            spec = self.spec
            stage = GuardFailureStage.BACKEND_SOURCE
            program_manifest = self._held.enter_context(
                LockedFileSource(
                    spec.backend_program_root / 'backend-program.v1.json',
                    max_file_bytes=MAX_MANIFEST_BYTES,
                    checkpoint=checkpoint,
                )
            )
            stage = GuardFailureStage.BACKEND_CONTRACT
            program = decode_backend_program_manifest(
                program_manifest.snapshot.raw, expected_sha256=spec.backend_manifest_sha256
            )
            options = {}
            image = None
            if spec.task is not None:
                stage = GuardFailureStage.TASK_PROGRAM
                image = hold_task_deployment_sources(
                    self._held,
                    spec.task.sources.binary,
                    spec.task.sources.plan,
                    deadline=deadline,
                    cancelled=cancelled,
                )
            if spec.runtime is not None:
                stage = GuardFailureStage.RUNTIME_ROOT
                runtime = spec.runtime
                parent = self._held.enter_context(
                    LocalPathGuard(runtime.source_parent.canonical_path, directory=True)
                )
                if parent.verify() != runtime.source_parent:
                    raise GuardDeploymentError('GUARD_DEPLOYMENT_TASK_SOURCE_DIFFERS')
                base = self._held.enter_context(
                    LocalDirectoryPin(
                        runtime.runtime_base.canonical_path, expected=runtime.runtime_base
                    )
                )
                root = TaskRuntimeRoot.open(base, spec.backend_sid, runtime.runtime_root)
                self._held.callback(root.close)
                options.update(task_source_parent=runtime.source_parent, task_runtime_root=root)
            if spec.task is not None:
                stage = GuardFailureStage.TASK_NETWORK
                task = spec.task
                task.network.admission.verify(
                    installation_ref=spec.installation_ref,
                    backend_program_ref=program.program_ref,
                    plan=task.sources.plan,
                    program_sha256=image.sha256,
                    network=task.network,
                    checkpoint=checkpoint,
                )
                options.update(
                    task_network=task.network,
                    task_runtime_bundle=TaskRuntimeBundleDeployment(
                        task.sources.binary.bundle, task.sources.plan.runtime_bundle_ref
                    ),
                    task_program=task.sources.binary,
                )
            if spec.checks is not None:
                stage = GuardFailureStage.CHECK_PROGRAMS
                verify_guard_check_deployments(
                    spec.checks,
                    spec.installation_ref,
                    program.program_ref,
                    deadline=deadline,
                    cancelled=cancelled,
                )
                options['project_checks'] = spec.checks.guard_deployments
            checkpoint()
            stage = GuardFailureStage.PRIVATE_JOURNAL
            journal = self._held.enter_context(LaunchJournal(spec.journal_root))
            stage = GuardFailureStage.CONTROLLER_RECORDS
            records = self._held.enter_context(GuardControllerRecords(journal))
            stage = GuardFailureStage.CONTROL_HOST
            self.host = GuardControlGitHost(
                records,
                spec.installation_ref,
                backend_sid=spec.backend_sid,
                package_root=spec.backend_program_root,
                manifest_sha256=spec.backend_manifest_sha256,
                **options,
            )
        except BaseException as original:
            diagnostic = diagnostic_for_failure(original, stage)
            self._retain(original)
            if self._orphans:
                error = GuardDeploymentError('GUARD_DEPLOYMENT_CHILD_OWNER_UNVERIFIED')
                error.guard_diagnostic = diagnostic
                error.retained_owner = self
                raise error from original
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.guard_diagnostic = diagnostic_for_failure(
                    cleanup, GuardFailureStage.SHUTDOWN
                )
                cleanup.retained_owner = self
                raise cleanup from original
            if isinstance(original, GuardDeploymentError):
                original.guard_diagnostic = diagnostic
                raise
            error = GuardDeploymentError('GUARD_DEPLOYMENT_UNVERIFIED')
            error.guard_diagnostic = diagnostic
            raise error from original

    def _retain(self, error):
        owner = getattr(error, 'retained_owner', None)
        if (
            owner is not None
            and owner is not self
            and owner is not self.host
            and all(item is not owner for item in self._orphans)
        ):
            self._orphans.append(owner)

    def serve(self, *, cancelled):
        if self._closed or self.host is None:
            raise GuardDeploymentError('GUARD_DEPLOYMENT_CLOSED')
        while not cancelled():
            try:
                if self.host._session is None:
                    self.host.accept_registered(
                        timeout_ms=self.spec.connection_timeout_ms, cancelled=cancelled
                    )
                else:
                    self.host.serve(timeout_ms=self.spec.request_timeout_ms, cancelled=cancelled)
            except RuntimeError:
                if self.host._session == 'FAILED':
                    self.host.retire_failed_session()
                elif self.host._session in ('ABORTED', 'UNADMITTED'):
                    self.host.retire_session()
                else:
                    raise

    def close(self):
        if self._closed:
            return
        if self._close_failed or self._orphans:
            error = GuardDeploymentError('GUARD_DEPLOYMENT_CLOSURE_REQUIRES_OBSERVATION')
            error.retained_owner = self
            raise error
        try:
            if self.host is not None:
                self.host.stop_owned(timeout_ms=self.spec.shutdown_timeout_ms)
                self.host.close()
                self.host = None
            self._held.close()
            self._closed = True
        except BaseException as error:
            self._close_failed = True
            self._retain(error)
            error.retained_owner = self
            raise
