"""Read one protected Testing CLI comparison after its original Job is closed."""

from backend.app.infrastructure.check_case_evidence import (
    CheckEvidenceUnknown,
    recover_cli_case,
)
from backend.app.infrastructure.check_case_pack import CheckCase
from backend.app.infrastructure.project_check_result import ProjectCheckDispatchResult
from backend.app.infrastructure.runtime_launch_journal import TestingLaunchScope


def original_cli_outcome(completed, scope, check, case, definition):
    """No result can be formed from candidate-authored frames or an unclosed Job."""
    if (
        type(completed) is not ProjectCheckDispatchResult
        or type(scope) is not TestingLaunchScope
        or type(case) is not CheckCase
        or len(case.steps) != 1
        or case.steps[0].op != 'RUN'
        or case.steps[0].operands[0] != definition.command_id
        or completed.result.scope != scope
        or completed.result.check != check
    ):
        raise CheckEvidenceUnknown('TESTING_CLI_ORIGINAL_SCOPE_DIFFERS')
    result = completed.result
    if not (result.result == 'PASSED' or result.reason_code == 'COMMAND_FAILED'):
        return None
    if (
        result.source_integrity != 'VERIFIED'
        or result.stdout is None
        or result.stderr is None
        or result.stop_receipt_sha256 is None
        or result.cleanup_ref is None
        or completed.prepared is None
        or completed.created is None
    ):
        raise CheckEvidenceUnknown('TESTING_CLI_ORIGINAL_OBSERVATION_REQUIRED')
    return recover_cli_case(
        case,
        exit_code=result.exit_code,
        stdout_byte_count=result.stdout.byte_count,
        stdout_sha256=result.stdout.sha256,
    )
