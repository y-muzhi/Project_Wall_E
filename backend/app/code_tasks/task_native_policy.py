"""Compile a pinned commandless managed-directory slice, never runtime admission."""

import hashlib
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import PureWindowsPath

from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.managed_read_scopes import (
    BASIS,
    RESOURCE_SHA256,
    WORKSPACE,
    load_managed_read_scopes,
)
from backend.app.infrastructure.windows_local_paths import (
    FileIdentity,
    LocalPathGuard,
    PathBoundaryError,
)
from backend.app.shared.http_boundary import HTTP_REQUEST_BYTES

from .authorization_scope import parse_authorization_scope, profile_scope_error
from .authorizations import project_grant
from .execution_profile_content import parse_execution_profile_content
from .task_configuration_live_records import stored_profile_content
from .task_initial_prompt import NativeCodingPolicy


class NativePolicyCompilationError(ValueError):
    pass


def _digest(value):
    return hashlib.sha256(canonical_input(value).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class ManagedNativePolicy:
    policy: NativeCodingPolicy
    profile_sha256: str
    scope_sha256: str
    read_roots: tuple[str, ...]
    workspace_sha256: str
    basis_sha256: str | None

    def evidence(self):
        return {
            'protocol_version': 'READ20-MANAGED-1',
            'resource_sha256': RESOURCE_SHA256,
            'profile_sha256': self.profile_sha256,
            'authorization_scope_sha256': self.scope_sha256,
            'read_roots': list(self.read_roots),
            'workspace_sha256': self.workspace_sha256,
            'basis_sha256': self.basis_sha256,
            'agent': self.policy.agent,
            'permission_sha256': _digest({'rules': self.policy.permission()}),
        }


def _directory_pair(workspace, basis):
    for identity in (workspace, basis):
        if (
            type(identity) is not FileIdentity
            or identity.is_directory is not True
            or identity.filesystem != 'NTFS'
        ):
            raise NativePolicyCompilationError('NATIVE_POLICY_DIRECTORY_IDENTITIES_REQUIRED')
    work = PureWindowsPath(workspace.canonical_path)
    fixed = PureWindowsPath(basis.canonical_path)
    if (
        not work.is_absolute()
        or not fixed.is_absolute()
        or work.name.casefold() != 'workspace'
        or fixed.name.casefold() != 'basis'
        or work.parent != fixed.parent
        or workspace.volume_serial != basis.volume_serial
        or workspace.file_id == basis.file_id
    ):
        raise NativePolicyCompilationError('NATIVE_POLICY_DIRECTORY_ROLES_DIFFER')


def _rules(basis, include_basis):
    # Native read/edit patterns are relative to the worktree, not absolute paths.
    # Fixed edit/write tools share edit permission; shell/network/search remain denied.
    rules = [('*', '*', 'deny'), ('read', '*', 'allow'), ('edit', '*', 'allow')]
    for permission in ('read', 'edit'):
        for pattern in ('..', '../*', '/*', '*:*'):
            rules.append((permission, pattern, 'deny'))
    if include_basis:
        rules.extend(
            (
                ('read', '../basis', 'allow'),
                ('read', '../basis/*', 'allow'),
                ('external_directory', basis.canonical_path.replace('\\', '/') + '/*', 'allow'),
            )
        )
    for permission in ('read', 'edit'):
        for pattern in ('*/..', '*/../*', '.git', '.git/*', '*/.git', '*/.git/*'):
            rules.append((permission, pattern, 'deny'))
    return tuple(rules)


def compile_managed_native_policy(profile, scope, *, agent, workspace, basis, checkpoint):
    """Physical identities and exact grant produce rules; callers still prove effective ownership."""
    if not callable(checkpoint):
        raise NativePolicyCompilationError('NATIVE_POLICY_CHECKPOINT_REQUIRED')
    checkpoint()
    load_managed_read_scopes()
    checked_profile = parse_execution_profile_content(profile, max_input_bytes=HTTP_REQUEST_BYTES)
    checked_scope = parse_authorization_scope(scope, max_input_bytes=HTTP_REQUEST_BYTES).value()
    content = checked_profile.value()
    if profile_scope_error(checked_scope, content) is not None:
        raise NativePolicyCompilationError('NATIVE_POLICY_SCOPE_EXCEEDS_PROFILE')
    references = set(checked_scope['read_roots'])
    if (
        WORKSPACE not in references
        or not references.issubset({WORKSPACE, BASIS})
        or checked_scope['allowed_command_ids']
        or checked_scope['network_targets']
    ):
        raise NativePolicyCompilationError('NATIVE_POLICY_SCOPE_UNSUPPORTED')
    _directory_pair(workspace, basis)
    checkpoint()
    try:
        with ExitStack() as held:
            actual_workspace = held.enter_context(
                LocalPathGuard(workspace.canonical_path, directory=True)
            )
            actual_basis = held.enter_context(LocalPathGuard(basis.canonical_path, directory=True))
            if actual_workspace.verify() != workspace or actual_basis.verify() != basis:
                raise NativePolicyCompilationError('NATIVE_POLICY_DIRECTORY_IDENTITIES_DIFFER')
            checkpoint()
            policy = NativeCodingPolicy(agent, _rules(basis, BASIS in references))
            result = ManagedNativePolicy(
                policy,
                checked_profile.sha256,
                _digest(checked_scope),
                tuple(sorted(references)),
                _digest(asdict(workspace)),
                _digest(asdict(basis)) if BASIS in references else None,
            )
            if actual_workspace.verify() != workspace or actual_basis.verify() != basis:
                raise NativePolicyCompilationError('NATIVE_POLICY_DIRECTORY_IDENTITIES_DIFFER')
            checkpoint()
            return result
    except PathBoundaryError as error:
        if getattr(error, 'retained_owner', None) is not None:
            raise
        raise NativePolicyCompilationError('NATIVE_POLICY_DIRECTORY_UNVERIFIED') from error


def read_managed_session_policy_input(connection, scope):
    from .task_start_session import StartSessionScope, SuccessorSessionScope

    if type(scope) not in (StartSessionScope, SuccessorSessionScope):
        raise NativePolicyCompilationError('NATIVE_POLICY_SESSION_SCOPE_REQUIRED')
    task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (scope.task_id,)).fetchone()
    session = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?', (scope.session_id, scope.task_id)
    ).fetchone()
    if (
        task is None
        or session is None
        or task['control_generation'] != scope.control_generation
        or task['workspace_id'] != scope.workspace_id
        or task['stop_requested_at'] is not None
        or session['instance_id'] != scope.instance_id
        or session['control_generation'] != scope.control_generation
        or session['role'] != (scope.role if type(scope) is SuccessorSessionScope else 'BACKEND')
        or session['status'] != 'PREPARING'
        or session['native_session_id'] is not None
    ):
        raise NativePolicyCompilationError('NATIVE_POLICY_SESSION_SOURCE_DIFFERS')
    profile = connection.execute(
        'SELECT * FROM code_execution_profile_versions WHERE id=?',
        (task['execution_profile_version_id'],),
    ).fetchone()
    grant = connection.execute(
        """SELECT * FROM code_authorizations WHERE id=? AND task_id=?
           AND profile_version_id=?""",
        (task['authorization_id'], task['id'], task['execution_profile_version_id']),
    ).fetchone()
    if profile is None or grant is None:
        raise NativePolicyCompilationError('NATIVE_POLICY_EFFECTIVE_PAIR_REQUIRED')
    if grant['status'] == 'BOUND_PENDING_APPLY':
        original = connection.execute(
            """SELECT o.expected_state_version FROM code_operations o
               JOIN code_operation_steps s ON s.operation_id=o.id AND s.step_no=5
               WHERE o.id=? AND o.task_id=? AND o.operation_type='START'
                 AND o.status='RUNNING' AND s.status='RUNNING'
                 AND o.session_id=? AND o.control_generation=?""",
            (scope.operation_id, scope.task_id, scope.session_id, scope.control_generation),
        ).fetchone()
        if (
            type(scope) is not StartSessionScope
            or original is None
            or original['expected_state_version'] + 2 != scope.state_version
            or scope.profile_id != profile['id']
            or scope.authorization_id != grant['id']
            or task['active_session_id'] is not None
            or task['status'] != 'PENDING'
        ):
            raise NativePolicyCompilationError('NATIVE_POLICY_PENDING_START_SOURCE_REQUIRED')
    elif grant['status'] != 'EFFECTIVE':
        raise NativePolicyCompilationError('NATIVE_POLICY_EFFECTIVE_PAIR_REQUIRED')
    content = stored_profile_content(profile)
    authorization = project_grant(grant)['scope']
    provenance = _digest(
        {
            'task': dict(task),
            'session': dict(session),
            'profile': content,
            'authorization': dict(grant),
        }
    )
    return content, authorization, provenance


def validate_managed_policy_evidence(value, profile, scope, workspace, agent):
    from backend.app.infrastructure.guard_task_basis_protocol import _hex
    from backend.app.shared.http_projection import exact

    fields = (
        'protocol_version',
        'resource_sha256',
        'profile_sha256',
        'authorization_scope_sha256',
        'read_roots',
        'workspace_sha256',
        'basis_sha256',
        'agent',
        'permission_sha256',
    )
    if type(agent) is not str or not agent or agent.strip() != agent:
        raise NativePolicyCompilationError('NATIVE_POLICY_EVIDENCE_AGENT_REQUIRED')
    try:
        proof = exact(value, fields)
    except (ValueError, TypeError) as error:
        raise NativePolicyCompilationError('NATIVE_POLICY_EVIDENCE_REQUIRED') from error
    expected = {
        'protocol_version': 'READ20-MANAGED-1',
        'resource_sha256': RESOURCE_SHA256,
        'profile_sha256': _digest(profile),
        'authorization_scope_sha256': _digest(scope),
        'read_roots': sorted(scope['read_roots']),
        'workspace_sha256': _digest(workspace),
        'agent': agent,
    }
    if any(proof[key] != item for key, item in expected.items()) or (
        not _hex(proof['permission_sha256'], 64)
        or (BASIS in scope['read_roots'] and not _hex(proof['basis_sha256'], 64))
        or (BASIS not in scope['read_roots'] and proof['basis_sha256'] is not None)
    ):
        raise NativePolicyCompilationError('NATIVE_POLICY_EVIDENCE_DIFFERS')
    return proof
