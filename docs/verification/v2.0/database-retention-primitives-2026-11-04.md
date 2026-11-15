# V2.0数据库结构与原值保留基础检查

日期：2026-11-04（Asia/Hong_Kong）。HEAD 28a7c9e；V2改动未提交。依据BE 0.17-draft-17第7.1.1—7.1.7及既有151实现，不修改两份设计。完整200 SQL／发布、维护工具及升级尚未实现。

## 实际实现与调用路径

- infrastructure/schema_inspection.py：SQLite词法token比对，保留字符串／引用标识符／运算符／数字边界；只处理无语义空白、注释及一个末尾分号。读取全部用户对象、table_xinfo／foreign_key_list／index_list／index_xinfo及STRICT／WITHOUT ROWID结构事实。对象缺失、多出或定义／PRAGMA变化拒绝；完整性与外键分别检查。不是从历史CREATE重建最终结构，也未伪造200发布清单。
- infrastructure/data_retention.py：在同一显式读事务按原列顺序及主键排序，逐值使用存储类型标签、长度和原字节；整数为固定有符号64位，REAL为IEEE754，NULL独立。返回表名／投影、行数、摘要，不返回业务行值。原schema_migrations的151投影和sequences保留；新增200行、列或业务表不混入原投影。
- inspect_v151_source→Database.transaction→事务内再次精确151校验→完整性／外键→结构及typed行清单。事务前验证不能替代事务内验证；外部在间隙改Schema会拒绝，在读取期间提交行修改则原读快照保持一致。
- 现有Database共享authorizer允许明确的只读结构PRAGMA参数；query_only／foreign_keys／writable_schema／journal_mode／user_version赋值、内层COMMIT／ROLLBACK／SAVEPOINT及读事务写入仍拒绝。
- 修正原Database对内部对象前缀的筛选：LIKE的下划线通配会漏掉sqliteX_hidden这类普通额外表；改为大小写归一后的GLOB精确sqlite_前缀。空库判定与精确结构验证同步修复，冻结151 SQL未改。

输入：现有明确Database／已建立事务及未来固定发布的预期结构；输出：只读结构事实、原列摘要或拒绝。不会创建新业务、执行DDL升级、操作用户库、启动模型或代替维护授权。所有新增／修改源码及格式结果均经同目录临时文件flush／fsync、并发复核及os.replace，成功失败清理。

## 环境与检查

项目.venv Python 3.13，Ruff 0.17.3；实际sqlite3.sqlite_version=3.45.3，低于设计最低3.51.3，未升级环境。以下均为基础算法和隔离151检查，不能用作200升级运行库准入。

| 实际命令／范围 | 实际结果 |
| --- | --- |
| 项目.venv，quality_python.py，test_v15_foundation.py＋test_v20_data_retention.py，-k 'not http_new_contracts'，-q -p no:cacheprovider --basetemp 自有目录 | 最终24 passed、1 deselected、9 subtests passed；其中新基础专项16项、既有非HTTP基础8项；8.74秒 |
| 单独test_http_new_contracts_replay_errors_and_removed_initialization，quality_python相同离线保护，在获准的外层环境复查，45秒超时及子进程树清理 | 1 passed，6.29秒。单项复查，不宣称重新跑过包含HTTP的一次完整25项 |
| python -m ruff format --no-cache --check backend/app | 130文件通过 |
| git diff --check | 通过 |

专项覆盖SQLite真实151全部17表、主键排序、同数量改值、存储类型／原JSON／Unicode／NUL／非UTF8文本字节区分、sqlite_sequence、仅投影旧列、151元数据保留、完整性与外键分别判定、真实Backup API含仍在WAL的已提交值、冻结checksum拒绝、Schema额外对象及谓词变化、事务内再验和双连接快照一致性。泛型新增列／200元数据测试只验证原列投影算法，未生成或验收V2 Schema。

最终保留1条既有Starlette/httpx弃用提示；未因此安装或更新依赖。前端本批未改，不重复其类型／构建／浏览器；前批结果按原日期。

## 遇到的问题及最终处理

1. 首轮系统临时路径权限导致锁文件创建／目录清理失败。改为自动清理的工作区专属临时目录，并兼容WALLE_CHECK_TEMP离线保护；后来以获准环境核实首次精确临时路径已不存在，不删除任意父目录。
2. 新夹具误写sequences列名、破坏checksum后未提交，均修正为真实entity_kind／last_value与夹具autocommit；未改生产Schema。
3. 实际调用暴露旧authorizer拒绝带参数的只读结构PRAGMA；按明确白名单修复并测试写入／事务保护。没有关闭检查或query_only。
4. 词法与额外对象检查发现LIKE通配问题，真实额外表夹具证实修复。补同快照精确151重验，避免事务前校验后结构变更漏检。
5. 首次扩大回归完成前五项后在HTTP用例停滞，未取得该用例结果；核实本轮进程归属后仅停止其子树，外层清理。随后24项非HTTP组合通过，原HTTP在获准环境中保持网络／凭据／数据隔离单独通过。停滞的根因未继续专项诊断，不据此重启用户服务或称产品故障已复现。

## 保护与剩余

冻结151 SQL SHA256=9e99874afdf857cafb649ab378431dfd6c12ebda87ea486cb5df463300e74811，未修改。两份设计摘要与前批一致。无真实模型／计数、凭据／正常业务库读取、用户服务启停、SQL200／真实升级、Git提交推送。

本轮自有v20-*工作区临时目录、备份库、WAL／SHM、pytest产物和进程已清理；未保留JSON报告、截图或日志。正常备份属于私有恢复资产的规则不变，本轮只清理自建隔离测试数据。

尚缺：固定SQLite运行包／摘要及能力准入、全第3章字段／关联逐项映射、200 fresh／upgrade SQL与真实发布清单、维护包／路径身份／ACL／空间及count-audit备份、plan／rehearse／apply／recover／check、原命令关闭及LLMUse三归属、实际候选／执行／页面。当前schema比较是可验证基础原语，未接200发布校验器，不构成可运行升级。

接续见[实现进度](../../project/v2.0/实现进度_V_2.0.md)及[映射](../../traceability/v2.0/需求实现映射_V_2.0.md)。
