"""Actual partial-to-native binding transfer, not production PREPARE admission.

The private journal/controller are established first; original intent precedes
all per-scope native resources. Pipe/program admission is not exercised here.
"""

import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.app.infrastructure import runtime_control_git as native
from backend.app.infrastructure.git_bundle import BUNDLE_PARENT
from backend.app.infrastructure.guard_action_journal import GuardActionJournal
from backend.app.infrastructure.guard_request_header import GuardRequestHeader
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, LaunchOutcomeUnknown
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_executable_pin import ExecutablePin
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.app.infrastructure.windows_stdio import GuardStandardIO
from backend.tests.infrastructure.test_v20_windows_native_process import peer, scope
from backend.tests.infrastructure.test_v20_windows_stdio import publish, wait_file
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.fixture
def prepared(peer):
    source, descriptor, _, directory = peer
    package = create_private_package(directory / 'transfer-journal')
    with (
        LaunchJournal(package) as journal,
        ControllerPrimaryToken(source, expected=source.identity) as token,
    ):
        request = GuardRequestHeader(
            'PREPARE', str(uuid4()), scope(), None, '{"fixture":"NATIVE_BINDING_TRANSFER_ONLY"}'
        )
        actions = GuardActionJournal(journal)
        start = actions.begin(request)
        registry = native.ControlGitRegistry(journal, token, controller_ref=scope().controller_ref)
        owner = registry.begin_preparation(actions, start)
        root = BUNDLE_PARENT / 'win-x64'
        inventory = json.loads((root / 'manifest.json').read_bytes())
        member = next(row for row in inventory['members'] if row['path'] == 'cmd/git.exe')
        try:
            image = owner.allocate(
                'PROGRAM',
                lambda: ExecutablePin(
                    root / 'cmd/git.exe',
                    expected_byte_count=member['byte_count'],
                    expected_sha256=member['sha256'],
                ),
            )
            job = owner.allocate(
                'JOB',
                lambda: OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024),
            )
            cwd = owner.allocate(
                'DIRECTORY', lambda: LocalPathGuard(directory, directory=True).__enter__()
            )
            streams = owner.allocate(
                'STDIO', lambda: GuardStandardIO(token, descriptor, scope=scope())
            )
            publish(directory / 'copy-ack.json', asdict(streams.binding))
            wait_file(directory / 'copy-released.json')
            resources = SimpleNamespace(
                journal=journal,
                token=token,
                image=image,
                job=job,
                streams=streams,
                cwd=cwd,
            )
            yield registry, owner, actions, start, resources
        finally:
            if not owner.handles_released:
                registry.stop(scope())
                entry = registry._entries.get(scope().key)
                if entry is not None:
                    if entry.root is not None:
                        assert (
                            entry.root._kernel.WaitForSingleObject(entry.root._info.process, 8000)
                            == 0
                        )
                    registry.release_native_handles(scope())
                owner.close_stopped_handles()
            registry.close_watch()


def bind(registry, owner, resources):
    return registry.register(
        scope(),
        resources.image,
        resources.job,
        resources.streams,
        resources.cwd,
        preparation=owner,
    )


def test_actual_binding_keeps_reserved_reference_and_real_original_git_ownership(prepared):
    registry, owner, actions, start, resources = prepared
    with pytest.raises(native.NativeRegistryError, match='TRANSFER_REQUIRED'):
        registry.register(scope(), resources.image, resources.job, resources.streams, resources.cwd)
    receipt = bind(registry, owner, resources)
    entry = registry._entry(scope())
    assert entry.job_ref == start.record.allocated_binding_ref == owner.binding_ref
    assert entry.preparation is owner and owner._bound_entry is entry
    assert bind(registry, owner, resources) == receipt
    assert owner.describe()['bound_to_registry']
    assert owner.describe()['phase'] == 'BOUND'
    actions.acknowledge(
        start.record, {'binding_ref': entry.job_ref, 'fixture': 'ORIGINAL_RESOURCES_BOUND'}
    )
    facts = registry.create(scope())
    assert facts['job_ref'] == owner.binding_ref
    registry.resume(scope())
    root = entry.root
    assert root._kernel.WaitForSingleObject(root._info.process, 8000) == 0
    registry.stop(scope())
    with pytest.raises(LaunchOutcomeUnknown, match='NATIVE_HANDLE_RELEASE_REQUIRED'):
        owner.close_stopped_handles()
    registry.release_native_handles(scope())
    owner.close_stopped_handles()
    assert owner.handles_released
    assert not hasattr(owner, 'cleanup_verified')


def test_failed_prepare_receipt_keeps_bound_original_objects_and_never_acknowledges_preparation(
    prepared,
):
    registry, owner, actions, start, resources = prepared
    with patch.object(native, 'MAX_RESOURCE_RECORDS', 0):
        with pytest.raises(LaunchOutcomeUnknown, match='CAPACITY'):
            bind(registry, owner, resources)
    entry = registry._entry(scope())
    assert entry.preparation is owner and entry.job is resources.job
    assert owner._bound_entry is entry
    assert not owner._transfer_active
    assert owner.describe()['phase'] == 'PREPARING'
    assert actions.find(scope(), 'PREPARE').phase == 'MAY_HAVE_BEEN_SENT'
    assert entry.root is None
    registry.stop(scope())
    registry.release_native_handles(scope())
    owner.close_stopped_handles()
