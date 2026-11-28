# V2.2 Windows 旧部署工具退役验证

2026-11-27，Windows Codex 工作区 `codex/v211-document-revision`，基线 `2fe9615`。清理包括旧 OpenAI 本机服务启动和独立 Guard 安装流程。

- `git diff --check`、Ruff 后端和修改文件的格式检查及新增文档链接核对通过。使用 `rg` 核对剩余程序、测试、工作流和资源中的删除路径，未发现引用。Windows 的 Mac 启动器文件存在。
- `python -B tools/openai-service.py --help` 显示只读核对和显式观测参数，旧 `--start` 以退出码 2 拒绝。
- 固定 SQLite 入口 `tools/python-v20.py` 和 `tools/quality_python.py` 的隔离测试中，OpenAI 只读核对、CLI 准入和发布摘要约束 3 项通过。保留的 Guard 诊断、包核对及后端打包专项 101 项通过，3 项受当前 Windows 沙箱限制。最小复核重现私有目录 `APPCONTAINER_OPERATOR_REJECTED` 和硬链接 `WinError 5`，涉及仍保留的原生路径。
- 独立观测的离线回归在 90 秒到达测试时限。诊断栈停在 Windows asyncio 创建本机回环 socket pair 的 `accept`，测试未跑到模型适配器断言。
- 本轮未访问真实模型或计数 API，未启动用户服务或修改已部署版本。
