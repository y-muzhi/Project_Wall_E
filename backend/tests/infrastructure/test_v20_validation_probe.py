"""A diagnostic observer cannot block atomic publication or business progress."""

from threading import Event, Thread

from backend.tests.infrastructure import v20_validation_probe as probe
from backend.tests.requirements.test_v15_foundation import tmp_path


def test_concurrent_reader_cannot_block_create_only_phase_markers(tmp_path):
    stop = Event()
    failures = []
    observed = []
    assert probe.validation_phase(tmp_path, 'BEGIN')

    def read():
        while not stop.is_set():
            current = probe.current_validation_phase(tmp_path)
            observed.append(current)
            if not current.startswith(('PHASE_', 'BEGIN')):
                failures.append(current)

    reader = Thread(target=read)
    reader.start()
    try:
        for number in range(128):
            assert probe.validation_phase(tmp_path, f'PHASE_{number:03d}')
    finally:
        stop.set()
        reader.join(timeout=2)
    assert not reader.is_alive() and observed and not failures
    assert probe.current_validation_phase(tmp_path) == 'PHASE_127'
    assert len(list(tmp_path.glob('.validation-phase-*'))) == 129


def test_failed_diagnostic_publication_preserves_previous_phase_without_interrupting(
    tmp_path, monkeypatch
):
    assert probe.validation_phase(tmp_path, 'PREVIOUS')

    def unavailable(*args):
        raise PermissionError('Injected temporary observer access failure')

    monkeypatch.setattr(probe.Path, 'open', unavailable)
    assert probe.validation_phase(tmp_path, 'NEXT') is False
    assert probe.current_validation_phase(tmp_path) == 'PREVIOUS'
    assert len(list(tmp_path.glob('.validation-phase-*'))) == 1
