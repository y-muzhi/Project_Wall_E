# V2.2 开发库文档 AI 结构演练

2026-11-27（香港时间）。独立检出 `990ed2d`，路径 `.tmp/v22-document-ai`。通过原 SSH 跳板确认 Mac Linux 的 `walle22-mac-dev.service` 为 active，定位开发库，并校验实际数据库的环境 ID。Mac 开发进程的 systemd 主 PID 指向系统包装器，直接复用该进程的解释器未通过 SQLite 版本前置检查。复验显式使用开发环境已固定的 `dev/runtime/bin/python3.13`，SQLite 3.54.1。

- Windows 合成验证先用项目固定 SQLite 3.54.1 和固定 `db20-r50` 构造 301 对象的 V2.2 派生结构。用 `sqlite3.Connection.backup` 备份，再在单一事务中执行 `db21-r8/upgrade-200.v1.sql` 的 74 条 DDL。环境绑定及序列内容保留，完整性、回滚后结构恢复、提交后新增对象和原件读回均通过。
- Mac Linux 在原库以 SQLite URI `mode=ro` 打开并设 `PRAGMA query_only=ON`，用 `Connection.backup` 生成来宾临时副本。副本执行同一固定 DDL。301 个原对象定义不变，新增 74 个对象，原 73 张表逐表内容摘要一致。`PRAGMA integrity_check`、`PRAGMA foreign_key_check`、事务回滚及提交后的读回复核均通过。只输出统计及结论。副本由 `TemporaryDirectory` 清理。
- 独立检出运行 `.venv` 对应的解释器加 `-B tools/openai-service.py`，报 `OPENAI_READY`、`gpt-6.2-sol`、`OFFLINE_READY`，凭据读取、供应方请求和服务启动均为零。
- `environment_binding.py` 仍精确核对普通结构、单条 Schema200 迁移记录及绑定。`environment_release_preflight.py` 和 `environment_release_compatibility.py` 检查前后结构摘要一致。此次只证明固定 DDL 能安全叠加到副本，需要正式的目标结构、来源凭证及非同结构切换支持后才能启动候选。

本次未改动运行库、网关或任何服务。未给副本写入正式 Formation 迁移标记，未接通 API、后台和页面，未执行真实模型或计数请求。
