"""Opt-in fixed nonnetwork capability observations, never product policy or a live connection."""

import os

import pytest

from backend.app.infrastructure import windows_job, windows_lpac_capabilities, windows_lpac_token
from backend.tests.infrastructure.test_v20_windows_lpac_profile import (
    controller,
    ordinary_controller,
    tmp_path,
    lpac_scope,
)
from backend.tests.infrastructure.v20_primary_lpac_probe import primary_probe

pytestmark = pytest.mark.skipif(
    os.environ.get('WALLE_TEST_RUNTIME_DIAGNOSTICS') != '1',
    reason='Explicit fixed local runtime diagnostics only',
)
DIAGNOSTIC_COMBINATIONS = (
    ('registryRead',),
    ('registryRead', 'lpacCom'),
    ('registryRead', 'lpacAppExperience'),
    ('registryRead', 'lpacSessionManagement'),
    ('registryRead', 'lpacCryptoServices'),
    ('registryRead', 'lpacIdentityServices'),
)


@pytest.mark.parametrize('names', DIAGNOSTIC_COMBINATIONS)
def test_observe_original_lpac_unconnected_socket_initialization(lpac_scope, monkeypatch, names):
    def diagnostic_names(value):
        if type(value) is not tuple or value not in ((), names):
            raise windows_lpac_capabilities.LpacCapabilityError(
                'FIXED_DIAGNOSTIC_CAPABILITY_COMBINATION_REQUIRED'
            )
        return value

    for module in (windows_job, windows_lpac_token, windows_lpac_capabilities):
        monkeypatch.setattr(module, 'validate_lpac_capability_names', diagnostic_names)
    observed = primary_probe(lpac_scope, 'python', capability_names=names)
    assert set(observed) == {'2', '23', 'overlapped'}
    assert all(type(value) is int for value in observed.values())
    print('LPAC_UNCONNECTED_SOCKET_CAPABILITY_OBSERVATION', names, observed, flush=True)
