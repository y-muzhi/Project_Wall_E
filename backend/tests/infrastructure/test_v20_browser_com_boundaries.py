"""Actual added COM capability must preserve private-file and socket denial."""

from pathlib import Path
import pytest
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.tests.infrastructure.v20_primary_lpac_probe import primary_probe
from backend.tests.infrastructure.test_v20_windows_lpac_profile import (
    controller,
    ordinary_controller,
    tmp_path,
    lpac_scope,
)


@pytest.mark.skipif(
    not Path('backend/distributions/windows/check-browser-20261114-1543-assets').is_dir(),
    reason='Explicit prepared fixed runtime is required',
)
def test_fixed_com_capability_keeps_host_and_guard_files_private(lpac_scope, tmp_path):
    directories, _, journal = lpac_scope
    host = create_private_package(tmp_path / 'protected-host-fixture')
    protected = (host / 'host-data', journal._package.path / 'private-guard-data')
    for path in protected:
        with path.open('xb') as stream:
            stream.write(b'owned fake boundary data')
        assert path.read_bytes() == b'owned fake boundary data'
    observed = primary_probe(
        lpac_scope,
        'python-boundaries',
        capability_names=('registryRead', 'lpacCom'),
        protected_files=protected,
    )
    assert observed['lpac'] == 'EFFECTIVE_OPT_OUT'
    assert observed['network'] == {'2': 10013, '23': 10013}
    assert observed['protected'] == [{'read': 5, 'write': 5, 'dacl': 5}] * 2
    assert observed['com_storage_hresult'] == '0x80030005'
    assert observed['scratch'] is True
    for path in protected:
        assert path.read_bytes() == b'owned fake boundary data'
