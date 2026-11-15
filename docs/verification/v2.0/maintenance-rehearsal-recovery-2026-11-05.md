# V2.0封存演练、原库提交及恢复组合

日期：2026-11-05；HEAD 28a7c9e，V2未提交。固定SQLite3.54.1，真实本轮私有临时包及非空151副本；未操作正常库、用户服务或真实供应方。

依据BE 7.1.3—7.1.6。schema_v20_maintenance.py将已封存计划／备份、同发布／程序／原路径和原生身份接入完整演练、原文件apply及只核对recover。

- 演练从实际已核验备份经Backup API生成独立UUID文件，同原upgrade_id而使用副本真实FileIdentity。实际同引擎升级、新连接重开、旧Requirement／Document／Audit仓储查询摘要对照、文档调用不能读作Coding／Testing、真实不可变／owner约束拒绝两项探针，完整旧投影和新业务表为空均核对后才封存PASSED。无调用行时明确探针数0，不虚填2。失败保留副本和INCOMPLETE回执，再次显式演练用新文件，不覆盖旧副本。
- apply必须读取同原upgrade_id／plan_sha256并核对备份、审计副本及真实演练库／封存摘要。原源未变才走同引擎单次提交；始终原路径，绝不以副本替换。重复已提交仅原marker核对，无再次DDL。
- 维护回执为私有目录中新UUID不可覆盖文件，绑定原计划／程序／发布与观察。数据库与回执两个事实分开：commit ACK未知不写成功；commit已成功但回执失败抛待核对，只能显式recover，不自动重试。
- recover以已封存历史证据加原库精确200／marker核对提交；原200后正常文档写入及新审计不会被旧摘要强制覆盖，返回ALREADY_COMMITTED与CURRENT_DATA_CHANGED，当前完整性／FK另查。源变／缺演练／篡改／未知对象阻断，保留原库及资产。
- 程序摘要覆盖backend/app全部Python源码、固定维护源清单、显式启动工具（已有CLI若存在也绑定）；代码变化使旧计划失效。仍无正常库授权或服务自动启停。

检查：tools/python-v20.py tools/quality_python.py，maintenance_flow／maintenance_plan／schema_release三文件，18通过／14子场景（79.83秒）。原路径全链路、同键重复、演练失败后新副本、源变／演练篡改、commit回执丢失、外部回执丢失、后续实际RequirementRepository.update_attributes写入均使用隔离真实SQLite。首轮5通过／2失败，原因是测试标题超20字及不存在的update方法；按当前业务夹具修正，非产品放宽校验。最终上述组合全通过。

测试专属临时目录已自动清理，无JSON报告／原始日志留存。正式维护备份／演练资产无GC；测试副本自动清理不用于正常资产。CLI／实际发布资源pin／正常启动200切换仍待接，未取得真实断电、LPAC／Guard、Git／OpenCode、供应方或前端验收。
