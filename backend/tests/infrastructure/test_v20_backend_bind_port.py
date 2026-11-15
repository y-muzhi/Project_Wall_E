"""An explicit loopback port never reaches SQLite or startup with invalid input."""

import pytest

from backend.app import __main__ as entry
from backend.app.infrastructure import sqlite_runtime


@pytest.mark.parametrize('port', [True, False, '8000', None, 0, 80, 1023, 65536, -1])
def test_invalid_bind_port_is_rejected_before_runtime_or_application(monkeypatch, port):
    def forbidden():
        raise AssertionError('Invalid binding must not reach SQLite activation')

    monkeypatch.setattr(sqlite_runtime, 'activate', forbidden)
    with pytest.raises(ValueError, match='local HTTP port'):
        entry.main(port=port)
