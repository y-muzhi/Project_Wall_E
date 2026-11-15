# V2.0 整组依据的原 PREPARE 认证传输

2026-11-09（Asia/Hong_Kong），Windows x64／本机 NTFS，工作树基线 `28a7c9e`，固定 SQLite 3.54.1。对照 BE 7.3.1—7.3.4 与 START_INSTANCE。 [独立迭代](../../iterations/pending/v2.0/WALL-E.启动固定依据准备_V_2.0.md)

- 实际同账户 Guard 和普通后端进程走本机认证管道、原 ProcessLock、原操作和目录。计划分段，Guard 核对完整摘要、按编号发放原最小写句柄，拒绝重复发放。后端从私有封存复制 UTF-8／CRLF 及空文件，经写端关闭、Guard 原读 pin 和后端读回确认，最后保存一次原整组关闭证据。保护程序准入为夹具。
- 分段少一部分时拒绝发放，重复分段拒绝。整组记录落盘后模拟发布回复未知，核对只读查回原证据，重复 FINISH 不写。STOP 在实际写端仍打开时返回 UNKNOWN，原 nonce 已封闭，迟到发放拒绝；后端关闭后由原 STOP 查实并确认，原目录文件仍在。
- 实际断线场景在 DuplicateHandle 成功、写句柄回复尚未交付时关闭原管道。后端收到原交换未知，Guard 保留原槽与目录，真实 NTFS 返回共享冲突 32。等原后端退出后原 Guard owner 关闭句柄，无整组关闭证据或启动回执。
- 命令使用 `tools.quality_gate.environment`、隔离 `--basetemp`、`WALLE_TEST_CONTROLLER_POSITIVE=1` 与 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short`。前三个原生场景 3 项通过（13.56 秒）。加入真实断线后数据库无关组合 98 项通过（72.82 秒）。完成分段后同范围最终 **98 项通过**（75.53 秒）。含 `test_authenticated_task_basis_transfer` 的四个场景、原目录保留、来源预检、已封存 TASK、VERSION／CONFIG_PARSE、Host、原回复丢失、Journal、owner、NTFS 目录／依据、私有记录和 WFP 组件。仅既有 Starlette 弃用提示。三个隔离命令退出 0，自动清理目录均已核对不存在。
- 内存容量检查以 1,024 项计划分 4 帧调用原 Guard 帧编码及同一计划重组逻辑，最大负载 30,849 字节，帧上限 65,532 字节，整组摘要相同。`.venv/Scripts/python.exe -B -m ruff format --no-cache --check backend/app` 检查 287 文件，7 个改动应用模块 Ruff lint、`git diff --check` 通过。
- 正常 START 的工作区发布、完整 PREPARE ACK／CREATE、跨控制方恢复、完整 RELEASE、部署的 SYSTEM／普通后端异账户及实际 LPAC／WFP 尚未验证。前批 `db20-r29` 的既有来源摘要差异仍在，数据库依赖的仓库登记本轮未复跑。 [前批证据](guard-task-file-reservation-2026-11-08.md)
