# WALL-E V2.2 完整备份包的隔离数据演练

实施条目 R16。依据 V2.01 后端 4.12.1—4.12.2、7.10。输入为 R15 已封存的普通环境备份包，演练经固定维护入口启动。

1. 受信演练计划固定独立的包验读计划、同一来源环境、新数据代次、Schema 根和专用新恢复根身份。新代次必须同时异于备份原代次及包内已引用的组件恢复代次。恢复根与包、程序、配置计划、运行、临时及 Schema 根分开。
2. 按固定清单验证全部包内文件并核对固定 Schema 的清单和契约。复用原独立换代工具，在验证专用根生成 SQLite 新副本，原首次初始化信息和业务内容保持，计数审计原字节随副本恢复。
3. 原结果仍以包内旧代次索引作为只读证据。原环境安装、业务库或原组件的文件身份不作为新恢复根的准入依据。最后重新查验包，并独立重开新副本；同一演练意图回读同一数据代次。中断后的部分新根保留供原意图核对。
4. 回执标明包完整恢复的数据证据和外发保留要求。此步骤从维护工具生成验证专用副本，与外层控制切换、禁外发应用实际启动和可读核对相接前，恢复点保持 `UNVERIFIED`。

`manage_registry.py rehearse-backup-package` 使用 `backup-package-rehearsal.v1.json` 及原计划摘要作为 `--anchor` 和 `--anchor-sha256`。版本为 1。字段为 `operation_id`、`package_verification`（R15 验包计划路径及摘要）、`source_environment_id`、`target_data_generation`、`target_directory`、`target_identity`、`schema_directory`。目标目录以 `operation_id` 命名，由本次执行身份预留。
