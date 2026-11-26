"""Verify a fixed candidate's schema against its own indexed source package."""

import json

import pytest

from backend.app.infrastructure import schema_v22_release as schema
from backend.app.infrastructure.database import SchemaMismatch


def test_fixed_schema_binds_the_candidate_program_instead_of_manager_bytes(tmp_path):
    runtime_pin = '1' * 64
    release_name = 'candidate-schema-test'
    contents = schema.build_candidate(release_name, runtime_pin)
    manifest = json.loads(contents[schema.MANIFEST])
    root = tmp_path / 'fixed-program'
    base = manifest['base_release']
    assert base['release_id'] == 'db20-r50'
    base_release = schema.RELEASE_PARENT.relative_to(schema.ROOT) / base['release_id']
    base_manifest = (schema.ROOT / base_release / 'manifest.json').read_bytes()
    assert schema.digest(base_manifest) == base['manifest_sha256']
    paths = (
        *manifest['sources'],
        *(item['path'] for item in manifest['design_sources']),
        *(base_release / name for name in ('manifest.json', schema.FRESH_SQL, schema.OBJECTS)),
    )
    changed_source = 'backend/app/infrastructure/environment_installation.py'
    for path in paths:
        original = (schema.ROOT / path).read_bytes()
        if path == changed_source:
            original += b'\n# Fixed candidate source has separate program metadata.\n'
            manifest['sources'][path] = schema.digest(original)
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original)

    released = tmp_path / release_name
    released.mkdir()
    contents[schema.MANIFEST] = schema.canonical_bytes(manifest)
    for name, data in contents.items():
        (released / name).write_bytes(data)
    pin = schema.digest(contents[schema.MANIFEST])

    with pytest.raises(SchemaMismatch, match='SCHEMA_RELEASE_MISMATCH'):
        schema.load_release(released, pin, runtime_pin)
    loaded = schema.load_release(released, pin, runtime_pin, source_root=root)
    assert loaded.schema_contract_sha256 == manifest['schema_contract_sha256']
    assert loaded.manifest_sha256 == pin
    with pytest.raises(SchemaMismatch, match='SCHEMA_RELEASE_MISMATCH'):
        schema.load_release(released, pin, '2' * 64, source_root=root)
