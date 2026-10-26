"""Materialize the EFFECTIVE V1.5 design into the next immutable resource batch.

No provider, database, credentials or service access. Refuses to overwrite a
release; formal resource JSON is an application input, not a test report.
"""
from pathlib import Path
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DESIGN = ROOT / 'docs/design/v1.5/WALL-E.后端设计文档_V_1.5.md'
DESIGN_SHA256 = '98520e1a6f8325a4df04a5c8afe9ea3f5eeba41d22d48688951e638d380c7a12'


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def build(*, batch='v9', design_sha256=DESIGN_SHA256, prompt_version='v1', release_version='v1', contract_version='v1', output_version='v1'):
    from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE
    from backend.app.infrastructure.schema_transport import named_schema
    from backend.app.infrastructure.resources import _validate
    raw = DESIGN.read_bytes()
    if hashlib.sha256(raw).hexdigest() != design_sha256:
        raise ValueError('Design changed: review affected definitions before generating another release')
    text = raw.decode('utf-8')
    blocks = [json.loads(value) for value in re.findall(r'```json\s*\n(.*?)\n```', text, re.S)]
    guides = next(value for value in blocks if isinstance(value, list) and len(value) == 4 and value[0].get('key') == 'collaboration.discovery')
    structures = next(value for value in blocks if isinstance(value, list) and len(value) == 3 and value[0].get('key') == 'structure.brief')
    schema = next(value for value in blocks if isinstance(value, dict) and value.get('$id') == 'urn:walle:collaboration-contract:v1')
    counting = next(value for value in blocks if isinstance(value, dict) and value.get('layout') == 'collaboration_context_v1')
    if len(schema['$defs']) != 89:
        raise ValueError('All 89 definitions required')
    prompt_section = text.split('**Prompt正式定义**', 1)[1].split('| 当前阶段 |', 1)[0]
    paragraphs = []
    for paragraph in re.findall(r'^> (.+(?:\n> .+)*)', prompt_section, re.M):
        paragraphs.append(paragraph.replace('\n> ', '\n'))
    if len(paragraphs) != 5:
        raise ValueError('Exactly five common prompt paragraphs required')
    files = {}
    refs = {}

    def add(path, content, key, version='v1'):
        data = content.encode('utf-8')
        files[path] = data
        reference = {'key': key, 'version': version, 'digest': hashlib.sha256(data).hexdigest()}
        refs[path] = reference
        return reference

    def add_json(path, value, key, entry):
        _validate(named_schema(schema, entry).schema_json, value)
        return add(path, compact(value), key)

    add('schemas/collaboration-contract.'+contract_version+'.json', compact(schema), 'collaboration.contract', contract_version)
    canonical = add('schemas/collaboration-canonical.v1.json', named_schema(schema, 'Canonical').schema_json, 'collaboration.canonical')
    wire = add('schemas/collaboration-wire.v1.json', named_schema(schema, 'Wire').schema_json, 'collaboration.wire')
    add('schemas/collaboration-basis.v1.json', named_schema(schema, 'ContextBasis').schema_json, 'collaboration.basis')
    message = add('schemas/collaboration-messages.v1.json', named_schema(schema, 'MessageStructures').schema_json, 'collaboration.messages')
    outputs = []
    for operation, entry in (('DISCUSS', 'OutputDiscuss'), ('GENERATE', 'OutputGenerate'), ('REVISE', 'OutputRevise'), ('PROPOSE_CHANGES', 'OutputPropose'), ('COMPARE', 'OutputCompare'), ('REVIEW', 'OutputReview')):
        ref = add('schemas/output-' + operation.lower() + '.'+output_version+'.json', named_schema(schema, entry).schema_json, 'collaboration.output.' + operation.lower(), output_version)
        outputs.append({'operation': operation, 'schema_ref': ref})
    guide_refs = [{'phase_kind': value['phase_kind'], 'resource_ref': add_json('guides/' + value['key'] + '.v1.json', value, value['key'], 'GuideDefinition')} for value in guides]
    structure_refs = [add_json('structures/' + value['key'] + '.v1.json', value, value['key'], 'StructureProfile') for value in structures]
    prompt = add('prompts/collaboration-common.'+prompt_version+'.md', '\n\n'.join(paragraphs), 'collaboration.common', prompt_version)
    count_ref = add_json('counting/collaboration-counting.v1.json', counting, 'collaboration.counting', 'CountingDefinition')
    # A non-secret placeholder is used only to obtain the existing public
    # immutable profile snapshot. No environment configuration is loaded.
    profile = ModelProfile('offline-resource-build', DEFAULT_PROFILE).snapshot
    profile_sha = hashlib.sha256(compact(profile).encode('utf-8')).hexdigest()
    release = {'schema_version': 1, 'key': 'collaboration_v1', 'version': release_version,
        'canonical_schema': canonical, 'wire_schema': wire, 'output_schemas': outputs,
        'guides': guide_refs, 'structure_profiles': structure_refs, 'prompt': prompt,
        'counting': count_ref, 'model_profile_sha256': profile_sha,
        'compiler_version': 'collaboration_compiler_v1', 'message_schema': message}
    # Declaration order, including message_schema before the excluded admission,
    # is fixed by Release.properties, not by dictionary construction order.
    properties = schema['$defs']['Release']['properties']
    release = {key: release[key] for key in properties if key != 'admission'}
    release_sha = hashlib.sha256(compact(release).encode('utf-8')).hexdigest()
    admission_schema = schema['$defs']['Admission']['properties']
    admission = {key: None for key in admission_schema}
    admission.update(state='OFFLINE_READY', profile_sha256=profile_sha, release_sha256=release_sha, reserve=1024)
    release['admission'] = admission
    release = {key: release[key] for key in properties}
    _validate(named_schema(schema, 'Release').schema_json, release)
    add('release.'+release_version+'.json', compact(release), 'collaboration.release', release_version)
    manifest = {'schema_version': 1, 'key': 'collaboration_v1', 'version': batch,
        'design_sha256': design_sha256, 'release_sha256': release_sha,
        'files': [{'path': path, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'resource_ref': refs[path]} for path, data in files.items()]}
    target = ROOT / 'backend/resources' / batch
    target.mkdir(exist_ok=False)
    for path, data in files.items():
        destination = target / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    manifest_bytes = compact(manifest).encode('utf-8')
    (target / 'manifest.json').write_bytes(manifest_bytes)
    print('files:', len(files), 'manifest_sha256:', hashlib.sha256(manifest_bytes).hexdigest(), 'release_sha256:', release_sha)


if __name__ == '__main__':
    if sys.argv[1:] == ['--v15']:
        build(batch='v15', design_sha256='9f7e6476861e8d954fc6be675973c6e829988b2c582a107367b3d764fb90bcdd', prompt_version='v6', release_version='v7', contract_version='v3', output_version='v3')
    elif sys.argv[1:] == ['--v14']:
        build(batch='v14', design_sha256='8c818b009879ce902b9ef2e2692028013437cc47a801d32b5ac7e484c38e80f0', prompt_version='v5', release_version='v6', contract_version='v3', output_version='v3')
    elif sys.argv[1:] == ['--v13']:
        build(batch='v13', design_sha256='901f0ed4684cae2324aec53810f24e558b3f0c720a2e80b09d72794ce54a482e', prompt_version='v4', release_version='v5', contract_version='v3', output_version='v3')
    elif sys.argv[1:] == ['--v12']:
        build(batch='v12', design_sha256='ab7c7812c6ff730ee4d072c8b52e105b4c2e1792046c3ddaf4d66a2ec85644b6', prompt_version='v3', release_version='v4', contract_version='v2', output_version='v2')
    elif sys.argv[1:] == ['--v11']:
        build(batch='v11', design_sha256='de47073e2dc7294831aa016a9e0d4ce840900da7bfb720dc3977efc75b7de307', prompt_version='v3', release_version='v3')
    elif sys.argv[1:] == ['--v10']:
        build(batch='v10', design_sha256='ec48d4b36869d11b7fa8032e9b6b60ad2b80e0021a47398d93b1106fb9db8e9c', prompt_version='v2', release_version='v2')
    elif not sys.argv[1:]:
        build()
    else:
        raise SystemExit('Usage: build-collaboration-resources.py [--v10|--v11|--v12|--v13|--v14|--v15]')
