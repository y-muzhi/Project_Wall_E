# 仓库登记已知来源失败验证

- 2026-11-07，V2 工作区，Windows、固定 SQLite 3.54.1、隔离私有 NTFS 目录和本机测试所有者。原登记 runner 在明确来源拒绝时先关闭所属本地读取资源，再在原范围确认 PREPARE 未可能派发或 RELEASE 已可靠清理。更新原 VALIDATE 和操作为 FAILED，保留 SAVE_FACT 待开始及原 202。原 MAY 存在而 RELEASE 未证实时保持原 UNKNOWN 路径。
- `tools/python-v20.py tools/quality_python.py`，三文件 `test_repository_git_dispatch.py`、`test_repository_operations.py`、`test_v20_guard_control_git_transport.py`，27 项通过，84.95 秒。实际空目录拒绝通过原 runner 与 API17 读取，原 202 重放、无仓库／任务且无 Guard 传输；派发 port 核对原 RELEASE 屏障，真实 Native 回归覆盖成功登记及 CREATE 回执丢失后的原资源清理。
- 236 个 app 文件 Ruff 格式、两处改动 Ruff lint 通过。固定 Schema 仍 db20-r15，未执行正常库升级或用户服务更新。Guard 系统宿主、C01／C02 业务 HTTP 和正常部署准入仍未接入。
