"""Prepare explicit Guard bootstrap resources for review; no installation or ACL changes."""

import argparse
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.infrastructure.deployment_manifest import digest
from backend.app.infrastructure.guard_deployment_configuration import decode_guard_deployment
from backend.app.infrastructure.program_manifest import BACKEND_PROGRAM_POLICY, GUARD_PROGRAM_POLICY
from backend.app.infrastructure.program_package import ProgramPackageLease
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.infrastructure.windows_guard_service import guard_service_name
from backend.app.infrastructure.windows_local_paths import LocalPathGuard, local_absolute_path
from backend.app.infrastructure.windows_process import ObservedProcess
from tools.windows_guard_plan import make_bootstrap_plan
from tools.windows_program_package import ProgramBuildError, validate_program_destination
from tools.windows_program_package import write_new_verified_file as _write_new

ROOT = Path(__file__).resolve().parents[1]


def _new_directory(path):
    path = local_absolute_path(path)
    if path.exists() or path.is_symlink() or path.is_junction():
        raise ProgramBuildError('NEW_INSTALLATION_OR_PREPARATION_DIRECTORY_REQUIRED')
    if any(ord(value) < 32 or value == '"' for value in str(path)):
        raise ProgramBuildError('INSTALLATION_PATH_CHARACTERS_UNSUPPORTED')
    return path


def _backend_sid():
    with ObservedProcess(os.getpid()) as process:
        observed = process.observe()
        identity = observed.identity
        if (
            observed.state != 'RUNNING'
            or identity.is_appcontainer
            or identity.is_elevated
            or identity.user_sid in ('S-1-5-18', 'S-1-5-19', 'S-1-5-20')
        ):
            raise ProgramBuildError('ORDINARY_BACKEND_PREPARATION_IDENTITY_REQUIRED')
        return identity.user_sid


def prepare(
    guard_root,
    guard_sha256,
    backend_root,
    backend_sha256,
    installation_root,
    installation_ref,
    output,
):
    installation_root = _new_directory(installation_root)
    output = _new_directory(output)
    if output.is_relative_to(installation_root) or installation_root.is_relative_to(output):
        raise ProgramBuildError('INSTALLATION_AND_PREPARATION_MUST_BE_SEPARATE')
    service_name = guard_service_name(installation_ref)
    guard_sha256, backend_sha256 = digest(guard_sha256), digest(backend_sha256)
    backend_sid = _backend_sid()
    with (
        ProgramPackageLease(
            guard_root, expected_sha256=guard_sha256, policy=GUARD_PROGRAM_POLICY
        ) as guard,
        ProgramPackageLease(
            backend_root, expected_sha256=backend_sha256, policy=BACKEND_PROGRAM_POLICY
        ) as backend,
        LocalPathGuard(output.parent, directory=True),
    ):
        for source in (guard.root, backend.root):
            if output.is_relative_to(source) or source.is_relative_to(output):
                raise ProgramBuildError('PREPARATION_OUTPUT_OVERLAPS_SOURCE')
            if installation_root.is_relative_to(source) or source.is_relative_to(installation_root):
                raise ProgramBuildError('INSTALLATION_ROOT_OVERLAPS_SOURCE')
        guard_manifest = guard._sources[GUARD_PROGRAM_POLICY.manifest_name].verified_raw()
        backend_manifest = backend._sources[BACKEND_PROGRAM_POLICY.manifest_name].verified_raw()
        guard_destination = installation_root / 'guard'
        backend_destination = installation_root / 'backend'
        validate_program_destination(
            guard_destination, guard_manifest, guard_sha256, policy=GUARD_PROGRAM_POLICY
        )
        validate_program_destination(
            backend_destination, backend_manifest, backend_sha256, policy=BACKEND_PROGRAM_POLICY
        )
        deployment = {
            'schema_version': 2,
            'protocol_version': 'DEPLOY20-GUARD-2',
            'installation_ref': installation_ref,
            'backend_sid': backend_sid,
            'backend_program': {
                'root': str(backend_destination),
                'manifest_sha256': backend_sha256,
            },
            'journal_root': str(installation_root / 'journal'),
            'task': None,
            'runtime': None,
            'checks': None,
            'connection_timeout_ms': 1000,
            'request_timeout_ms': 120000,
            'shutdown_timeout_ms': 120000,
        }
        raw = _bytes(deployment)
        decode_guard_deployment(raw)
        deployment_sha256 = hashlib.sha256(raw).hexdigest()
        plan = make_bootstrap_plan(raw, guard.root, guard.spec, backend.root, backend.spec)
        plan_raw = _bytes(plan)
        plan_sha256 = hashlib.sha256(plan_raw).hexdigest()
        readme = f"""# Guard独立启动准备

此目录是可审阅的部署输入，未安装／启动服务、修改ACL／WFP或创建安装目标；不产生OS准入或ready。

安装标识：{installation_ref}
服务名：{service_name}
计划SHA256：{plan_sha256}
部署文件SHA256：{deployment_sha256}
预定全新目录：{installation_root}

guard-deployment.json严格通过现有DEPLOY20-GUARD-2 decoder；实际固定后台和Guard源包均全成员核对。源包／目标或计划改变时重新准备，不把此摘要当永久安装授权。

这是最小Guard启动配置：task／runtime／checks均为空；不部署Coding、Testing执行或模型，不添加防火墙规则。不能据SCM运行就提升任务目录ready或视为完整产品验收。

管理员执行前必须重新核对两个源包、固定计划和目标仍不存在。仅在新目录中创建受保护程序、部署文件和SYSTEM私有journal，所有者和权限需由真实安装验证；普通后台对程序／部署仅读执行，不能改正文、删除、改ACL或所有者。必须核对祖先的有效权限，不能只设置文件只读属性或在可修改父目录里放置受保护子目录。

install-plan.v1.json的service.arguments是Win32参数数组，image_path是SCM二进制路径字符串，应原样作为一个字段交给服务API，不经Shell拼接或当作任意命令执行。只注册计划中的全新按需LocalSystem服务，不覆盖现有服务，不整体提升后台。

完成受保护复制和原字节校验后才允许启动。真实SCM／SYSTEM／原资源核对、停止原进程并确认无所属活动后，再按本轮所有权清理；停止失败／原状态未知时保留，不能以端口空闲、PID消失或服务删除返回当完整清理。没有用户当前系统安装授权时停留在准备阶段。

运行资源和完整包的只读核验见项目受信部署启动说明；本准备器不会生成FileID、WFP证明、运行回执或假OS证据。来源清单内的JSON是正式资源输入，非测试报告。
"""
        with TemporaryDirectory(prefix='.we-gp-', dir=output.parent) as temporary:
            stage = Path(temporary) / 'prepared'
            stage.mkdir()
            _write_new(stage / 'guard-deployment.json', raw)
            _write_new(stage / 'install-plan.v1.json', plan_raw)
            _write_new(stage / 'README.md', readme.encode('utf-8'))
            guard.verify()
            backend.verify()
            _new_directory(installation_root)
            _new_directory(output)
            os.rename(stage, output)
            return plan_sha256, deployment_sha256


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guard-package', type=Path, required=True)
    parser.add_argument('--guard-sha256', required=True)
    parser.add_argument('--backend-package', type=Path, required=True)
    parser.add_argument('--backend-sha256', required=True)
    parser.add_argument('--installation-root', type=Path, required=True)
    parser.add_argument('--installation-ref', required=True)
    parser.add_argument('--output', type=Path, required=True)
    values = parser.parse_args(arguments)
    try:
        plan, deployment = prepare(
            values.guard_package,
            values.guard_sha256,
            values.backend_package,
            values.backend_sha256,
            values.installation_root,
            values.installation_ref,
            values.output,
        )
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        if getattr(error, 'retained_owner', None) is not None:
            raise
        print('GUARD_BOOTSTRAP_PREPARATION_REJECTED')
        return 1
    print(f'GUARD_BOOTSTRAP_PREPARED plan={plan} deployment={deployment}')
    print('NO_INSTALLATION_SERVICE_ACL_WFP_OR_OS_ADMISSION')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
