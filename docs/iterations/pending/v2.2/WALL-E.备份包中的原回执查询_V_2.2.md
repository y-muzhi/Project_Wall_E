# WALL-E V2.2 完整备份包中的原回执查询

实施条目 R17。依据 V2.01 后端 4.12.2、7.10。维护身份使用 R15 受信验包计划固定包身份和清单摘要，并显式提供来源环境、旧数据代次、原能力、原目标与原请求键。

- 原结果只从包内已封存索引读取。先核对包清单及同源证据，再核对索引范围和所查询分片字节。使用原结果摘要语义，返回已核实的终态、原 HTTP 状态与证据摘要。
- 错来源或错代次拒绝。索引中不存在或仍为处理中时记录为 `UNVERIFIABLE`。新业务库及其同名对象不参与此查询，也不查询原效果之外的正文。
- 此入口为原恢复材料的受信离线读取。应用与管理站接入仍按原读取权限，恢复包的数据状态保持原规定。

`manage_registry.py lookup-backup-result` 复用 `verify-backup-package` 的受信 `--anchor` 与摘要，附加 `--source-environment-id`、`--source-data-generation`、`--original-capability`、`--original-target`、`--original-request-key`。旧索引摘要取自固定包清单。
