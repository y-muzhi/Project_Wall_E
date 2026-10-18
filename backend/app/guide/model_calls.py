"""Read-only projections of the saved request, never reconstructed CURRENT."""
import json

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.validation import InvalidInput, strict_integer


def _json(text):
    try: return json.loads(text) if isinstance(text, str) else None
    except (ValueError, TypeError): return None


def _number(value):
    return value if type(value) is int and 0 <= value <= 9007199254740991 else None


def _identity(value):
    number = _number(value)
    return number if number and number >= 1 else None


def _dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _summary(row):
    cache = _json(row['cache_info_json'])
    cached = _number(cache.get('cached_tokens')) if isinstance(cache, dict) else None
    incoming, outgoing = _number(row['input_tokens']), _number(row['output_tokens'])
    return {key: row[key] for key in ('id', 'guide_run_id', 'call_no', 'attempt_no', 'model_name', 'call_status', 'parse_status', 'validation_status', 'started_at', 'ended_at')} | {
        'user_message_id': _identity(row['user_message_id']), 'document_version': _identity(row['document_version']),
        'input_tokens': incoming, 'output_tokens': outgoing,
        'total_tokens': None if incoming is None or outgoing is None else _number(incoming + outgoing),
        'cached_tokens': cached, 'duration_ms': _number(row['duration_ms'])}


# Extract the small identity fields in SQLite; list responses never include or
# parse the entire (potentially large) request snapshot in Python.
CALL_COLUMNS = """l.id,l.guide_run_id,l.call_no,l.attempt_no,l.model_name,l.call_status,l.parse_status,l.validation_status,
 l.input_tokens,l.output_tokens,l.cache_info_json,l.duration_ms,l.started_at,l.ended_at,
 CASE WHEN json_valid(l.request_snapshot_json) THEN CASE WHEN json_valid(json_extract(l.request_snapshot_json,'$.request.messages[1].content')) THEN coalesce(
 json_extract(l.request_snapshot_json,'$.request.messages[1].content') ->> '$.current_request.user_message_id',
 json_extract(l.request_snapshot_json,'$.request.messages[1].content') ->> '$.request_metadata.user_message_id',
 json_extract(l.request_snapshot_json,'$.request.messages[1].content') ->> '$.user_input.message_id') END END AS user_message_id,
 CASE WHEN json_valid(l.request_snapshot_json) THEN CASE WHEN json_valid(json_extract(l.request_snapshot_json,'$.request.messages[1].content')) THEN coalesce(
 json_extract(l.request_snapshot_json,'$.request.messages[1].content') ->> '$.current_request.document_ref.content_version',
 json_extract(l.request_snapshot_json,'$.request.messages[1].content') ->> '$.request_metadata.current_document.content_version',
 json_extract(l.request_snapshot_json,'$.request.messages[1].content') ->> '$.current_document.content_version') END END AS document_version"""


def list_model_calls(database, guide_run_id):
    try: identity = strict_integer(guide_run_id, 'guide_run_id')
    except InvalidInput as error: return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            run = connection.execute('SELECT id,requirement_id,action_type,status,current_step,trigger_message_id FROM guide_runs WHERE id=?', (identity,)).fetchone()
            if run is None: return {'code': 'NOT_FOUND', 'data': None, 'details': None}
            rows = connection.execute('SELECT ' + CALL_COLUMNS + ' FROM llm_uses l WHERE l.guide_run_id=? ORDER BY l.call_no,l.attempt_no,l.id', (identity,)).fetchall()
            program = connection.execute("SELECT 1 FROM conversation_messages WHERE guide_run_id=? AND role='ASSISTANT' AND content LIKE '程序已%'", (identity,)).fetchone()
            data = dict(run) | {'program_processed': not rows and bool(program), 'items': [_summary(row) for row in rows]}
            return {'code': 'READ_OK', 'data': data, 'details': None}
    except StorageUnavailable: return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception: return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}


def _sections(request):
    sections, wire = [], None
    names = {'template': '完整模板', 'current_document': '当前正文与读取区块', 'history': '历史消息',
             'user_input': '本轮用户输入', 'source': '来源信息', 'request_metadata': '身份、范围与权限',
             'requirement': '需求信息', 'scope': '操作范围', 'allowed_targets': '写入权限', 'read_manifest': '实际读取清单',
             'task': '本轮任务', 'section_index': '章节索引', 'document_context': '当前正文与读取区块',
             'recent_history': '历史消息', 'current_request': '本轮输入、范围与候选操作'}
    messages = request.get('messages')
    for index, message in enumerate(messages if isinstance(messages, list) else []):
        if not isinstance(message, dict) or not isinstance(message.get('content'), str): continue
        content = message['content']; role = message.get('role', 'unknown')
        value = _json(content) if role == 'user' else None
        if isinstance(value, dict) and ('user_input' in value or value.get('input_version') == 'context_projection_v1'):
            wire = value
            for key, part in value.items():
                if key not in names: continue
                text = _dump(part)
                count = len(part) if isinstance(part, list) else None
                if key in ('current_document', 'document_context') and isinstance(part, dict) and isinstance(part.get('read_blocks'), list): count = len(part['read_blocks'])
                sections.append({'key': f'{index}:{key}', 'title': names[key], 'content': text, 'characters': len(text), 'item_count': count})
        else:
            sections.append({'key': str(index), 'title': '系统提示词与输出格式约束' if role == 'system' else f'{role} 消息',
                             'content': content, 'characters': len(content), 'item_count': None})
    return sections, wire


def get_model_call(database, llm_use_id):
    try: identity = strict_integer(llm_use_id, 'llm_use_id')
    except InvalidInput as error: return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            row = connection.execute('SELECT ' + CALL_COLUMNS + ',l.request_snapshot_json,g.requirement_id,g.action_type FROM llm_uses l JOIN guide_runs g ON g.id=l.guide_run_id WHERE l.id=?', (identity,)).fetchone()
            if row is None: return {'code': 'NOT_FOUND', 'data': None, 'details': None}
            snapshot = _json(row['request_snapshot_json'])
            snapshot = snapshot if isinstance(snapshot, dict) else {}
            request = snapshot.get('request')
            # The audited Chat body is the snapshot source. Profile and
            # count-journal internals are outside this object and stay private.
            request = request if isinstance(request, dict) else None
            sections, wire = _sections(request or {})
            protocol = snapshot.get('protocol') or {}
            protocol = protocol if isinstance(protocol, dict) else {}
            counting = snapshot.get('counting') or {}
            counting = counting if isinstance(counting, dict) else {}
            attempts = counting.get('count_attempts', [])
            attempts = attempts if isinstance(attempts, list) else []
            final = attempts[-1] if attempts and isinstance(attempts[-1], dict) else {}
            measurement = final.get('measurement') or {}
            counts = measurement.get('counts') if isinstance(measurement, dict) else None
            counts = counts if isinstance(counts, list) and len(counts) == 6 else [None] * 6
            budget = None
            if counting.get('release_sha256'):
                try:
                    from .counted_context import counting_release
                    from backend.app.infrastructure.model_profile import ModelProfile
                    budget = counting_release(ModelProfile.from_snapshot(snapshot['profile']), release_sha256=counting['release_sha256'])['budget']
                except (ValueError, KeyError, RuntimeError): pass
            metadata = wire.get('request_metadata', {}) if isinstance(wire, dict) else {}
            metadata = metadata if isinstance(metadata, dict) else {}
            history = wire.get('recent_history', wire.get('history', [])) if isinstance(wire, dict) else []
            refs = metadata.get('history_message_refs', history)
            included = [item['id'] for item in refs if isinstance(item, dict) and _number(item.get('id'))] if isinstance(refs, list) else []
            trimmed = final.get('removed_history_ids', [])
            trimmed = [item for item in trimmed if _number(item)] if isinstance(trimmed, list) else []
            strategy = wire.get('input_version') if isinstance(wire, dict) else None
            strategy = strategy if strategy == 'context_projection_v1' else None
            selection = None
            if strategy:
                basis = snapshot.get('context_basis')
                saved = basis.get('selection', {}) if isinstance(basis, dict) else {}
                target = _number(saved.get('soft_input_target')) if isinstance(saved, dict) else None
                document_part = wire.get('document_context')
                blocks = document_part.get('read_blocks') if isinstance(document_part, dict) else None
                estimate = _number(counting.get('input_tokens_candidate'))
                selection = {'read_blocks': len(blocks) if isinstance(blocks, list) else None,
                    'history_messages': len(history) if isinstance(history, list) else None,
                    'soft_input_target': target, 'count_attempts': len(attempts) if isinstance(counting.get('count_attempts'), list) else None,
                    'soft_target_exceeded': None if target is None or estimate is None else estimate > target}
            data = {'call': _summary(row), 'requirement_id': row['requirement_id'], 'action_type': row['action_type'],
                'prompt_reference': protocol.get('prompt') if isinstance(protocol.get('prompt'), str) else None,
                'context_reference': protocol.get('context_template') if isinstance(protocol.get('context_template'), str) else None,
                'context_strategy': strategy, 'selection_summary': selection,
                'sections': sections, 'included_history_ids': included, 'budget_removed_history_ids': trimmed,
                'raw_request_json': None if request is None else _dump(request),
                'preflight': {'input_tokens': _number(counting.get('input_tokens_candidate')), 'budget': budget,
                    'counts': [ _number(value) for value in counts ]}}
            return {'code': 'READ_OK', 'data': data, 'details': None}
    except StorageUnavailable: return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception: return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
