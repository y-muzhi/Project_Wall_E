# WALL-E 数据库保留升级与恢复迭代 V2.0

日期：2026-11-03（Asia/Hong_Kong）。编号：Q20-DB／DB20-UPGRADE-1。状态：设计已定／待实现及隔离升级验证；保留pending，未合入正式设计。

## 1. 任务、来源与现场

继续逐项处理V2.0设计中的技术空白。本项只编制Markdown并静态阅读源码和官方资料，不打开、备份或升级正常业务数据库，不创建迁移／Schema资源，不启停服务、调用模型／计数、运行产品测试或提交推送。用户先前关于可放弃V1.0测试数据的阶段说明不构成V2.0清库许可。

共同规则仍归[后端草稿](../../../design/v2.0/WALL-E.后端设计文档_V_2.0.md)第3章及INF-CODE-DB；[前端草稿](../../../design/v2.0/WALL-E.前端设计文档_V_2.0.md)只展开可见行为。本迭代是来源和变更记录，不建立第三份现行共同规格。前七项设计及两项用户确认保持。

静态现场：

- database.py的SCHEMA_VERSION=151，唯一MIGRATIONS为schemas/v1_5.sql；不是把migrations/001—004或evidence_150作为现行生产升级链。v1_5.sql SHA256为9e99874afdf857cafb649ab378431dfd6c12ebda87ea486cb5df463300e74811；旧文件、旧checksum和既有applied_at不改。
- _check_schema逐项比较sqlite_master对象类型／SQL及完整对象集合，还要求WAL；不能向旧迁移简单追加ALTER后继续拿旧CREATE判最终结构。initialize只创建空库或核对现有库，service.create_app不负责初始化或修复。
- ProcessLock是原路径对应的应用进程锁，不阻止任意SQLite工具。backup_to已有SQLite Backup API入口，但其完成不等同备份完整性／行保留／可恢复验证。
- llm_uses.guide_run_id当前NOT NULL，CHECK(call_no=1 AND attempt_no=1)；AuditRepository多个方法以id读后直接找GuideRun，purge_raw按时间全表更新。必须改实际调用边界，不能只放宽DDL。
- CountingJournal根为原数据库文件名加.count-audit；CollaborationAdmission保存source_database并读取原证据。数据库路径、原调用ID、审计目录及外部准入证据引用不得因升级换写。
- 本轮未查看任何实际数据库内容／配置秘密，也未探测服务或在途任务。当前Python链接的SQLite版本和实际运行包未验证。

## 2. 目标结构和兼容矩阵

目标存储版本定为200，仅表示V2.0 SQLite结构版本，不改业务协议schema_version。新增SchemaReleaseManifest固定release_id、schema_version=200、schema_contract_sha256、expected_objects_ref、fresh_sql_ref、upgrade_sql_ref及资源摘要。实际清单和SQL均尚未发布，不造占位文件／摘要。

最终Schema与迁移历史分别校验：最终对象以该发布的完整对象清单为唯一依据，按类型、名称、规范化SQL及相关PRAGMA结构事实精确比对，额外／缺失对象一律拒绝。规范化按SQLite词法处理，仅统一语句末尾分号和无语义空白，不重写字符串、标识符、约束、索引谓词；构建时以同一SQLite运行包验证fresh和upgrade得到相同对象清单。不能从全部历史CREATE拼接推断最终对象，也不能通过修改历史SQL迎合校验。

新增code_schema_state单例（singleton_id=1）：schema_version、schema_contract_sha256、origin（FRESH_V20／UPGRADED_V151）、upgrade_id可null、source_data_sha256可null、committed_at。FRESH两项source／upgrade均null；UPGRADED两项必有并不可变。这是存储元数据，不是新业务聚合或第二个任务状态源。

| 输入 | 允许动作与结果 |
| --- | --- |
| 显式绝对路径、文件不存在，或无任何非sqlite_用户对象／迁移元数据及逻辑数据的真正空库 | 单独init-v20创建200最终Schema；schema_migrations只登记200及fresh_sql原字节摘要，state为FRESH_V20；不伪造执行过151 |
| 精确151、冻结checksum和完整对象集合均匹配，完整性与外键通过 | 仅显式upgrade命令；保留151行原字节值，成功追加200及upgrade_sql原字节摘要，state为UPGRADED_V151 |
| 精确200，state／最终对象／允许历史一致 | check-v20；同upgrade_id重复apply只返回原结果，不再执行DDL |
| V1.0、证据库150、未知／较新版本、缺元数据、非空但未登记、改过checksum或额外对象 | 拒绝，保留数据；不降级、推测修复、初始化覆盖或自动删表 |
| 151但行数据／外键不合格；200但发布或历史不一致 | 拒绝并给出非秘密差异，不以手工改版本号通行 |

200允许的历史只有上述两种，不能只看MAX(version)=200。schema_contract_sha256指最终清单的真实发布摘要；checksum仍指实际执行的fresh或upgrade SQL原字节，不混为一种哈希。空库初始化与升级都使用原短事务机制，任何非空库不得走fresh分支。

## 3. 数据保留与LLMUse双归属

保留全部原业务表、主键、序列、文档正文／版本／确认、Revision、评论／建议／消息、GuideRun、幂等／手工编辑证据、业务状态、调用请求／响应／用量／成本及未知状态。JSON按原TEXT字节复制，不重新排序／序列化／脱敏／补字段；Money、null和真实0不互换。不“修好”历史错误，不取消／完成旧任务，不清空或重置sequences。新代码资源／任务／价格／授权表初始为空，不自动发布配置、生成假价格、预留、LLMUse或GuideRun。

llm_uses用新表复制再替换旧表定义，固定列名逐列INSERT SELECT，不用SELECT *、INSERT OR IGNORE或REPLACE。原全部列同值，新代码专属列为null；document分支不强制补代码协议／用途／捕获状态。新调用分支遵守：

- (guide_run_id IS NOT NULL AND execution_session_id IS NULL)或相反，恰一非null；两列都是真实外键。原归属及id、function_type不可变，新代码归属、operation_id、gateway_request_id、call_no／attempt_no和重试关联亦不可改。
- 文档分支保留call_no=1 AND attempt_no=1及原校验／输出规则，原唯一(guide_run_id,call_no,attempt_no)继续有效；代码列必须null。
- 代码分支function_type=CODE_EXECUTION、attempt_no=1、call_no为正整数；UNIQUE(execution_session_id,call_no)，gateway_request_id全局唯一。operation、session、task等用复合外键和一致快照核对，不能串任务；call_no分配和发送预留在同一写事务。
- 代码parse_status／validation_status均NOT_APPLICABLE，parsed_output_json／trusted_output_json均null；protocol／purpose／transport／capture及来源、原操作必须完整。代码调用仍记录真实LLMUse；请求／响应帧和预留按现有模型设计，不另造账。
- retry_of_llm_use_id可null；有值须真实引用同会话较小call_no的调用，不接受自环、未来序号或其他任务。不能把供应方request_id重复误当同一实际HTTP请求。
- 历史文档列表／详情、恢复、准入、解析／可信输出及错误更新显式核对document归属；代码更新走同一审计基础的代码分支。只凭id读取不得直接调用GuideRepository或套文档Schema。错误归属为拒绝，不产生空GuideRun。
- 原文档purge_raw限制document分支；不得把旧30天清理自动套给代码SSE证据／私有内容／费用未核清调用。V2代码没有本轮新增自动清理策略。

外部冻结证据读取继续复用evidence_database入口，但按实际完整历史选择150／151冻结精确校验器或200最终校验器；不能把原default Database从151改200后让旧证据失效，也不能只看version数字跳过checksum／对象校验。该入口仅为已登记准入证据，以mode=ro／query_only读取真实document调用；不作为旧业务库的HTTP服务、升级或写入适配。原150／151 Schema文件、外部source_database和调用id保持，原路径不可读／WAL只读条件不足则准入不可用，不迁移、不删sidecar、不用不真实的immutable声明或新付费观测补证据。

所有新表按后端第3章字段和7.1关联映射生成；code_verification_case_results、交付窗口、模型响应帧等均含真实外键。跨任务关系、活动任务唯一、授权首次绑定、候选／验收关联、序号与预算不变量需真实SQLite并发／故障验证，应用检查不能代替可表达的数据库约束。既有已损坏／不满足目标保留规则的行不得静默跳过。

## 4. 显式离线升级流程

复用Database、ProcessLock、现有配置和审计设施；维护工具不另建HTTP升级服务。计划中的命令语义为plan、rehearse、apply、recover、check，不表示已有可执行脚本。每项均显式接收绝对database路径、私有package目录及原upgrade_id／计划摘要；不默选业务库、不接受任意SQL。初始plan产生一次性upgrade_id和可审阅计划；apply必须重新核对计划，不能把旧计划当永久写许可。

### 4.1 准备、计划和备份

1. 后续实际操作前另获用户授权并安排维护窗口；停止接单、按原机制核对／停止所属活动并关闭后端。维护工具取得同一路径ProcessLock，证明所有本应用写入者／后台审计清理都已退场，操作者关闭外部SQLite写入工具。不能根据文件锁名字、PID文件或超时假定安全；本轮不执行这些动作。
2. 固定原路径与文件身份／NTFS卷、发布和维护程序摘要、schema151及数据清单；拒绝网络文件系统、链接／reparse／多硬链接路径或身份变化。审计根／配置外部证据引用只登记路径、摘要及可读性，不读取秘密到计划；原配置、原绝对路径不改。权限包仅维护操作者／后端可读，AI／浏览器无权取得。
3. 从一致SQLite读快照计算全部旧表保留摘要：按固定列顺序和主键排序，以SQLite存储类型＋长度＋原值编码逐字段散列（TEXT取UTF-8原值、BLOB原字节、INTEGER固定有符号编码、REAL固定IEEE754、NULL独立标签），计入表名／列名／行数。不能只比较count(*)或SQL dump文本；旧schema_migrations及sequences另逐值比对。完整性要求integrity_check唯一ok、foreign_key_check零行。
4. 以SQLite Backup API写全新目标，拒绝已存在备份；所有连接关闭后核验备份结构、相同旧表摘要、完整性／外键，保证可重新打开。正常WAL可能仍含提交数据，不能只复制主文件、删-wal／-shm或把checkpoint当备份。原数据库保持WAL，不为升级切成DELETE。Backup API行为依据[官方备份说明](https://sqlite.org/backup.html)，WAL边界依据[官方WAL说明](https://sqlite.org/wal.html)。
5. 同一静止窗口保存现存count-audit全部正常业务证据的独立字节备份与清单（包括准入记录）；其他外部证据原地不改并记录可核验引用，不递归复制任意外部目录。缺失／重定向／变化／无法证明一致则备份不合格。不存在审计根和空根分别登记，不能创建伪证据补齐。
6. 升级包至少保存原备份、审计字节备份、最终发布引用、typed行清单、计划和追加维护回执、演练库；原业务内容不写docs或终端原始输出。先计算数据库／审计／演练／WAL增长及安全余量所需空间，磁盘不足直接失败，不删原数据腾空间。备份／含正常数据的演练库是私有恢复资产，禁止当测试垃圾自动清理。

计划和维护回执是正常业务维护证据，采用有界、去秘密、原子保存／写回和原身份追加；其JSON若实现，不属于本轮允许留存的测试报告。原子文件保存不能使数据库与包元数据成为一个事务。

### 4.2 副本演练及原库单事务

1. 从已验证备份生成独立演练库。使用批准的固定SQLite运行包，维护专用连接在事务外设置foreign_keys=OFF并读回，再BEGIN IMMEDIATE；该放宽仅限本次离线连接，普通应用始终ON。需要改定义时按“建新表→逐列复制→删旧表→新表改正式名→重建精确索引／触发器”的顺序，不能先改旧表名；不写sqlite_schema、不用writable_schema或executescript隐式提交。依据[SQLite表变更程序](https://sqlite.org/lang_altertable.html)。
2. 在同一事务内创建全部新表及约束、复制LLMUse、恢复索引／触发器、保留151记录、追加200和写code_schema_state；依赖有序，迁移中不触发业务副作用。事务内验证最终对象、全部旧列投影摘要／计数／序列、新增业务表为空（code_schema_state等存储元数据除外）及integrity_check／foreign_key_check。检查后二者结果严格判定，不能以完整性检查替代外键检查；事务外再启foreign_keys并读回，依据[PRAGMA说明](https://sqlite.org/pragma.html)。
3. 演练提交后关闭并重开，按200校验器重新核对最终Schema、历史／state及全部保留证据，并验证原文档查询／双归属约束的隔离专项。实际代码、SQL和专项尚未实现／运行，演练标记只有真实证据后才可写PASSED；本轮没有演练库。
4. 正式apply仍在原数据库路径操作，绝不以演练文件替换原库。重新持有ProcessLock及维护窗口，写前在BEGIN IMMEDIATE同一快照重验151精确结构、全部行摘要与已批准计划／备份一致；有任何变化返回SOURCE_CHANGED，旧计划不可继续。更新计划／备份需要显式新计划，不能临时补拷后假称原计划。
5. 按同一固定SQL在原库执行同一事务及事务内检查，再单次commit。DB内200版本和本upgrade_id／source_data_sha256一起提交；正常应用在完成核对前不能接单。原WAL／同步保护不关，DDL不拆为多批提交，迁移事务较长是离线维护例外；模型、命令、文件捕获和业务回调均不在该事务中。
6. 成功后新连接foreign_keys=ON／synchronous=FULL／WAL，核验精确200、原id／typed投影及state；追加维护回执。后核对失败或commit异常都保持待核对，不能自动运行迁移、恢复旧备份或启动服务。正常应用启动只检查200；151明确要求离线升级，缺失库要求单独初始化，绝不自动修改结构。旧151程序应因迁移历史和对象集不同拒绝200。
7. 默认SQLite运行包须修复官方WAL-reset问题：首期最低3.51.3并固定实际运行库／构建及摘要，不拿Python包版本或系统sqlite3命令版本代替；外键、STRICT、JSON和WAL能力实测。官方记载[WAL-reset修复版本](https://sqlite.org/wal.html)。当前运行包未准入，不因最低版本已写就宣称可运行；不在本轮升级Python／SQLite。

## 5. 中断、重入和恢复

recover只核对原upgrade_id、同原路径／发布／包和真实DB持久事实，不自动重试apply或回放模型。SQLite提交与外部维护回执不组成分布式事务；退出码、超时、磁盘上的旧计划／备份存在都不能单独证明成功或未提交。

| 原库可验证事实 | 原操作结果与后续 |
| --- | --- |
| 精确151，typed数据仍等于原计划；没有200 state | 未升级；确认无活动事务／旧维护进程后结束本次失败。可在新明确维护动作中重演练／重验原计划，再执行原upgrade_id；不自动重试 |
| 精确200，state为本upgrade_id／原source摘要，旧列投影全部相等 | 原升级已提交，补同一回执；缺失成功输出不重做DDL |
| 精确200，但别的upgrade_id／来源或正常新数据已加入 | 不宣称本次无差别成功；核对原提交标记与新写入来源，历史升级事实与当前库健康分开。禁止用旧投影摘要覆盖后来的数据 |
| 部分结构、未知版本／对象、源变化、损坏、连接／身份／提交无法判定 | UNKNOWN／阻断接单，保留原库、WAL、审计和包；只出非秘密诊断，不删锁／改版本／重建或重试 |
| DB已提交而外部回执写入失败 | 以原DB marker及一致证据补原回执，不要求回滚已提交事务 |
| 升级前演练失败或磁盘满／取消且原库仍精确151 | 保留原库及恢复资产，记录失败；不把部分演练库当正式库 |

恢复后可核对成功但200随后有业务变化时，不要求当前全库等于升级瞬间摘要才能承认旧marker；使用原已封存演练／计划和marker证明原事实，另执行当前200完整性及外键校验。证据不够就UNKNOWN，不回写猜测。

rollback不是自动恢复策略。只有另获明确授权、再次停止全部写入、确认成功提交后从未接受任何新业务写入且证据完整，才可另拟显式灾难恢复操作；首期不提供版本降级命令，不将恢复旧备份作为升级重试；不能仅因新代码尚无任务或mtime未变就认为无写入。200正常写入后禁止降级或直接覆盖为151丢新数据，只保留现状诊断并另定恢复方案。备份和审计无自动过期、覆盖或GC。

## 6. 前后端与实施边界

不新增浏览器升级／备份／恢复按钮，不增加任意路径／SQL HTTP接口。后端未通过Schema检查时按现有启动失败与服务不可达展示，不编造已经运行的维护进度，也不回退演示／本地空任务。用户草稿与PendingAction保留；服务恢复后只读原幂等回执，不自动重发写动作或触发模型。代码能力缺资源仍ready=false，文档既有能力只有完整200／原配置／准入均通过后才可使用；存储通过不代表Windows、模型、检查或Git准入通过。

共享调用详情按真实归属解码；旧文档不显示虚构CODE用途／预算／NOT_APPLICABLE，代码NOT_APPLICABLE明确为“不适用”，不渲染为失败或文档解析通过。后端查询按归属授权，前端不能凭可null GuideRun绕过所属任务检查。

实施次序为最终发布清单和fresh／upgrade SQL → 200精确校验器／独立维护入口 → 逐列复制与备份／演练／恢复 → LLMUse读写及原文档回归 → 新表并发／关联 → 前端读取／断线恢复。实际实现计划、映射和运行检查等用户启动实施后建立；本轮不把设计接续表写成实现进度。

## 7. 验证目标、差异与接续

TC20-85—92覆盖：输入矩阵／最终Schema、旧行及审计保留、备份与演练、双归属／清理、SQLite并发约束、提交不明、断电／进程故障、写后恢复限制。TC-FE20-53—55覆盖：服务不可达及草稿、调用归属／不适用、恢复后原动作只查回执。均为目标，本轮执行0。

本项替代后端原“升级命令和恢复方案未完成”的设计空白；不替代任何旧运行证据或新增实际操作授权。设计已定不表示SQL、校验器、维护工具、备份、SQLite运行包、演练或恢复已完成；两份草稿继续DRAFT。前七项也仍待实现／资源发布和运行验证。完成本项后，八项技术设计有明确选择，后续进入两份草稿整体一致性复核及实施前准入准备，不再把这些验证缺口写成用户尚未决定。

本单元静态结果见[核对记录](../../../verification/v2.0/database-upgrade-design-2026-11-03.md)，唯一断点见[设计进度](../../../project/v2.0/设计进度_V_2.0.md)。未全文审计SQLite／OS实现或实际DLL，未执行任何数据库连接、迁移、产品测试、服务命令或真实调用。
