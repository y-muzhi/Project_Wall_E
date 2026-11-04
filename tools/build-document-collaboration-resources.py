"""Build immutable document-driven collaboration bundles without provider I/O."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ITERATION = ROOT / 'docs/iterations/pending/v1.5/WALL-E.文档驱动讨论与设置精简_V_1.5.md'


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def atomic_new(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError('Immutable destination already exists: ' + str(path))
    fd, name = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content.encode('utf-8'))
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise ValueError('Destination appeared while building')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def remove_property(definition, name):
    definition['properties'].pop(name, None)
    definition['required'] = [key for key in definition['required'] if key != name]


def build(source_batch, batch):
    if not ITERATION.is_file():
        raise ValueError('Missing adopted iteration source')
    from backend.app.infrastructure.schema_transport import named_schema
    from backend.app.infrastructure.resources import _validate

    source = ROOT / 'backend/resources' / source_batch
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    by_key = {row['resource_ref']['key']: row for row in manifest['files']}

    def read(key):
        entry = by_key[key]
        raw = (source / entry['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('Frozen input changed')
        return raw.decode('utf-8')

    schema = json.loads(read('collaboration.contract'))
    contract_version = 'v5' if batch == 'v17' else 'v6'
    counting_version = 'v3' if batch == 'v17' else 'v4'
    schema['$id'] = 'urn:walle:collaboration-contract:' + contract_version
    definitions = schema['$defs']
    discussion = definitions['Discussion']
    remove_property(discussion, 'phase')
    discussion['properties']['schema_version']['const'] = 2
    remove_property(discussion['properties']['counters'], 'phase')
    remove_property(definitions['TopicState'], 'phase_ref')
    remove_property(definitions['Position'], 'phase_kind')
    remove_property(definitions['Position'], 'phase_ref')
    definitions['Position']['properties'] = {'document_kind': {'$ref': '#/$defs/DocumentKind'}, **definitions['Position']['properties']}
    definitions['Position']['required'].insert(0, 'document_kind')
    remove_property(definitions['BasisRef'], 'phase_ref')
    definitions['BasisRef']['properties']['document_kind'] = {'$ref': '#/$defs/DocumentKind'}
    definitions['BasisRef']['required'].append('document_kind')
    remove_property(definitions['GuideDefinition'], 'phase_kind')
    definitions['GuideDefinition']['properties']['document_kind'] = {'$ref': '#/$defs/DocumentKind'}
    definitions['GuideDefinition']['required'].append('document_kind')
    guides_schema = definitions['Release']['properties']['guides']
    remove_property(guides_schema['items'], 'phase_kind')
    guides_schema['items']['properties']['document_kind'] = {'$ref': '#/$defs/DocumentKind'}
    guides_schema['items']['required'].insert(0, 'document_kind')
    guides_schema['minItems'] = guides_schema['maxItems'] = 3
    for key in ('ModelCardGroup', 'StoredCardGroup'):
        definitions[key]['oneOf'] = [
            item for item in definitions[key]['oneOf']
            if item['properties']['purpose'].get('const') != 'PHASE_CHANGE'
        ]
    definitions['NextStep']['properties']['action']['enum'].remove('PROPOSE_PHASE_CHANGE')
    definitions['EvidenceChange']['properties']['change']['enum'].append('USER_REPLACE')
    definitions['EvidenceChange']['allOf'].append({
        'if': {'properties': {'change': {'const': 'USER_REPLACE'}}},
        'then': {'properties': {
            'supersedes': {'minItems': 1},
            'origin': {'const': 'USER_STATEMENT'},
            'source_refs': {'minItems': 1, 'maxItems': 1},
        }},
    })
    for key in ('PhaseAction', 'PhaseKind'):
        definitions.pop(key, None)
    files, references = {}, {}

    def add(path, text, key, version):
        reference = {'key': key, 'version': version, 'digest': hashlib.sha256(text.encode('utf-8')).hexdigest()}
        files[path] = text
        references[path] = reference
        return reference

    add('schemas/collaboration-contract.' + contract_version + '.json', compact(schema), 'collaboration.contract', contract_version)
    named = {}
    for entry, filename, key in (
        ('Canonical', 'canonical', 'canonical'), ('Wire', 'wire', 'wire'),
        ('ContextBasis', 'basis', 'basis'), ('MessageStructures', 'messages', 'messages'),
    ):
        named[entry] = add('schemas/collaboration-' + filename + '.v2.json', named_schema(schema, entry).schema_json, 'collaboration.' + key, 'v2')
    outputs = []
    for operation, entry in (
        ('DISCUSS', 'OutputDiscuss'), ('GENERATE', 'OutputGenerate'),
        ('REVISE', 'OutputRevise'), ('PROPOSE_CHANGES', 'OutputPropose'),
        ('COMPARE', 'OutputCompare'), ('REVIEW', 'OutputReview'),
    ):
        ref = add('schemas/output-' + operation.lower() + '.v4.json', named_schema(schema, entry).schema_json, 'collaboration.output.' + operation.lower(), 'v4')
        outputs.append({'operation': operation, 'schema_ref': ref})
    guides = []
    for kind, previous in (('brief', 'discovery'), ('design', 'solution'), ('specification', 'specification')):
        guide = json.loads(read('collaboration.' + previous))
        guide.pop('phase_kind')
        guide.update(key='collaboration.' + kind, version='v2', document_kind=kind)
        guide['redirection_policy'] = '用户要求优先；区分本轮顺序、本文档约束和明确业务范围。暂缓不等于永久取消，恢复议题无需额外手续。明确用户改向才更新当前意见；不清则保留冲突并必要澄清。不建立或切换阶段。暂不生成只针对具体建议；有新成果或用户明确要求时重新核实执行。'
        guide['design_methods'].append('文档类型给默认方向，本轮指令决定具体工作；检查是操作，不设阶段门槛。')
        ref = add('guides/' + guide['key'] + '.v2.json', compact(guide), guide['key'], 'v2')
        _validate(named_schema(schema, 'GuideDefinition').schema_json, guide)
        guides.append({'document_kind': kind, 'resource_ref': ref})
    structures = []
    for kind in ('brief', 'design', 'specification'):
        old = by_key['structure.' + kind]
        structures.append(add(old['path'], read('structure.' + kind), 'structure.' + kind, old['resource_ref']['version']))
    prompt = read('collaboration.common')
    prompt = prompt.replace('阶段', '文档工作').replace('当前文档工作topic_ref', '本文档topic_ref')
    prompt += '\n\n当前协议由document_kind决定默认指引；检查和对照是本轮操作，不输出PHASE_CHANGE或阶段建议。文档内主题可连续补充和恢复。自由原话的暂缓、范围及改向只作带来源的USER_STATEMENT整理；区分本轮、本文档、明确业务范围，不扩大原意。处理改向时携带相关旧依据。USER_REPLACE仅用于用户明确改变同一适用范围的旧意见：assertion必须逐字等于一条本轮实际携带的pending用户TEXT原文，source_refs仅该m引用，supersedes仅同一applies_to的旧依据。不能逐字引用、范围不同或用户未明确改向时用PROPOSE_SUPERSEDE，保留争议并必要澄清。普通意见不冒充正式USER_DECISION。暂不生成只针对原建议，后续明确出稿按新请求核实。不得仅为填全主线重复追问；进展未发生可靠变化时返回null。'
    prompt_ref = add('prompts/collaboration-common.v7.md', prompt, 'collaboration.common', 'v7')
    counting = json.loads(read('collaboration.counting'))
    counting_ref = add('counting/collaboration-counting.' + counting_version + '.json', compact(counting), 'collaboration.counting', counting_version)
    release = deepcopy(json.loads(read('collaboration.release')))
    release.update(version='v9' if batch == 'v17' else 'v10', canonical_schema=named['Canonical'], wire_schema=named['Wire'], output_schemas=outputs, guides=guides, structure_profiles=structures, prompt=prompt_ref, counting=counting_ref, message_schema=named['MessageStructures'])
    order = definitions['Release']['properties']
    release = {key: release[key] for key in order}
    body = {key: value for key, value in release.items() if key != 'admission'}
    digest = hashlib.sha256(compact(body).encode('utf-8')).hexdigest()
    release['admission']['release_sha256'] = digest
    _validate(named_schema(schema, 'Release').schema_json, release)
    add('release.' + release['version'] + '.json', compact(release), 'collaboration.release', release['version'])
    final = {
        'schema_version': 1, 'key': 'collaboration_v1', 'version': batch,
        'design_sha256': 'ec0bf3601fb6904a3450ff86e884de9a47b05c48627ec27de052a80c93d4e919',
        'release_sha256': digest,
        'files': [{'path': path, 'bytes': len(text.encode('utf-8')), 'sha256': references[path]['digest'], 'resource_ref': references[path]} for path, text in files.items()],
    }
    target = ROOT / 'backend/resources' / batch
    if target.exists():
        raise ValueError('Immutable batch already exists')
    for path, text in files.items():
        atomic_new(target / path, text)
    serialized = compact(final)
    atomic_new(target / 'manifest.json', serialized)
    print(batch, 'manifest', hashlib.sha256(serialized.encode('utf-8')).hexdigest(), 'release', digest, 'files', len(files))


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(ROOT))
    build('v15', 'v17')
    build('v16', 'v18')
