"""V2 immutable evidence and registered-operation SQL guards."""

from backend.app.code_tasks.operation_protocol import CODING_STEPS, RESOURCE_STEPS, TESTING_STEPS

from .schema_inspection import quote_identifier
from .schema_v20 import RELATIONAL_FIELDS
from .schema_v20_columns import COLUMNS

MUTABLE = {
    'code_tasks': 'execution_profile_version_id authorization_id budget_limit_cny status phase resume_phase state_version control_generation workspace_id active_session_id current_candidate_id current_verification_id current_test_report_id current_delivery_plan_id current_delivery_id stop_requested_at stopped_at updated_at started_at ended_at last_observed_at',
    'code_candidates': 'published_for_testing_at publication_operation_id',
    'code_repairs': 'status result_candidate_id ended_at failure_code',
    'code_deliveries': 'status git_write_status postcheck_status current_window_id commit_input_ref commit_input_sha256 planned_commit_oid observed_target_commit delivered_at last_reconciled_at failure_code',
    'code_workspaces': 'status ready_at',
    'code_instances': 'status process_identity runtime_binding connection_ref native_storage_ref ready_at stopped_at',
    'code_sessions': 'status native_session_id native_message_id gateway_credential_ref model_window last_observed_at',
    'code_commands': 'status session_id verification_item_id process_identity runtime_binding exit_code started_at ended_at',
    'code_operations': 'status session_id started_at ended_at failure_code',
    'code_operation_steps': 'status external_identity result_ref started_at ended_at last_observed_at',
    'code_waiting_items': 'status resolved_at resolution_ref',
    'code_authorizations': 'task_id status',
    'code_configuration_applications': 'status applied_at effective_evidence',
    'code_verifications': 'status stop_status cleanup_status source_integrity_status ended_at',
    'code_verification_items': 'command_execution_id result reason_code expected_case_count executed_case_count passed_case_count failed_case_count reused_from_item_id evidence_summary started_at ended_at',
    'code_questions': 'status resolved_at',
    'code_permissions': 'status resolved_at',
    'code_task_reservations': 'status settled_cny settled_at settlement_basis',
    'testing_tasks': 'plan_version_id test_pack_version_id authorization_id budget_limit_cny status phase state_version control_generation current_verification_id draft_plan_operation_id active_operation_id report_id stop_requested_at stopped_at ended_at',
    'testing_plan_versions': 'behaviors cases unresolved_questions status state_version published_at revoked_at revocation_reason',
    'testing_pack_versions': 'check_set_version_id content_ref sha256 status validation_id state_version published_at revoked_at revocation_reason',
    'testing_pack_validations': 'result ended_at',
    'testing_findings': 'classification state_version review_reason review_operation_id',
    'testing_authorizations': 'testing_task_id validation_id status',
    'model_usage_evidence': 'status',
}
WRITE_ONCE = {
    'code_task_reservations': 'settled_cny settled_at settlement_basis',
    'testing_plan_versions': 'published_at revoked_at revocation_reason',
    'testing_pack_versions': 'published_at revoked_at revocation_reason',
    'code_candidates': 'published_for_testing_at publication_operation_id',
    'code_deliveries': 'commit_input_ref commit_input_sha256 planned_commit_oid delivered_at',
    'code_workspaces': 'ready_at',
    'code_instances': 'process_identity runtime_binding connection_ref native_storage_ref ready_at stopped_at',
    'code_sessions': 'native_session_id gateway_credential_ref',
    'code_commands': 'process_identity runtime_binding started_at ended_at exit_code',
    'code_operation_steps': 'external_identity result_ref',
    'code_authorizations': 'task_id',
    'testing_authorizations': 'testing_task_id validation_id',
    'testing_tasks': 'report_id',
}


def guard(name: str, event: str, table: str, condition: str, reason: str) -> str:
    return (
        f'CREATE TRIGGER {quote_identifier(name)} BEFORE {event} ON {quote_identifier(table)}\n'
        f"WHEN {condition}\nBEGIN SELECT RAISE(ABORT,'{reason}'); END;\n"
    )


def changed(fields: set[str]) -> str:
    return (
        ' OR '.join(
            f'NEW.{quote_identifier(field)} IS NOT OLD.{quote_identifier(field)}'
            for field in sorted(fields)
        )
        or '0'
    )


def physical_fields(table: str) -> set[str]:
    owner, columns = COLUMNS[table]
    return {column[0] for column in columns if f'{owner}.{column[0]}' not in RELATIONAL_FIELDS}


def immutable_triggers() -> tuple[str, ...]:
    statements = []
    for table in COLUMNS:
        if table in ('llm_uses', 'code_delivery_repository_locks'):
            continue
        fields = physical_fields(table)
        frozen = fields - set(MUTABLE.get(table, '').split())
        statements.append(
            guard(
                table + '_identity_fixed',
                'UPDATE',
                table,
                changed(frozen),
                'IMMUTABLE_RECORD_INPUT',
            )
        )
        statements.append(
            guard(table + '_history_retained', 'DELETE', table, '1', 'HISTORY_MUST_BE_RETAINED')
        )
        for field in WRITE_ONCE.get(table, '').split():
            statements.append(
                guard(
                    table + '_' + field + '_fixed',
                    'UPDATE',
                    table,
                    f'OLD.{quote_identifier(field)} IS NOT NULL AND NEW.{quote_identifier(field)} IS NOT OLD.{quote_identifier(field)}',
                    'ORIGINAL_FACT_IS_FIXED',
                )
            )
    for table in ('code_tasks', 'testing_tasks'):
        fields = physical_fields(table) - {'last_observed_at', 'updated_at'}
        statements.append(
            guard(
                table + '_terminal_fixed',
                'UPDATE',
                table,
                "OLD.status IN ('COMPLETED','TERMINATED') AND (" + changed(fields) + ')',
                'TASK_ENDED',
            )
        )
    for table in ('testing_plan_versions', 'testing_pack_versions'):
        allowed = {
            'status',
            'state_version',
            'revoked_at',
            'revocation_reason',
            'published_at',
            'validation_id',
        }
        fields = physical_fields(table) - allowed
        frozen_status = (
            "('PUBLISHED','REVOKED')"
            if table == 'testing_plan_versions'
            else "('SEALED','PUBLISHED','REVOKED')"
        )
        statements.append(
            guard(
                table + '_published_input_fixed',
                'UPDATE',
                table,
                f'OLD.status IN {frozen_status} AND (' + changed(fields) + ')',
                'PUBLISHED_RESOURCE_IS_FIXED',
            )
        )
    return tuple(statements)


def step_registration_trigger() -> str:
    alternatives = []
    for owner, registry in (
        ('CODING', CODING_STEPS),
        ('TESTING', TESTING_STEPS),
        ('RESOURCE', RESOURCE_STEPS),
    ):
        owner_check = {
            'CODING': 'o.task_id IS NOT NULL AND o.testing_task_id IS NULL',
            'TESTING': 'o.testing_task_id IS NOT NULL AND o.task_id IS NULL',
            'RESOURCE': 'o.task_id IS NULL AND o.testing_task_id IS NULL',
        }[owner]
        for operation, steps in registry.items():
            for number, step in enumerate(steps, 1):
                alternatives.append(
                    f"({owner_check} AND o.operation_type='{operation}' AND NEW.step_no={number} AND NEW.step_type='{step}')"
                )
    condition = (
        'NOT EXISTS(SELECT 1 FROM code_operations o WHERE o.id=NEW.operation_id AND ('
        + ' OR '.join(alternatives)
        + '))'
    )
    condition += ' OR (NEW.step_no>1 AND NOT EXISTS(SELECT 1 FROM code_operation_steps p WHERE p.operation_id=NEW.operation_id AND p.step_no=NEW.step_no-1))'
    return guard(
        'code_step_registration',
        'INSERT',
        'code_operation_steps',
        condition,
        'UNREGISTERED_OPERATION_STEP',
    )


def legacy_guard_triggers() -> tuple[str, ...]:
    return (
        guard(
            'idempotency_v2_unknown_retained',
            'DELETE',
            'idempotency_records',
            "OLD.status='PROCESSING' AND (OLD.capability_id GLOB 'APP-CODE-CMD-C[0-9][0-9]' OR OLD.capability_id GLOB 'APP-TEST-CMD-C[0-9][0-9]')",
            'UNKNOWN_RECEIPT_MUST_BE_RETAINED',
        ),
        guard(
            'idempotency_v2_terminal_fixed',
            'UPDATE',
            'idempotency_records',
            "OLD.status IN ('REJECTED','CLOSED')",
            'IMMUTABLE_TERMINAL_RECEIPT',
        ),
        guard(
            'idempotency_v2_terminal_retained',
            'DELETE',
            'idempotency_records',
            "OLD.status IN ('REJECTED','CLOSED')",
            'TERMINAL_RECEIPT_MUST_BE_RETAINED',
        ),
        guard(
            'llm_v2_identity_fixed',
            'UPDATE',
            'llm_uses',
            changed(
                {
                    'execution_session_id',
                    'testing_task_id',
                    'operation_id',
                    'gateway_request_id',
                    'call_no',
                    'attempt_no',
                    'retry_of_llm_use_id',
                    'protocol_version',
                    'call_purpose',
                    'source_evidence_ref',
                }
            ),
            'IMMUTABLE_CALL_OWNER',
        ),
        guard(
            'llm_v2_evidence_retained',
            'DELETE',
            'llm_uses',
            'OLD.guide_run_id IS NULL',
            'CALL_EVIDENCE_MUST_BE_RETAINED',
        ),
    )


def ownership_triggers() -> tuple[str, ...]:
    rules = {
        'code_candidates': (
            'NOT EXISTS(SELECT 1 FROM code_tasks t WHERE t.id=NEW.task_id AND t.base_snapshot_id=NEW.base_snapshot_id)',
            'CANDIDATE_BASE_MISMATCH',
        ),
        'code_snapshots': (
            (
                'NOT EXISTS(SELECT 1 FROM code_repositories r WHERE r.id=NEW.repository_id '
                "AND length(NEW.commit_oid)=CASE r.object_format WHEN 'sha1' THEN 40 WHEN 'sha256' THEN 64 END "
                'AND length(NEW.content_tree_oid)=length(NEW.commit_oid))'
            ),
            'REPOSITORY_OBJECT_FORMAT_MISMATCH',
        ),
        'code_acceptances': (
            (
                'NOT EXISTS(SELECT 1 FROM testing_reports r WHERE r.id=NEW.test_report_id '
                'AND NEW.manual_risk_accepted=(json_array_length(r.manual_coverage_ids)>0))'
            ),
            'MANUAL_RISK_ACCEPTANCE_MISMATCH',
        ),
        'testing_tasks': (
            (
                'NOT EXISTS(SELECT 1 FROM testing_authorizations a WHERE a.id=NEW.authorization_id '
                'AND a.profile_version_id=NEW.profile_version_id AND ('
                "(NEW.kind='PRODUCT' AND a.scope_kind='TASK' AND a.testing_task_id=NEW.id AND a.validation_id IS NULL) "
                "OR (NEW.kind='PACK_VALIDATION' AND NEW.purpose='PACK_VALIDATION' AND NEW.budget_limit_cny='0.000000' "
                "AND a.scope_kind='PACK_VALIDATION' AND a.testing_task_id IS NULL AND a.validation_id=NEW.validation_id "
                'AND EXISTS(SELECT 1 FROM testing_pack_validations v WHERE v.id=NEW.validation_id '
                'AND v.profile_version_id=NEW.profile_version_id AND v.test_pack_version_id=NEW.test_pack_version_id))))'
            ),
            'TESTING_AUTHORIZATION_OWNER_MISMATCH',
        ),
        'code_task_reservations': (
            (
                'NOT EXISTS(SELECT 1 FROM llm_uses u LEFT JOIN code_sessions s ON s.id=u.execution_session_id '
                'WHERE u.id=NEW.llm_use_id AND ((NEW.task_id IS NOT NULL AND s.task_id=NEW.task_id AND u.testing_task_id IS NULL) '
                'OR (NEW.testing_task_id IS NOT NULL AND u.testing_task_id=NEW.testing_task_id AND u.execution_session_id IS NULL)))'
            ),
            'CALL_RESERVATION_OWNER_MISMATCH',
        ),
        'llm_uses': (
            (
                '(NEW.execution_session_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM code_operations o '
                'JOIN code_sessions s ON s.id=NEW.execution_session_id WHERE o.id=NEW.operation_id '
                'AND o.task_id=s.task_id AND o.testing_task_id IS NULL))'
                ' OR (NEW.testing_task_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM code_operations o WHERE '
                'o.id=NEW.operation_id AND o.testing_task_id=NEW.testing_task_id AND o.task_id IS NULL))'
                ' OR (NEW.retry_of_llm_use_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM llm_uses p WHERE '
                'p.id=NEW.retry_of_llm_use_id AND p.execution_session_id IS NEW.execution_session_id '
                'AND p.testing_task_id IS NEW.testing_task_id AND p.call_no<NEW.call_no))'
            ),
            'CALL_OPERATION_OWNER_MISMATCH',
        ),
    }
    statements = []
    for table, (condition, reason) in rules.items():
        for event in ('INSERT', 'UPDATE'):
            statements.append(
                guard(table + '_owner_' + event.lower(), event, table, condition, reason)
            )
    return tuple(statements)


def source_reference_triggers() -> tuple[str, ...]:
    sources = {
        'OPERATION': 'SELECT 1 FROM code_operations s WHERE s.id=NEW.source_id AND s.task_id=NEW.task_id',
        'COMMAND': 'SELECT 1 FROM code_commands s WHERE s.id=NEW.source_id AND s.task_id=NEW.task_id',
        'QUESTION': 'SELECT 1 FROM code_questions s WHERE s.id=NEW.source_id AND s.task_id=NEW.task_id',
        'PERMISSION': 'SELECT 1 FROM code_permissions s WHERE s.id=NEW.source_id AND s.task_id=NEW.task_id',
        'LLM_USE': 'SELECT 1 FROM llm_uses u JOIN code_sessions s ON s.id=u.execution_session_id WHERE u.id=NEW.source_id AND s.task_id=NEW.task_id',
    }
    invalid = ' OR '.join(
        f"(NEW.source_kind='{kind}' AND NOT EXISTS({query}))" for kind, query in sources.items()
    )
    statements = [
        guard(
            'code_record_source_fixed',
            'INSERT',
            'code_execution_records',
            invalid,
            'OBSERVATION_SOURCE_OWNER_MISMATCH',
        )
    ]
    for table in ('code_operations', 'code_commands', 'code_repairs'):
        statements.append(
            guard(
                table + '_terminal_status_fixed',
                'UPDATE',
                table,
                "OLD.status IN ('SUCCEEDED','FAILED','CANCELLED') AND NEW.status IS NOT OLD.status",
                'TERMINAL_OPERATION_IS_FIXED',
            )
        )
    return tuple(statements)


def verification_handoff_triggers() -> tuple[str, ...]:
    invalid = (
        "NEW.owner_kind='CODING' AND ("
        'NOT EXISTS(SELECT 1 FROM code_candidates c WHERE c.id=NEW.candidate_id AND c.task_id=NEW.task_id AND c.role=NEW.role)'
        ' OR NOT EXISTS(SELECT 1 FROM code_check_set_versions s JOIN code_execution_profile_versions p '
        'ON p.id=NEW.profile_version_id WHERE s.id=NEW.check_set_version_id '
        "AND p.check_set_version_id=s.id AND s.owner_module='CODING')"
        ' OR (NEW.backend_handoff_operation_id IS NOT NULL AND NOT EXISTS('
        'SELECT 1 FROM code_operations o WHERE o.id=NEW.backend_handoff_operation_id AND o.task_id=NEW.task_id '
        "AND o.operation_type='HANDOFF_ROLE' AND o.status='SUCCEEDED'))"
        ' OR (NEW.frontend_handoff_operation_id IS NOT NULL AND NOT EXISTS('
        'SELECT 1 FROM code_operations o WHERE o.id=NEW.frontend_handoff_operation_id AND o.task_id=NEW.task_id '
        "AND o.operation_type='HANDOFF_ROLE' AND o.status='SUCCEEDED'))"
        ' OR (NEW.frontend_handoff_operation_id IS NOT NULL AND NOT EXISTS('
        'SELECT 1 FROM code_operations b JOIN code_operations f ON f.id=NEW.frontend_handoff_operation_id '
        'WHERE b.id=NEW.backend_handoff_operation_id AND b.id<>f.id AND b.created_at<=f.created_at)))'
    )
    return tuple(
        guard(
            'code_verification_handoff_' + event.lower(),
            event,
            'code_verifications',
            invalid,
            'VERIFICATION_STAGE_NOT_READY',
        )
        for event in ('INSERT', 'UPDATE')
    )


def resource_operation_triggers() -> tuple[str, ...]:
    targets = {
        'TASK': 'code_tasks',
        'TESTING_TASK': 'testing_tasks',
        'TEST_PLAN': 'testing_plans',
        'TEST_PLAN_VERSION': 'testing_plan_versions',
        'TEST_PACK_VERSION': 'testing_pack_versions',
        'TEST_PROFILE_VERSION': 'testing_profile_versions',
        'TEST_AUTHORIZATION': 'testing_authorizations',
        'TEST_REPORT': 'testing_reports',
        'TESTING_FINDING': 'testing_findings',
        'REPOSITORY': 'code_repositories',
        'SNAPSHOT': 'code_snapshots',
        'EXECUTION_PROFILE': 'code_execution_profiles',
        'EXECUTION_PROFILE_VERSION': 'code_execution_profile_versions',
        'CHECK_SET': 'code_check_sets',
        'CHECK_SET_VERSION': 'code_check_set_versions',
        'AUTHORIZATION': 'code_authorizations',
    }
    reservation = (
        "NEW.operation_type='REGISTER_REPOSITORY' AND NEW.task_id IS NULL "
        'AND NEW.testing_task_id IS NULL AND NEW.session_id IS NULL '
        'AND NEW.control_generation IS NULL AND NEW.expected_state_version IS NULL '
        "AND NEW.status='PENDING' "
        "AND EXISTS(SELECT 1 FROM sequences q WHERE q.entity_kind='CodeRepository' AND q.last_value=NEW.resource_id) "
        "AND json_type(NEW.fixed_input,'$.name')='text' "
        "AND json_type(NEW.fixed_input,'$.root_path')='text' "
        'AND (SELECT count(*) FROM json_each(NEW.fixed_input))=2 '
        'AND EXISTS(SELECT 1 FROM idempotency_records i '
        "WHERE i.capability_id='APP-CODE-CMD-C01' "
        "AND i.target_identity='POST /api/v1/code-repositories' "
        "AND i.idempotency_key=NEW.idempotency_key AND i.status='PROCESSING' "
        'AND i.business_input_json=NEW.fixed_input)'
    )
    clauses = []
    for kind, table in targets.items():
        absent = f"NEW.resource_kind='{kind}' AND NOT EXISTS(SELECT 1 FROM {table} s WHERE s.id=NEW.resource_id)"
        if kind == 'REPOSITORY':
            absent += ' AND NOT COALESCE((' + reservation + '),0)'
        clauses.append('(' + absent + ')')
    invalid = ' OR '.join(clauses)
    return (
        guard(
            'code_operation_resource_exists',
            'INSERT',
            'code_operations',
            invalid,
            'OPERATION_RESOURCE_MISSING',
        ),
    )


def waiting_source_triggers() -> tuple[str, ...]:
    shared = 's.task_id IS NEW.task_id AND s.testing_task_id IS NEW.testing_task_id'
    sources = {
        'OPERATION': f'SELECT 1 FROM code_operations s WHERE s.id=NEW.source_id AND {shared}',
        'QUESTION': 'SELECT 1 FROM code_questions s WHERE s.id=NEW.source_id AND s.task_id=NEW.task_id AND NEW.testing_task_id IS NULL',
        'PERMISSION': 'SELECT 1 FROM code_permissions s WHERE s.id=NEW.source_id AND s.task_id=NEW.task_id AND NEW.testing_task_id IS NULL',
        'VERIFICATION_ITEM': 'SELECT 1 FROM code_verification_items i JOIN code_verifications s ON s.id=i.verification_id '
        f'WHERE i.id=NEW.source_id AND {shared}',
        'LLM_USE': 'SELECT 1 FROM llm_uses u LEFT JOIN code_sessions s ON s.id=u.execution_session_id '
        'WHERE u.id=NEW.source_id AND ((NEW.task_id IS NOT NULL AND s.task_id=NEW.task_id) '
        'OR (NEW.testing_task_id IS NOT NULL AND u.testing_task_id=NEW.testing_task_id))',
        'DELIVERY': 'SELECT 1 FROM code_deliveries s WHERE s.id=NEW.source_id AND s.task_id=NEW.task_id AND NEW.testing_task_id IS NULL',
    }
    invalid = ' OR '.join(
        f"(NEW.source_kind='{kind}' AND NOT EXISTS({query}))" for kind, query in sources.items()
    )
    return (
        guard(
            'code_waiting_source_exists',
            'INSERT',
            'code_waiting_items',
            invalid,
            'WAITING_SOURCE_OWNER_MISMATCH',
        ),
    )


def defect_reference_triggers() -> tuple[str, ...]:
    sources = {
        'OPERATION': 'SELECT 1 FROM code_operations s WHERE s.id=NEW.source_id AND s.task_id=d.task_id',
        'COMMAND': 'SELECT 1 FROM code_commands s WHERE s.id=NEW.source_id AND s.task_id=d.task_id',
        'QUESTION': 'SELECT 1 FROM code_questions s WHERE s.id=NEW.source_id AND s.task_id=d.task_id',
        'VERIFICATION_ITEM': 'SELECT 1 FROM code_verification_items i JOIN code_verifications s ON s.id=i.verification_id WHERE i.id=NEW.source_id AND s.task_id=d.task_id',
        'LLM_USE': 'SELECT 1 FROM llm_uses u JOIN code_sessions s ON s.id=u.execution_session_id WHERE u.id=NEW.source_id AND s.task_id=d.task_id',
    }
    valid = ' OR '.join(
        f"(NEW.kind='{kind}' AND EXISTS({query}))" for kind, query in sources.items()
    )
    condition = (
        'NOT EXISTS(SELECT 1 FROM code_defects d WHERE d.id=NEW.defect_id AND (' + valid + '))'
    )
    condition += ' OR (NEW.ordinal>1 AND NOT EXISTS(SELECT 1 FROM code_defect_evidence_refs p WHERE p.defect_id=NEW.defect_id AND p.ordinal=NEW.ordinal-1))'
    basis = (
        'NOT EXISTS(SELECT 1 FROM revisions r WHERE r.id=NEW.basis_revision_id AND r.document_id=NEW.basis_document_id '
        "AND instr(r.markdown_snapshot,json_extract(NEW.basis_ref,'$.quote'))>0 AND ("
        'EXISTS(SELECT 1 FROM code_tasks t WHERE t.id=NEW.task_id AND t.document_id=r.document_id AND t.design_revision_id=r.id)'
        ' OR EXISTS(SELECT 1 FROM code_task_materials m WHERE m.task_id=NEW.task_id AND m.document_id=r.document_id AND m.revision_id=r.id)))'
    )
    return (
        guard(
            'code_defect_evidence_owner',
            'INSERT',
            'code_defect_evidence_refs',
            condition,
            'DEFECT_EVIDENCE_OWNER_MISMATCH',
        ),
        guard('code_defect_fixed_basis', 'INSERT', 'code_defects', basis, 'BASIS_REF_INVALID'),
    )
