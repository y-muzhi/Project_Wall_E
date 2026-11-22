# WALL-E V2.2 普通环境备份包

实施条目 R15。依据 V2.01 后端设计 4.12.1–4.12.3、7.10，接续 R6 的停写捕获、R7 的独立换代、R8 的原结果索引和 R14 的同源核对。

- 受信封存计划固定来源安装、同源链摘要及独立输出目录。维护身份在核对原组件后，仅从已封存的恢复点复制数据库、计数审计和原回执索引。数据库按块复制，同时校验原快照的长度、摘要及文件身份。
- 私有临时目录准备完整内容，最后写入 `backup-manifest.v1.json`，复核后原子发布到固定包目录。重复同一意图读回同一份包。已发布目录保留供重新核验。
- 清单记录来源环境、代次、部署、控制修订、截止点和原逻辑内容，固定运行包及配置引用，及实际数据库、计数资料、原结果索引、独立恢复回执与覆盖核对摘要。恢复证据中的历史文件身份仅供追溯。包内引用使用相对路径。
- 独立验包入口以受信计划固定清单摘要、备份键和当前包根身份，可在原环境和原组件均不可访问时重新检查目录成员、全部资产和所有索引分片。发现变更、缺件、额外成员或其他来源时停止。固定清单外置可信摘要按部署规则传递。
- 完整性核对后的包状态为 `UNVERIFIED`，表示尚待以完整封存包为输入的独立演练。R14 原组件恢复证据随包保留。只有独立演练及异机实际取回复核分别完成后才进入对应更高状态。

`manage_registry.py seal-backup-package` 使用来源安装的 `--anchor` 与 `--anchor-sha256`，另提供 `--backup-package-policy` 和摘要。受保护的 `backup-package-policy.v1.json` 固定 `operation_id`、`backup_id`、`installation_sha256`、`chain_policy`（路径及摘要）、`recovery_chain_sha256`、`recovery_directory` 和 `recovery_identity`。

`verify-backup-package` 则以受保护的 `backup-package-verification.v1.json` 及摘要作为 `--anchor` 与 `--anchor-sha256`。该计划固定 `backup_id`、`package_directory`、`package_identity` 和 `backup_manifest_sha256`，取回时使用当前独立验包根的实际身份。两种计划均为 `format_version=1`，继承固定维护运行包和执行身份参数。
