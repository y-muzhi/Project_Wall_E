"""V2.0 schema construction from the reviewed column registry.

This builder creates SQL in memory. It neither opens nor upgrades a database.
A release still requires fresh/upgrade equivalence and the fixed runtime.
"""

from collections.abc import Iterable

from backend.app.code_tasks.error_codes import ERROR_HTTP
from backend.app.code_tasks.operation_protocol import (
    CODING_STEPS,
    RESOURCE_KINDS,
    RESOURCE_STEPS,
    TESTING_STEPS,
)

from .schema_inspection import quote_identifier
from .schema_v20_columns import COLUMNS

MAX_ID = 9_007_199_254_740_991
TASK_PHASES = 'PREPARING BACKEND FRONTEND INTEGRATION TESTING ACCEPTANCE DELIVERY FINISHED'
TEST_PHASES = 'PLAN PREPARE EXECUTE REPORT FINISHED'
OP_STATUS = 'PENDING RUNNING SUCCEEDED FAILED UNKNOWN CANCELLED'
ROLES = 'BACKEND FRONTEND INTEGRATION'
ENUMS = {
    'CodeTask.status': 'PENDING RUNNING WAITING VERIFYING AWAITING_TESTING AWAITING_ACCEPTANCE STOPPING COMPLETED TERMINATED',
    'CodeWorkspace.status': 'PREPARING READY UNKNOWN RELEASED',
    'ManagedInstance.status': 'STARTING READY STOPPING STOPPED UNKNOWN',
    'ExecutionSession.status': 'PREPARING ACTIVE QUIESCING RETIRED UNKNOWN',
    'CommandExecution.status': OP_STATUS,
    'CommandExecution.purpose': 'EXECUTION CHECK SERVICE CONTROL_GIT',
    'CodeRepair.status': OP_STATUS,
    'Delivery.status': 'PENDING PREPARING WRITING UNKNOWN SUCCEEDED BLOCKED CANCELLED',
    'Delivery.git_write_status': 'NOT_DISPATCHED PREPARED MAY_HAVE_BEEN_SENT CONFIRMED ABORTED_UNSENT UNKNOWN',
    'Delivery.postcheck_status': 'NOT_RUN VERIFIED CONFLICT UNKNOWN',
    'ExecutionRecord.kind': 'MESSAGE TOOL COMMAND_OUTPUT CONTROL ERROR',
    'ExecutionRecord.source_kind': 'OPERATION COMMAND QUESTION PERMISSION LLM_USE',
    'OperationRecord.status': OP_STATUS,
    'OperationStep.status': OP_STATUS,
    'WaitingItem.status': 'OPEN RESOLVED',
    'WaitingItem.kind': 'PREPARATION QUESTION PERMISSION BUDGET MODEL_RESULT OPERATION_RESULT CHECK_FAILURE CHECK_ENVIRONMENT CHECK_RESULT CONFIGURATION TARGET_CHANGED DELIVERY_RESULT',
    'WaitingItem.source_kind': 'OPERATION QUESTION PERMISSION VERIFICATION_ITEM LLM_USE DELIVERY',
    'Verification.status': 'PENDING RUNNING FINISHED UNKNOWN CANCELLED',
    'Verification.purpose': 'HANDOFF DIAGNOSTIC ACCEPTANCE PACK_VALIDATION',
    'Verification.stop_status': 'NOT_STARTED ACTIVE VERIFIED UNKNOWN',
    'Verification.cleanup_status': 'NOT_STARTED CLEANING VERIFIED FAILED UNKNOWN',
    'Verification.source_integrity_status': 'NOT_CHECKED VERIFIED CHANGED UNKNOWN',
    'VerificationItem.result': 'NOT_RUN RUNNING PASSED FAILED UNAVAILABLE UNKNOWN CANCELLED',
    'VerificationItem.check_kind': 'PROJECT_COMMAND CONTROLLED_ASSERTION',
    'VerificationItem.evidence_kind': 'PROCESS_EXIT CONTROLLED_CASES CONTENT_INTEGRITY',
    'VerificationItem.reason_code': 'COMMAND_FAILED ASSERTION_FAILED NO_CONTROLLED_CASES RESOURCE_MISSING DEPENDENCY_MISMATCH ISOLATION_UNAVAILABLE TARGET_UNVERIFIED APPLICATION_START_FAILED TIMEOUT OUTPUT_LIMIT INPUT_CHANGED EVIDENCE_INCOMPLETE PROCESS_STATE_UNKNOWN CLEANUP_UNVERIFIED',
    'VerificationCaseResult.result': 'PASSED FAILED',
    'VerificationCaseResult.capture_status': 'FULL REDACTED INCOMPLETE',
    'LLMResponseFrame.capture_status': 'FULL REDACTED INCOMPLETE',
    'CodeTaskReservation.status': 'RESERVED SETTLED RELEASED_UNSENT UNKNOWN DISPUTED',
    'CodeTaskReservation.settlement_basis': 'VERIFIED_USAGE PROVIDER_BILL',
    'ModelUsageEvidence.status': 'VERIFIED REJECTED DISPUTED',
    'NativeQuestion.status': 'OPEN ANSWERING RESOLVED REJECTED UNKNOWN OBSOLETE',
    'NativePermission.status': 'OPEN ANSWERING RESOLVED REJECTED UNKNOWN OBSOLETE',
    'QuestionHandoffEvent.kind': 'PREPARED DISCUSSION_LINKED REVISION_LINKED ABANDONED',
    'CodeRepository.object_format': 'sha1 sha256',
    'RepositoryObservation.status': 'READABLE UNAVAILABLE UNKNOWN',
    'AuthorizationGrant.status': 'APPROVED_UNBOUND BOUND_PENDING_APPLY EFFECTIVE APPLY_FAILED APPLY_UNKNOWN RETIRED',
    'TaskConfigurationApplication.status': 'PENDING APPLYING APPLIED FAILED UNKNOWN',
    'RuntimeBoundaryObservation.kind': 'PREPARE QUIESCE STOP CLEANUP',
    'RuntimeBoundaryObservation.result': 'VERIFIED UNAVAILABLE UNKNOWN',
}
ENUMS.update(
    {
        'ModelPriceVersion.channel': 'ARK_CN_BEIJING',
        'NativePermission.requested_action': 'READ WRITE EXECUTE NETWORK UNKNOWN',
        'OperationRecord.resource_kind': ' '.join(RESOURCE_KINDS),
        'OperationRecord.operation_type': ' '.join(
            sorted(set(CODING_STEPS) | set(TESTING_STEPS) | set(RESOURCE_STEPS))
        ),
        'OperationStep.step_type': ' '.join(
            sorted(
                {
                    step
                    for registry in (CODING_STEPS, TESTING_STEPS, RESOURCE_STEPS)
                    for steps in registry.values()
                    for step in steps
                }
            )
        ),
        'OperationRecord.failure_code': ' '.join((*ERROR_HTTP, 'EVIDENCE_INCOMPLETE')),
        'LLMUse.function_type': 'DISCUSS GENERATE REVISE REVIEW PROPOSE_CHANGES COMPARE CODE_EXECUTION TEST_PLAN_DRAFT',
        'LLMUse.call_purpose': 'CODE COMPACTION TEST_DESIGN',
        'LLMUse.parse_status': 'PENDING SUCCEEDED FAILED NOT_APPLICABLE',
        'LLMUse.validation_status': 'PENDING SUCCEEDED FAILED NOT_APPLICABLE',
        'LLMUse.transport_status': 'NOT_SENT SENDING SENT COMPLETE INTERRUPTED UNKNOWN',
        'LLMUse.capture_status': 'FULL REDACTED INCOMPLETE',
    }
)

JSON_OBJECTS = frozenset(
    (
        'BasisRef',
        'ProcessIdentity',
        'RuntimeBinding',
        'ModelWindow',
        'NativeToolRef',
        'PrivateNativePermissionObservation',
        'ExecutorConfiguration',
        'GitConfiguration',
        'ModelConfiguration',
        'EnvironmentConfiguration',
        'CaptureRules',
        'DeliveryConfiguration',
        'ExecutionLimits',
        'TariffRules',
        'UsageEvidence',
        'TestingLimits',
        'TestingModelBinding',
        'AuthorizationScope',
        'ConfigurationEffectiveEvidence',
        '原步骤允许的外部身份结构',
        '所属APP操作的固定输入结构',
        '所属步骤的持久结果引用',
        '解除事项的真实结果引用',
        '脱敏实际SSE帧结构',
        '文档解析结果结构',
        '文档可信输出结构',
        '脱敏实际供应方请求结构',
        '脱敏响应或分块描述结构',
        '既有LLMUse缓存用量结构',
    )
)
TEXT_TYPES = frozenset(
    (
        '非空文本',
        '非空不透明文本',
        '不透明文本',
        '文本（格式见约束）',
        '实际Prompt与配置引用文本',
        '已登记安全错误编码文本',
    )
)
PRIMARY_KEYS = {
    'code_defect_evidence_refs': ('defect_id', 'ordinal'),
    'code_operation_steps': ('operation_id', 'step_no'),
    'code_verification_case_results': ('item_id', 'case_id'),
    'code_model_response_frames': ('llm_use_id', 'seq'),
    'code_delivery_repository_locks': ('repository_id',),
    'code_task_materials': ('task_id', 'document_id'),
    'code_repair_defects': ('repair_id', 'defect_id'),
    'testing_task_materials': ('testing_task_id', 'document_id'),
    'testing_plan_materials': ('plan_version_id', 'document_id'),
    'testing_validation_tasks': ('validation_id', 'testing_task_id'),
    'code_schema_state': ('singleton_id',),
}
RELATIONAL_FIELDS = {
    'CodeDefect.evidence_refs',
    'CodeRepair.defect_ids',
    'TestingTask.material_refs',
    'TestPlanVersion.material_refs',
    'TestPackValidation.testing_task_ids',
}


def literals(values: Iterable[str]) -> str:
    return ','.join("'" + value.replace("'", "''") + "'" for value in values)


def in_values(column: str, values: str) -> str:
    return f'{quote_identifier(column)} IN ({literals(values.split())})'


def column_sql(owner: str, name: str, kind: str, nullable: bool) -> str:
    column = quote_identifier(name)
    check = None
    sql_type = 'TEXT'
    if kind in ('ID', '正安全整数', '非负安全整数', '有符号整数', 'Boolean'):
        sql_type = 'INTEGER'
        if kind == 'Boolean':
            check = f'{column} IN (0,1)'
        elif kind != '有符号整数':
            minimum = 0 if kind == '非负安全整数' else 1
            check = f'{column} BETWEEN {minimum} AND {MAX_ID}'
    elif kind == 'UtcTime':
        check = f"length({column})=24 AND {column} GLOB '????-??-??T??:??:??.???Z'"
    elif kind == 'Sha256':
        check = f"length({column})=64 AND {column} NOT GLOB '*[^0-9a-f]*'"
    elif kind == 'GitOID':
        check = f"length({column}) IN (40,64) AND {column} NOT GLOB '*[^0-9a-f]*'"
    elif kind == 'Money':
        # Canonical six-decimal storage. API input normalization is separate.
        check = (
            f"instr({column},'.')=length({column})-6 AND length({column})>=8 "
            f"AND {column} NOT GLOB '*[^0-9.]*' "
            f"AND substr({column},-6) NOT GLOB '*[^0-9]*' "
            f"AND instr(substr({column},1,length({column})-7),'.')=0 "
            f"AND (substr({column},1,1)<>'0' OR substr({column},1,2)='0.')"
        )
    elif kind.endswith('[]'):
        check = f"json_valid({column}) AND json_type({column})='array'"
    elif kind in JSON_OBJECTS:
        check = f"json_valid({column}) AND json_type({column})='object'"
    elif kind.startswith('文本固定'):
        check = f'{column}={literals((kind.removeprefix("文本固定"),))}'
    elif kind in ('TaskPhase', 'TestingPhase', 'TaskPhase或TestingPhase', 'TestingStatus'):
        values = {
            'TaskPhase': TASK_PHASES,
            'TestingPhase': TEST_PHASES,
            'TaskPhase或TestingPhase': ' '.join(
                dict.fromkeys((TASK_PHASES + ' ' + TEST_PHASES).split())
            ),
            'TestingStatus': 'DRAFT PLANNING READY RUNNING WAITING STOPPING COMPLETED TERMINATED',
        }[kind]
        check = in_values(name, values)
    elif kind.startswith('Role'):
        check = in_values(name, ROLES)
    elif '／' in kind and '枚举' not in kind:
        check = in_values(name, kind.replace('／', ' '))
    elif '枚举' in kind:
        reference = kind.split('枚举')[0]
        if reference in ENUMS:
            check = in_values(name, ENUMS[reference])
        else:
            raise ValueError(f'Unmapped enum: {reference}')
    elif kind in TEXT_TYPES:
        check = f'length({column})>0'
    else:
        raise ValueError(f'Unmapped column type: {owner}.{name}: {kind}')
    result = f'{column} {sql_type}'
    if not nullable:
        result += ' NOT NULL'
    if check is not None:
        result += f' CHECK({column} IS NULL OR ({check}))' if nullable else f' CHECK({check})'
    return result


def create_table_sql(table: str, constraints: tuple[str, ...] = ()) -> str:
    if table == 'llm_uses':
        raise ValueError('LLMUse must retain every frozen column through llm_table_sql')
    owner, fields = COLUMNS[table]
    definitions = [
        column_sql(owner, name, kind, nullable)
        for name, kind, nullable in fields
        if f'{owner}.{name}' not in RELATIONAL_FIELDS
    ]
    if owner in ('CodeDefect', 'TestingFinding'):
        required = ' NOT NULL' if owner == 'CodeDefect' else ''
        for field in ('document_id', 'revision_id'):
            definitions.append(
                f'"basis_{field}" INTEGER GENERATED ALWAYS AS '
                f"(json_extract(basis_ref,'$.{field}')) STORED{required}"
            )
        definitions.append(
            "CHECK((basis_ref IS NULL OR (json_type(basis_ref,'$.document_id')='integer' "
            "AND json_type(basis_ref,'$.revision_id')='integer' "
            "AND json_type(basis_ref,'$.quote')='text' "
            "AND length(json_extract(basis_ref,'$.quote'))>0)) IS TRUE)"
        )
    keys = PRIMARY_KEYS.get(table, ('id',))
    definitions.append('PRIMARY KEY(' + ','.join(map(quote_identifier, keys)) + ')')
    definitions.extend(constraints)
    return (
        f'CREATE TABLE {quote_identifier(table)} (\n  '
        + ',\n  '.join(definitions)
        + '\n) STRICT;\n'
    )
