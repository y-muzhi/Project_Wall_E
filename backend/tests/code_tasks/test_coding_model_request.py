"""Fixed Coding supplier request and content/linkage rejection cases."""

from copy import deepcopy

import pytest

from backend.app.code_tasks.coding_model_request import (
    REQUEST_BYTES,
    CodingModelProtocolError,
    CodingRequestContract,
    parse_request,
    prepare_request,
)
from backend.app.infrastructure.runtime_launch_journal import _bytes


def _request():
    call = {
        'id': 'call_original',
        'type': 'function',
        'function': {'name': 'lookup', 'arguments': '{"值": 1}'},
    }
    return {
        'model': 'walle-code',
        'messages': [
            {'role': 'system', 'content': '固定上下文'},
            {'role': 'user', 'content': [{'type': 'text', 'text': '读取原材料'}]},
            {'role': 'assistant', 'content': None, 'tool_calls': [call]},
            {'role': 'tool', 'tool_call_id': call['id'], 'content': '原结果'},
        ],
        'tools': [
            {
                'type': 'function',
                'function': {
                    'name': 'lookup',
                    'parameters': {'type': 'object', 'properties': {'value': {'type': 'integer'}}},
                },
            }
        ],
        'tool_choice': {'type': 'function', 'function': {'name': 'lookup'}},
        'parallel_tool_calls': False,
    }


def _contract(**values):
    return CodingRequestContract(
        **{
            'alias': 'walle-code',
            'model_name': 'fixture-provider-model',
            'input_cap': 100,
            'context_cap': 160,
            'output_cap': 80,
            'authorization_output_cap': 75,
            **values,
        }
    )


def test_exact_history_and_tool_arguments_are_preserved_while_policy_is_fixed():
    native = _request()
    prepared = prepare_request(parse_request(_bytes(native)), _contract())
    assert prepared.native == native
    assert prepared.supplier['messages'] == native['messages']
    assert prepared.supplier['tools'] == native['tools']
    assert prepared.supplier['max_tokens'] == prepared.output_cap == 60
    assert prepared.supplier['model'] == 'fixture-provider-model'
    assert prepared.supplier['stream_options'] == {'include_usage': True}
    assert prepared.supplier['thinking'] == {'type': 'disabled'}
    assert prepared.supplier['temperature'] == 0 and prepared.supplier['n'] == 1
    assert prepared.supplier['stream'] is True and prepared.supplier['service_tier'] == 'default'
    assert prepare_request({**native, 'max_tokens': 31}, _contract()).output_cap == 31


def test_openai_chat_projection_preserves_input_and_binds_endpoint():
    native = {**_request(), 'temperature': 0, 'max_tokens': 31, 'thinking': {'type': 'disabled'}}
    contract = _contract(model_name='gpt-6.2-sol', provider='openai')
    prepared = prepare_request(parse_request(_bytes(native)), contract)
    assert prepared.native == native
    assert contract.supplier_endpoint == 'https://api.openai.com/v1/chat/completions'
    assert (
        _contract().supplier_endpoint == 'https://ark.cn-beijing.volces.com/api/v3/chat/completions'
    )
    assert prepared.supplier == {
        key: value
        for key, value in native.items()
        if key not in ('temperature', 'max_tokens', 'thinking')
    } | {
        'model': 'gpt-6.2-sol',
        'stream': True,
        'n': 1,
        'service_tier': 'default',
        'stream_options': {'include_usage': True},
        'max_completion_tokens': 31,
        'store': False,
        'reasoning_effort': 'medium',
    }
    assert prepared.output_cap == 31 and prepared.supplier_body == _bytes(prepared.supplier)
    with pytest.raises(CodingModelProtocolError):
        _contract(model_name='gpt-6.2-sol', provider='openai', chunk_usage=True)


@pytest.mark.parametrize(
    'replacement',
    [
        {'model': 'provider-name'},
        {'endpoint': 'https://invalid'},
        {'store': True},
        {'temperature': False},
        {'stream': False},
        {'service_tier': 'priority'},
        {'n': True},
        {'max_tokens': 61},
        {'max_tokens': True},
        {'thinking': {'type': 'enabled'}},
        {'stream_options': {'include_usage': False}},
        {'stream_options': {'chunk_include_usage': True}},
        {'top_p': 0.5},
        {'tools': [{'type': 'remote'}]},
        {'tool_choice': 'any'},
        {'parallel_tool_calls': 0},
    ],
)
def test_unsupported_fields_and_policy_overrides_are_rejected(replacement):
    with pytest.raises(CodingModelProtocolError):
        prepare_request(parse_request(_bytes({**_request(), **replacement})), _contract())


@pytest.mark.parametrize(
    'change', ['attachment', 'missing', 'duplicate', 'wrong_result', 'external_schema']
)
def test_history_and_tool_schemas_reject_remote_or_unbound_inputs(change):
    value = deepcopy(_request())
    if change == 'attachment':
        value['messages'][1]['content'] = [
            {'type': 'image_url', 'image_url': {'url': 'https://invalid'}}
        ]
    elif change == 'missing':
        value['messages'].pop()
    elif change == 'duplicate':
        value['messages'].extend(value['messages'][2:])
    elif change == 'wrong_result':
        value['messages'][3]['tool_call_id'] = 'other'
    else:
        value['tools'][0]['function']['parameters']['$ref'] = 'https://invalid/schema'
    with pytest.raises(CodingModelProtocolError):
        prepare_request(parse_request(_bytes(value)), _contract())


def test_strict_bytes_limits_and_explicit_optional_contract():
    for raw in (
        b'{"model":"walle-code","model":"other","messages":[]}',
        b'{' * (REQUEST_BYTES + 1),
        b'{"model":"walle-code","messages":[],"top_p":1e999}',
    ):
        with pytest.raises(CodingModelProtocolError):
            parse_request(raw)
    value = {**_request(), 'top_p': 0.5, 'stream_options': {'chunk_include_usage': False}}
    prepared = prepare_request(
        parse_request(_bytes(value)),
        _contract(chunk_usage=True, optional_fields=frozenset({'top_p'})),
    )
    assert prepared.supplier['top_p'] == 0.5
    assert prepared.supplier['stream_options'] == {
        'include_usage': True,
        'chunk_include_usage': False,
    }
