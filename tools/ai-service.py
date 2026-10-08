"""Offline readiness by default; --start explicitly imports local credentials.

Does not initialize/migrate the database, invoke the model, or select a model
alias. Uses the application's ordinary single-process production entry point.
"""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.infrastructure.production_ai import before_count
from backend.app.infrastructure.local_credentials import read_local_credential
from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE
from backend.app.infrastructure.resources import ConfigInvalid, ResourceCatalog, FUNCTIONS
from backend.app.guide.counted_context import counting_release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', action='store_true')
    parser.add_argument('--credential-file', type=Path)
    args = parser.parse_args()
    if args.credential_file and not args.start:
        parser.error('credential import requires explicit startup')
    profile = ModelProfile('offline-readiness-no-credential', DEFAULT_PROFILE)
    release = counting_release(profile)
    catalog = ResourceCatalog()
    enabled = all(before_count(profile,catalog.freeze(action,source),release) for action,source in FUNCTIONS)
    print(f'模型：{profile.model_name}；预算模式：{release["admission_mode"]}；封装余量：1024。')
    print('准入：' + ('已启用实用预算控制。' if enabled else '关闭，等待获准的观测和离线专项完成。'))
    if not args.start:
        print('离线检查；未读取密钥；未请求 Provider；未打开业务数据库。')
        return
    if not enabled:
        raise ValueError('AI admission is not enabled')
    if args.credential_file:
        key = read_local_credential(args.credential_file)
    else:
        key = os.environ.get('WALLE_MODEL_API_KEY') or read_local_credential(ROOT / '.env.local')
    # Set only this child process; inherited old model overrides cannot change
    # the exact approved default. Never export credentials to a shell or file.
    ModelProfile(key, DEFAULT_PROFILE)
    os.environ['WALLE_MODEL_API_KEY'] = key
    os.environ['WALLE_MODEL_ID'] = profile.model_name
    os.environ['WALLE_MODEL_VERSION'] = profile.model_version
    from backend.app.__main__ import main as serve
    serve()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, ConfigInvalid):
        print('AI 服务未启动：请检查准入状态、本机凭据或运行配置。', file=sys.stderr)
        raise SystemExit(1)
