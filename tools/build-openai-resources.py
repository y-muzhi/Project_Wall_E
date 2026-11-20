"""Freeze an independent OpenAI V2.1 resource bundle without credentials or API I/O."""

import json
import os
import sys
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build():
    from backend.app.infrastructure.collaboration_resources import (
        ROOT as SOURCE,
    )
    from backend.app.infrastructure.collaboration_resources import (
        CollaborationResources,
    )
    from backend.app.infrastructure.model_profile import OPENAI_PROFILE, ModelProfile
    from backend.app.infrastructure.openai_schema import MODE, schema_for
    from backend.app.infrastructure.resources import _validate
    from backend.app.infrastructure.schema_transport import compact, named_schema

    source = CollaborationResources.load(SOURCE.parent / 'v37')
    schema = deepcopy(source.bundle)
    schema['$id'] = 'urn:walle:collaboration-contract:openai-v2'
    definitions = schema['$defs']
    profile = ModelProfile('offline-resource-build-only', OPENAI_PROFILE)
    counting = deepcopy(source.counting)
    counting.update(
        model=profile.model_name,
        model_version=profile.model_version,
        roles=['developer', 'user'],
        framing_reserve=0,
        system_text='openai_whole_request_v1',
        admission_mode='openai_exact_request_v1',
    )
    for key in (
        'model',
        'model_version',
        'roles',
        'framing_reserve',
        'system_text',
        'admission_mode',
    ):
        definitions['CountingDefinition']['properties'][key]['const'] = counting[key]
    definitions['Release']['properties']['model_transport']['const'] = MODE
    admission = definitions['Admission']
    for key in ('counted_system_tokens', 'counted_user_tokens', 'framing_gap'):
        del admission['properties'][key]
        admission['required'].remove(key)
    admission['properties']['request_input_tokens'] = deepcopy(
        admission['properties']['actual_input_tokens']
    )
    admission['properties']['count_gap'] = {
        'anyOf': [{'type': 'integer', 'const': 0}, {'type': 'null'}]
    }
    admission['properties']['reserve']['const'] = 0
    admission['required'].extend(('request_input_tokens', 'count_gap'))
    files, refs = {}, {}

    def add(path, text, key, version='openai-v2'):
        raw = text.encode('utf-8')
        reference = {'key': key, 'version': version, 'digest': sha256(raw).hexdigest()}
        files[path] = raw
        refs[path] = reference
        return reference

    add('schemas/collaboration-contract.openai-v2.json', compact(schema), 'collaboration.contract')
    named = {}
    for name, stem in (
        ('Canonical', 'canonical'),
        ('Wire', 'wire'),
        ('ContextBasis', 'basis'),
        ('MessageStructures', 'messages'),
    ):
        named[name] = add(
            'schemas/collaboration-' + stem + '.openai-v2.json',
            named_schema(schema, name).schema_json,
            'collaboration.' + stem,
        )
    outputs = []
    for operation, entry in (
        ('DISCUSS', 'OutputDiscuss'),
        ('GENERATE', 'OutputGenerate'),
        ('REVISE', 'OutputRevise'),
        ('PROPOSE_CHANGES', 'OutputPropose'),
        ('COMPARE', 'OutputCompare'),
        ('REVIEW', 'OutputReview'),
    ):
        text = named_schema(schema, entry).schema_json
        schema_for(text)  # Refuse unsupported root/grammar/capacity before publishing.
        if operation == 'DISCUSS':
            schema_for(text, block_refs=[])
            schema_for(text, block_refs=['d42v1b1'])
        outputs.append(
            {
                'operation': operation,
                'schema_ref': add(
                    'schemas/output-' + operation.lower() + '.openai-v2.json',
                    text,
                    'collaboration.output.' + operation.lower(),
                ),
            }
        )
    guides = []
    for kind in ('brief', 'design', 'specification'):
        reference = source.reference('collaboration.' + kind)
        new = add(
            'guides/' + kind + '.json',
            source.content(reference),
            reference['key'],
            reference['version'],
        )
        guides.append({'document_kind': kind, 'resource_ref': new})
    structures = []
    for kind in ('brief', 'design', 'specification'):
        reference = source.reference('structure.' + kind)
        structures.append(
            add(
                'structures/' + kind + '.json',
                source.content(reference),
                reference['key'],
                reference['version'],
            )
        )
    prompt = add('prompts/collaboration-common.openai-v2.md', source.prompt, 'collaboration.common')
    count_ref = add(
        'counting/collaboration-counting.openai-v2.json',
        compact(counting),
        'collaboration.counting',
    )
    profile_hash = sha256(compact(profile.snapshot).encode()).hexdigest()
    release = deepcopy(source.release)
    release.update(
        version='openai-v2',
        canonical_schema=named['Canonical'],
        wire_schema=named['Wire'],
        message_schema=named['MessageStructures'],
        output_schemas=outputs,
        guides=guides,
        structure_profiles=structures,
        prompt=prompt,
        counting=count_ref,
        model_profile_sha256=profile_hash,
        model_transport=MODE,
    )
    release['admission'] = {
        'state': 'OFFLINE_READY',
        'profile_sha256': profile_hash,
        'release_sha256': '0' * 64,
        'evidence_ref': None,
        'count_request_sha256': None,
        'chat_request_sha256': None,
        'actual_input_tokens': None,
        'request_input_tokens': None,
        'count_gap': None,
        'reserve': 0,
    }
    release = {key: release[key] for key in definitions['Release']['properties']}
    release_hash = sha256(
        compact({key: value for key, value in release.items() if key != 'admission'}).encode()
    ).hexdigest()
    release['admission']['release_sha256'] = release_hash
    _validate(named_schema(schema, 'CountingDefinition').schema_json, counting)
    _validate(named_schema(schema, 'Release').schema_json, release)
    add('release.openai-v2.json', compact(release), 'collaboration.release')
    design = ROOT / 'docs/iterations/pending/v2.1/WALL-E.后端设计文档_V_2.1.md'
    manifest = {
        'schema_version': 1,
        'key': 'collaboration_v1',
        'version': 'openai-v2',
        'design_sha256': sha256(design.read_bytes()).hexdigest(),
        'release_sha256': release_hash,
        'files': [
            {
                'path': name,
                'bytes': len(raw),
                'sha256': refs[name]['digest'],
                'resource_ref': refs[name],
            }
            for name, raw in files.items()
        ],
    }
    encoded = compact(manifest).encode()
    destination = ROOT / 'backend/resources/openai-v2'
    if destination.exists():
        raise ValueError('Immutable OpenAI resource already exists')
    with TemporaryDirectory(prefix='.openai-release-', dir=destination.parent) as directory:
        staged = Path(directory) / 'openai-v2'
        for name, raw in {**files, 'manifest.json': encoded}.items():
            path = staged / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        if destination.exists():
            raise ValueError('OpenAI destination appeared concurrently')
        os.replace(staged, destination)
    return {
        'manifest_sha256': sha256(encoded).hexdigest(),
        'release_sha256': release_hash,
        'files': len(files),
        'provider_calls': 0,
    }


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(build()))
