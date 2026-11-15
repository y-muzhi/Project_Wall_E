"""Read the original Windows managed source without writing system configuration."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.app.infrastructure import opencode_managed_config as probe


def test_program_data_uses_the_windows_known_folder_on_owner_thread(monkeypatch, tmp_path):
    with ThreadPoolExecutor(max_workers=1) as thread:
        original = thread.submit(probe._program_data).result(timeout=10)
        monkeypatch.setenv('ProgramData', str(tmp_path))
        assert thread.submit(probe._program_data).result(timeout=10) == original
        assert original.is_dir()


@pytest.mark.parametrize('managed', ['absent', 'file', 'directory', 'missing_root'])
def test_managed_source_fails_closed_when_present_or_unavailable(monkeypatch, tmp_path, managed):
    root = tmp_path / 'isolated-programdata'
    if managed != 'missing_root':
        root.mkdir()
    entry = root / 'opencode'
    if managed == 'file':
        entry.write_bytes(b'fixture')
    elif managed == 'directory':
        entry.mkdir()
    monkeypatch.setattr(probe, '_program_data', lambda: root)
    assert probe.opencode_managed_source_clear() == (managed == 'absent')
    if managed == 'file':
        assert entry.read_bytes() == b'fixture'
    elif managed == 'directory':
        assert entry.is_dir()
    else:
        assert not entry.exists()
