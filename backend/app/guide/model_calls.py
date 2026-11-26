"""Read-only projections of the saved request, never reconstructed CURRENT."""

import json

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.resources import ConfigInvalid, ResourceCatalog
from backend.app.shared.validation import InvalidInput, strict_integer


def _json(text):
    try:
        return json.loads(text) if isinstance(text, str) else None
    except (ValueError, TypeError):
        return None


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
    return {
        key: row[key]
        for key in (
            'id',
            'guide_run_id',
            'call_no',
            'attempt_no',
            'model_name',
            'call_status',
            'parse_status',
            'validation_status',
            'started_at',
            'ended_at',
        )
    } | {
        'user_message_id': _identity(row['user_message_id']),
        'document_version': _identity(row['document_version']),
        'input_tokens': incoming,
        'output_tokens': outgoing,
        'total_tokens': _number(row['actual_total_tokens']),
        'cached_tokens': cached,
        'duration_ms': _number(row['duration_ms']),
    }


# Extract the small identity fields in SQLite; list responses never include or
# parse the entire (potentially large) request snapshot in Python.
CALL_COLUMNS = """l.id,l.guide_run_id,l.call_no,l.attempt_no,l.model_name,l.call_status,l.parse_status,l.validation_status,
 l.input_tokens,l.output_tokens,l.cache_info_json,l.duration_ms,l.started_at,l.ended_at,
 CASE WHEN json_valid(l.raw_response_json) THEN CASE WHEN json_type(l.raw_response_json,'$.usage.total_tokens')='integer'
 THEN json_extract(l.raw_response_json,'$.usage.total_tokens') END END AS actual_total_tokens,
 CASE WHEN json_valid(l.request_snapshot_json) THEN CASE WHEN json_valid(coalesce(json_extract(l.request_snapshot_json,'$.request.messages[1].content'),json_extract(l.request_snapshot_json,'$.request.input[1].content'))) THEN coalesce(
 coalesce(json_extract(l.request_snapshot_json,'$.request.messages[1].content'),json_extract(l.request_snapshot_json,'$.request.input[1].content')) ->> '$.current_request.message_id',
 coalesce(json_extract(l.request_snapshot_json,'$.request.messages[1].content'),json_extract(l.request_snapshot_json,'$.request.input[1].content')) ->> '$.current_request.user_message_id',
 coalesce(json_extract(l.request_snapshot_json,'$.request.messages[1].content'),json_extract(l.request_snapshot_json,'$.request.input[1].content')) ->> '$.request_metadata.user_message_id',
 coalesce(json_extract(l.request_snapshot_json,'$.request.messages[1].content'),json_extract(l.request_snapshot_json,'$.request.input[1].content')) ->> '$.user_input.message_id') END END AS user_message_id,
 CASE WHEN json_valid(l.request_snapshot_json) THEN CASE WHEN json_valid(coalesce(json_extract(l.request_snapshot_json,'$.request.messages[1].content'),json_extract(l.request_snapshot_json,'$.request.input[1].content'))) THEN coalesce(
 json_extract(l.request_snapshot_json,'$.context_basis.canonical.authorization.expected_content_version'),
 coalesce(json_extract(l.request_snapshot_json,'$.request.messages[1].content'),json_extract(l.request_snapshot_json,'$.request.input[1].content')) ->> '$.current_request.document_ref.content_version',
 coalesce(json_extract(l.request_snapshot_json,'$.request.messages[1].content'),json_extract(l.request_snapshot_json,'$.request.input[1].content')) ->> '$.request_metadata.current_document.content_version',
 coalesce(json_extract(l.request_snapshot_json,'$.request.messages[1].content'),json_extract(l.request_snapshot_json,'$.request.input[1].content')) ->> '$.current_document.content_version') END END AS document_version"""


# Select only the resource references and small profile needed to resolve the budget.
CALL_BUDGET_REFERENCE = """CASE WHEN json_valid(l.request_snapshot_json) THEN
 json_extract(l.request_snapshot_json,'$.protocol.function_type','$.protocol.release',
 '$.counting.counting_resource','$.counting.release_sha256','$.profile')
 END AS budget_reference"""


def _collaboration_budget(resources, reference):
    if reference is None:
        return None
    fixed = _json(resources.content(reference))
    return {
        'total_tokens': fixed['total_limit'],
        'input_tokens': fixed['input_limit'],
        'output_tokens': fixed['output_limit'],
        'framing_reserve': fixed['framing_reserve'],
        'soft_input_target': fixed['soft_input_target'],
        'counting': fixed['admission_mode'],
    }


def _legacy_budget(release_digest, profile):
    if not release_digest:
        return None
    from backend.app.infrastructure.model_profile import ModelProfile

    from .counted_context import counting_release

    try:
        return counting_release(ModelProfile.from_snapshot(profile), release_sha256=release_digest)[
            'budget'
        ]
    except (ValueError, KeyError, RuntimeError):
        return None


def _saved_input_limit(reference_json, catalog):
    if reference_json is None:
        return None
    function_type, release, counting_reference, digest, profile = _json(reference_json)
    if function_type == 'collaboration_v1':
        if counting_reference is None:
            return None
        try:
            resources = catalog.for_collaboration_release(release).collaboration
            budget = _collaboration_budget(resources, counting_reference)
        except (ConfigInvalid, KeyError, TypeError):
            return None
    else:
        budget = _legacy_budget(digest, profile)
    return _identity(budget['input_tokens']) if budget else None


def list_model_calls(database, guide_run_id, *, include_input_limit=False, catalog=None):
    try:
        identity = strict_integer(guide_run_id, 'guide_run_id')
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            run = connection.execute(
                'SELECT id,requirement_id,action_type,operation,status,current_step,trigger_message_id FROM guide_runs WHERE id=?',
                (identity,),
            ).fetchone()
            if run is None:
                return {'code': 'NOT_FOUND', 'data': None, 'details': None}
            columns = CALL_COLUMNS
            if include_input_limit:
                columns += ',' + CALL_BUDGET_REFERENCE
            rows = connection.execute(
                'SELECT '
                + columns
                + ' FROM llm_uses l WHERE l.guide_run_id=? ORDER BY l.call_no,l.attempt_no,l.id',
                (identity,),
            ).fetchall()
            program = connection.execute(
                "SELECT 1 FROM conversation_messages WHERE guide_run_id=? AND role='ASSISTANT' AND content LIKE '程序已%'",
                (identity,),
            ).fetchone()
            items = [_summary(row) for row in rows]
            if include_input_limit:
                catalog = catalog if catalog is not None else ResourceCatalog()
                input_limits = {}
                for row, item in zip(rows, items, strict=True):
                    reference = row['budget_reference']
                    if reference not in input_limits:
                        input_limits[reference] = _saved_input_limit(reference, catalog)
                    item['input_token_limit'] = input_limits[reference]
            data = dict(run) | {
                'program_processed': not rows and bool(program),
                'items': items,
            }
            return {'code': 'READ_OK', 'data': data, 'details': None}
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}


def _sections(request):
    sections, wire = [], None
    names = {
        'template': '完整模板',
        'current_document': '当前正文与读取区块',
        'history': '历史消息',
        'user_input': '本轮用户输入',
        'source': '来源信息',
        'request_metadata': '身份、范围与权限',
        'requirement': '需求信息',
        'scope': '操作范围',
        'allowed_targets': '写入权限',
        'read_manifest': '实际读取清单',
        'task': '本轮任务',
        'section_index': '章节索引',
        'document_context': '当前正文与读取区块',
        'recent_history': '历史消息',
        'current_request': '本轮输入、范围与候选操作',
    }
    messages = request.get('messages')
    for index, message in enumerate(messages if isinstance(messages, list) else []):
        if not isinstance(message, dict) or not isinstance(message.get('content'), str):
            continue
        content = message['content']
        role = message.get('role', 'unknown')
        value = _json(content) if role == 'user' else None
        if isinstance(value, dict) and (
            'user_input' in value or value.get('input_version') == 'context_projection_v1'
        ):
            wire = value
            for key, part in value.items():
                if key not in names:
                    continue
                text = _dump(part)
                count = len(part) if isinstance(part, list) else None
                if (
                    key in ('current_document', 'document_context')
                    and isinstance(part, dict)
                    and isinstance(part.get('read_blocks'), list)
                ):
                    count = len(part['read_blocks'])
                sections.append(
                    {
                        'key': f'{index}:{key}',
                        'title': names[key],
                        'content': text,
                        'characters': len(text),
                        'item_count': count,
                    }
                )
        else:
            sections.append(
                {
                    'key': str(index),
                    'title': '系统提示词与输出格式约束' if role == 'system' else f'{role} 消息',
                    'content': content,
                    'characters': len(content),
                    'item_count': None,
                }
            )
    return sections, wire


def _collaboration_detail(row, snapshot, *, catalog=None):
    """Project saved bytes and measurements only; never compile or count on GET."""
    catalog = catalog if catalog is not None else ResourceCatalog()
    resources = catalog.for_collaboration_release(snapshot['protocol']['release']).collaboration
    request = snapshot.get('request')
    protocol = snapshot.get('protocol') or {}
    counting = snapshot.get('counting') or {}
    basis = snapshot.get('context_basis') or {}
    sections = []
    wire = None
    messages = request.get('messages', []) if isinstance(request, dict) else []
    openai_count = snapshot.get('profile', {}).get('provider') == 'openai'
    if openai_count:
        native = request.get('input', [])
        if len(native) == 2 and [item.get('role') for item in native] == ['developer', 'user']:
            messages = [
                {'role': 'system', 'content': native[0]['content']},
                {'role': 'user', 'content': native[1]['content']},
            ]

    if len(messages) == 2 and [message.get('role') for message in messages] == ['system', 'user']:
        system = messages[0].get('content')
        wire = _json(messages[1].get('content'))
        resources.validate('Wire', wire)
        if not isinstance(system, str):
            raise ValueError('Actual saved system text required')
        sections.append(
            {
                'key': 'system',
                'title': '系统规则与阶段指引',
                'content': system,
                'characters': len(system),
                'item_count': 1,
            }
        )
        names = [
            ('structure', '文档结构'),
            ('goal_and_decisions', '需求与已确认内容'),
            ('project_position', '项目进展'),
            ('current_topic', '当前主题'),
            ('documents', '文档内容'),
            ('recent_history', '历史消息'),
            ('current_request', '本轮输入'),
        ]
        for key, title in names:
            part = wire[key]
            text = _dump(part)
            number = (
                (0 if part is None else 1)
                if key in ('structure', 'current_topic', 'current_request')
                else len(part)
            )
            if key == 'project_position':
                number = len(part['mainlines'])
            if key == 'documents':
                number = sum(len(document['blocks']) for document in part)
            sections.append(
                {
                    'key': key,
                    'title': title,
                    'content': text,
                    'characters': len(text),
                    'item_count': number,
                }
            )
    attempts = counting.get('count_attempts')
    attempts = attempts if isinstance(attempts, list) else []
    final = attempts[-1] if attempts and isinstance(attempts[-1], dict) else {}
    measurement = final.get('measurement') or {}
    counts = measurement.get('counts')
    counts = (
        [_number(value) for value in counts]
        if isinstance(counts, list) and len(counts) == 8
        else [None] * 8
    )
    if openai_count:
        counts = [_number(measurement.get('request_tokens'))]
    budget = _collaboration_budget(resources, counting.get('counting_resource'))
    selection = None
    if wire is not None:
        resources.validate('ContextBasis', basis)
        selected = basis['selected']
        omitted = basis['omitted']
        selection = {
            'read_blocks': sum(len(document['blocks']) for document in wire['documents']),
            'history_messages': len(wire['recent_history']),
            'soft_input_target': _number(counting.get('soft_input_target')),
            'count_attempts': len(attempts),
            'soft_target_exceeded': counting.get('soft_target_exceeded')
            if type(counting.get('soft_target_exceeded')) is bool
            else None,
            'selected_materials': selected,
            'omitted_materials': omitted,
            'resource_refs': [item['resource_ref'] for item in basis['canonical']['resources']],
        }
    history = wire['recent_history'] if wire else []
    aliases = {item['ref']: item['source_refs'] for item in basis.get('aliases', [])}
    included = list(
        dict.fromkeys(
            source['message_id']
            for item in history
            for source in aliases.get(item['ref'], [])
            if source['kind'] in ('MESSAGE', 'CARD_ANSWER')
        )
    )
    removed = list(
        dict.fromkeys(
            source['message_id']
            for item in basis.get('omitted', [])
            if item['reason'] == 'BUDGET_OPTIONAL_HISTORY'
            for source in item['source_refs']
            if source['kind'] in ('MESSAGE', 'CARD_ANSWER')
        )
    )
    prompt = protocol.get('prompt')
    return {
        'call': _summary(row),
        'requirement_id': row['requirement_id'],
        'action_type': row['action_type'],
        'operation': row['operation'],
        'prompt_reference': prompt if isinstance(prompt, str) else None,
        'context_reference': 'collaboration_context_v1',
        'context_strategy': 'collaboration_context_v1',
        'selection_summary': selection,
        'sections': sections,
        'included_history_ids': included,
        'budget_removed_history_ids': removed,
        'raw_request_json': _dump(request) if isinstance(request, dict) else None,
        'preflight': {
            'input_tokens': _number(counting.get('input_tokens_candidate')),
            'budget': budget,
            'counts': counts,
        },
    }


def get_model_call(database, llm_use_id, *, catalog=None):
    try:
        identity = strict_integer(llm_use_id, 'llm_use_id')
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            row = connection.execute(
                'SELECT '
                + CALL_COLUMNS
                + ',l.request_snapshot_json,g.requirement_id,g.action_type,g.operation FROM llm_uses l JOIN guide_runs g ON g.id=l.guide_run_id WHERE l.id=?',
                (identity,),
            ).fetchone()
            if row is None:
                return {'code': 'NOT_FOUND', 'data': None, 'details': None}
            snapshot = _json(row['request_snapshot_json'])
            snapshot = snapshot if isinstance(snapshot, dict) else {}
            if snapshot.get('protocol', {}).get('function_type') == 'collaboration_v1':
                return {
                    'code': 'READ_OK',
                    'data': _collaboration_detail(row, snapshot, catalog=catalog),
                    'details': None,
                }
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
            budget = _legacy_budget(counting.get('release_sha256'), snapshot.get('profile'))
            metadata = wire.get('request_metadata', {}) if isinstance(wire, dict) else {}
            metadata = metadata if isinstance(metadata, dict) else {}
            history = (
                wire.get('recent_history', wire.get('history', []))
                if isinstance(wire, dict)
                else []
            )
            refs = metadata.get('history_message_refs', history)
            included = (
                [item['id'] for item in refs if isinstance(item, dict) and _number(item.get('id'))]
                if isinstance(refs, list)
                else []
            )
            trimmed = final.get('removed_history_ids', [])
            trimmed = (
                [item for item in trimmed if _number(item)] if isinstance(trimmed, list) else []
            )
            strategy = wire.get('input_version') if isinstance(wire, dict) else None
            strategy = strategy if strategy == 'context_projection_v1' else None
            selection = None
            if strategy:
                basis = snapshot.get('context_basis')
                saved = basis.get('selection', {}) if isinstance(basis, dict) else {}
                target = (
                    _number(saved.get('soft_input_target')) if isinstance(saved, dict) else None
                )
                document_part = wire.get('document_context')
                blocks = (
                    document_part.get('read_blocks') if isinstance(document_part, dict) else None
                )
                estimate = _number(counting.get('input_tokens_candidate'))
                selection = {
                    'read_blocks': len(blocks) if isinstance(blocks, list) else None,
                    'history_messages': len(history) if isinstance(history, list) else None,
                    'soft_input_target': target,
                    'count_attempts': len(attempts)
                    if isinstance(counting.get('count_attempts'), list)
                    else None,
                    'soft_target_exceeded': None
                    if target is None or estimate is None
                    else estimate > target,
                }
            data = {
                'call': _summary(row),
                'requirement_id': row['requirement_id'],
                'action_type': row['action_type'],
                'operation': row['operation'],
                'prompt_reference': protocol.get('prompt')
                if isinstance(protocol.get('prompt'), str)
                else None,
                'context_reference': protocol.get('context_template')
                if isinstance(protocol.get('context_template'), str)
                else None,
                'context_strategy': strategy,
                'selection_summary': selection,
                'sections': sections,
                'included_history_ids': included,
                'budget_removed_history_ids': trimmed,
                'raw_request_json': None if request is None else _dump(request),
                'preflight': {
                    'input_tokens': _number(counting.get('input_tokens_candidate')),
                    'budget': budget,
                    'counts': [_number(value) for value in counts],
                },
            }
            return {'code': 'READ_OK', 'data': data, 'details': None}
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
