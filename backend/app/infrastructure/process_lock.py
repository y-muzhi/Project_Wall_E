"""OS-owned single process lock. A stale PID/file is never execution authority."""
from pathlib import Path
import os
from uuid import uuid4


class ProcessAlreadyRunning(RuntimeError):
    pass


class ProcessLock:
    @classmethod
    def for_database(cls, database_path: Path | str) -> 'ProcessLock':
        database = Path(database_path).resolve()
        return cls(database.with_suffix(database.suffix + '.lock'))

    def __init__(self, path: Path | str):
        self.path = Path(path).resolve()
        self.owner_epoch: str | None = None
        self._file = None
        self._pid = None

    def acquire(self) -> 'ProcessLock':
        if self._file is not None:
            raise RuntimeError('Process lock already acquired by this object')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open('a+b')
        try:
            # Always lock byte zero. Appending to an existing file cannot move it.
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'\0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            raise ProcessAlreadyRunning('Another process holds the WALL-E execution lock') from error
        self._file = handle
        self._pid = os.getpid()
        self.owner_epoch = str(uuid4())
        return self

    def assert_owned(self) -> None:
        if self._file is None or self._file.closed or self._pid != os.getpid() or self.owner_epoch is None:
            raise RuntimeError('A current OS process lock is required')

    def release(self) -> None:
        self.assert_owned()
        handle = self._file
        try:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._file = None
            self.owner_epoch = None
            self._pid = None

    def __enter__(self) -> 'ProcessLock':
        return self.acquire()

    def __exit__(self, exception_type, exception, traceback) -> None:
        self.release()
