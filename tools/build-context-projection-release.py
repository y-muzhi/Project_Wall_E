"""Generate the additive CTX-002-A frozen release from existing resources.

Only writes new formal resource directories; no database, credentials or I/O
to providers. Refuses to overwrite a published release.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.guide.context_projection import FIELD_ORDER, LAYOUT, projection_prompt
from backend.app.infrastructure.resources import FUNCTIONS, V4_MANIFEST_SHA256, V5_MANIFEST_SHA256


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def obj(properties, required=None):
    return {'type': 'object', 'properties': properties, 'required': list(properties) if required is None else required, 'additionalProperties': False}


def array(items, maximum=10000):
    return {'type': 'array', 'items': items, 'maxItems': maximum}


def section_schema():
    return obj({'section_ref': {'type': 'string', 'maxLength': 100},
        'heading_block_id': {'type': 'integer', 'minimum': 1, 'maximum': 9007199254740991},
        'level': {'type': 'integer', 'minimum': 1, 'maximum': 6},
        'title': {'type': 'string', 'maxLength': 1000000}, 'parent_ref': {'type': ['string', 'null'], 'maxLength': 100}})


def canonical_schema(old, title):
    value = deepcopy(old)
    value['$id'], value['title'] = 'urn:walle:' + title.replace('@', ':'), title
    value['properties']['section_lookup'] = obj({'sections': array(section_schema()), 'block_sections': array(obj({
        'block_id': {'type':'integer','minimum':1,'maximum':9007199254740991}, 'section_ref': {'type':['string','null'],'maxLength':100}}))})
    value['required'].append('section_lookup')
    return value


def wire_schema(old, title):
    ref = lambda name: {'$ref': '#/$defs/' + name}
    identity = {'type': 'integer', 'minimum': 1, 'maximum': 9007199254740991}
    text = {'type': 'string', 'maxLength': 1000000}
    nullable_ref = {'type': ['string', 'null'], 'maxLength': 100}
    block_properties = {'block_id': identity, 'block_type': old['$defs']['block_metadata']['properties']['block_type'],
        'section_ref': nullable_ref, 'markdown_content': old['$defs']['read_block']['properties']['markdown_content'],
        'heading_level': {'type': 'integer', 'minimum': 1, 'maximum': 6}}
    section = section_schema()
    template = obj({key: old['$defs']['template']['properties'][key] for key in ('template_key', 'template_version', 'markdown_content')})
    user = old['$defs']['user_input']['properties']
    request = obj({'user_message_id': identity, 'document_ref': obj({'id': identity, 'content_version': identity}),
        'content': user['content'], 'formal_responses': user['formal_responses'], 'scope': ref('scope'),
        'capability_groups': array(obj({'block_ids': {**array(identity), 'uniqueItems': True, 'minItems': 1},
            'operations': old['$defs']['allowed_target']['properties']['operations']})),
        'restricted_targets': array(ref('allowed_target')), 'locked_heading_block_ids': {**array(identity), 'uniqueItems': True}})
    properties = {'input_version': {'const': LAYOUT, 'type': 'string'},
        'task': obj({key: old['properties'][key] for key in ('function_type', 'action_type', 'source_type')}),
        'template': template,
        'requirement': obj({key: old['$defs']['requirement']['properties'][key] for key in ('title', 'requirement_type', 'status', 'initialization_mode')}),
        'section_index': array(section),
        'document_context': obj({'read_blocks': array(obj(block_properties, ['block_id', 'block_type', 'section_ref', 'markdown_content']))}),
        'recent_history': old['properties']['history'], 'source': old['properties']['source'], 'current_request': request}
    assert tuple(properties) == FIELD_ORDER
    return {'$schema': old['$schema'], '$id': 'urn:walle:' + title.replace('@', ':'), 'title': title,
        **obj(properties), '$defs': deepcopy(old['$defs'])}


def main():
    base = ROOT / 'backend/resources'
    release = base / 'v8'
    destinations = [release, base / 'counting/v9', base / 'counting/v10']
    if any(path.exists() for path in destinations):
        raise SystemExit('Refusing to overwrite an existing frozen release')
    functions = []
    for action_source, (function, key) in FUNCTIONS.items():
        canonical = read(base / f'v2/schemas/{key}_INPUT.v1.json')
        canonical_ref = key + '_CANONICAL_INPUT@v1'
        write(release / f'schemas/{key}_CANONICAL_INPUT.v1.json', canonical_schema(canonical, canonical_ref))
        wire_ref = key + '_INPUT@v3'
        write(release / f'schemas/{key}_INPUT.v3.json', wire_schema(canonical, wire_ref))
        for version, previous in (('v8', 'v6' if action_source[0] == 'INITIALIZE' else 'v4'),
                                  ('v9', 'v7' if action_source[0] == 'INITIALIZE' else 'v5')):
            previous_root = base / ('v5' if action_source[0] == 'INITIALIZE' else 'v4')
            entry = {'function_type': function, 'version': version, 'action_type': action_source[0], 'source_type': action_source[1],
                'input_schema': canonical_ref, 'output_schema': key + '_OUTPUT@v1',
                'context_template': key + '_CONTEXT@' + version, 'prompt': function + '@' + version}
            policy = read(previous_root / f'contexts/{key}_CONTEXT.{previous}.json')
            entry['output_schema'] = policy['output_schema']
            policy.update(input_schema=canonical_ref,prompt=entry['prompt'], field_order=list(FIELD_ORDER), transport_layout=LAYOUT,
                transport_input_schema=wire_ref, context_basis_version=LAYOUT, selection_strategy='existing_read_set_v1')
            write(release / f'contexts/{key}_CONTEXT.{version}.json', policy)
            old_prompt = (previous_root / f'prompts/{function}.{previous}.md').read_text(encoding='utf-8')
            prompt = projection_prompt(old_prompt, function, key, version, wire_ref)
            target = release / f'prompts/{function}.{version}.md'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(prompt.encode('utf-8'))
            functions.append(entry)
    write(release / 'functions.v8.json', {'schema_version': 1, 'proposal': False, 'functions': functions})
    files = [{'path': p.relative_to(release).as_posix(), 'bytes': p.stat().st_size, 'sha256': digest(p)}
        for p in sorted(release.rglob('*')) if p.is_file() and p.name != 'manifest.json']
    write(release / 'manifest.json', {'schema_version': 1, 'status': 'APPROVED', 'decision': 'CTX-002-A',
        'version': 'v8', 'approved_on': '2026-10-18', 'base_manifest_sha256s': [V4_MANIFEST_SHA256, V5_MANIFEST_SHA256],
        'scope': 'PHASE_A_ONLY', 'validation_status': 'IMPLEMENTED_NOT_VERIFIED', 'files': files})
    manifest_digest = digest(release / 'manifest.json')
    for count_version, version, source_count, admission_base in (
            (9, 'v8', 5, '42c894b46677f366813f696a95e4e9793329e74a6d9ed33fed46aedbefe1279a'),
            (10, 'v9', 6, '688d0cc8941f84e0bcfa2e33cac07ca7a29f3da2b6946f960ffb911c86b7741e')):
        strategy = read(base / f'counting/v{source_count}/strategy.json')
        strategy.update(schema_version=count_version, strategy=f'ark_exact_text_counts_context_projection_v{count_version}',
            status='ADOPTED_BY_USER_PHASE_A_APPROVAL', decision='CTX-002-A', function_manifest_sha256=manifest_digest,
            function_version=version, serialization='json_utf8_ensure_ascii_false_compact_context_projection_v1',
            proof_requirement='User approved phase A implementation on 2026-10-18. Existing hard budgets, exact counting and 1024 empirical reserve retained. No new paid observation or provider compatibility proof.',
            component_selectors=['system', 'input', 'current_request.{user_message_id,content,formal_responses}', 'source', 'template', 'recent_history'])
        path = base / f'counting/v{count_version}'
        write(path / 'strategy.json', strategy)
        write(path / 'admission.json', {'schema_version': 1, 'decision': 'CTX-002-A', 'status': 'ENABLED_BY_USER_PHASE_A_APPROVAL',
            'approved_on': '2026-10-18', 'user_instruction': '按照计划改造代码吧（仅一期）', 'base_admission_sha256': admission_base,
            'release_sha256': digest(path / 'strategy.json'), 'function_manifest_sha256': manifest_digest, 'function_version': version,
            'admission_mode': strategy['admission_mode'], 'model': strategy['model'], 'provider_compatibility_proved': False,
            'validation_status': 'IMPLEMENTED_NOT_VERIFIED', 'paid_observation_authorized': False})
        print(f'{version}: strategy={digest(path / "strategy.json")} admission={digest(path / "admission.json")}')
    print('manifest=' + manifest_digest)


if __name__ == '__main__':
    main()
