"""One explicit Ark DeepSeek connectivity test, never a production adapter.

Offline by default. One durable local attempt slot; no retries or redirects.
Only --execute reads the ignored .env.local credential. No business DB access.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from time import monotonic

import httpx

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'deepseek-v4-1-flash-260910'
ENDPOINT = 'https://ark.cn-beijing.volces.com/api/v3/chat/completions'
BODY = {
    'model': MODEL,
    'messages': [
        {'role': 'system', 'content': '这是连通性测试。只输出OK。'},
        {'role': 'user', 'content': '请仅回复：OK'},
    ],
    'max_tokens': 128,
    'stream': False,
    'thinking': {'type': 'disabled'},
}
LIMITS = {'maximum_chat_requests': 1, 'tokenization_requests': 0, 'retries': 0,
          'maximum_output_tokens': 128, 'maximum_input_utf8_bytes': 200,
          'wall_timeout_seconds': 45, 'maximum_response_bytes': 65536}


def credential(path):
    """Read only the named assignment, as data; never evaluate dotenv content."""
    if path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError('Invalid local credential file')
    values = []
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        left, separator, right = line.partition('=')
        if separator and left.strip() == 'WALLE_MODEL_API_KEY':
            value = right.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values.append(value)
    if len(values) != 1:
        raise ValueError('Exactly one WALLE_MODEL_API_KEY assignment is required')
    value = values[0]
    if not value or len(value) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError('Local credential is missing or invalid')
    return value


def save(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        handle.flush()
        os.fsync(handle.fileno())


def count(value):
    return value if type(value) is int and 0 <= value <= 9007199254740991 else None


def safe(value, key, limit):
    return value.replace(key, '[REDACTED]')[:limit] if type(value) is str else None


async def invoke(key, *, transport=None):
    started = monotonic()
    result = {'passed': False, 'adapter_invocations': 1, 'http_status': None,
              'outcome': 'UNKNOWN', 'actual_charge': None, 'production_enabled': False,
              'provider_compatibility_proved': False, 'model_effects_proved': False}
    selected = transport if transport is not None else httpx.AsyncHTTPTransport(retries=0, trust_env=False)
    try:
        async with asyncio.timeout(LIMITS['wall_timeout_seconds']):
            async with httpx.AsyncClient(transport=selected, trust_env=False, follow_redirects=False,
                                         timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10)) as client:
                async with client.stream('POST', ENDPOINT, headers={'Authorization': 'Bearer ' + key}, json=BODY) as response:
                    result['http_status'] = response.status_code
                    parts = []; size = 0
                    async for part in response.aiter_bytes():
                        size += len(part)
                        if size > LIMITS['maximum_response_bytes']:
                            result['outcome'] = 'RESPONSE_CAPACITY'; return result
                        parts.append(part)
                    try:
                        envelope = json.loads(b''.join(parts))
                    except (ValueError, UnicodeError):
                        result['outcome'] = 'RESPONSE_PROTOCOL'; return result
                    if type(envelope) is not dict:
                        result['outcome'] = 'RESPONSE_PROTOCOL'; return result
                    if response.status_code != 200 or 'error' in envelope:
                        error = envelope.get('error')
                        result['error_code'] = safe(error.get('code'), key, 128) if type(error) is dict else None
                        result['outcome'] = 'HTTP_ERROR'; return result
                    result['returned_model'] = safe(envelope.get('model'), key, 128)
                    usage = envelope.get('usage')
                    if type(usage) is dict:
                        result['usage'] = {field: count(usage.get(field)) for field in
                                           ('prompt_tokens', 'completion_tokens', 'total_tokens')}
                    choices = envelope.get('choices')
                    if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
                        result['outcome'] = 'RESPONSE_PROTOCOL'; return result
                    choice = choices[0]; message = choice.get('message')
                    if type(message) is not dict:
                        result['outcome'] = 'RESPONSE_PROTOCOL'; return result
                    content = message.get('content')
                    result['reply'] = safe(content, key, 128)
                    result['finish_reason'] = safe(choice.get('finish_reason'), key, 32)
                    result['passed'] = (envelope.get('model') == MODEL and message.get('role') == 'assistant'
                                        and type(content) is str and content.strip() == 'OK'
                                        and choice.get('finish_reason') == 'stop'
                                        and not message.get('tool_calls') and not message.get('refusal'))
                    result['outcome'] = 'COMPLETED' if result['passed'] else 'RESPONSE_MISMATCH'
    except (httpx.HTTPError, TimeoutError):
        # Failure can follow remote acceptance: never automatically resend.
        result['outcome'] = 'TRANSPORT_UNKNOWN'
    finally:
        result['duration_ms'] = round((monotonic() - started) * 1000)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--attempt', type=int, choices=(1, 2, 3), default=1,
                        help='Slots 2/3 require the separate human authorizations after credential correction/model activation')
    args = parser.parse_args()
    description = {'scope': 'One short connectivity test only; no normal DB or production model change',
                   'model': MODEL, 'endpoint': ENDPOINT, 'request': BODY, 'limits': LIMITS}
    actual_bytes = sum(len(message['content'].encode('utf-8')) for message in BODY['messages'])
    if actual_bytes > LIMITS['maximum_input_utf8_bytes']:
        raise ValueError('Input exceeds fixed test cap')
    description['actual_input_utf8_bytes'] = actual_bytes
    if not args.execute:
        print(json.dumps({**description, 'paid_requests': 0}, ensure_ascii=False)); return
    key = credential(ROOT / '.env.local')
    # The human authorized this one batch on 2026-10-07. Reusing the same
    # directory is refused, including after an interrupted/unknown outcome.
    slot = 'one-shot-2026-10-07' + (f'-{args.attempt}' if args.attempt != 1 else '')
    directory = ROOT / 'output/model-smoke' / slot
    directory.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir()
    save(directory / 'prepared.json', {**description, 'attempt_slot': args.attempt,
                                      'recorded_at': datetime.now(timezone.utc).isoformat(),
                                      'prepared_is_not_proof_of_send_or_charge': True})
    result = asyncio.run(invoke(key))
    save(directory / 'finished.json', result)
    print(json.dumps({'evidence': str(directory / 'finished.json'), **result}, ensure_ascii=False))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError):
        print('Test refused; check local configuration or existing attempt record. No automatic resend.', file=sys.stderr)
        raise SystemExit(1)
