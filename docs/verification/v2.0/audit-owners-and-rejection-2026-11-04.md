# V2.0 LLMUse归属、只读证据与拒绝回滚

日期：2026-11-04；HEAD 28a7c9e，源码未提交V2，无正常库／服务／真实模型或计数操作。

依据：BE 2.2确定拒绝、7.1.2三归属及外部冻结证据规则、7.1.7同原claim事务；完整阅读相关原实现、调用方、CountingJournal和CollaborationAdmission。FE 6.1及7.4本轮已全文阅读，客户端尚未实施。

实现：
- transaction_savepoint.py由现有Database事务owner控制单个业务保存点。仅执行自身精确BEGIN／ROLLBACK TO／RELEASE时暂开对应authorizer权限；回调COMMIT／ROLLBACK／SAVEPOINT仍拒绝，读事务与嵌套尝试禁止。LeasedDatabase复用原事务和退场屏障。
- 原幂等claim先保存于同事务；业务返回确定4xx或抛已登记应用拒绝时，先可靠回滚本次业务变更，再核对仍有效的原claim并提交REJECTED。500／503、提交／未知异常不转换成永久拒绝；受控回滚失败也不伪记REJECTED。
- AuditRepository.get默认只读真实document调用；显式CODING／TESTING读取必须给真实task owner ID并在SQL中核对。原transport／parse／validation／admission方法只用document读取，不对非文档调用查空GuideRun或套文档输出。prune_raw只触及guide_run_id非null分支，Coding／Testing原始证据不套旧30天清理。
- Database增加read_only明确模式，SQLite真实mode=ro且query_only，禁止初始化和写事务。CollaborationAdmission的evidence_database按真实150／151／200历史选择精确冻结／发布校验器，不默认猜151；实际只读事务内重验完整结构／checksum，200仍需要实际受信发布。保存准入与suspension查询亦限制document归属。
- 200证据分支专项用真实构造包的受信加载结果注入未发布load_release边界；不是已发布pin、正常库升级或供应方准入。

实际检查：
- 先前受控回滚＋保留／state／release组合39通过、17子场景（19.95秒）。
- 最后完整受影响组合固定SQLite启动器＋tools/quality_python.py运行13文件：v20_audit_owners／command_http／command_receipts／data_retention／schema_state／schema_release，原shared/http_errors、idempotency、execution_lease、service_foundation，原v15_model_calls／admission／recovery。结果87通过、47子场景（156.94秒）。使用真实文件SQLite及真实服务factory进程内HTTP、隔离私有替身；外网／正常data／本地凭据访问均禁止。
- audit_owners的6项覆盖真实FK三owner图、跨owner读取及旧文档变更拒绝、prune仅doc、150／151／200只读原路径、绕过query_only仍不能写mode=ro连接、伪造checksum／未知版本／相对证据路径拒绝。图中profile／来源为不可运行测试夹具，不是Git／模型／Guard准入。
- command_receipts现14项，补关闭先提交的真实第二连接竞争、关闭commit回执丢失、写后4xx返回／异常回滚、500未知不永久化、精确保存点权限及事务控制集合清理。
- 后端146文件格式及diff检查通过；专属e-*／v20-state-*／attempt-*／command-*临时目录核对无残留。测试仅Markdown记录，无原始报告／日志／截图留存。

继续：实际Schema200发布pin、Windows本地路径／文件身份／NTFS／私有包ACL、审计字节备份／空间、计划／演练／原库提交／恢复维护工具。当前未开始该单元源码；仅已分析下一批依赖。P2、全部Coding／Testing业务、真实执行器／费用、客户端恢复／页面和整版验收仍未完成，不以87项通过宣称V2完工。
