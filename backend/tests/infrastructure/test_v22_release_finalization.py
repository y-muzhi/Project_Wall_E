"""Exercise late admission of the compatibility proof for an immutable release draft."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure.environment_files import EnvironmentFailure, canonical, digest


@pytest.fixture
def draft(monkeypatch, tmp_path):
    pytest.importorskip('fcntl')
    from backend.app.infrastructure import environment_release_compatibility as compatibility
    from backend.app.infrastructure.environment_installation import CAPABILITIES

    manifest = {
        'release_id': str(uuid4()),
        'runtime_manifest_sha256': 'a' * 64,
        'schema_manifest_sha256': 'b' * 64,
        'application_index_ref': {'sha256': 'c' * 64},
        'frontend_index_ref': {'sha256': 'd' * 64},
    }
    source = SimpleNamespace(
        configuration_sha256='1' * 64,
        description={
            'program_source': {'sha256': '2' * 64},
            'schema_manifest_sha256': '3' * 64,
            'runtime_manifest_sha256': 'a' * 64,
            'required_capabilities': sorted(CAPABILITIES),
        },
    )
    schema = SimpleNamespace(schema_contract_sha256='e' * 64)
    pin = 'f' * 64
    proof = compatibility.compatibility_record(str(uuid4()), source, schema, manifest, schema, pin)
    path = tmp_path / compatibility.COMPATIBILITY
    monkeypatch.setattr(compatibility, 'read_protected', Path.read_bytes)
    return SimpleNamespace(
        proof=proof,
        path=path,
        check=lambda expected: compatibility.compatibility_reference(
            path,
            expected,
            manifest,
            schema.schema_contract_sha256,
            pin,
            code='RELEASE_FINALIZATION_UNVERIFIED',
        ),
    )


def test_same_schema_proof_returns_original_reference(draft):
    raw = canonical(draft.proof)
    draft.path.write_bytes(raw)
    assert draft.check(digest(raw)) == {
        'ref': draft.proof['compatibility_id'],
        'sha256': digest(raw),
    }
    with pytest.raises(EnvironmentFailure, match='RELEASE_FINALIZATION_UNVERIFIED'):
        draft.check('0' * 64)


@pytest.mark.parametrize(
    ('field', 'substitute'),
    (
        ('target_release_id', str(uuid4())),
        ('target_program_snapshot_sha256', '0' * 64),
        ('target_frontend_index_sha256', '0' * 64),
        ('schema_contract_sha256', '0' * 64),
        ('required_capabilities', ['DOCUMENT_READ']),
    ),
)
def test_protected_proof_must_belong_to_the_draft(draft, field, substitute):
    raw = canonical({**draft.proof, field: substitute})
    draft.path.write_bytes(raw)
    with pytest.raises(EnvironmentFailure, match='RELEASE_FINALIZATION_UNVERIFIED'):
        draft.check(digest(raw))
