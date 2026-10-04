"""I11 nested transport fields; identity/source relationships stay in the APP."""
from backend.app.shared.validation import object_fields, strict_integer, strict_enum, text_value, reject
from backend.app.infrastructure.idempotency import canonical_input
from .markdown import BLOCK_TYPES, DocumentInvalid
from .snapshot import FIELDS, ACTORS, SOURCES, _time


def snapshot_input(markdown, state):
    raw = text_value(markdown, 'markdown_content')
    if len(raw) > 1_000_000:
        reject('markdown_content', 'TOO_LONG', '完整正文最多1000000个Unicode码点')
    try:
        raw.encode('utf-8')
    except UnicodeError:
        reject('markdown_content', 'INVALID_FORMAT', '正文必须使用有效Unicode')
    root = object_fields(state, 'block_state_json', ('schema_version', 'next_block_id', 'blocks'), ('schema_version', 'next_block_id', 'blocks'))
    strict_integer(root['schema_version'], 'block_state_json.schema_version', maximum=1)
    strict_integer(root['next_block_id'], 'block_state_json.next_block_id')
    if type(root['blocks']) is not list:
        reject('block_state_json.blocks', 'INVALID_TYPE', '必须是区块数组')
    if len(root['blocks']) > 10000:
        reject('block_state_json.blocks', 'TOO_LONG', '最多允许10000个顶层区块')
    for index, value in enumerate(root['blocks']):
        path = f'block_state_json.blocks[{index}]'
        block = object_fields(value, path, FIELDS, FIELDS)
        strict_integer(block['block_id'], path+'.block_id')
        strict_enum(block['block_type'], path+'.block_type', BLOCK_TYPES)
        if type(block['section_path']) is not list:
            reject(path+'.section_path', 'INVALID_TYPE', '必须是章节文本数组')
        for part, text in enumerate(block['section_path']):
            text_value(text, f'{path}.section_path[{part}]')
            try:
                text.encode('utf-8')
            except UnicodeError:
                reject(f'{path}.section_path[{part}]', 'INVALID_FORMAT', '必须使用有效Unicode')
        for prefix in ('created', 'last_modified'):
            strict_enum(block[prefix+'_by_type'], path+'.'+prefix+'_by_type', ACTORS)
            strict_enum(block[prefix+'_source_type'], path+'.'+prefix+'_source_type', SOURCES)
            if block[prefix+'_source_id'] is not None:
                strict_integer(block[prefix+'_source_id'], path+'.'+prefix+'_source_id')
            text_value(block[prefix+'_at'], path+'.'+prefix+'_at')
            try:
                _time(block[prefix+'_at'])
            except DocumentInvalid:
                reject(path+'.'+prefix+'_at', 'INVALID_FORMAT', '必须为合法UTC毫秒时间')
    if len(canonical_input(state).encode('utf-8')) > 4*1024*1024:
        reject('block_state_json', 'TOO_LONG', '区块状态超过4MiB容量')
