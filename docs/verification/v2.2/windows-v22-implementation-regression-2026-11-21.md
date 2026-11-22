# V2.2 Windows 隔离实施回归

2026-11-21。代码状态为 `codex/v2.2-windows-implementation` 的工作区，固定 Git 参考 `a0f40592702cb702ed928849ac540479c22c224f`，未暂存或提交。最终源码差异及验证摘要见 [R61](windows-source-transfer-r61-2026-11-21.md)。

## 检查结果

- 普通与管理前端均在临时依赖和产物目录执行。全前端 Node 测试 602 项通过，`npm run typecheck`、`npm run format:check`、普通构建和固定独立管理构建通过。普通和管理构建分别为 120／3 个文件。普通 Vite 构建报告既有 500 kB 包体提示。
- `python -m ruff format --no-cache --check backend/app tools/linux_runtime` 602 个文件通过。管理、环境及固定入口的 `ruff check --no-cache --select F` 通过，两套 Linux 固定入口 `--help` 核对已接的实际动作。V2.01 的五份文件字节摘要与基线一致。
- 用 `pytest -q -p no:cacheprovider` 共运行旧文档编辑、多文档、需求基础及 `backend/tests/test_service.py` 34 项，31 项通过。三项失败集中在旧服务用例，仍构造 `template_key`、`template_version`、`initialization_mode` 或读取旧 `guide_run_id`。提取独立的原固定 Git 基线并复跑该旧服务文件，复现完全相同的三个失败。相关测试与请求契约原字节相同。V2.2 普通服务创建、保存、重启及关停前已取得事务的撤销和原数据核对见 [R63/R65](windows-ordinary-environment-cycle-r63-2026-11-21.md)。
- 将真实管理接口及恢复只读资料与固定管理前端配套回放。隔离 Firefox 启停、维护、原发布确认、两层回执恢复、候选证据、备份、原容量控制、空／错／权限和窄布局通过对应专项。Windows 测试目录、专属浏览器配置及临时 Git 索引按所有者正常清理。原生 ARM64 的进程、服务和供应方证据分别记在各自范围。
