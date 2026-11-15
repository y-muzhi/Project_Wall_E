"""Fixed archive binding with real temporary PE and NTFS file leases."""

import hashlib
import sys
from pathlib import Path
from time import monotonic
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from backend.app.infrastructure import opencode_binary as binary
from backend.app.infrastructure.windows_executable_pin import ExecutablePinError


@pytest.fixture
def binary_installation(tmp_path, monkeypatch):
    image = tmp_path / binary.IMAGE_NAME
    raw = Path(sys.executable).read_bytes()
    image.write_bytes(raw)
    archive = tmp_path / binary.ARCHIVE_NAME
    with ZipFile(archive, 'x', compression=ZIP_DEFLATED) as package:
        package.writestr(binary.IMAGE_NAME, raw)
    monkeypatch.setattr(binary, 'RELEASE_SHA256', hashlib.sha256(archive.read_bytes()).hexdigest())
    source = binary.OpenCodeBinarySource(archive, image, 'test-executor', 'test-runtime')
    executor = {
        'version': binary.VERSION,
        'binary_ref': source.binary_ref,
        'runtime_bundle_ref': source.runtime_bundle_ref,
    }
    return source, executor


def test_exact_installed_pe_is_pinned_to_original_zip(binary_installation):
    source, executor = binary_installation
    member = binary.verify_opencode_archive(
        source.archive, deadline=monotonic() + 10, cancelled=lambda: False
    )
    with binary.open_opencode_binary(
        source, executor, deadline=monotonic() + 10, cancelled=lambda: False
    ) as pin:
        image = pin.verify()
        assert image.sha256 == member.sha256
        assert image.byte_count == member.byte_count
        with pytest.raises(OSError):
            source.image.open('wb').close()

    raw = source.image.read_bytes()
    source.image.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(ExecutablePinError):
        with binary.open_opencode_binary(
            source, executor, deadline=monotonic() + 10, cancelled=lambda: False
        ):
            pytest.fail('Changed binary was pinned')


def test_archive_digest_version_reference_and_cancellation_fail_closed(binary_installation):
    source, executor = binary_installation
    for field, value in (
        ('version', '1.19.4'),
        ('binary_ref', 'other-program'),
        ('runtime_bundle_ref', 'other-bundle'),
    ):
        with pytest.raises(binary.OpenCodeBinaryError, match='INSTALLATION_DIFFERS'):
            with binary.open_opencode_binary(
                source,
                {**executor, field: value},
                deadline=monotonic() + 10,
                cancelled=lambda: False,
            ):
                pytest.fail('Wrong fixed installation was pinned')
    with pytest.raises(binary.OpenCodeBinaryError, match='CANCELLED_OR_EXPIRED'):
        binary.verify_opencode_archive(
            source.archive, deadline=monotonic() + 10, cancelled=lambda: True
        )
    with source.archive.open('ab') as stream:
        stream.write(b'x')
    with pytest.raises(binary.OpenCodeBinaryError, match='ARCHIVE_DIGEST_DIFFERS'):
        binary.verify_opencode_archive(
            source.archive, deadline=monotonic() + 10, cancelled=lambda: False
        )


@pytest.mark.parametrize('other', ['OPENCODE.EXE', 'nested/opencode.exe', 'opencode.exe/'])
def test_archive_does_not_choose_an_ambiguous_or_different_image(tmp_path, monkeypatch, other):
    archive = tmp_path / binary.ARCHIVE_NAME
    with ZipFile(archive, 'x', compression=ZIP_DEFLATED) as package:
        package.writestr(other, b'invalid fixture')
        if other == 'OPENCODE.EXE':
            package.writestr(binary.IMAGE_NAME, b'second invalid fixture')
    monkeypatch.setattr(binary, 'RELEASE_SHA256', hashlib.sha256(archive.read_bytes()).hexdigest())
    with pytest.raises(binary.OpenCodeBinaryError, match='IMAGE_NOT_UNIQUE'):
        binary.verify_opencode_archive(archive, deadline=monotonic() + 10, cancelled=lambda: False)


def test_task_program_holds_original_pe_and_fixed_control_arguments(binary_installation):
    from dataclasses import replace

    from backend.app.infrastructure.opencode_runtime_bundle import REF_PREFIX
    from backend.app.infrastructure.opencode_task_launch import (
        TaskExecutionError,
        TaskExecutionPlan,
        TaskProgramOwner,
    )

    installed, _ = binary_installation
    source = replace(installed, runtime_bundle_ref=REF_PREFIX + 'a' * 64)
    execution = {
        'binary_ref': source.binary_ref,
        'version': binary.VERSION,
        'active_process_limit': 2,
        'job_memory_limit_bytes': 16 * 1024 * 1024,
    }
    network = {
        'model': [{'address': '127.0.0.1', 'port': 41001}],
        'forward': [],
        'control': [{'address': '127.0.0.1', 'port': 41002}],
        'application': [],
    }
    plan = TaskExecutionPlan.parse(execution, network, source.runtime_bundle_ref)
    assert plan.arguments == ('serve', '--hostname', '127.0.0.1', '--port', '41002', '--no-mdns')
    for data, ports, message in (
        ({**execution, 'active_process_limit': True}, network, 'INPUT_DIFFERS'),
        ({**execution, 'arguments': ['other']}, network, 'FIELDS_REQUIRED'),
        (
            execution,
            {**network, 'control': [{'address': '0.0.0.0', 'port': 41002}]},
            'NETWORK_DIFFERS',
        ),
        (execution, {**network, 'control': [{'address': '::1', 'port': 41002}]}, 'IPV4_INSTANCE'),
    ):
        with pytest.raises(TaskExecutionError, match=message):
            TaskExecutionPlan.parse(data, ports, source.runtime_bundle_ref)
    with pytest.raises(TaskExecutionError, match='DEPLOYMENT_DIFFERS'):
        TaskProgramOwner(installed, plan)
    program = TaskProgramOwner(source, plan)
    try:
        digest = program.prepare(deadline=monotonic() + 15, cancelled=lambda: False)
        assert program.verify() == digest
        with pytest.raises(OSError):
            source.image.rename(source.image.with_suffix('.old'))
        with pytest.raises(TaskExecutionError, match='ALREADY_PINNED'):
            program.prepare(deadline=monotonic() + 15, cancelled=lambda: False)
    finally:
        program.close()
    with pytest.raises(TaskExecutionError, match='UNVERIFIED'):
        program.verify()
