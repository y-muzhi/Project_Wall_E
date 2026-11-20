"""Repeated message projection reuses immutable protocols without caching card validation."""

import json
from copy import deepcopy

import pytest

from backend.app.formation.proposal_contracts import proposal_group
from backend.app.infrastructure.resources import ProtocolInvalid, ResourceCatalog
from backend.app.messages import queries
from backend.app.shared.validation import InvalidInput
from backend.tests.formation.test_v21_proposal_contracts import group


@pytest.mark.parametrize('purpose', ['STAGED_WRITE', 'FORMATION_PATH_CHANGE'])
def test_repeated_message_validation_loads_fallback_once_and_stays_strict(monkeypatch, purpose):
    catalog = ResourceCatalog()
    legacy = catalog.collaboration
    calls = []

    def counted_catalog():
        calls.append(True)
        return catalog

    queries._formation_reading_protocol.cache_clear()
    monkeypatch.setattr(queries, 'ResourceCatalog', counted_catalog)
    try:
        original = group(purpose)
        raw = json.dumps(original)
        protocols = [queries.reading_protocol(raw, legacy) for _ in range(20)]
        assert len(calls) == 1
        assert all(protocol is protocols[0] for protocol in protocols)
        assert protocols[0].formation_driven
        assert queries.reading_protocol(raw, protocols[0]) is protocols[0]
        assert (
            queries.reading_protocol(json.dumps({'purpose': 'FACT_CONFIRMATION'}), legacy) is legacy
        )
        for protocol in protocols:
            assert proposal_group(original, protocol) == original
        invalid = deepcopy(original)
        invalid['action_payload']['unregistered_authority'] = True
        with pytest.raises((InvalidInput, ProtocolInvalid)):
            proposal_group(invalid, protocols[0])
        assert proposal_group(original, protocols[0]) == original
        assert len(calls) == 1
    finally:
        queries._formation_reading_protocol.cache_clear()
