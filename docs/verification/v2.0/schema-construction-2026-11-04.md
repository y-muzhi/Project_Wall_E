# V2.0 Schema构造与固定运行库检查（进行中）

日期：2026-11-04，HEAD 28a7c9e。代码尚未提交V2；未操作正常库、启停用户服务或调用真实模型／计数。

依据BE 0.17-draft-17第3章42组字段表及正文、7.1完整存储规则、4章固定步骤、6.1错误及116接口标题／48业务POST。6.2完整DTO、Git／Windows／OpenCode全文及前端逐页仍须按批阅读。

- schema_v20_columns.py覆盖全部521条正式字段（独立文档覆盖专项核对），含4个名称带数字的sha256字段；加内联／关联／元数据共56组定义。fresh／151重建最终72表结构及PRAGMA一致。
- schema_v20.py／relations／triggers：严格列类型、Money／JSON、真实复合owner外键、固定依据生成列及引用、连续步骤与证据关联、状态与不可变／追加保留。复杂跨记录业务资格仍须应用事务验证。
- legacy／assembly：冻结151不改；显式逐原列复制，保留额外原列；LLMUse三owner、原幂等账REJECTED／CLOSED排他形状。
- schema_v20_release.py：固定运行库下构造真实SQL／最终对象／来源摘要，fresh与upgrade一致才返回候选；加载时核对编译pin、资源、构造源码和运行库。尚未发布真实SchemaRelease或接入普通Database200检查，不能用于正常库升级。
- sqlite_runtime.py、tools/python-v20.py及backend/runtime/sqlite：项目内固定SQLite3.54.1 Windows x64 DLL，SHA256=4b59d3cded9dc1608544160f3b4b10ac974c6ac0d6ffc23064e5f4c8dbd05aea；官方来源ZIP／SHA3核对及清单在运行包目录。默认Python原3.45.3未替换。激活必须早于sqlite3导入且实际句柄／版本／source_id／JSON／STRICT／FK实测，拒绝未知加载；未全局安装或重启服务。
- 用户已确认ARK_CN_BEIJING和READ／WRITE／EXECUTE／NETWORK／UNKNOWN枚举建议，见pending独立迭代；UNKNOWN禁止授权的原生适配器尚待实施。

实际检查（均隔离，禁止外网与正常数据／凭据访问）：

- 固定运行库启动器运行test_v20_schema_construction：11通过，含521字段覆盖和fresh／upgrade一致。
- tools/python-v20.py tools/quality_python.py运行test_v20_schema_graph及test_v20_schema_migration：最近一次共8通过（49.82秒），含非空真实151原值／序列保留、失败回滚、重开、旧程序拒绝200、跨owner／固定依据及多态来源。
- test_v20_schema_release：3通过，实际候选加载、篡改拒绝、未知DLL拒绝。
- test_v20_data_retention：此前16通过。不同时间的检查不拼为一次全量通过。
- 固定运行库下原V1.5质量入口32个文件逐文件隔离回归：31文件通过；test_v15_evaluation_tool在300秒限制内出现1个失败并超时，尚待单项定位。不是完整通过，也不重复运行已通过文件。既有Starlette弃用提示未改依赖。
- 31文件分别覆盖comments、documents／editing、guide的acceptance／admission／cards／context／comment_guides／count_probe／counting／document_driven／document_assistant_isolation／execution／local_revision／model_calls／long_output／observation／progress／recovery／scenarios／startup_tool／worker_recovery／usage、基础资源／模型审计、requirements、history、suggestions及service_foundation。

已修复构造问题：旧新列须在表约束前、LLM owner括号、复合FK所需UNIQUE、字段提取漏数字、Money多小数点、NULL绕过CHECK、发布资源名单误加源码。测试发现失败后修复并重查对应路径。

待完成：普通Database200最终结构／两种历史与state校验、实际发布pin、显式plan／rehearse／apply／recover／check维护工具及Windows路径／ACL／身份／审计备份安全边界；随后原幂等事务接收／关闭／回执和业务接入。当前没有正常库升级／Windows Guard／OpenCode／Git／供应方或整版产品验收证据。测试临时库和产物按所有权清理，未保留原始测试JSON／日志。

## Database200入口单元完成

现有Database新增显式schema_release参数，旧默认151不变；schema_v20_state在实际事务内核验最终72表及完整对象／PRAGMA、两种允许迁移历史和单例marker、WAL。init仅空库建200，151／只含view的非空库拒绝，重复初始化只检查；提交后新连接重开。backup_to复用SQLite Backup API，增加同读快照检查及排他新目标创建。

最近组合命令：固定启动器＋tools/quality_python.py，test_v20_schema_state、test_v20_data_retention、test_v20_schema_release及test_v15_foundation：34通过、12子场景通过（12.56秒）。新state6项包括真实151非空升级后继续原文档业务写入、marker不强求当前数据等于升级快照、备份重新打开；无正常库操作。最初测试夹具误以为sqlite连接上下文会关闭连接，导致临时清理失败，现用closing显式关闭并重查通过。默认受限环境HTTP检查超时，本轮专属进程／路径经核对后清理，最终在获准隔离环境检查，外网／正常数据／凭据保护保持。

评估工具原失败单项在无并发源码修改的隔离环境1通过（214.12秒）；其余11项另次67.81秒通过。原先31文件结果加该文件分次检查，不称一次全量通过；原并发失败原因未取得完整traceback，不推断已证明是摘要竞态。未保留临时原日志／报告。

下一单元：同一幂等账内原键原子接收／关闭及可信原回执；共享HTTP按V2细节契约接入，原文档错误形状保持。完整Schema发布pin／正式维护流程仍待实现。
