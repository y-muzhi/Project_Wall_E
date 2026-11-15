"""V2 registered operation steps, not a generic workflow engine.

Each tuple belongs to the original operation and is persisted before dispatch.
An UNKNOWN step must be reconciled using its original external identity.
"""

CODING_STEPS = {
    'START': (
        'RESTORE_WORKSPACE',
        'PREPARE_BASIS',
        'CHECK_CONDITIONS',
        'START_INSTANCE',
        'CREATE_SESSION',
        'SEND_INITIAL',
    ),
    'RESUME': ('RECONCILE', 'CHECK_CONDITIONS', 'CONTINUE_OR_OBSERVE'),
    'ANSWER_QUESTION': ('READ_NATIVE', 'SEND_RESPONSE', 'CONFIRM_NATIVE'),
    'DECIDE_PERMISSION': ('READ_NATIVE', 'SEND_RESPONSE', 'CONFIRM_NATIVE'),
    'PREPARE_HANDOFF': ('VALIDATE', 'SAVE_FACT'),
    'APPLY_CONFIGURATION': ('BLOCK_NEW', 'QUIESCE_IF_REQUIRED', 'APPLY_PAIR', 'VERIFY_EFFECTIVE'),
    'VERIFY_CANDIDATE': ('CHECK_CONDITIONS', 'RESTORE_CHECK_COPY', 'CHECK'),
    'SUBMIT_FOR_TESTING': ('VALIDATE', 'SAVE_FACT'),
    'LINK_TEST_REPORT': ('VALIDATE', 'SAVE_FACT'),
    'CAPTURE_AND_CHECK': ('QUIESCE', 'CAPTURE', 'PUBLISH', 'CHECK'),
    'REPAIR': ('RESTORE_SOURCE', 'SEND_REPAIR', 'OBSERVE', 'CAPTURE_RESULT'),
    'HANDOFF_ROLE': ('QUIESCE', 'REVOKE', 'CHECK', 'CREATE_SESSION', 'SEND_HANDOFF'),
    'PREPARE_DELIVERY': ('VALIDATE_REPORT', 'READ_TARGET', 'SEAL_TARGET', 'SAVE_PLAN'),
    'DELIVER': (
        'FIX_COMMIT_INPUT',
        'BUILD_OBJECTS',
        'SAVE_PLANNED_COMMIT',
        'PREPARE_REF',
        'VERIFY_LOCKED_TARGET',
        'DISPATCH_COMMIT_ONCE',
        'RECONCILE',
        'FINALIZE_OWNED_RUNTIME',
    ),
    'TERMINATE': (
        'BLOCK_NEW',
        'REVOKE_GATEWAY',
        'ABORT_IF_APPLICABLE',
        'STOP_OWNED_ACTIVITY',
        'RECONCILE_WRITES',
        'CLEANUP',
    ),
    'RECONCILE': ('QUERY', 'COMPARE', 'RECORD'),
}
TESTING_STEPS = {
    'DRAFT_PLAN': ('BUILD_CONTEXT', 'RESERVE', 'CALL_MODEL', 'SAVE_DRAFT'),
    'SEAL_PACK': ('VALIDATE_PLAN', 'COMPILE', 'SEAL', 'SAVE_PACK'),
    'VALIDATE_PACK': (
        'FIX_REFERENCE_SET',
        'CREATE_CHILD_TASKS',
        'OBSERVE_CHILDREN',
        'SAVE_VALIDATION',
    ),
    'RUN_TEST': (
        'FIX_INPUT',
        'MATERIALIZE',
        'PREPARE',
        'EXECUTE',
        'STOP',
        'VERIFY_INPUT',
        'CLEANUP',
        'SAVE_REPORT',
    ),
    'TERMINATE': ('FENCE', 'STOP_OWN_ACTIVITIES', 'VERIFY_STOP', 'CLEANUP', 'SAVE_TERMINATED'),
    'RESUME': ('RECONCILE', 'CHECK_CONDITIONS', 'CONTINUE_OR_OBSERVE'),
    'RECONCILE': ('QUERY', 'COMPARE', 'RECORD'),
    **{
        name: ('VALIDATE', 'SAVE_FACT')
        for name in (
            'ATTACH_ASSETS',
            'INCREASE_TEST_BUDGET',
            'REVIEW_FINDING',
            'PUBLISH_PLAN',
            'PUBLISH_PACK',
            'REVOKE_PLAN',
            'REVOKE_PACK',
        )
    },
}
RESOURCE_STEPS = {
    'REGISTER_BASE': ('VALIDATE_COMMIT', 'PIN_COMMIT', 'VERIFY_PINNED_OBJECTS', 'SAVE_BASELINE'),
    'REFRESH_REPOSITORY': ('READ_REPOSITORY', 'SAVE_OBSERVATION'),
    **{
        name: ('VALIDATE', 'SAVE_FACT')
        for name in (
            'REGISTER_REPOSITORY',
            'CREATE_EXECUTION_PROFILE',
            'CREATE_CHECK_SET',
            'PUBLISH_EXECUTION_PROFILE',
            'PUBLISH_CHECK_SET',
            'APPROVE_AUTHORIZATION',
            'CREATE_PLAN',
            'EDIT_PLAN',
            'PUBLISH_PLAN',
            'REVOKE_PLAN',
            'SEAL_PACK',
            'PUBLISH_PACK',
            'REVOKE_PACK',
            'REVIEW_FINDING',
        )
    },
}
RESOURCE_KINDS = (
    'TASK',
    'TESTING_TASK',
    'TEST_PLAN',
    'TEST_PLAN_VERSION',
    'TEST_PACK_VERSION',
    'TEST_PROFILE_VERSION',
    'TEST_AUTHORIZATION',
    'TEST_REPORT',
    'TESTING_FINDING',
    'REPOSITORY',
    'SNAPSHOT',
    'EXECUTION_PROFILE',
    'EXECUTION_PROFILE_VERSION',
    'CHECK_SET',
    'CHECK_SET_VERSION',
    'AUTHORIZATION',
)


def operation_steps(owner: str, operation_type: str) -> tuple[str, ...]:
    registry = {'CODING': CODING_STEPS, 'TESTING': TESTING_STEPS, 'RESOURCE': RESOURCE_STEPS}
    if owner not in registry or operation_type not in registry[owner]:
        raise ValueError('Operation is not registered for this owner')
    return registry[owner][operation_type]


# Resource sealing/validation uses the same explicit fixed protocol without a task owner.
RESOURCE_STEPS.update({name: TESTING_STEPS[name] for name in ('SEAL_PACK', 'VALIDATE_PACK')})
