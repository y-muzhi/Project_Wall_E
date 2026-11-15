"""V2 physical references and row invariants, shared by fresh and upgrade DDL."""

from .schema_v20_columns import COLUMNS
from .schema_inspection import quote_identifier

COMMON_REFERENCES = {
    'requirement_id': 'requirements',
    'document_id': 'requirement_documents',
    'design_revision_id': 'revisions',
    'revision_id': 'revisions',
    'repository_id': 'code_repositories',
    'base_snapshot_id': 'code_snapshots',
    'task_id': 'code_tasks',
    'testing_task_id': 'testing_tasks',
    'workspace_id': 'code_workspaces',
    'instance_id': 'code_instances',
    'session_id': 'code_sessions',
    'active_session_id': 'code_sessions',
    'candidate_id': 'code_candidates',
    'current_candidate_id': 'code_candidates',
    'parent_candidate_id': 'code_candidates',
    'source_candidate_id': 'code_candidates',
    'result_candidate_id': 'code_candidates',
    'snapshot_id': 'code_snapshots',
    'operation_id': 'code_operations',
    'capture_operation_id': 'code_operations',
    'registration_operation_id': 'code_operations',
    'publication_operation_id': 'code_operations',
    'backend_handoff_operation_id': 'code_operations',
    'frontend_handoff_operation_id': 'code_operations',
    'draft_plan_operation_id': 'code_operations',
    'active_operation_id': 'code_operations',
    'review_operation_id': 'code_operations',
    'execution_profile_version_id': 'code_execution_profile_versions',
    'effective_profile_version_id': 'code_execution_profile_versions',
    'old_profile_version_id': 'code_execution_profile_versions',
    'new_profile_version_id': 'code_execution_profile_versions',
    'config_version_id': 'code_execution_profile_versions',
    'testing_profile_version_id': 'testing_profile_versions',
    'check_set_version_id': 'code_check_set_versions',
    'check_set_id': 'code_check_sets',
    'verification_id': 'code_verifications',
    'current_verification_id': 'code_verifications',
    'verification_item_id': 'code_verification_items',
    'item_id': 'code_verification_items',
    'reused_from_item_id': 'code_verification_items',
    'environment_record_id': 'code_environment_records',
    'effective_config_application_id': 'code_configuration_applications',
    'command_id': 'code_commands',
    'command_execution_id': 'code_commands',
    'delivery_plan_id': 'code_delivery_plans',
    'current_delivery_plan_id': 'code_delivery_plans',
    'delivery_id': 'code_deliveries',
    'current_delivery_id': 'code_deliveries',
    'acceptance_id': 'code_acceptances',
    'current_window_id': 'code_delivery_windows',
    'test_report_id': 'testing_reports',
    'current_test_report_id': 'testing_reports',
    'report_id': 'testing_reports',
    'testing_finding_id': 'testing_findings',
    'plan_id': 'testing_plans',
    'plan_version_id': 'testing_plan_versions',
    'test_pack_version_id': 'testing_pack_versions',
    'validation_id': 'testing_pack_validations',
    'test_report_id': 'testing_reports',
    'previous_testing_task_id': 'testing_tasks',
    'question_id': 'code_questions',
    'handoff_id': 'code_question_handoffs',
    'guide_run_id': 'guide_runs',
    'message_id': 'conversation_messages',
    'llm_use_id': 'llm_uses',
    'price_version_id': 'model_price_versions',
    'defect_id': 'code_defects',
    'repair_id': 'code_repairs',
}
UNIQUE_FIELDS = {
    'code_repositories': [('git_common_dir',)],
    'code_snapshots': [('registration_operation_id',), ('repository_id', 'retention_ref')],
    'code_candidates': [('capture_operation_id',), ('publication_operation_id',)],
    'code_workspaces': [('task_id',)],
    'code_deliveries': [('acceptance_id',)],
    'code_delivery_windows': [('delivery_id', 'operation_id')],
    'code_execution_profile_versions': [('profile_id', 'version')],
    'code_check_set_versions': [('check_set_id', 'version')],
    'code_verification_items': [('verification_id', 'check_id')],
    'code_questions': [('instance_id', 'session_id', 'native_question_id')],
    'code_permissions': [('instance_id', 'session_id', 'native_permission_id')],
    'code_task_reservations': [('llm_use_id',)],
    'model_usage_evidence': [('source_ref', 'external_evidence_id')],
    'testing_plan_versions': [('plan_id', 'version')],
    'testing_pack_versions': [('plan_version_id', 'version')],
    'testing_reports': [('testing_task_id',), ('verification_id',)],
    'testing_profile_versions': [('name', 'version')],
}
ROW_CHECKS = {
    'code_tasks': [
        "status<>'WAITING' OR resume_phase IS NOT NULL",
        "status<>'STOPPING' OR stop_requested_at IS NOT NULL",
        "status<>'TERMINATED' OR (stopped_at IS NOT NULL AND ended_at IS NOT NULL)",
        "status<>'COMPLETED' OR (ended_at IS NOT NULL AND phase='FINISHED')",
        'stopped_at IS NULL OR (stop_requested_at IS NOT NULL AND stopped_at>=stop_requested_at)',
    ],
    'code_snapshots': [
        "retention_ref='refs/walle/baselines/'||id",
        'created_at>=registered_at',
    ],
    'code_candidates': [
        '(published_for_testing_at IS NULL)=(publication_operation_id IS NULL)',
        'created_at>=captured_at',
    ],
    'code_operations': [
        "(resource_kind='TASK' AND task_id IS NOT NULL AND testing_task_id IS NULL AND resource_id=task_id AND expected_state_version IS NOT NULL AND control_generation IS NOT NULL)"
        " OR (resource_kind='TESTING_TASK' AND testing_task_id IS NOT NULL AND task_id IS NULL AND resource_id=testing_task_id AND expected_state_version IS NOT NULL AND control_generation IS NOT NULL)"
        " OR (resource_kind NOT IN ('TASK','TESTING_TASK') AND task_id IS NULL AND testing_task_id IS NULL AND control_generation IS NULL)",
    ],
    'code_execution_records': ['(source_kind IS NULL)=(source_id IS NULL)'],
    'code_runtime_observations': [
        "result<>'VERIFIED' OR json_array_length(reason_codes)=0",
        "(instance_id IS NOT NULL OR command_id IS NOT NULL) OR kind IN ('STOP','CLEANUP')",
    ],
    'code_commands': [
        '(task_id IS NULL)=(config_version_id IS NULL)',
        '(testing_task_id IS NULL)=(testing_profile_version_id IS NULL)',
    ],
    'code_verifications': [
        '(candidate_id IS NULL)<>(snapshot_id IS NULL)',
        "(owner_kind='CODING' AND task_id IS NOT NULL AND testing_task_id IS NULL AND candidate_id IS NOT NULL AND profile_version_id IS NOT NULL AND testing_profile_version_id IS NULL AND role IS NOT NULL AND purpose='HANDOFF')"
        " OR (owner_kind='TESTING' AND testing_task_id IS NOT NULL AND task_id IS NULL AND profile_version_id IS NULL AND testing_profile_version_id IS NOT NULL AND role IS NULL AND backend_handoff_operation_id IS NULL AND frontend_handoff_operation_id IS NULL AND purpose IN ('DIAGNOSTIC','ACCEPTANCE','PACK_VALIDATION'))",
    ],
    'code_verification_items': [
        "(evidence_kind='CONTROLLED_CASES' AND expected_case_count IS NOT NULL AND executed_case_count IS NOT NULL AND passed_case_count IS NOT NULL AND failed_case_count IS NOT NULL AND executed_case_count=passed_case_count+failed_case_count AND executed_case_count<=expected_case_count)"
        " OR (evidence_kind<>'CONTROLLED_CASES' AND expected_case_count IS NULL AND executed_case_count IS NULL AND passed_case_count IS NULL AND failed_case_count IS NULL)",
        "result<>'PASSED' OR evidence_kind<>'CONTROLLED_CASES' OR (executed_case_count=expected_case_count AND expected_case_count>0)",
    ],
    'testing_tasks': [
        "(target_kind='CANDIDATE' AND candidate_id IS NOT NULL AND snapshot_id IS NULL) OR (target_kind='SNAPSHOT' AND snapshot_id IS NOT NULL AND candidate_id IS NULL)",
        "(kind='PACK_VALIDATION')=(validation_id IS NOT NULL)",
        '(plan_version_id IS NULL)=(test_pack_version_id IS NULL)',
        "status<>'STOPPING' OR stop_requested_at IS NOT NULL",
        "status<>'TERMINATED' OR (stopped_at IS NOT NULL AND ended_at IS NOT NULL)",
        "status<>'COMPLETED' OR (report_id IS NOT NULL AND ended_at IS NOT NULL AND phase='FINISHED')",
    ],
    'testing_authorizations': [
        (
            "(scope_kind='TASK' AND validation_id IS NULL) OR "
            "(scope_kind='PACK_VALIDATION' AND testing_task_id IS NULL AND budget_limit_cny='0.000000')"
        ),
        "status<>'APPROVED_UNBOUND' OR (testing_task_id IS NULL AND validation_id IS NULL)",
        "status<>'EFFECTIVE' OR (testing_task_id IS NULL)<>(validation_id IS NULL)",
    ],
    'testing_findings': ['case_id IS NULL OR item_id IS NOT NULL'],
    'code_schema_state': [
        'singleton_id=1',
        'schema_version=200',
        "(origin='FRESH_V20' AND upgrade_id IS NULL AND source_data_sha256 IS NULL)"
        " OR (origin='UPGRADED_V151' AND upgrade_id IS NOT NULL AND source_data_sha256 IS NOT NULL)",
    ],
}


ROW_CHECKS['code_tasks'].extend(
    (
        "status<>'COMPLETED' OR stop_requested_at IS NULL",
        "status<>'TERMINATED' OR phase='FINISHED'",
    )
)
ROW_CHECKS['code_task_reservations'] = [
    '(settled_cny IS NULL AND settled_at IS NULL AND settlement_basis IS NULL) OR (settled_cny IS NOT NULL AND settled_at IS NOT NULL AND settlement_basis IS NOT NULL)',
    "status<>'SETTLED' OR settled_cny IS NOT NULL",
]
ROW_CHECKS['code_runtime_observations'].append(
    "result<>'VERIFIED' OR kind NOT IN ('STOP','CLEANUP') OR active_process_count=0"
)


def names(table: str) -> set[str]:
    return {field[0] for field in COLUMNS[table][1]}


def foreign_key(columns: tuple[str, ...], target: str, target_columns: tuple[str, ...]) -> str:
    source = ','.join(map(quote_identifier, columns))
    destination = ','.join(map(quote_identifier, target_columns))
    return (
        f'FOREIGN KEY({source}) REFERENCES {quote_identifier(target)}({destination})'
        ' DEFERRABLE INITIALLY DEFERRED'
    )


def table_constraints(table: str) -> tuple[str, ...]:
    fields = names(table)
    result = []
    for owner in ('task_id', 'testing_task_id'):
        if owner in fields and 'id' in fields:
            result.append(f'UNIQUE(id,{owner})')
    if {'task_id', 'testing_task_id'} <= fields and table != 'code_operations':
        result.append('CHECK((task_id IS NULL)<>(testing_task_id IS NULL))')
    for group in UNIQUE_FIELDS.get(table, ()):
        result.append('UNIQUE(' + ','.join(group) + ')')
    references = dict(COMMON_REFERENCES)
    if 'authorization_id' in fields:
        references['authorization_id'] = (
            'testing_authorizations' if table.startswith('testing_') else 'code_authorizations'
        )
    if 'profile_version_id' in fields:
        references['profile_version_id'] = (
            'testing_profile_versions'
            if table.startswith('testing_')
            else 'code_execution_profile_versions'
        )
    if 'profile_id' in fields:
        references['profile_id'] = 'code_execution_profiles'
    for field in sorted(fields & references.keys()):
        target = references[field]
        if target == table and field == 'id':
            continue
        result.append(foreign_key((field,), target, ('id',)))
        for owner in ('task_id', 'testing_task_id'):
            if owner in fields and field != owner and target in COLUMNS and owner in names(target):
                result.append(foreign_key((field, owner), target, ('id', owner)))
    if {'document_id', 'requirement_id'} <= fields:
        result.append(
            foreign_key(
                ('document_id', 'requirement_id'), 'requirement_documents', ('id', 'requirement_id')
            )
        )
    if {'design_revision_id', 'document_id'} <= fields:
        result.append(
            foreign_key(('design_revision_id', 'document_id'), 'revisions', ('id', 'document_id'))
        )
    if {'revision_id', 'document_id'} <= fields:
        result.append(
            foreign_key(('revision_id', 'document_id'), 'revisions', ('id', 'document_id'))
        )
    if table == 'testing_findings':
        result.append(
            foreign_key(
                ('item_id', 'case_id'), 'code_verification_case_results', ('item_id', 'case_id')
            )
        )
    for field in sorted(fields & references.keys()):
        target = references[field]
        root_owner = (
            'task_id'
            if table == 'code_tasks'
            else 'testing_task_id'
            if table == 'testing_tasks'
            else None
        )
        # A Testing validation's group grant has no individual task owner.
        # Its conditional scope is checked by the Testing owner trigger.
        if table == 'testing_tasks' and field == 'authorization_id':
            continue
        if root_owner is not None and target in COLUMNS and root_owner in names(target):
            result.append(foreign_key((field, 'id'), target, ('id', root_owner)))
    if table in ('code_defects', 'testing_findings'):
        result.append(foreign_key(('basis_document_id',), 'requirement_documents', ('id',)))
        result.append(
            foreign_key(
                ('basis_revision_id', 'basis_document_id'), 'revisions', ('id', 'document_id')
            )
        )
    for source, target, destination in FIXED_REFERENCES.get(table, ()):
        result.append(foreign_key(source, target, destination))
    result.extend('CHECK((' + check + ') IS TRUE)' for check in ROW_CHECKS.get(table, ()))
    return tuple(result)


# These references bind the same immutable candidate/report/plan, not merely
# another record belonging to the same task.
UNIQUE_FIELDS.setdefault('code_tasks', []).append(('id', 'repository_id'))
UNIQUE_FIELDS['code_snapshots'].append(('id', 'repository_id'))
UNIQUE_FIELDS.setdefault('code_delivery_plans', []).append(
    ('id', 'task_id', 'candidate_id', 'test_report_id')
)
UNIQUE_FIELDS.setdefault('code_acceptances', []).append(('id', 'task_id', 'delivery_plan_id'))
UNIQUE_FIELDS['code_delivery_windows'].append(('id', 'delivery_id'))
UNIQUE_FIELDS['testing_pack_versions'].append(('id', 'plan_version_id'))

FIXED_REFERENCES = {
    'code_tasks': [
        (('base_snapshot_id', 'repository_id'), 'code_snapshots', ('id', 'repository_id')),
    ],
    'code_delivery_plans': [
        (('task_id', 'repository_id'), 'code_tasks', ('id', 'repository_id')),
    ],
    'code_acceptances': [
        (
            ('delivery_plan_id', 'task_id', 'candidate_id', 'test_report_id'),
            'code_delivery_plans',
            ('id', 'task_id', 'candidate_id', 'test_report_id'),
        ),
    ],
    'code_deliveries': [
        (
            ('acceptance_id', 'task_id', 'delivery_plan_id'),
            'code_acceptances',
            ('id', 'task_id', 'delivery_plan_id'),
        ),
        (('current_window_id', 'id'), 'code_delivery_windows', ('id', 'delivery_id')),
    ],
    'testing_tasks': [
        (
            ('test_pack_version_id', 'plan_version_id'),
            'testing_pack_versions',
            ('id', 'plan_version_id'),
        ),
    ],
    'testing_reports': [
        (
            ('test_pack_version_id', 'plan_version_id'),
            'testing_pack_versions',
            ('id', 'plan_version_id'),
        ),
    ],
}
ROW_CHECKS['code_tasks'].extend(
    (
        "budget_limit_cny<>'0.000000'",
        "status NOT IN ('VERIFYING','AWAITING_TESTING','AWAITING_ACCEPTANCE') OR current_candidate_id IS NOT NULL",
        "status<>'AWAITING_ACCEPTANCE' OR current_test_report_id IS NOT NULL",
        "status<>'RUNNING' OR (active_session_id IS NOT NULL AND started_at IS NOT NULL)",
        "status<>'COMPLETED' OR current_delivery_id IS NOT NULL",
    )
)
ROW_CHECKS['code_candidates'].append("content_policy_version='CONTENT20-STORE-1'")

ROW_CHECKS['code_verifications'].append(
    "owner_kind<>'CODING' OR "
    "(role='BACKEND' AND backend_handoff_operation_id IS NULL AND frontend_handoff_operation_id IS NULL "
    "AND json_array_length(scope_stages)=1 AND json_extract(scope_stages,'$[0]')='BACKEND') OR "
    "(role='FRONTEND' AND backend_handoff_operation_id IS NOT NULL AND frontend_handoff_operation_id IS NULL "
    "AND json_array_length(scope_stages)=2 AND json_extract(scope_stages,'$[0]')='BACKEND' AND json_extract(scope_stages,'$[1]')='FRONTEND') OR "
    "(role='INTEGRATION' AND backend_handoff_operation_id IS NOT NULL AND frontend_handoff_operation_id IS NOT NULL "
    "AND json_array_length(scope_stages)=3 AND json_extract(scope_stages,'$[0]')='BACKEND' AND json_extract(scope_stages,'$[1]')='FRONTEND' AND json_extract(scope_stages,'$[2]')='INTEGRATION')"
)
