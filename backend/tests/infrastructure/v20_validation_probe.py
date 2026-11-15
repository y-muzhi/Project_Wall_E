"""Bounded create-only phase markers in a test-owned temporary directory.

Only fixed phase names and relative timing are emitted. No request bodies, paths,
credentials or raw reports. Marker creation never replaces a reader-held file,
and diagnostic failures cannot interrupt the actual validation.
"""

import re
import os
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from time import monotonic

_PHASE = re.compile('[A-Z][A-Z0-9_]{0,63}')
_MARKER = re.compile(r'\.validation-phase-([0-9]{4})-([A-Z][A-Z0-9_]{0,63})')
_MAX_MARKERS = 256


def _markers(root):
    rows = []
    with os.scandir(root) as listing:
        for entry in listing:
            match = _MARKER.fullmatch(entry.name)
            if match is not None:
                rows.append((int(match[1]), match[2]))
                if len(rows) > _MAX_MARKERS:
                    raise OSError('Diagnostic marker bound exceeded')
    return rows


def validation_phase(root, name):
    if type(name) is not str or _PHASE.fullmatch(name) is None:
        raise ValueError('Fixed diagnostic phase required')
    try:
        rows = _markers(root)
        if len(rows) >= _MAX_MARKERS:
            return False
        number = max((number for number, _ in rows), default=0) + 1
        if number > _MAX_MARKERS:
            return False
        path = Path(root) / f'.validation-phase-{number:04d}-{name}'
        with path.open('xb'):
            pass
        return True
    except OSError:
        return False


def current_validation_phase(root):
    try:
        rows = _markers(root)
        return max(rows)[1] if rows else 'WAITING_FOR_BACKEND'
    except OSError:
        return 'PHASE_READ_UNAVAILABLE'


@contextmanager
def watch_validation_phase(root, *, enabled):
    if not enabled:
        yield
        return
    stop = Event()
    started = monotonic()

    def observe():
        previous = None
        last_report = started
        emitted = 0
        while not stop.wait(0.1):
            current = current_validation_phase(root)
            now = monotonic()
            if current == previous and now - last_report < 15:
                continue
            if emitted >= 120:
                return
            print('TESTING_PHASE', current, round(now - started, 2), flush=True)
            emitted += 1
            previous = current
            last_report = now

    worker = Thread(target=observe, name='walle-test-validation-phase', daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=2)
        if worker.is_alive():
            raise AssertionError('Owned diagnostic watcher did not stop')
