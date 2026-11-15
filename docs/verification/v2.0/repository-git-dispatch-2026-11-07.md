# 仓库原 Guard 派发记录验证（2026-11-07）

原业务范围仍为 REGISTER_REPOSITORY.VALIDATE，固定两步骤。后端在原 SQLite 行一次性保存真实控制方、epoch、随机 nonce 和私有记录根的 FileID。每个技术动作在原私有包追加不可覆盖的 MAY 和 ACK，复用现有 LaunchJournal scope 门和 PrivateRecordAppend。SQLite 不在等待管道期间持有写事务。

首轮保留数据库触发器时，最初回写 external_identity 的实现被 ORIGINAL_FACT_IS_FIXED 拒绝。已改为不可变指向和追加原证据，未修改 Schema、触发器或正常业务库。实际临时 SQLite 与 NTFS 记录组合验证派发前 MAY 已可重读、CREATE ACK 保存完整原进程事实后才可 RESUME、缺前置和重复派发拒绝、丢 CREATE 回执保留原 MAY 且禁止重新创建或恢复。传输用显式端口，真实管道证据见配置管道记录。

`tools/python-v20.py tools/quality_python.py` 在清理式临时目录运行本批及仓库登记／接收／操作查询 4 文件，**43 项通过**（64.24 秒）。只有既有 Starlette 依赖弃用提示。235 个 app 文件 Ruff 格式及新增模块 lint、Git 差异检查通过。后端生产 runner、C01／C02 HTTP 及未知后观察／清理继续接入。
