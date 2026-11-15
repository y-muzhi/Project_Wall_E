"""Immutable bindings for each registered project check in one original operation."""

from dataclasses import asdict, dataclass

from backend.app.infrastructure.check_runner_bundle import reference, valid_sha256
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guard_controller_binding import owner_epoch as require_owner_epoch
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.runtime_launch_journal import LaunchScope, _hex
from backend.app.infrastructure.windows_job import MAX_JOB_PROCESSES
from backend.app.infrastructure.windows_project_check_command import ProjectCheckCommand
from backend.app.infrastructure.windows_task_directories import ProjectCheckInput
from backend.app.shared.validation import strict_integer, strict_json_object

from .coding_check_plan import CodingCheckPlanError

_MAX_PROJECTS = 32


@dataclass(frozen=True)
class CodingProjectCheckAdmission:
    runner_ref: str
    runner_manifest_sha256: str
    runtime_refs: tuple[str, ...]
    command: ProjectCheckCommand
    active_process_limit: int
    job_memory_limit_bytes: int

    def __post_init__(self):
        reference(self.runner_ref)
        if (
            not valid_sha256(self.runner_manifest_sha256)
            or type(self.runtime_refs) is not tuple
            or len(set(self.runtime_refs)) != len(self.runtime_refs)
            or type(self.command) is not ProjectCheckCommand
            or self.command.purpose != 'CHECK'
        ):
            raise ValueError('Original Coding project check admission required')
        for ref in self.runtime_refs:
            reference(ref)
        strict_integer(self.active_process_limit, 'active_process_limit', maximum=MAX_JOB_PROCESSES)
        strict_integer(self.job_memory_limit_bytes, 'job_memory_limit_bytes')


@dataclass(frozen=True)
class CodingProjectCheckClaim:
    scope: LaunchScope
    check: ProjectCheckInput
    command_execution_id: int
    integrity_item_ids: tuple[int, ...]
    session_id: int
    state_version: int
    profile_version_id: int
    runner_manifest_sha256: str
    owner_epoch: str | None = None
    max_output_bytes: int | None = None

    def fixed(self):
        data = {**asdict(self), 'integrity_item_ids': list(self.integrity_item_ids)}
        if self.owner_epoch is None and self.max_output_bytes is None:
            del data['owner_epoch'], data['max_output_bytes']
        return canonical_input(data)

    @classmethod
    def load(cls, stored):
        try:
            data = strict_json_object(stored)
            data['scope'] = LaunchScope(**data['scope'])
            data['check'] = ProjectCheckInput(**data['check'])
            items = data['integrity_item_ids']
            if type(items) is not list or not items or len(items) != len(set(items)):
                raise ValueError('Original integrity item set differs')
            data['integrity_item_ids'] = tuple(strict_integer(item, 'item_id') for item in items)
            claim = cls(**data)
            for field in (
                'command_execution_id',
                'session_id',
                'state_version',
                'profile_version_id',
            ):
                strict_integer(getattr(claim, field), field)
            _hex(claim.runner_manifest_sha256)
            if claim.owner_epoch is not None or claim.max_output_bytes is not None:
                require_owner_epoch(claim.owner_epoch)
                strict_integer(claim.max_output_bytes, 'max_output_bytes')
            if claim.fixed() != stored:
                raise ValueError('Original project check claim differs')
        except (KeyError, TypeError, RuntimeError, ValueError) as error:
            raise StorageUnavailable('Original project check claim is unreadable') from error
        return claim


@dataclass(frozen=True)
class ProjectCommandSelection:
    check_id: str
    admission: CodingProjectCheckAdmission
    timeout_seconds: int


def require_project_check_admissions(selection, admissions, *, definitions=None):
    items = selection['items']
    if any(
        item['protected_input_refs']
        or item['evidence_rule']['kind'] not in ('PROCESS_EXIT', 'CONTENT_INTEGRITY')
        for item in items
    ):
        raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
    selected = []
    for item in items:
        if item['evidence_rule']['kind'] != 'PROCESS_EXIT':
            continue
        matches = [
            admission
            for admission in admissions
            if admission.runner_ref == item['runner_ref']
            and admission.command.command_id == item['command_id']
            and set(item['environment_refs']).issubset(admission.runtime_refs)
        ]
        if len(matches) != 1:
            raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
        admission = matches[0]
        if definitions is not None:
            declared = [row for row in definitions if row['command_id'] == item['command_id']]
            if len(declared) != 1 or ProjectCheckCommand.decode(declared[0]) != admission.command:
                raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
        selected.append(
            ProjectCommandSelection(
                item['check_id'],
                admission,
                min(item['timeout_seconds'], admission.command.timeout_seconds),
            )
        )
    integrity = [item for item in items if item['evidence_rule']['kind'] == 'CONTENT_INTEGRITY']
    runner_refs = {}
    for item in selected:
        admission = item.admission
        digest = runner_refs.setdefault(admission.runner_ref, admission.runner_manifest_sha256)
        if digest != admission.runner_manifest_sha256:
            raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
    if (
        not 1 <= len(selected) <= _MAX_PROJECTS
        or not integrity
        or any(
            not any(
                row.admission.runner_ref == item['runner_ref']
                and set(item['environment_refs']).issubset(row.admission.runtime_refs)
                for row in selected
            )
            for item in integrity
        )
    ):
        raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
    return tuple(selected)


def encode_check_claims(claims):
    if len(claims) == 1:
        return claims[0].fixed()
    return canonical_input(
        {'project_checks': [strict_json_object(claim.fixed()) for claim in claims]}
    )


def check_claims(raw):
    value = strict_json_object(raw)
    if 'project_checks' not in value:
        return (CodingProjectCheckClaim.load(raw),)
    rows = value['project_checks']
    if (
        set(value) != {'project_checks'}
        or type(rows) is not list
        or not 2 <= len(rows) <= _MAX_PROJECTS
    ):
        raise StorageUnavailable('Original project check group differs')
    claims = tuple(CodingProjectCheckClaim.load(canonical_input(row)) for row in rows)
    first = claims[0]
    if (
        len({claim.scope for claim in claims}) != len(claims)
        or len({claim.command_execution_id for claim in claims}) != len(claims)
        or len({claim.check.item_id for claim in claims}) != len(claims)
        or any(
            claim.scope.operation_id != first.scope.operation_id
            or claim.scope.step_no != first.scope.step_no
            or claim.scope.controller_ref != first.scope.controller_ref
            or claim.owner_epoch != first.owner_epoch
            or claim.owner_epoch is None
            or claim.max_output_bytes != first.max_output_bytes
            or claim.integrity_item_ids != first.integrity_item_ids
            or claim.session_id != first.session_id
            or claim.state_version != first.state_version
            or claim.profile_version_id != first.profile_version_id
            or claim.check.verification_id != first.check.verification_id
            or claim.check.candidate_id != first.check.candidate_id
            or claim.check.owner_id != first.check.owner_id
            or claim.check.control_generation != first.check.control_generation
            or claim.check.manifest_sha256 != first.check.manifest_sha256
            or claim.check.item_id in first.integrity_item_ids
            for claim in claims
        )
        or encode_check_claims(claims) != raw
    ):
        raise StorageUnavailable('Original project check group ownership differs')
    return claims
