# R72 恢复代次的稳定数据目录

日期 2026-11-22。Windows 独立实施分支 `codex/v2.2-windows-implementation`，固定基线 `a0f40592702cb702ed928849ac540479c22c224f`，工作区源码。Linux 维护入口由 `manage_registry.py --help` 列出 `prepare-restore-generation`。测试使用临时真实 SQLite、实际文件发布和系统外进程锁，Windows 适配 Linux 所有者、目录描述符、ext4 和运行映射。FastAPI 测试不监听 TCP；临时目录和锁最终清理。

- 从真实较早包经过 R67、R68、R70 和 R71 的准备与只读核验，按原计划把实际数据库写入新代次的应用路径。真实计数审计的有文件、空目录、缺失三种情况全部通过。新库和实际审计与准备副本同字节，旧库保留。
- 模拟代次目录排他发布后丢失回执，首次结果为未确认。重试检查同一实际目录、数据库和凭证，发布只执行一次。拒绝错只读回执、外发冻结解除、审计篡改以及新数据目录意外出现 WAL。旧数据及原控制内容保持。R67—R72 串联后从两份原索引读回各自真实的原成功结果，PROCESSING 及新代次原结果返回 UNVERIFIABLE。
- 固定 Windows 运行时回归通过 30 项。命令为 `python -X utf8 -B tools/python-v20.py -m pytest -q -p no:cacheprovider --basetemp <本轮临时目录> backend/tests/infrastructure/test_v20_schema_release.py backend/tests/infrastructure/test_v20_guard_recovery.py`。后端与固定入口 Ruff 格式检查 608 个文件通过，受影响源码的未定义变量专项和差异空白检查通过。
- 最新源码从固定基线经独立临时 Git 索引验证 83 项修改、121 项新增。差异 1,638,062 字节，SHA256 `bfd3ee9496af6ef8dcb5228b999b35c8af7221be25fa4611ca6f78c0ff6b6484`，结果 Git 树 `2dcd41908de07a3790cb69561b4f554189531c67`。可在基线上重新生成，不落地长久补丁。实际索引未改写。五份 V2.01 设计逐文件 SHA256 与基线一致。
- 用既有固定程序清单计算与复验函数构造了包含 1,237 个输入的 Windows 临时应用快照，覆盖本轮六个恢复模块及受信入口。临时副本改动一个恢复模块后被拒绝。该检查适配文件归属，不代替 ARM64 封存及运行准入。
- 仅完成新代次数据目录准备。还需在 ARM64 验证新目录的实际系统归属、排他目录发布、固定进程与控制变更。普通应用仍依据原活动控制，尚未通过正式新代次进行对外服务。
