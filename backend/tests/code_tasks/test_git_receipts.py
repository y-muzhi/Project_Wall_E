"""Private Git receipt bytes/owner decoding, never write/result authority."""

from dataclasses import FrozenInstanceError, replace
import json

import pytest

from backend.app.infrastructure import git_receipts as receipts
from backend.app.infrastructure.runtime_launch_journal import LaunchScope

TIME = '2026-11-05T01:02:03.456Z'


def binding(format='sha1'):
    return receipts.GitReceiptBinding(
        LaunchScope('a' * 64, 11, 2, 'original-git-nonce-0001'),
        'b' * 32,
        22,
        'c' * 64,
        'd' * (40 if format == 'sha1' else 64),
        format,
    )


def facts(**changes):
    value = receipts.GitReceiptFacts(None, None, None, None, None, None)
    return replace(value, **changes)


def receipt(format='sha1', **changes):
    value = receipts.GitReceipt(binding(format), 'OBSERVED', TIME, facts())
    return replace(value, **changes)


def encode(value):
    return receipts.encode_receipt(value, max_receipt_bytes=4096)


def decode(raw, expected=None):
    return receipts.decode_receipt(raw, expected or binding(), max_receipt_bytes=4096)


@pytest.mark.parametrize('format', ['sha1', 'sha256'])
@pytest.mark.parametrize('phase', receipts.PHASES)
def test_exact_schema_and_null_unknowns_survive_canonical_roundtrip(format, phase):
    original = receipt(format, phase=phase)
    raw = encode(original)
    assert raw.endswith(b'\n') and decode(raw, original.binding) == original
    value = json.loads(raw)
    assert set(value) == {
        'schema_version',
        'operation_id',
        'step_no',
        'guard_run_ref',
        'nonce',
        'protocol_version',
        'repository_id',
        'repository_fingerprint_sha256',
        'planned_commit_oid',
        'phase',
        'observed_at',
        'facts',
    }
    assert all(value is None for value in value['facts'].values())
    assert 'object_format' not in value and 'controller_ref' not in value
    with pytest.raises(FrozenInstanceError):
        original.phase = 'EXITED'


@pytest.mark.parametrize('format', ['sha1', 'sha256'])
def test_actual_allowed_fact_types_ref_and_fingerprint_roundtrip(format):
    observed = receipts.GitRefObservation(
        'refs/heads/项目/topic', 'a' * (40 if format == 'sha1' else 64), None
    )
    original = receipt(
        format,
        facts=facts(
            prepared_ack=True,
            commit_ack=True,
            exit_code=0,
            ref_observation=observed,
            worktree_fingerprint_sha256='f' * 64,
            postcheck_status='VERIFIED',
        ),
    )
    assert decode(encode(original), original.binding) == original
    # These are facts only: neither exit0 nor phase is execution permission.
    absent = receipts.GitRefObservation('refs/walle/baselines/33', None, None)
    assert (
        decode(encode(receipt(facts=facts(ref_observation=absent)))).facts.ref_observation == absent
    )


@pytest.mark.parametrize('target', ['refs/remotes/origin/main', 'refs/other/branch', 'HEAD'])
def test_observed_unsupported_symref_can_be_preserved_without_authorizing_it(target):
    original = receipt(
        facts=facts(
            ref_observation=receipts.GitRefObservation('refs/heads/alias', 'a' * 40, target)
        )
    )
    assert decode(encode(original)) == original


@pytest.mark.parametrize(
    'name,value',
    [
        ('operation_id', 12),
        ('step_no', 3),
        ('guard_run_ref', 'e' * 32),
        ('nonce', 'other-git-nonce-0001'),
        ('repository_id', 23),
        ('repository_fingerprint_sha256', 'e' * 64),
        ('planned_commit_oid', 'e' * 40),
        ('protocol_version', 'OTHER'),
        ('operation_id', True),
        ('step_no', 2.0),
    ],
)
def test_receipt_cannot_move_to_another_original_binding(name, value):
    data = json.loads(encode(receipt()))
    data[name] = value
    raw = (json.dumps(data, sort_keys=True, separators=(',', ':')) + '\n').encode()
    with pytest.raises(receipts.GitReceiptError, match='BINDING_DIFFERS'):
        decode(raw)


@pytest.mark.parametrize(
    'changes',
    [
        {'repository_id': 0},
        {'repository_id': False},
        {'repository_id': 2**53},
        {'guard_run_ref': '../private'},
        {'repository_fingerprint_sha256': 'A' * 64},
        {'planned_commit_oid': '0' * 40},
        {'planned_commit_oid': 'abc'},
        {'planned_commit_oid': 'a' * 64},
        {'object_format': 'sha512'},
        {'scope': {}},
    ],
)
def test_invalid_original_binding_rejected(changes):
    with pytest.raises(receipts.GitReceiptError):
        replace(binding(), **changes)


@pytest.mark.parametrize(
    'name,value',
    [
        ('prepared_ack', 0),
        ('prepared_ack', 'true'),
        ('commit_ack', 1),
        ('exit_code', False),
        ('exit_code', 1.5),
        ('exit_code', 2**53),
        ('ref_observation', {}),
        ('worktree_fingerprint_sha256', ''),
        ('postcheck_status', 'PASSED'),
        ('postcheck_status', False),
    ],
)
def test_invalid_fact_types_do_not_coerce_to_observed_success(name, value):
    with pytest.raises(receipts.GitReceiptError):
        encode(receipt(facts=facts(**{name: value})))


@pytest.mark.parametrize(
    'ref,oid,symref',
    [
        ('HEAD', None, None),
        ('refs/tags/tag', None, None),
        ('refs/walle/baselines/01', None, None),
        ('refs/walle/baselines/9007199254740992', None, None),
        ('refs/heads/bad name', None, None),
        ('refs/heads/main', '0' * 40, None),
        ('refs/heads/main', 'abc', None),
        ('refs/heads/main', None, 'refs/remotes/x bad'),
        ('refs/heads/main', None, 'PRIVATE_CONFIG_VALUE\n'),
        ('refs/heads/main', None, {}),
    ],
)
def test_bad_reference_facts_rejected(ref, oid, symref):
    with pytest.raises(receipts.GitReceiptError):
        encode(receipt(facts=facts(ref_observation=receipts.GitRefObservation(ref, oid, symref))))


@pytest.mark.parametrize(
    'time',
    [
        '',
        '2026-11-05',
        '2026-11-05T01:02:03Z',
        '2026-11-05T01:02:03.456+00:00',
        '2026-13-05T01:02:03.456Z',
        '2026-11-31T01:02:03.456Z',
        '2026-11-05T24:02:03.456Z',
        '2026-11-05T01:02:60.456Z',
    ],
)
def test_timestamp_must_be_actual_canonical_utc_ms(time):
    with pytest.raises(receipts.GitReceiptError, match='TIMESTAMP_INVALID'):
        encode(receipt(observed_at=time))


@pytest.mark.parametrize('schema', [None, True, 1.0, 0, 2])
def test_invalid_schema_never_accepts_bool_or_float(schema):
    raw = encode(receipt()).replace(
        b'"schema_version":1', b'"schema_version":' + json.dumps(schema).encode()
    )
    with pytest.raises(receipts.GitReceiptError, match='SCHEMA_INVALID'):
        decode(raw)


@pytest.mark.parametrize('level', ['root', 'facts', 'ref'])
@pytest.mark.parametrize(
    'field', ['stderr', 'stdout', 'config', 'arbitrary_result', 'process_handle']
)
def test_unregistered_or_secret_fields_rejected_at_every_level(level, field):
    data = json.loads(
        encode(
            receipt(
                facts=facts(
                    ref_observation=receipts.GitRefObservation('refs/heads/main', None, None)
                )
            )
        )
    )
    target = data if level == 'root' else data['facts']
    if level == 'ref':
        target = target['ref_observation']
    target[field] = 'PRIVATE_CONFIG_BODY'
    with pytest.raises(receipts.GitReceiptError, match='FIELDS_INVALID') as error:
        decode(json.dumps(data).encode())
    assert 'PRIVATE_CONFIG_BODY' not in str(error.value)


@pytest.mark.parametrize(
    'mutation',
    [
        lambda raw: raw.replace(b'"phase":', b'"phase":"OBSERVED","phase":'),
        lambda raw: raw.replace(b'"exit_code":null', b'"exit_code":null,"exit_code":0'),
        lambda raw: raw.replace(b'"exit_code":null', b'"exit_code":NaN'),
        lambda raw: raw + b'{}',
        lambda raw: b'\xff',
        lambda raw: b'[]',
    ],
)
def test_malformed_duplicate_or_nonfinite_json_is_not_repaired(mutation):
    with pytest.raises(receipts.GitReceiptError, match='JSON_INVALID'):
        decode(mutation(encode(receipt())))


def test_canonical_utf8_bytes_and_complete_required_fields():
    data = json.loads(encode(receipt()))
    for raw in (
        json.dumps(data, indent=2).encode(),
        encode(receipt()).rstrip(b'\n'),
    ):
        with pytest.raises(receipts.GitReceiptError, match='CANONICAL_BYTES_DIFFER'):
            decode(raw)
    del data['facts']['prepared_ack']
    with pytest.raises(receipts.GitReceiptError, match='FIELDS_INVALID'):
        decode(json.dumps(data).encode())


@pytest.mark.parametrize('limit', [None, False, 0, -1, 1.5, 2**53])
def test_limit_required_before_encode_or_decode(limit):
    with pytest.raises(receipts.GitReceiptError, match='LIMIT_INVALID'):
        receipts.encode_receipt(receipt(), max_receipt_bytes=limit)
    with pytest.raises(receipts.GitReceiptError, match='LIMIT_INVALID'):
        receipts.decode_receipt(b'', binding(), max_receipt_bytes=limit)


def test_exact_byte_limit_and_explicit_no_planned_commit_are_supported():
    original = replace(receipt(), binding=replace(binding(), planned_commit_oid=None))
    raw = encode(original)
    assert receipts.decode_receipt(raw, original.binding, max_receipt_bytes=len(raw)) == original
    with pytest.raises(receipts.GitReceiptError, match='BYTES_INVALID'):
        receipts.decode_receipt(raw, original.binding, max_receipt_bytes=len(raw) - 1)
    with pytest.raises(receipts.GitReceiptError, match='BYTES_EXCEEDED'):
        receipts.encode_receipt(original, max_receipt_bytes=len(raw) - 1)
