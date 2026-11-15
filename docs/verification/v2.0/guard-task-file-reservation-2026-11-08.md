# V2.0 Guard 认证管道中的原任务文件保留

2026-11-08（Asia/Hong_Kong），Windows x64／本机 NTFS，工作树基线 `28a7c9e`，固定 SQLite 3.54.1。对照 BE 7.3.1—7.3.4 与 START_INSTANCE。 [独立迭代](../../iterations/pending/v2.0/WALL-E.启动固定依据准备_V_2.0.md)

- 真实同账户双进程经本机命名管道、原 ProcessLock、管道进程身份和原 Guard Journal 发送文件保留。Guard 从原后端复制属性句柄并核对来源，在同一 PREPARE 首次接收后持久登记范围和计划摘要，保留原角色目录。完整分配保存实际 FileID；OBSERVE 同时核对私有回执和活句柄，才返回 HELD。保护程序准入为夹具。
- 新专项覆盖完整目录、部分分配、完整目录但无可观察身份回执、回执落盘后模拟发布回复未知。相同请求和同域改摘要都不重建。错误绑定拒绝，原 STOP 和 STOP 先到均保持原屏障；停后关闭原句柄，原目录对象仍在，RELEASE 保持 UNKNOWN。未派发 CREATE 或 RESUME。
- 命令使用 `tools.quality_gate.environment`、隔离 `--basetemp`、`WALLE_TEST_CONTROLLER_POSITIVE=1` 与 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short`。首次两种原生场景 **2 项通过**（5.48 秒）。补齐身份回执后，数据库无关组合 **94 项通过**（60.21 秒），包括新管道场景、来源预检、已封存 TASK、VERSION／CONFIG_PARSE、Host 会话、丢回复、Journal、控制方 owner、任务目录、依据、私有记录及 WFP 组件。仅既有 Starlette 弃用提示，命令退出 0，自动清理的测试目录已核对不存在。
- 初次扩大组合 10 项通过后，`test_real_original_endpoints_run_fixed_commands_with_durable_replies[REGISTER]` 的子进程在连接管道前由 Schema 准入拒绝。冻结 `db20-r29` 的 `windows_local_paths.py` 来源摘要为 `3355969351811f653ee5a91fcf33cb6ac8a65bc4b8fb7e89587ad300c73cf3f6`，工作区为 `3f08b2ae96143ee1b2a3ed8fbefc586add53f3ba95505dbd99f2452752691509`。该文件及 Schema pin 未参与本批修改。仓库登记相关数据库回归未通过，后续独立核对来源及发布。
- `.venv/Scripts/python.exe -B -m ruff format --no-cache --check backend/app` 检查 285 文件，六个本批应用模块 Ruff lint 与 `git diff --check` 通过。Git 提示既有前端文件 CRLF。
- 本批验证文件角色保留和原句柄生命周期。整组依据成员与工作区发布的认证传输、完整 PREPARE ACK、已派发启动、跨控制方恢复、完整 RELEASE 及部署的 SYSTEM／普通后端、LPAC／WFP 有效访问仍待验证。
