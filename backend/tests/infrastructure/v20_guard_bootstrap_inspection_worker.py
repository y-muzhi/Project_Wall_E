"""Inspect actual prepared packages and parent rights using an owned ordinary reader Job."""

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep

from backend.app.infrastructure.windows_access_check import ControllerAccessQuery
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from tools.windows_guard_inspection import GuardBootstrapSources


def exercise(prepared, expected):
    with TemporaryDirectory(prefix='we-guard-parent-check-') as temporary:
        directory = Path(temporary)
        job = OwnedJob(active_process_limit=4, job_memory_limit_bytes=512 * 1024**2)
        root = None
        try:
            root = TestSuspendedRoot(
                job,
                directory,
                'import time;time.sleep(300)',
                executable=sys._base_executable,
            )
            with ObservedProcess(root.pid) as reader:
                assert job.contains_process(reader)
                assert not reader.identity.is_appcontainer and not reader.identity.is_elevated
                root.resume()
                with GuardBootstrapSources(prepared, expected) as inputs:
                    print('ACTUAL_BOOTSTRAP_SOURCE_BINDINGS_CHECKED', flush=True)
                    with (
                        ControllerPrimaryToken(reader, expected=reader.identity) as token,
                        ControllerAccessQuery(token) as access,
                    ):
                        for path in reversed(Path(inputs.plan['installation_root']).parents):
                            with LocalPathGuard(path, directory=True) as parent:
                                fact = access.query(parent)
                                print(
                                    'ACTUAL_PARENT_ACCESS_FACT',
                                    str(path),
                                    hex(fact.granted_access),
                                    fact.owner_sid,
                                    flush=True,
                                )
                    facts = inputs.verify_parent_access(reader)
                    assert facts and all(fact.file.is_directory for fact in facts)
                    assert reader.observe().state == 'RUNNING'
                    assert not Path(inputs.plan['installation_root']).exists()
                    print(
                        'ACTUAL_ORIGINAL_READER_PARENT_ACCESS_CHECKED',
                        len(facts),
                        'no_installation_no_os_admission',
                        flush=True,
                    )
        finally:
            job.terminate_owned(1)
            if root is not None:
                assert job._kernel.WaitForSingleObject(root.info.process, 10000) == 0
            deadline = monotonic() + 10
            while monotonic() < deadline:
                members = job.observe_members()
                if members.complete and not members.process_ids:
                    break
                sleep(0.01)
            else:
                raise AssertionError('Owned diagnostic reader Job did not empty')
            if root is not None:
                root.close()
            job.close()
    print('OWNED_READER_STOPPED_AND_TEMPORARY_INPUTS_CLEANED', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    values = parser.parse_args()
    exercise(values.prepared, values.plan_sha256)


if __name__ == '__main__':
    main()
