"""Fixed current-role check selection for an explicit original C39 proposal."""

import hashlib
from dataclasses import asdict

from backend.app.infrastructure.check_runner_bundle import valid_sha256
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_integer, strict_json_object

from .authorizations import project_grant
from .coding_check_plan import (
    CODING_STAGES,
    CodingCheckPlanError,
    read_profile_check_basis,
    validate_profile_check_selection,
)
from .coding_project_check_scope import (
    CodingProjectCheckAdmission,
    require_project_check_admissions,
)
from .task_role_chain import RoleChainUnavailable, current_role_chain

CHECK_CONFIGURATION_FIELDS = (
    'check_set_version_id',
    'check_set_sha256',
    'scope_stages',
    'selection_sha256',
    'admissions_sha256',
)


def _digest(value):
    return hashlib.sha256(canonical_input(value).encode()).hexdigest()


def _admission_facts(selection):
    value = asdict(selection)
    value['admission']['runtime_refs'] = list(selection.admission.runtime_refs)
    value['admission']['command']['argument_template'] = list(
        selection.admission.command.argument_template
    )
    return value


def observe_check_configuration(
    connection, catalog, task, profile_id, authorization_id, admissions, *, include_output=False
):
    """Validate a real unbound/pending proposal; never rewrite the task to test it."""
    profile = connection.execute(
        'SELECT * FROM code_execution_profile_versions WHERE id=?', (profile_id,)
    ).fetchone()
    grant_row = connection.execute(
        'SELECT * FROM code_authorizations WHERE id=?', (authorization_id,)
    ).fetchone()
    if profile is None or grant_row is None:
        raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
    grant = project_grant(grant_row)
    unbound = grant['task_id'] is None and grant['status'] == 'APPROVED_UNBOUND'
    pending = grant['task_id'] == task['id'] and grant['status'] in (
        'BOUND_PENDING_APPLY',
        'APPLY_UNKNOWN',
    )
    if grant['profile_version_id'] != profile_id or not (unbound or pending):
        raise CodingCheckPlanError('AUTHORIZATION_NOT_APPLICABLE')
    if type(admissions) is not tuple or any(
        type(row) is not CodingProjectCheckAdmission for row in admissions
    ):
        raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
    try:
        chain = current_role_chain(connection, task)
    except RoleChainUnavailable as error:
        raise CodingCheckPlanError('VERIFICATION_STAGE_NOT_READY') from error
    version, content, selected, definitions = validate_profile_check_selection(
        connection, catalog, task, profile, chain.stages, grant['scope']
    )
    prepared = require_project_check_admissions(selected, admissions, definitions=definitions)
    output = (
        {'max_output_bytes': effective_check_output_limit(profile, grant['scope'])}
        if include_output
        else {}
    )
    return {
        **output,
        'check_set_version_id': version['id'],
        'check_set_sha256': content.sha256,
        'scope_stages': list(chain.stages),
        'selection_sha256': _digest(selected),
        'admissions_sha256': _digest({'commands': [_admission_facts(row) for row in prepared]}),
    }


def check_configuration_changes(before, after, previous_scope, next_scope):
    output_changed = (
        before['limits']['max_check_output_bytes'],
        previous_scope['limits']['max_check_output_bytes'],
    ) != (
        after['limits']['max_check_output_bytes'],
        next_scope['limits']['max_check_output_bytes'],
    )
    return before['check_set_version_id'] != after['check_set_version_id'], output_changed


def effective_check_output_limit(profile, scope):
    limits = strict_json_object(profile['limits'])
    return strict_integer(
        min(limits['max_check_output_bytes'], scope['limits']['max_check_output_bytes']),
        'max_output_bytes',
    )


def validate_retained_check_configuration(connection, task_id, profile, scope, role, value):
    """Historical facts do not depend on a later live resource catalogue."""
    try:
        with_output = 'max_output_bytes' in value
        value = exact(
            value, (*CHECK_CONFIGURATION_FIELDS, *(('max_output_bytes',) if with_output else ()))
        )
        if with_output and (
            strict_integer(value['max_output_bytes'], 'max_output_bytes')
            != effective_check_output_limit(profile, scope)
        ):
            raise ValueError('Retained check output limit differs')
        strict_integer(value['check_set_version_id'], 'check_set_version_id')
        if (
            role not in CODING_STAGES
            or value['check_set_version_id'] != profile['check_set_version_id']
            or any(
                not valid_sha256(value[field])
                for field in ('check_set_sha256', 'selection_sha256', 'admissions_sha256')
            )
        ):
            raise ValueError('Retained Coding check configuration identity differs')
        stages = CODING_STAGES[: CODING_STAGES.index(role) + 1]
        if value['scope_stages'] != list(stages):
            raise ValueError('Retained Coding check stages differ')
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        if task is None:
            raise ValueError('Original check owner is missing')
        _, content, selected = read_profile_check_basis(connection, task, profile, stages)
        if value['check_set_sha256'] != content.sha256 or value['selection_sha256'] != _digest(
            selected
        ):
            raise ValueError('Retained Coding check selection differs')
    except (ValueError, TypeError, KeyError, CodingCheckPlanError) as error:
        raise StorageUnavailable('Original check configuration evidence differs') from error
    return value
