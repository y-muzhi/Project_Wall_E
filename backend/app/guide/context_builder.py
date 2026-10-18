"""Frozen ContextTemplate assembly and approved conservative byte budget.

This release cannot prove Provider token compatibility. The conservative gate
is enforced, including the complete System schema; it never calls a Provider.
"""
from dataclasses import dataclass, field
import json

from backend.app.infrastructure.resources import FrozenFunction, ProtocolInvalid
from backend.app.shared.validation import strict_json_object
from backend.app.documents.markdown import parse_markdown


class ContextLimitExceeded(ValueError):
    code = 'CONTEXT_LIMIT_EXCEEDED'


def _serialize(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _bytes(value):
    return len(_serialize(value).encode('utf-8'))


@dataclass(frozen=True)
class BuiltContext:
    system: str
    input_json: str
    manifest_json: str
    input_bytes: int
    removed_history_ids: tuple[int, ...]
    removed_neighbor_ids: tuple[int, ...]
    basis_json: str | None = field(default=None, repr=False, kw_only=True)

    @property
    def input(self):
        return strict_json_object(self.input_json)


def assemble_input(context, function: FrozenFunction):
    """Exact model input from the complete trusted C03 snapshot, before budget."""
    root, current, user = context['requirement'], context['current_document'], context['user_input']
    run, scope = context['run'], context['scope']
    if run['function_type'] != function.function_type or run['action_type'] != function.action_type or run['source_type'] != function.source_type:
        raise ValueError('Context must bind the frozen run Function')
    manifest = function.validate_read_manifest(context['read_manifest'])
    if manifest['function_type'] != function.function_type or manifest['document_id'] != current['id'] or manifest['content_version'] != current['content_version']:
        raise ValueError('Context manifest must bind the actual current identity and version')
    parsed = parse_markdown(current['markdown_content'])
    metadata = current['block_state_json']['blocks']
    if len(metadata) != len(parsed.blocks): raise ValueError('Context must retain its complete document pair')
    allowed = function.validate_allowed_targets({'schema_version': 1, 'targets': context['allowed_targets']})['targets']
    # Scope reading and stored grants stay separate; adjacent read blocks
    # cannot become writable by being included in this serialized input.
    value = {'schema_version': 1, 'function_type': function.function_type, 'action_type': function.action_type, 'source_type': function.source_type,
        'requirement': {'id': root['id'], 'requirement_no': root['requirement_no'], 'requirement_type': root['requirement_type'],
            'title': root['title'], 'status': root['status'], 'initialization_mode': run['mode_snapshot'] if function.action_type == 'INITIALIZE' else root['initialization_mode']},
        'current_document': {'id': current['id'], 'content_version': current['content_version'], 'read_blocks': [
            {'metadata': item, 'markdown_content': block.markdown, 'plain_text': block.plain_text, 'heading_level': block.heading_level}
            for block, item in zip(parsed.blocks, metadata) if item['block_id'] in scope['read_block_ids']]},
        'template': context['template'], 'scope': {key: scope[key] for key in ('scope_type', 'scope_ref')}, 'allowed_targets': allowed,
        'user_input': {'message_id': user['id'], 'content': user['content'], 'formal_responses': user['structured_content']},
        'history': [{key: item[key] for key in ('id', 'sequence_no', 'role', 'message_type', 'content')} | {'formal_responses': item['structured_content']} for item in context['history']],
        'source': context['source'], 'read_manifest': manifest}
    if function.context_policy.get('transport_layout') == 'context_projection_v1':
        from .context_projection import document_sections
        value['section_lookup'] = document_sections(parsed, metadata, set(scope['read_block_ids']))
    return function.validate_input(value)


def transport_input(value, function: FrozenFunction):
    """Serialize one validated snapshot according to its frozen transport.

    Old protocols retain their exact field order. New content arrays and their
    metadata arrays are derived together, after each whole-item trim. Phase A
    instead retains omitted facts in a separate private basis.
    """
    policy = function.context_policy
    if policy.get('transport_layout') == 'context_projection_v1':
        from .context_projection import project
        function.validate_input(value)
        wire = project(value)
        function.validate_transport_input(wire)
        return wire
    if policy.get('transport_layout') is None:
        return {key: value[key] for key in policy['field_order']}
    if policy['transport_layout'] != 'stable_prefix_v1' or function.transport_input_schema_json is None:
        raise ValueError('Unsupported frozen transport layout')
    function.validate_input(value)
    document, template, user = value['current_document'], value['template'], value['user_input']
    wire = {key: value[key] for key in ('schema_version', 'function_type', 'action_type', 'source_type')}
    wire.update({
        'template': {key: template[key] for key in ('template_key', 'template_version', 'markdown_content')},
        'current_document': {'read_blocks': [
            {key: block[key] for key in ('markdown_content', 'plain_text', 'heading_level')}
            for block in document['read_blocks']]},
        'history': [{key: message[key] for key in ('role', 'message_type', 'content', 'formal_responses')}
            for message in value['history']],
        'user_input': {key: user[key] for key in ('content', 'formal_responses')},
        'source': value['source'],
        'request_metadata': {
            'requirement': value['requirement'],
            'current_document': {key: document[key] for key in ('id', 'content_version')},
            'locked_heading_block_ids': template['locked_heading_block_ids'],
            'read_block_metadata': [block['metadata'] for block in document['read_blocks']],
            'history_message_refs': [{key: message[key] for key in ('id', 'sequence_no')} for message in value['history']],
            'user_message_id': user['message_id'],
            'scope': value['scope'], 'allowed_targets': value['allowed_targets'],
            'read_manifest': value['read_manifest']}})
    function.validate_transport_input(wire)
    return {key: wire[key] for key in policy['field_order']}


def serialize_input(value, function: FrozenFunction) -> str:
    return _serialize(transport_input(value, function))


def restore_transport_input(wire, function: FrozenFunction, *, basis=None):
    """Restore canonical facts for all existing authorization/evidence gates."""
    if function.context_policy.get('transport_layout') == 'context_projection_v1':
        from .context_projection import restore
        return restore(wire, function, basis)
    if function.context_policy.get('transport_layout') is None:
        return function.validate_input(wire)
    if function.context_policy['transport_layout'] != 'stable_prefix_v1' or function.transport_input_schema_json is None:
        raise ValueError('Unsupported frozen transport layout')
    wire = function.validate_transport_input(wire)
    metadata = wire['request_metadata']
    blocks, block_metadata = wire['current_document']['read_blocks'], metadata['read_block_metadata']
    history, refs = wire['history'], metadata['history_message_refs']
    if len(blocks) != len(block_metadata) or len(history) != len(refs):
        raise ValueError('Transport content and identity arrays must pair exactly')
    value = {key: wire[key] for key in ('schema_version', 'function_type', 'action_type', 'source_type')}
    value.update({
        'requirement': metadata['requirement'],
        'current_document': {**metadata['current_document'], 'read_blocks': [
            {**block, 'metadata': block_metadata[index]} for index, block in enumerate(blocks)]},
        'template': {**wire['template'], 'locked_heading_block_ids': metadata['locked_heading_block_ids']},
        'scope': metadata['scope'], 'allowed_targets': metadata['allowed_targets'],
        'user_input': {**wire['user_input'], 'message_id': metadata['user_message_id']},
        'history': [{**message, **refs[index]} for index, message in enumerate(history)],
        'source': wire['source'], 'read_manifest': metadata['read_manifest']})
    return function.validate_input(value)


def build_context(context, function: FrozenFunction) -> BuiltContext:
    value = assemble_input(context, function)
    policy, removed_history, removed_neighbors = function.context_policy, [], []
    budget = policy['budget']
    if budget['counting'] != 'conservative_utf8_bytes_pending_provider_proof':
        raise ValueError('No unproven tokenizer or mutable counting policy is permitted')
    # Preserve the complete frozen output schema. Whitespace compaction does
    # not remove schema keywords or redefine validation.
    system = function.prompt+'\n'+_serialize(json.loads(function.output_schema_json))
    if len(system.encode('utf-8')) > budget['prompt_tokens']:
        raise ContextLimitExceeded('System context exceeds its approved conservative budget')
    for field, limit in (('user_input', 'current_user_tokens'), ('source', 'source_tokens'), ('template', 'template_tokens')):
        if _bytes(value[field]) > budget[limit]:
            raise ContextLimitExceeded('Required context exceeds its approved conservative budget')
    required = set(context['scope']['required_read_block_ids']) | {item['block_id'] for item in value['allowed_targets']}
    required.update(value['template']['locked_heading_block_ids'])
    optional = [item['metadata']['block_id'] for item in value['current_document']['read_blocks'] if item['metadata']['block_id'] not in required]
    history_by_id = {item['id']: item for item in context['history']}
    def update_manifest():
        ids = {context['user_input']['id'], *(item['id'] for item in value['history'])}
        originals = [context['user_input'], *(history_by_id[item['id']] for item in value['history'])]
        ids.update(item['reply_to_message_id'] for item in originals if item['message_type'] == 'CARD_RESPONSE')
        value['read_manifest']['message_ids'] = [identity for identity in context['read_manifest']['message_ids'] if identity in ids]
        value['read_manifest']['block_ids'] = [item['metadata']['block_id'] for item in value['current_document']['read_blocks']]
    def size():
        return len(system.encode('utf-8'))+len(serialize_input(value, function).encode('utf-8'))
    while value['history'] and (_bytes(value['history']) > budget['history_tokens'] or size() > budget['input_tokens']):
        removed_history.append(value['history'].pop(0)['id']); update_manifest()
    while optional and size() > budget['input_tokens']:
        identity = optional.pop(0)
        value['current_document']['read_blocks'] = [item for item in value['current_document']['read_blocks'] if item['metadata']['block_id'] != identity]
        removed_neighbors.append(identity); update_manifest()
    if size() > budget['input_tokens'] or size()+budget['output_tokens'] > budget['total_tokens']:
        raise ContextLimitExceeded('Required context exceeds its approved conservative budget')
    function.validate_input(value)
    basis = None
    if policy.get('transport_layout') == 'context_projection_v1':
        from .context_projection import make_basis
        basis = _serialize(make_basis(value, function))
    return BuiltContext(system, serialize_input(value, function), _serialize(value['read_manifest']), size(), tuple(removed_history), tuple(removed_neighbors), basis_json=basis)
