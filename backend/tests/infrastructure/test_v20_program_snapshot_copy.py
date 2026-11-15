"""A verified source lease cannot by itself prove the temporary compiler copy."""

from pathlib import Path

import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path
from tools.windows_program_package import ProgramBuildError, snapshot_files


@pytest.mark.parametrize('failure', ['short-write', 'same-size-corruption'])
def test_source_snapshot_rejects_actual_incomplete_or_corrupt_destination(
    tmp_path, monkeypatch, failure
):
    original = tmp_path / 'original-input.bin'
    raw = b'original\r\n\0payload' * 90000
    with original.open('xb') as stream:
        stream.write(raw)
    destination = tmp_path / 'compiler-snapshot'
    destination.mkdir()
    target = destination / 'backend/input.bin'
    real_open = Path.open

    class FaultedCopy:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *arguments):
            return self.stream.__exit__(*arguments)

        def write(self, value):
            if failure == 'short-write':
                return self.stream.write(value[:-1])
            changed = bytes((value[0] ^ 1,)) + value[1:]
            return self.stream.write(changed)

        def flush(self):
            self.stream.flush()

        def fileno(self):
            return self.stream.fileno()

    def fault_only_owned_copy(path, *arguments, **options):
        stream = real_open(path, *arguments, **options)
        if path == target and arguments and arguments[0] == 'xb':
            return FaultedCopy(stream)
        return stream

    monkeypatch.setattr(Path, 'open', fault_only_owned_copy)
    reason = 'WRITE_INCOMPLETE' if failure == 'short-write' else 'COPY_BYTES_DIFFER'
    with pytest.raises(ProgramBuildError, match=reason):
        snapshot_files({'backend/input.bin': original}, destination)
    assert original.read_bytes() == raw
    # Native source/target leases must already be closed on the failed copy.
    target.rename(target.with_suffix('.released'))
    original.rename(original.with_suffix('.released'))
