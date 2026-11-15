"""Pinned create-only Guard installation and an explicitly separate bounded start/stop."""

import argparse
import hashlib
import os
import re
import sys
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep

from backend.app.infrastructure.deployment_manifest import absolute_path, digest, file_identity
from backend.app.infrastructure.program_manifest import BACKEND_PROGRAM_POLICY, GUARD_PROGRAM_POLICY
from backend.app.infrastructure.program_package import ProgramPackageLease
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_local_paths import LocalPathGuard, local_absolute_path
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.app.shared.strict_objects import exact
from backend.app.shared.validation import strict_json_object
from tools.windows_guard_bootstrap import _new_directory
from tools.windows_guard_inspection import GuardBootstrapSources
from tools.windows_guard_install_contract import (
    INSTALLER_POLICY,
    INTENT_NAME,
    REQUEST_NAME,
    GuardInstallationError,
    make_installation_request,
    verify_installation_request,
)
from tools.windows_guard_install_files import ProtectedInstallationWriter
from tools.windows_guard_install_identity import InstallationOperator
from tools.windows_guard_install_service import NativeGuardService
from tools.windows_guard_plan import DEPLOYMENT_NAME
from tools.windows_program_package import write_new_verified_file

RECEIPT_NAME = 'installation-receipt.v1.json'


def require_installer_runtime():
    if (
        not getattr(sys, 'frozen', False)
        or Path(sys.executable).name != INSTALLER_POLICY.entry_name
    ):
        raise GuardInstallationError('DEDICATED_FROZEN_INSTALLER_REQUIRED')
    if any(
        name == prefix or name.startswith(prefix + '.')
        for name in sys.modules
        for prefix in ('backend.app.service', 'backend.app.infrastructure.database', 'sqlite3')
    ):
        raise GuardInstallationError('INSTALLER_BUSINESS_IMPORT_REJECTED')


def require_backend_reader(inputs, reader):
    original = reader.observe()
    expected = inputs.backend.root / inputs.backend.spec.entry
    if (
        original.state != 'RUNNING'
        or original.identity.is_appcontainer
        or original.identity.is_elevated
        or original.identity.user_sid != inputs.plan['backend_sid']
        or absolute_path(original.identity.image_path) != expected
    ):
        raise GuardInstallationError('ORIGINAL_FIXED_BACKEND_READER_REQUIRED')
    inputs.backend.verify()


def prepare_request(prepared, plan_sha, installer_root, installer_sha, output):
    output = _new_directory(output)
    with (
        GuardBootstrapSources(prepared, plan_sha) as inputs,
        ProgramPackageLease(
            installer_root, expected_sha256=installer_sha, policy=INSTALLER_POLICY
        ) as installer,
        LocalPathGuard(output.parent, directory=True),
    ):
        for root in (inputs.root, inputs.guard.root, inputs.backend.root, installer.root):
            if output.is_relative_to(root) or root.is_relative_to(output):
                raise GuardInstallationError('INSTALLATION_REQUEST_OUTPUT_OVERLAPS_SOURCE')
        target = absolute_path(inputs.plan['installation_root'])
        if output.is_relative_to(target) or target.is_relative_to(output):
            raise GuardInstallationError('INSTALLATION_REQUEST_OUTPUT_OVERLAPS_TARGET')
        raw = _bytes(make_installation_request(inputs, installer.spec.manifest_sha256))
        expected = hashlib.sha256(raw).hexdigest()
        text = (
            '# Guard受信安装输入\n\n'
            '此目录只准备输入，未创建安装目标、注册／启停服务或修改ACL／WFP。\n\n'
            f'固定请求SHA256：{expected}\n\n'
            f'计划安装目录：{target}\n\n'
            f'唯一新服务：{inputs.plan["service"]["name"]}\n\n'
            '安装和启停是两个显式动作，必须先有本轮系统授权及管理员确认。'
            '只操作请求中的全新私有目录／服务，普通后台／浏览器不提权；'
            'task／runtime／checks=null，不调用模型或更改WFP。'
            '请求明确程序／journal／服务Owner、DACL、必要权限和固定时限。'
            '不覆盖现有目录或服务，不自动修复、回滚删除或重试未知动作。\n\n'
            '使用专用walle-guard-installer.exe，固定--program-sha256、--request和'
            '--request-sha256；原普通后台读者另明确--reader-pid与--reader-created-at。'
            '--inspect只核对原输入；--install创建／复核新资源并注册为停止状态；'
            '--start-stop另需本轮私有--probe-channel进行有界启停。'
            '源或请求变化必须重新准备，不能使用latest或把此说明当永久授权。\n'
        )
        with TemporaryDirectory(prefix='.we-ir-', dir=output.parent) as temporary:
            stage = Path(temporary) / 'prepared'
            stage.mkdir()
            write_new_verified_file(stage / REQUEST_NAME, raw)
            write_new_verified_file(stage / 'README.md', text.encode('utf-8'))
            inputs.verify()
            installer.verify()
            _new_directory(output)
            os.rename(stage, output)
        return expected


def install(inputs, reader, request, request_raw, request_sha, operator):
    require_backend_reader(inputs, reader)
    inputs.verify_parent_access(reader)

    def checkpoint():
        inputs._checkpoint()
        if reader.observe().state != 'RUNNING':
            raise GuardInstallationError('ORIGINAL_BACKEND_READER_EXITED')

    with (
        NativeGuardService(request, operator, new=True) as service,
        ProtectedInstallationWriter(request, operator, checkpoint) as writer,
    ):
        root_id = writer.create_directory(writer.root)
        inputs.bind_new_installation_root(writer._guards[writer.root])
        writer.write_bytes(writer.root / INTENT_NAME, request_raw)
        writer.copy_program('guard', inputs.guard, GUARD_PROGRAM_POLICY)
        writer.copy_program('backend', inputs.backend, BACKEND_PROGRAM_POLICY)
        writer.write_file(writer.root / DEPLOYMENT_NAME, inputs._inputs[DEPLOYMENT_NAME])
        journal_id = writer.create_system_journal()
        with ControllerPrimaryToken(reader, expected=reader.identity) as token:
            writer.verify_program_access(token, {'guard': inputs.guard, 'backend': inputs.backend})
        inputs.verify()
        service.create()
        receipt = {
            'schema_version': 1,
            'policy_version': 'GUARD20-INSTALLATION-RECEIPT-1',
            'request_sha256': request_sha,
            'installation_root': asdict(root_id),
            'journal_root': asdict(journal_id),
            'service_name': service.name,
            'state': 'REGISTERED_STOPPED',
        }
        writer.write_bytes(writer.root / RECEIPT_NAME, _bytes(receipt))
        with ControllerPrimaryToken(reader, expected=reader.identity) as token:
            writer.verify_program_access(
                token, {'guard': inputs.guard, 'backend': inputs.backend}, include_receipt=True
            )
        service.verify()
        if service.status().state != 1:
            raise GuardInstallationError('INSTALLED_SERVICE_STOPPED_STATE_UNVERIFIED')
    print('NEW_GUARD_REGISTERED_STOPPED no_os_runtime_or_task_admission', flush=True)


def verify_installed(inputs, reader, request, request_sha, operator):
    root = absolute_path(request['installation_root'])
    expected_names = {'guard', 'backend', 'journal', INTENT_NAME, DEPLOYMENT_NAME, RECEIPT_NAME}
    with os.scandir(root) as entries:
        if {entry.name for entry in entries} != expected_names:
            raise GuardInstallationError('INSTALLED_ROOT_MEMBERS_DIFFER')
    with (
        LockedFileSource(root / INTENT_NAME, max_file_bytes=256 * 1024) as intent,
        LockedFileSource(root / DEPLOYMENT_NAME, max_file_bytes=2 * 1024**2) as deployment,
        LockedFileSource(root / RECEIPT_NAME, max_file_bytes=16384) as receipt_source,
        ProgramPackageLease(
            root / 'guard',
            expected_sha256=inputs.guard.spec.manifest_sha256,
            policy=GUARD_PROGRAM_POLICY,
        ),
        ProgramPackageLease(
            root / 'backend',
            expected_sha256=inputs.backend.spec.manifest_sha256,
            policy=BACKEND_PROGRAM_POLICY,
        ),
        ProtectedInstallationWriter(request, operator, inputs._checkpoint) as verifier,
        ControllerPrimaryToken(reader, expected=reader.identity) as token,
    ):
        if (
            intent.snapshot.sha256 != request_sha
            or deployment.snapshot.sha256 != request['deployment_sha256']
        ):
            raise GuardInstallationError('INSTALLED_ORIGINAL_INPUTS_DIFFER')
        receipt = exact(
            strict_json_object(receipt_source.snapshot.raw),
            (
                'schema_version',
                'policy_version',
                'request_sha256',
                'installation_root',
                'journal_root',
                'service_name',
                'state',
            ),
        )
        if (
            type(receipt['schema_version']) is not int
            or receipt['schema_version'] != 1
            or receipt['policy_version'] != 'GUARD20-INSTALLATION-RECEIPT-1'
            or receipt['request_sha256'] != request_sha
            or receipt['service_name'] != request['service']['name']
            or receipt['state'] != 'REGISTERED_STOPPED'
            or _bytes(receipt) != receipt_source.snapshot.raw
        ):
            raise GuardInstallationError('INSTALLED_RECEIPT_BINDING_DIFFERS')
        with LocalPathGuard(root, directory=True) as original:
            if file_identity(receipt['installation_root'], directory=True) != original.verify():
                raise GuardInstallationError('INSTALLED_ORIGINAL_ROOT_DIFFERS')
        journal = file_identity(receipt['journal_root'], directory=True)
        if journal.canonical_path != str(root / 'journal'):
            raise GuardInstallationError('INSTALLED_ORIGINAL_JOURNAL_REFERENCE_DIFFERS')
        # SYSTEM-only journal contents remain private. Guard verifies the actual journal on startup.
        verifier.verify_program_access(
            token, {'guard': inputs.guard, 'backend': inputs.backend}, include_receipt=True
        )


class ProbeChannel:
    def __init__(self, root, request_sha, reader):
        self._root = local_absolute_path(root)
        self._package = PrivatePackageGuard(self._root)
        self._source = None
        self._owners = [self._package]
        self._closed = False
        self._close_failed = False
        self._orphaned = []
        try:
            self._package.__enter__()
            with os.scandir(self._root) as entries:
                if {entry.name for entry in entries} != {'channel.v1.json'}:
                    raise GuardInstallationError('NEW_PRIVATE_PROBE_CHANNEL_REQUIRED')
            self._source = LockedFileSource(self._root / 'channel.v1.json', max_file_bytes=4096)
            self._owners.append(self._source)
            raw = self._source.snapshot.raw
            value = exact(
                strict_json_object(raw),
                ('request_sha256', 'reader_pid', 'reader_created_at', 'channel_ref'),
            )
            if (
                value['request_sha256'] != request_sha
                or type(value['reader_pid']) is not int
                or value['reader_pid'] != reader.identity.pid
                or value['reader_created_at'] != reader.identity.creation_time_hex
                or digest(value['channel_ref']) != value['channel_ref']
                or _bytes(value) != raw
            ):
                raise GuardInstallationError('ORIGINAL_PRIVATE_PROBE_CHANNEL_DIFFERS')
        except BaseException as original:
            retained = getattr(original, 'retained_owner', None)
            if retained in self._owners:
                self._owners.remove(retained)
                self._orphaned.append(retained)
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def _verify(self):
        if self._closed or self._close_failed:
            raise GuardInstallationError('PROBE_CHANNEL_OWNER_UNVERIFIED')
        self._package.verify()
        self._source.verify()

    def stopped(self):
        self._verify()
        target = self._root / 'STOP'
        try:
            target.lstat()
        except FileNotFoundError:
            return False
        with LockedFileSource(target, max_file_bytes=16) as source:
            if source.snapshot.raw != b'STOP\n':
                raise GuardInstallationError('PROBE_CHANNEL_COMMAND_REJECTED')
        return True

    def ready(self, identity):
        self._verify()
        write_new_verified_file(
            self._root / 'READY',
            _bytes({'pid': identity.pid, 'created_at': identity.creation_time_hex}),
        )

    def close(self):
        if self._close_failed:
            error = GuardInstallationError('PROBE_CHANNEL_CLOSURE_PREVIOUSLY_UNVERIFIED')
            error.retained_owner = self
            raise error
        if self._closed:
            return
        failures = []
        for owner in reversed(self._owners):
            try:
                owner.close()
            except BaseException as error:  # noqa: BLE001 -- Close all known owners once.
                failures.append(error)
                self._orphaned.append(owner)
        if failures or self._orphaned:
            self._close_failed = True
            error = GuardInstallationError('PROBE_CHANNEL_CLOSURE_UNVERIFIED')
            error.retained_owner = self
            raise error from (failures[0] if failures else None)
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        self.close()


def start_stop(inputs, reader, request, request_sha, operator, channel_root, *, undispatched=False):
    require_backend_reader(inputs, reader)
    inputs.verify_parent_access(reader)
    verify_installed(inputs, reader, request, request_sha, operator)
    with (
        NativeGuardService(request, operator, new=False) as service,
        ProbeChannel(channel_root, request_sha, reader) as channel,
    ):
        service.verify()
        if undispatched:
            state = service.status()
            if (
                state.state != 1
                or state.pid != 0
                or state.win32_exit_code != 1077
                or state.service_exit_code != 0
            ):
                raise GuardInstallationError('ORIGINAL_GUARD_NEVER_STARTED_STATE_REQUIRED')

        def cancelled():
            return reader.observe().state != 'RUNNING' or channel.stopped()

        try:
            identity = service.start(cancelled)
            channel.ready(identity)
            deadline = monotonic() + request['limits_ms']['probe_hold'] / 1000
            while monotonic() < deadline and not cancelled():
                if service._process.observe().state != 'RUNNING' or service.status().state != 4:
                    raise GuardInstallationError('ORIGINAL_GUARD_LOST_DURING_PROBE')
                sleep(0.1)
        finally:
            service.stop_owned()
    print('OWNED_GUARD_START_AND_STOP_VERIFIED no_task_wfp_or_product_admission', flush=True)


def main(arguments=None):
    require_installer_runtime()
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--install', action='store_true')
    mode.add_argument('--start-stop', action='store_true')
    parser.add_argument('--program-sha256', required=True)
    parser.add_argument('--request', required=True)
    parser.add_argument('--request-sha256', required=True)
    parser.add_argument('--reader-pid', type=int, required=True)
    parser.add_argument('--reader-created-at', required=True)
    parser.add_argument('--probe-channel')
    parser.add_argument('--original-installer-package', type=Path)
    values = parser.parse_args(arguments)
    if re.fullmatch('[0-9a-f]{16}', values.reader_created_at) is None:
        parser.error('An original reader creation time is required')
    if values.original_installer_package is not None and not values.start_stop:
        parser.error('Original installer continuation is only permitted for --start-stop')
    if values.start_stop != (values.probe_channel is not None):
        parser.error('Only --start-stop requires the new private probe channel')
    with (
        ProgramPackageLease(
            Path(sys.executable).parent,
            expected_sha256=values.program_sha256,
            policy=INSTALLER_POLICY,
        ) as own_program,
        LockedFileSource(absolute_path(values.request), max_file_bytes=256 * 1024) as source,
        ObservedProcess(values.reader_pid) as reader,
        ExitStack() as originals,
    ):
        own_program.verify_running_entry(sys.executable)
        if source.snapshot.sha256 != digest(values.request_sha256):
            raise GuardInstallationError('ORIGINAL_INSTALLATION_REQUEST_DIGEST_DIFFERS')
        header = strict_json_object(source.snapshot.raw)
        bootstrap = exact(header.get('bootstrap'), ('root', 'plan_sha256'))
        request_program_sha = own_program.spec.manifest_sha256
        undispatched = values.original_installer_package is not None
        if undispatched:
            original_program = originals.enter_context(
                ProgramPackageLease(
                    local_absolute_path(values.original_installer_package),
                    expected_sha256=digest(header.get('installer_program_sha256')),
                    policy=INSTALLER_POLICY,
                )
            )
            request_program_sha = original_program.spec.manifest_sha256
            if request_program_sha == own_program.spec.manifest_sha256:
                raise GuardInstallationError('DISTINCT_FIXED_CONTINUATION_TOOL_REQUIRED')
        if reader.identity.creation_time_hex != values.reader_created_at:
            raise GuardInstallationError('ORIGINAL_READER_CREATION_TIME_DIFFERS')
        with GuardBootstrapSources(
            absolute_path(bootstrap['root']),
            digest(bootstrap['plan_sha256']),
            reader=reader,
            allow_existing_target=values.start_stop,
            timeout_ms=300000,
        ) as inputs:
            request = verify_installation_request(
                source.snapshot.raw,
                source.snapshot.sha256,
                inputs,
                request_program_sha,
            )
            require_backend_reader(inputs, reader)
            if values.inspect:
                inputs.verify_parent_access(reader)
                print('INSTALLATION_REQUEST_INSPECTED no_system_changes_or_admission', flush=True)
                return 0
            with InstallationOperator(request['backend_sid']) as operator:
                if values.install:
                    install(
                        inputs,
                        reader,
                        request,
                        source.snapshot.raw,
                        source.snapshot.sha256,
                        operator,
                    )
                else:
                    start_stop(
                        inputs,
                        reader,
                        request,
                        source.snapshot.sha256,
                        operator,
                        absolute_path(values.probe_channel),
                        undispatched=undispatched,
                    )
            source.verify()
        own_program.verify()
    return 0
