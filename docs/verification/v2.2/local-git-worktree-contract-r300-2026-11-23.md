# R300 工作树归属的共享 Git 契约回归

2026-11-23，独立 `codex/2.2`，Windows 既有锁定 Python 和固定 SQLite 3.54.1。R290 的实际 Git 工作树与分支归属校验通过后，复核共用工作树读取、引用输入、配置来源与原回执契约。

- 运行 `test_git_worktrees.py`、`test_git_ref_protocol.py`、`test_git_local_config.py`、`test_git_private_config_parse.py` 和 `test_git_receipts.py`。包括真实固定 Git 对私有配置副本的两种对象格式解析、原借用归还和精准清理。
- 第一次 294 项通过，两个 Windows 工作进程在启动前失败。旧测试入口默认从当前 Git 根下的 `.venv` 启动解释器，隔离副本只显式引用项目锁定解释器。给这两个测试的原工作进程传入已工作的同一解释器后，全部 296 项通过。调整只存在于临时测试运行器。
- 实际管理换代、原工作树、原分支和宿主权限证据见 [R290](local-x86-recovered-live-runtime-r290-2026-11-23.md)。本轮共享 Git 检查无提交、推送和远端访问。
