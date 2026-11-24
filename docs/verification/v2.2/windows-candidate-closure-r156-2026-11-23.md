# R156 最新本地源码及固定入口回归

2026-11-23 香港时间。独立 Windows 仓库 `output/v22-dev-isolated`，其 Git 元数据独立于主仓库，分支 `codex/v2.2-windows-implementation`，保留既有检查点 `deacba8a9545122f35a2f85c125a354205e06461`。

- 在隔离副本用项目锁定依赖运行前端 `npm run format:check`、`npm run typecheck`、`npm test`、`npm run build` 和 `npm exec --offline vite -- build --config vite.management.config.ts`。604 项前端检查通过，普通工作台和独立管理构建均通过；新增历史原操作／采用回执核对含版本错配拒绝。首轮独立副本缺少测试项目默认的 Python 路径，随后用既有锁定环境解释器设置 `WALLE_OFFLINE_TEST_PYTHON`，完整复跑通过。
- 用锁定 Python 和 SQLite 运行 `backend/tests/infrastructure/test_v22_registry_recovery_dispatch.py` 和 `backend/tests/infrastructure/test_v22_registry_recovery_disposition.py`，合计 101 项通过。另执行固定 SQLite 原四类未派发处置与实际 RESTORE、停止、采用、开放、普通应用重启联验。后端 Ruff 格式及改动范围静态检查、固定管理入口 `--help` 与 `git diff --check` 通过。用 7 种公开及内部入口核对完整参数、每个缺项及越权附带参数，在宿主动作前结束。额外扫描整个管理目录检出本轮改动范围外的 33 个既有导入排序问题。本轮改动未出现该类问题。Windows 组、Linux 私有目录和启动控制通过适配，真正 systemd 及特权资源归属仍待原生验证。
- 临时 Git 索引从 ARM64 基线 `a0f40592702cb702ed928849ac540479c22c224f` 装配并再次应用四处源码差异。84 个修改、175 个新增、2282566 字节，树 `9d546223c19e4508805036741cc2cfb6beddd7ad`，差异 SHA256 `8b9c787d254dbc3bdb97fc8b78bbc97c672d80361a7b6a6886bdf177597e42d1`。V2.01 五份设计原字节哈希与真实 Git 索引字节保持。
- 香港时间 11 月 22 日约 23:45—23:52 的严格只读 SSH 已确认 `aarch64`、独立远端路径 `~/walle-v22-validation/scopes/candidate-r65/source` 的 `codex/v2.2-arm64-r65`，同一基线且工作目录干净。复核当前仍使用管道转储，固定路径未发现 `docker`、`runsc`。现有证据不满足 P2-a 的秘密进程排除条件。原审批拒绝传输本机四处源码差异，最新源码未传输，未启动远端产品验证。
- 本地专项使用当轮拥有的临时目录和应用生命周期，测试结束清理。无 Git 提交、推送、采购、真实模型或计数访问，无用户服务更新。
