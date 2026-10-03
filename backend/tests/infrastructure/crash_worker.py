"""Test-only subprocess with real abrupt exits, never a production dispatcher."""
import os
from pathlib import Path
import sys

from backend.app.infrastructure.database import Database
from backend.app.infrastructure.idempotency import Idempotency, Scope, Success
from backend.app.infrastructure.process_lock import ProcessLock, ProcessAlreadyRunning
from backend.tests.infrastructure.test_database import insert_requirement


KEY = '00000000-0000-4000-8000-000000000099'
SCOPE = Scope('APP-REQ-CMD-C01', 'RequirementCollection', KEY)
INPUT = {'title': '失去响应'}
SUCCESS = Success({'code': 'CREATED', 'data': {'requirement_id': 101}, 'details': None}, 201)


def main():
    path, mode = Path(sys.argv[1]), sys.argv[2]
    database = Database(path)
    try:
        lock = ProcessLock.for_database(path).acquire()
    except ProcessAlreadyRunning:
        print('LOCKED', flush=True)
        sys.exit(7)
    if mode == 'hold-lock':
        print(f'READY {os.getpid()}', flush=True)
        sys.stdin.readline()
        lock.release()
        return
    idempotency = Idempotency(database, lock)
    if mode == 'claimed':
        idempotency.claim(SCOPE, INPUT)
        os._exit(21)
    if mode == 'uncommitted':
        claim = idempotency.claim(SCOPE, INPUT)
        with database.transaction(write=True) as connection:
            insert_requirement(connection)
            idempotency.succeed(connection, claim, SUCCESS)
            os._exit(22)
    if mode == 'committed':
        def operation(connection):
            insert_requirement(connection)
            return SUCCESS
        idempotency.execute(SCOPE, INPUT, operation)
        os._exit(23)
    lock.release()
    raise ValueError('Unknown test mode')


if __name__ == '__main__':
    main()
