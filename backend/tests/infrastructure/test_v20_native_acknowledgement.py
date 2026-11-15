"""Conflicting private receipts fail before external native reads or sends."""

from copy import deepcopy

import pytest

from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.shared.validation import strict_json_object
from backend.tests.infrastructure import test_v20_native_permission_application as permissions
from backend.tests.infrastructure import test_v20_opencode_instance_control as native

native_control = native.native_control


@pytest.mark.parametrize('action', ['session', 'initial', 'permission', 'send'])
@pytest.mark.parametrize('defect', ['scope', 'action', 'input', 'extra', 'result', 'json'])
def test_conflicting_ack_is_rejected_before_any_external_request(
    native_control, monkeypatch, action, defect
):
    _, original, state, scope = native_control
    if action == 'permission':
        actions, before, _ = permissions.prepare(native_control)
        actions.apply_permission(
            before, [permissions.RESET, permissions.READ], native._CHECKPOINT, **native._TIMEOUT
        )
        kind = 'permission'
    else:
        actions = original
        actions.create_session(native._session_input(scope), native._CHECKPOINT, **native._TIMEOUT)
        prompt = actions.initial_payload('walle-code', 'walle', 'walle-code', ['fixed'])
        kind = 'initial' if action == 'initial' else 'session'
        if action == 'initial':
            actions.send_initial(native._SESSION, prompt, native._CHECKPOINT, **native._TIMEOUT)

    def invoke():
        if action == 'permission':
            return actions.observe_permission(native._CHECKPOINT, **native._TIMEOUT)
        if action == 'initial':
            return actions.observe_initial(native._CHECKPOINT, **native._TIMEOUT)
        if action == 'send':
            return actions.send_initial(
                native._SESSION, prompt, native._CHECKPOINT, **native._TIMEOUT
            )
        return actions.observe_session(native._CHECKPOINT, **native._TIMEOUT)

    read = actions._read
    receipt = deepcopy(strict_json_object(read(kind, 'ack')))
    if defect == 'scope':
        receipt['scope'] += '-foreign'
    elif defect == 'action':
        receipt['action'] = 'foreign'
    elif defect == 'input':
        receipt['input']['foreign'] = True
    elif defect == 'extra':
        receipt['result']['foreign'] = True
    elif defect == 'result':
        if kind == 'initial':
            receipt['result']['accepted'] = 1
        elif kind == 'permission':
            receipt['result']['permission'] = []
        else:
            receipt['result']['native_session_id'] = True
    raw = b'{' if defect == 'json' else _bytes(receipt)

    def corrupted_read(selected, phase):
        return raw if (selected, phase) == (kind, 'ack') else read(selected, phase)

    requests = tuple(state['requests'])
    monkeypatch.setattr(actions, '_read', corrupted_read)
    with pytest.raises(TaskExecutionError):
        invoke()
    assert tuple(state['requests']) == requests
    if action == 'send':
        assert read('initial', 'intent') is None
    monkeypatch.setattr(actions, '_read', read)
    invoke()


@pytest.mark.parametrize('defect', ['session', 'payload', 'extra', 'json'])
def test_lost_message_ack_cannot_redirect_original_read(native_control, monkeypatch, defect):
    _, actions, state, scope = native_control
    actions.create_session(native._session_input(scope), native._CHECKPOINT, **native._TIMEOUT)
    prompt = actions.initial_payload('walle-code', 'walle', 'walle-code', ['fixed'])
    state['drops'].add(('POST', '/session/' + native._SESSION + '/prompt_async'))
    with pytest.raises(TaskExecutionError):
        actions.send_initial(native._SESSION, prompt, native._CHECKPOINT, **native._TIMEOUT)
    assert actions._read('initial', 'ack') is None
    read = actions._read
    intent = strict_json_object(read('initial', 'intent'))
    if defect == 'session':
        intent['input']['session_id'] = 'ses_foreign'
    elif defect == 'payload':
        intent['input']['payload']['messageID'] = True
    else:
        intent['input']['extra'] = True

    def redirected_intent(action, phase):
        return (
            (b'{' if defect == 'json' else _bytes(intent))
            if (action, phase) == ('initial', 'intent')
            else read(action, phase)
        )

    requests = tuple(state['requests'])
    monkeypatch.setattr(actions, '_read', redirected_intent)
    with pytest.raises(TaskExecutionError):
        actions.observe_initial(native._CHECKPOINT, **native._TIMEOUT)
    assert tuple(state['requests']) == requests
    assert read('initial', 'ack') is None
    monkeypatch.setattr(actions, '_read', read)
    actions.observe_initial(native._CHECKPOINT, **native._TIMEOUT)
    assert actions._read('initial', 'ack') is not None


@pytest.mark.parametrize('defect', ['model', 'metadata', 'extra', 'json'])
def test_lost_session_ack_validates_creation_before_lookup(native_control, monkeypatch, defect):
    _, actions, state, scope = native_control
    state['drops'].add(('POST', '/session'))
    with pytest.raises(TaskExecutionError):
        actions.create_session(native._session_input(scope), native._CHECKPOINT, **native._TIMEOUT)
    assert actions._read('session', 'ack') is None
    read = actions._read
    intent = strict_json_object(read('session', 'intent'))
    if defect == 'model':
        intent['input']['model'] = None
    elif defect == 'metadata':
        intent['input']['metadata']['walle']['operation_id'] = float(scope.operation_id)
    else:
        intent['input']['foreign'] = True

    def malformed_creation(action, phase):
        return (
            (b'{' if defect == 'json' else _bytes(intent))
            if (action, phase) == ('session', 'intent')
            else read(action, phase)
        )

    requests = tuple(state['requests'])
    monkeypatch.setattr(actions, '_read', malformed_creation)
    with pytest.raises(TaskExecutionError):
        actions.observe_session(native._CHECKPOINT, **native._TIMEOUT)
    assert tuple(state['requests']) == requests
    assert read('session', 'ack') is None
    monkeypatch.setattr(actions, '_read', read)
    assert actions.observe_session(native._CHECKPOINT, **native._TIMEOUT)['id'] == native._SESSION


@pytest.mark.parametrize('defect', ['missing', 'extra', 'model', 'parts', 'json'])
def test_saved_plan_is_fully_validated_without_allocating_replacement(
    native_control, monkeypatch, defect
):
    _, actions, state, _ = native_control
    arguments = ('walle-code', 'walle', 'walle-code', ['fixed'])
    planned = actions.plan_initial_payload(*arguments)
    read = actions._read
    before = read('initial', 'planned')
    record = strict_json_object(before)
    if defect == 'missing':
        record.pop('payload')
    elif defect == 'extra':
        record['extra'] = True
    elif defect == 'model':
        record['payload']['model'] = None
    elif defect == 'parts':
        record['payload']['parts'][0]['extra'] = True
    raw = b'{' if defect == 'json' else _bytes(record)

    def malformed_plan(action, phase):
        return raw if (action, phase) == ('initial', 'planned') else read(action, phase)

    requests = tuple(state['requests'])
    monkeypatch.setattr(actions, '_read', malformed_plan)
    with pytest.raises(TaskExecutionError):
        actions.plan_initial_payload(*arguments)
    assert tuple(state['requests']) == requests
    assert read('initial', 'planned') == before
    monkeypatch.setattr(actions, '_read', read)
    assert actions.plan_initial_payload(*arguments) == planned


@pytest.mark.parametrize('action', ['session', 'initial', 'permission'])
def test_reopened_action_rejects_physically_misbound_receipt(native_control, action):
    from backend.app.code_tasks.task_native_actions import TaskNativeActions

    control, original, state, scope = native_control
    if action == 'permission':
        actions, before, _ = permissions.prepare(native_control)
        state['drops'].add(permissions.ROUTE)
        with pytest.raises(TaskExecutionError):
            actions.apply_permission(
                before, [permissions.RESET, permissions.READ], native._CHECKPOINT, **native._TIMEOUT
            )
        result = {
            'native_session_id': native._SESSION,
            'permission': before['permission'] + [permissions.RESET, permissions.READ],
        }
    else:
        actions = original
        if action == 'session':
            state['drops'].add(('POST', '/session'))
            with pytest.raises(TaskExecutionError):
                actions.create_session(
                    native._session_input(scope), native._CHECKPOINT, **native._TIMEOUT
                )
            result = {'native_session_id': native._SESSION}
        else:
            actions.create_session(
                native._session_input(scope), native._CHECKPOINT, **native._TIMEOUT
            )
            prompt = actions.initial_payload('walle-code', 'walle', 'walle-code', ['fixed'])
            state['drops'].add(('POST', '/session/' + native._SESSION + '/prompt_async'))
            with pytest.raises(TaskExecutionError):
                actions.send_initial(native._SESSION, prompt, native._CHECKPOINT, **native._TIMEOUT)
            result = {'native_message_id': prompt['messageID'], 'accepted': True}
    assert actions._read(action, 'ack') is None
    wrong = {**actions._original(action), 'scope': 'foreign-original-step', 'result': result}
    actions._write(action, 'ack', wrong)
    stored = actions._read(action, 'ack')
    reopened = TaskNativeActions(
        original._package,
        scope,
        control,
        action_scope=actions._scope if action == 'permission' else None,
    )
    requests = tuple(state['requests'])
    observe = {
        'session': reopened.observe_session,
        'initial': reopened.observe_initial,
        'permission': reopened.observe_permission,
    }[action]
    with pytest.raises(TaskExecutionError, match='ACK_DIFFERS'):
        observe(native._CHECKPOINT, **native._TIMEOUT)
    assert tuple(state['requests']) == requests
    assert actions._read(action, 'ack') == stored
