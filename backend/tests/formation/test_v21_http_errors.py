"""Formation failures use the shared safe HTTP envelope and cannot expose private basis."""

from backend.app.shared.http_errors import error_response

REQUEST = '00000000-0000-4000-8000-000000000001'


def project(code, details):
    return error_response(code, details, allowed_errors=[code], request_id=REQUEST)


def test_formation_failure_codes_and_safe_limit_shape():
    assert project('FORMATION_INVALID', None).status == 422
    details = {'resource_kind': 'CHANGE_COUNT', 'limit': 20, 'actual': 21}
    response = project('FORMATION_LIMIT_EXCEEDED', details)
    assert response.status == 422
    assert response.body['error']['details'] == details
    assert project('FORMATION_LIMIT_EXCEEDED', {**details, 'actual': True}).status == 500


def test_state_conflict_accepts_only_registered_reason_and_exact_refs():
    original = {
        'reason': 'PROPOSAL_BASIS_CHANGED',
        'step_ref': 's1',
        'proposal': {'message_id': 12, 'card_key': 'original'},
    }
    response = project('STATE_CONFLICT', original)
    assert response.status == 409
    original['proposal']['card_key'] = 'changed-after-projection'
    assert response.body['error']['details']['proposal']['card_key'] == 'original'
    for invalid in (
        {**original, 'reason': 'SQL_OR_PRIVATE_BASIS'},
        {**original, 'step_ref': 'new_step_1'},
        {**original, 'binding_json': {'secret': 'private-data'}},
    ):
        result = project('STATE_CONFLICT', invalid)
        assert result.status == 500
        assert result.body['error']['details'] is None
        assert 'private-data' not in str(result.body)


def test_content_version_failure_keeps_existing_null_details_contract():
    assert project('CONTENT_VERSION_CONFLICT', None).status == 409
    assert project('CONTENT_VERSION_CONFLICT', {'actual_version': 2}).status == 500
