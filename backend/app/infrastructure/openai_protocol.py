"""Native OpenAI Responses protocol; no Ark envelope or credentials in snapshots."""

import json

from .resources import ConfigInvalid
from .schema_transport import compact

BASE_URL = 'https://api.openai.com/v1'
ENDPOINT = BASE_URL + '/responses'
COUNT_ENDPOINT = ENDPOINT + '/input_tokens'
MODEL = 'gpt-6.2-sol'
PROFILE = 'openai-sol-v1'


def snapshot(output_limit):
    return {
        'provider': 'openai',
        'model_name': MODEL,
        'model_version': MODEL,
        'model_identity': 'alias',
        'endpoint': ENDPOINT,
        'max_output_tokens': output_limit,
        'reasoning': {'effort': 'medium'},
        'store': False,
        'stream': False,
        'truncation': 'disabled',
        'timeouts': {'connect': 10, 'read': 180, 'write': 10, 'pool': 10},
        'transport_retries': 0,
    }


def request(context, output_limit):
    from .openai_schema import output_format

    if type(context.system) is not str or not context.system:
        raise ConfigInvalid('OpenAI developer protocol is required')
    json.loads(context.input_json)
    return {
        'model': MODEL,
        'input': [
            {'role': 'developer', 'content': context.system},
            {'role': 'user', 'content': context.input_json},
        ],
        'text': {'format': output_format(context)},
        'reasoning': {'effort': 'medium'},
        'max_output_tokens': output_limit,
        'store': False,
        'stream': False,
        'truncation': 'disabled',
    }


def count_request(body):
    # The count endpoint accepts semantic input/format/reasoning, not generation
    # controls such as max_output_tokens or persistence/streaming settings.
    if body.get('model') != MODEL or set(body) != {
        'model',
        'input',
        'text',
        'reasoning',
        'max_output_tokens',
        'store',
        'stream',
        'truncation',
    }:
        raise ConfigInvalid('Unknown OpenAI request shape')
    return {key: body[key] for key in ('model', 'input', 'text', 'reasoning', 'truncation')}


def output_text(raw, *, complete=True):
    """Read actual native messages without manufacturing a chat.completion."""
    if type(raw) is not dict or raw.get('object') != 'response':
        raise ValueError('A native OpenAI response is required')
    if complete and (
        raw.get('status') != 'completed'
        or raw.get('error') is not None
        or raw.get('incomplete_details') is not None
    ):
        raise ValueError('OpenAI response is incomplete')
    output = raw.get('output')
    if type(output) is not list:
        raise ValueError('OpenAI output is missing')
    messages = []
    for item in output:
        if type(item) is not dict:
            raise ValueError('OpenAI output item is invalid')
        if item.get('type') == 'reasoning':
            continue  # Private reasoning is never document JSON.
        if item.get('type') != 'message' or item.get('role') != 'assistant':
            raise ValueError('Unexpected tool or output type')
        if complete and item.get('status') != 'completed':
            raise ValueError('OpenAI assistant message is incomplete')
        content = item.get('content')
        if type(content) is not list or not content:
            raise ValueError('OpenAI assistant content is missing')
        text = []
        for part in content:
            if (
                type(part) is not dict
                or part.get('type') != 'output_text'
                or type(part.get('text')) is not str
            ):
                raise ValueError('OpenAI content is refused or not text')
            text.append(part['text'])
        messages.append(''.join(text))
    if len(messages) != 1 or not messages[0]:
        raise ValueError('OpenAI requires one unambiguous assistant message')
    return messages[0]


def usage(raw):
    value = raw['usage']
    if type(value) is not dict:
        raise ValueError('OpenAI actual usage is missing')
    numbers = [value.get(key) for key in ('input_tokens', 'output_tokens', 'total_tokens')]
    if any(type(number) is not int or not 0 <= number <= 9007199254740991 for number in numbers):
        raise ValueError('OpenAI actual token usage is invalid')
    incoming, outgoing, total = numbers
    if total != incoming + outgoing:
        raise ValueError('OpenAI actual token total differs')
    details = value.get('input_tokens_details')
    if details is not None:
        if (
            type(details) is not dict
            or type(details.get('cached_tokens')) is not int
            or not 0 <= details['cached_tokens'] <= incoming
        ):
            raise ValueError('OpenAI cached usage is invalid')
    return incoming, outgoing, details


def digest(value):
    from hashlib import sha256

    return sha256(compact(value).encode('utf-8')).hexdigest()
