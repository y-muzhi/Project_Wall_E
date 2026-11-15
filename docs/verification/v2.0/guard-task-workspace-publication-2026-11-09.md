# V2.0 固定工作区的原 PREPARE 认证发布

2026-11-09（Asia/Hong_Kong），Windows x64／本机 NTFS，工作树基线 `28a7c9e`，固定 SQLite 3.54.1。对照 BE 7.3.1—7.3.4 与 START_INSTANCE。 [独立迭代](../../iterations/pending/v2.0/WALL-E.启动固定依据准备_V_2.0.md)

- 实际同账户 Guard 和普通后端经本机认证管道使用同一原 ProcessLock、START_INSTANCE 范围及目录身份。原 PREPARE 固定工作区清单摘要，错误摘要拒绝；Guard 在发放前保存发布意图。后端只持有不可继承的匿名管道原写端，复制并读回原树字节和 NTFS 身份。Guard 只核对原读端的断开状态和原目录，再持久追加发布回执。管道内没有正文，保护程序准入为夹具。
- 正常复制覆盖多层文件、空文件、CRLF 与二进制字节。原发布回执写入后模拟回复未知，后端以只读方式核对原本机树与 Guard 回执，重复 BEGIN 拒绝。复制首个文件后发 STOP，原 nonce 封闭、STOP 为 UNKNOWN，原文件保留；写端关闭后原 STOP 才确认未派发停止。真实断线在 Guard 已复制写端、回执未送达时关闭原管道，原后端存活期间 Guard 仍能观察写端活动，等进程退出才释放原句柄。两个中断场景均未保存成功发布证据。
- 同一 PREPARE 组合以实际私有设计封存完成只读依据发布，再发布固定工作区。两个回执指向同一原输入，STOP 关闭同一 owner，业务 PREPARE 仍处原待确认阶段。
- 使用 `tools.quality_gate.environment`、隔离 `--basetemp`、`WALLE_TEST_CONTROLLER_POSITIVE=1` 执行 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short`。首轮管道 4 项通过（13.38 秒）；数据库无关扩大组合 **105 项通过**（92.33 秒），含固定工作区原组件、工作区及依据管道、Host、原记录、目录／句柄、网络回归。新增同一 PREPARE 组合单项通过（7.32 秒），最后工作区管道五种场景 **5 项通过**（18.96 秒）。仅既有 Starlette 弃用提示，隔离临时目录已核对清理。
- `.venv/Scripts/python.exe -B -m ruff format --no-cache --check backend/app` 核对 290 文件，9 个改动应用模块 Ruff lint、`git diff --check` 通过。
- 原生管道证明受控同步复制作用域的关闭，工作区全树须在启动前再次复验。受管配置与运行包、完整 PREPARE、实际 LPAC／WFP、Job、跨控制方恢复、完整 RELEASE 和任务启动仍待。前批 `db20-r29` 既有来源摘要差异仍在，数据库依赖的仓库登记本轮未复跑。 [前批证据](guard-task-file-reservation-2026-11-08.md)
