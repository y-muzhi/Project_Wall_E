"""One registered V2 POST identity for acceptance, receipts and original-key close."""

import re
from dataclasses import dataclass

from backend.app.infrastructure.idempotency import Scope, request_key
from backend.app.shared.validation import MAX_SAFE_INTEGER, decimal_integer


@dataclass(frozen=True)
class CommandRoute:
    module: str
    number: str
    path_template: str

    @property
    def capability_id(self) -> str:
        return f'APP-{self.module}-CMD-C{self.number}'

    def match(self, path: str) -> dict[str, int] | None:
        parts = re.split(r'(\{[a-z_]+\})', self.path_template)
        pattern = ''.join(
            f'(?P<{part[1:-1]}>[1-9][0-9]*)' if part.startswith('{') else re.escape(part)
            for part in parts
        )
        match = re.fullmatch(pattern, path)
        if match is None:
            return None
        return {name: decimal_integer(value, name) for name, value in match.groupdict().items()}


@dataclass(frozen=True)
class RegisteredCommand:
    route: CommandRoute
    path: str
    key: str

    @property
    def scope(self) -> Scope:
        return Scope(self.route.capability_id, 'POST ' + self.path, self.key)


def registered_command(method: object, path: object, key: object) -> RegisteredCommand:
    if method != 'POST' or type(path) is not str:
        raise ValueError('Only registered business POST identities are allowed')
    normalized_key = request_key(key)
    if key != normalized_key:
        raise ValueError('V2 requires a lowercase UUID v4 key')
    for route in COMMAND_ROUTES:
        if route.match(path) is not None:
            return RegisteredCommand(route, path, normalized_key)
    raise ValueError('The original command route is not registered')


# Static routes reviewed against the pinned design. GET and CONTROL_CLOSE are
# intentionally absent; closing a close action would recursively create intent.
COMMAND_ROUTES = (
    CommandRoute('CODE', '01', '/api/v1/code-repositories'),
    CommandRoute('CODE', '02', '/api/v1/code-repositories/{id}/refresh'),
    CommandRoute('CODE', '05', '/api/v1/code-repositories/{id}/snapshots'),
    CommandRoute('CODE', '07', '/api/v1/code-execution-profiles/{profile_id}/versions'),
    CommandRoute('CODE', '08', '/api/v1/code-check-sets/{check_set_id}/versions'),
    CommandRoute('CODE', '09', '/api/v1/code-execution-profiles'),
    CommandRoute('CODE', '10', '/api/v1/code-check-sets'),
    CommandRoute('CODE', '15', '/api/v1/code-authorizations'),
    CommandRoute('CODE', '32', '/api/v1/documents/{document_id}/code-tasks'),
    CommandRoute('CODE', '35', '/api/v1/code-tasks/{task_id}/start'),
    CommandRoute('CODE', '36', '/api/v1/code-tasks/{task_id}/resume'),
    CommandRoute('CODE', '37', '/api/v1/code-tasks/{task_id}/terminate'),
    CommandRoute('CODE', '38', '/api/v1/code-tasks/{task_id}/reconcile'),
    CommandRoute('CODE', '39', '/api/v1/code-tasks/{task_id}/configuration'),
    CommandRoute('CODE', '40', '/api/v1/code-tasks/{task_id}/budget'),
    CommandRoute('CODE', '46', '/api/v1/code-tasks/{task_id}/questions/{question_id}/responses'),
    CommandRoute(
        'CODE', '47', '/api/v1/code-tasks/{task_id}/permissions/{permission_id}/responses'
    ),
    CommandRoute('CODE', '48', '/api/v1/code-tasks/{task_id}/questions/{question_id}/handoff'),
    CommandRoute('CODE', '49', '/api/v1/code-tasks/{task_id}/handoffs/{handoff_id}/links'),
    CommandRoute('CODE', '50', '/api/v1/code-tasks/{task_id}/candidates'),
    CommandRoute(
        'CODE', '51', '/api/v1/code-tasks/{task_id}/candidates/{candidate_id}/verifications'
    ),
    CommandRoute('CODE', '58', '/api/v1/code-tasks/{task_id}/defects'),
    CommandRoute('CODE', '59', '/api/v1/code-tasks/{task_id}/repairs'),
    CommandRoute('CODE', '62', '/api/v1/code-tasks/{task_id}/delivery-plans'),
    CommandRoute('CODE', '64', '/api/v1/code-tasks/{task_id}/accept'),
    CommandRoute('CODE', '68', '/api/v1/code-tasks/{task_id}/testing-publication'),
    CommandRoute('CODE', '69', '/api/v1/code-tasks/{task_id}/test-reports'),
    CommandRoute('TEST', '01', '/api/v1/testing-profile-versions'),
    CommandRoute('TEST', '04', '/api/v1/testing-authorizations'),
    CommandRoute('TEST', '06', '/api/v1/test-plans'),
    CommandRoute('TEST', '09', '/api/v1/test-plans/{plan_id}/versions'),
    CommandRoute('TEST', '12', '/api/v1/test-plan-versions/{id}/draft'),
    CommandRoute('TEST', '13', '/api/v1/test-plan-versions/{id}/publish'),
    CommandRoute('TEST', '14', '/api/v1/test-plan-versions/{id}/revoke'),
    CommandRoute('TEST', '15', '/api/v1/test-plan-versions/{plan_version_id}/packs'),
    CommandRoute('TEST', '18', '/api/v1/test-pack-versions/{id}/seal'),
    CommandRoute('TEST', '19', '/api/v1/test-pack-versions/{id}/validations'),
    CommandRoute('TEST', '21', '/api/v1/test-pack-versions/{id}/publish'),
    CommandRoute('TEST', '22', '/api/v1/test-pack-versions/{id}/revoke'),
    CommandRoute('TEST', '23', '/api/v1/testing-tasks'),
    CommandRoute('TEST', '26', '/api/v1/testing-tasks/{testing_task_id}/draft-plan'),
    CommandRoute('TEST', '27', '/api/v1/testing-tasks/{testing_task_id}/assets'),
    CommandRoute('TEST', '28', '/api/v1/testing-tasks/{testing_task_id}/run'),
    CommandRoute('TEST', '29', '/api/v1/testing-tasks/{testing_task_id}/budget'),
    CommandRoute('TEST', '30', '/api/v1/testing-tasks/{testing_task_id}/resume'),
    CommandRoute('TEST', '31', '/api/v1/testing-tasks/{testing_task_id}/terminate'),
    CommandRoute('TEST', '32', '/api/v1/testing-tasks/{testing_task_id}/reconcile'),
    CommandRoute('TEST', '40', '/api/v1/testing-findings/{id}/review'),
)


REPOSITORY_OPERATIONS = {
    'APP-CODE-CMD-C01': 'REGISTER_REPOSITORY',
    'APP-CODE-CMD-C02': 'REFRESH_REPOSITORY',
    'APP-CODE-CMD-C05': 'REGISTER_BASE',
}


def validate_registered_success(command, data, code, http_status):
    """Only actual implemented business DTOs; never project arbitrary stored data."""
    if command.route.capability_id in REPOSITORY_OPERATIONS:
        if (
            code != 'OPERATION_ACCEPTED'
            or http_status != 202
            or type(data) is not dict
            or set(data) != {'resource_kind', 'resource_id', 'operation_id', 'operation_status'}
            or data['resource_kind'] != 'REPOSITORY'
            or data['operation_status'] != 'PENDING'
            or any(
                type(data[key]) is not int or not 1 <= data[key] <= MAX_SAFE_INTEGER
                for key in ('resource_id', 'operation_id')
            )
        ):
            raise ValueError('Original repository acceptance contract differs')
        return
    if command.route.capability_id in ('APP-CODE-CMD-C35', 'APP-CODE-CMD-C37'):
        starting = command.route.capability_id == 'APP-CODE-CMD-C35'
        from .initial_task_view import validate_stopped_task

        task_id = command.route.match(command.path)['task_id']
        if not starting and code == 'TASK_ALREADY_ENDED' and http_status == 200:
            validate_stopped_task(data, task_id, terminal=True)
        elif (
            code != 'OPERATION_ACCEPTED'
            or http_status != 202
            or type(data) is not dict
            or set(data)
            != {'task_id', 'operation_id', 'operation_status', 'task_status', 'state_version'}
            or data['operation_status'] != 'PENDING'
            or data['task_status'] != ('PENDING' if starting else 'STOPPING')
            or any(
                type(data[key]) is not int or not 1 <= data[key] <= MAX_SAFE_INTEGER
                for key in ('task_id', 'operation_id', 'state_version')
            )
            or data['task_id'] != task_id
        ):
            raise ValueError('Original task control receipt differs')
        return
    if command.route.capability_id in (
        'APP-TEST-CMD-C26',
        'APP-TEST-CMD-C28',
        'APP-TEST-CMD-C30',
        'APP-TEST-CMD-C32',
    ):
        if (
            code != 'OPERATION_ACCEPTED'
            or http_status != 202
            or type(data) is not dict
            or set(data) != {'testing_task_id', 'operation_id', 'state_version'}
            or data['testing_task_id'] != command.route.match(command.path)['testing_task_id']
            or any(
                type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER
                for value in data.values()
            )
        ):
            raise ValueError('Original Testing control receipt differs')
        return
    if command.route.capability_id == 'APP-CODE-CMD-C39':
        from .task_configuration_apply import configuration_receipt

        if code != 'OPERATION_ACCEPTED':
            raise ValueError('Original configuration result must be an acceptance')
        configuration_receipt(command, data, http_status)
        return
    if command.route.capability_id in ('APP-CODE-CMD-C62', 'APP-CODE-CMD-C64'):
        from .task_delivery_api import project_delivery_receipt

        if code != 'OPERATION_ACCEPTED':
            raise ValueError('Original delivery result must be an acceptance')
        project_delivery_receipt(command, data, http_status)
        return
    if command.route.capability_id == 'APP-CODE-CMD-C59':
        from .task_repairs import project_repair_receipt

        if code != 'OPERATION_ACCEPTED':
            raise ValueError('Original repair result must be an acceptance')
        project_repair_receipt(command, data, http_status)
        return
    if command.route.capability_id == 'APP-CODE-CMD-C58':
        owner = command.route.match(command.path)['task_id']
        if (
            code != 'CREATED'
            or http_status != 201
            or type(data) is not dict
            or set(data) != {'defect_id', 'task_id', 'candidate_id'}
            or data['task_id'] != owner
            or any(
                type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER
                for value in data.values()
            )
        ):
            raise ValueError('Original Coding defect receipt differs')
        return
    if command.route.capability_id == 'APP-CODE-CMD-C32':
        from .initial_task_view import validate_initial_task

        if code != 'CREATED' or http_status != 201 or type(data) is not dict:
            raise ValueError('Original task creation contract differs')
        validate_initial_task(data, command.route.match(command.path)['document_id'])
        return
    kind = {
        'APP-CODE-CMD-C07': 'EXECUTION_PROFILE_VERSION',
        'APP-CODE-CMD-C08': 'CHECK_SET_VERSION',
        'APP-CODE-CMD-C09': 'EXECUTION_PROFILE',
        'APP-CODE-CMD-C10': 'CHECK_SET',
        'APP-CODE-CMD-C15': 'AUTHORIZATION',
    }.get(command.route.capability_id)
    if kind is None:
        return
    if (
        code != 'CREATED'
        or http_status != 201
        or type(data) is not dict
        or set(data) != {'resource_kind', 'resource_id'}
        or data['resource_kind'] != kind
        or type(data['resource_id']) is not int
        or not 1 <= data['resource_id'] <= MAX_SAFE_INTEGER
    ):
        raise ValueError('Original configuration identity success contract differs')
