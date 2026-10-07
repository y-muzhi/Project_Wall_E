# 真实HTTP产品闭环验证

2026-10-07（Asia/Hong_Kong）。最新整轮命令：`product-flow-command-2026-10-07T01-56-27-420Z.json`。55个独立库分支全部通过，覆盖TC-E2E-01—10十条核心串联的本文范围；其中八个幂等分支各含不同Python子进程原键重放。以下第一张21分支表保留较早历史范围，最新完整表见末尾。每个重新初始化SQLite，经正式create_app/lifespan、GuideWorker及公开HTTP创建需求；无前一场景数据依赖。8.1样例ID以实际创建回执绑定，不把样例ID硬编码到业务库。

| 场景 | 断言数（含真实轮询） | 原始证据 |
| --- | --- | --- |
| TC-E2E-01 | 73 | [product-flow-2026-10-06T17-57-44-736872+00-00-TC-E2E-01.json](product-flow-2026-10-06T17-57-44-736872+00-00-TC-E2E-01.json) |
| TC-E2E-02 | 140 | [product-flow-2026-10-06T17-57-48-620584+00-00-TC-E2E-02.json](product-flow-2026-10-06T17-57-48-620584+00-00-TC-E2E-02.json) |
| TC-E2E-04 | 116 | [product-flow-2026-10-06T17-57-51-909054+00-00-TC-E2E-04.json](product-flow-2026-10-06T17-57-51-909054+00-00-TC-E2E-04.json) |
| TC-E2E-03-APPLY | 136 | [product-flow-2026-10-06T17-57-58-054639+00-00-TC-E2E-03-APPLY.json](product-flow-2026-10-06T17-57-58-054639+00-00-TC-E2E-03-APPLY.json) |
| TC-E2E-03-NOCHANGE | 112 | [product-flow-2026-10-06T17-58-02-359104+00-00-TC-E2E-03-NOCHANGE.json](product-flow-2026-10-06T17-58-02-359104+00-00-TC-E2E-03-NOCHANGE.json) |
| TC-E2E-03-PENDING | 112 | [product-flow-2026-10-06T17-58-06-116825+00-00-TC-E2E-03-PENDING.json](product-flow-2026-10-06T17-58-06-116825+00-00-TC-E2E-03-PENDING.json) |
| TC-E2E-03-VERSIONS | 120 | [product-flow-2026-10-06T17-58-09-924556+00-00-TC-E2E-03-VERSIONS.json](product-flow-2026-10-06T17-58-09-924556+00-00-TC-E2E-03-VERSIONS.json) |
| TC-E2E-03-STALE | 115 | [product-flow-2026-10-06T17-58-13-613379+00-00-TC-E2E-03-STALE.json](product-flow-2026-10-06T17-58-13-613379+00-00-TC-E2E-03-STALE.json) |
| TC-E2E-03-TARGET | 116 | [product-flow-2026-10-06T17-58-17-332529+00-00-TC-E2E-03-TARGET.json](product-flow-2026-10-06T17-58-17-332529+00-00-TC-E2E-03-TARGET.json) |
| TC-E2E-03-COMBINATION | 119 | [product-flow-2026-10-06T17-58-21-038073+00-00-TC-E2E-03-COMBINATION.json](product-flow-2026-10-06T17-58-21-038073+00-00-TC-E2E-03-COMBINATION.json) |
| TC-E2E-03-TABLE_ROW | 140 | [product-flow-2026-10-06T17-58-24-848269+00-00-TC-E2E-03-TABLE_ROW.json](product-flow-2026-10-06T17-58-24-848269+00-00-TC-E2E-03-TABLE_ROW.json) |
| TC-E2E-03-TABLE_APPEND | 140 | [product-flow-2026-10-06T17-58-28-545067+00-00-TC-E2E-03-TABLE_APPEND.json](product-flow-2026-10-06T17-58-28-545067+00-00-TC-E2E-03-TABLE_APPEND.json) |
| TC-E2E-05-OPEN-ATTACHED | 191 | [product-flow-2026-10-06T17-58-32-383607+00-00-TC-E2E-05-OPEN-ATTACHED.json](product-flow-2026-10-06T17-58-32-383607+00-00-TC-E2E-05-OPEN-ATTACHED.json) |
| TC-E2E-05-OPEN-ORPHANED | 180 | [product-flow-2026-10-06T17-58-36-629925+00-00-TC-E2E-05-OPEN-ORPHANED.json](product-flow-2026-10-06T17-58-36-629925+00-00-TC-E2E-05-OPEN-ORPHANED.json) |
| TC-E2E-05-RESOLVED-ATTACHED | 193 | [product-flow-2026-10-06T17-58-40-151047+00-00-TC-E2E-05-RESOLVED-ATTACHED.json](product-flow-2026-10-06T17-58-40-151047+00-00-TC-E2E-05-RESOLVED-ATTACHED.json) |
| TC-E2E-05-RESOLVED-ORPHANED | 182 | [product-flow-2026-10-06T17-58-44-429069+00-00-TC-E2E-05-RESOLVED-ORPHANED.json](product-flow-2026-10-06T17-58-44-429069+00-00-TC-E2E-05-RESOLVED-ORPHANED.json) |
| TC-E2E-10-LIST | 822 | [product-flow-2026-10-06T17-58-47-934255+00-00-TC-E2E-10-LIST.json](product-flow-2026-10-06T17-58-47-934255+00-00-TC-E2E-10-LIST.json) |
| TC-E2E-10-READS | 592 | [product-flow-2026-10-06T17-59-30-137026+00-00-TC-E2E-10-READS.json](product-flow-2026-10-06T17-59-30-137026+00-00-TC-E2E-10-READS.json) |
| TC-E2E-06-CANCEL_FIRST | 87 | [product-flow-2026-10-06T17-59-53-002406+00-00-TC-E2E-06-CANCEL_FIRST.json](product-flow-2026-10-06T17-59-53-002406+00-00-TC-E2E-06-CANCEL_FIRST.json) |
| TC-E2E-06-PERSIST_FIRST | 85 | [product-flow-2026-10-06T17-59-56-572509+00-00-TC-E2E-06-PERSIST_FIRST.json](product-flow-2026-10-06T17-59-56-572509+00-00-TC-E2E-06-PERSIST_FIRST.json) |
| TC-E2E-06-LATE_TCP | 88 | [product-flow-2026-10-06T18-00-00-208347+00-00-TC-E2E-06-LATE_TCP.json](product-flow-2026-10-06T18-00-00-208347+00-00-TC-E2E-06-LATE_TCP.json) |

程序使用明确私有兼容回调、合成计数及受控本机Tokenization/Chat TCP；实际C03、ORCH、审计、完整v2签名校验、C07与所有HTTP/事务保持原实现；取消竞争仅在真实函数入口加暂停并继续调用原实现。这证明可控模型下的程序链路，不证明火山准确计数、角色封装、真实效果或生产启用。付费请求0，不读取.env.local，不接触正常业务库。

TC-E2E-01：201受理屏障、明确用户声明事实、初始化COMPLETED/IDLE、BASELINE唯一/版本1且不更改CURRENT完整模型、创建及基线原键重放。TC-E2E-02：完整模板F-A CURRENT3、F-C区块/选区，独立取消、草稿1→2→CURRENT4；六个原生SQL ABORT阶段全库前后逐字相等；完成仅更新anchor_status而保评论业务状态/时间，保留最小编辑来源。

TC-E2E-04：原文F-K c1/c2，两路径各在真实能力入口以native Barrier竞争，真实HTTP成功响应在客户端读取后丢弃；原键恢复原202且request_id新建。必答缺失、重复键、非法选项、必答跳过整组拒绝。初始化另建Run，ASK继续原Run/call_no=2；实际3Run、2正式响应、4模型尝试及4次各本机计数/Chat。

TC-E2E-03：每分支先实际合法C07生成≥2项。逐项决定不更新正文；接受/编辑/删除只一次采用；拒绝NO_CHANGE完全不改CURRENT；表格行替换与整表追加保未选行/表头及来源；未决定拒绝、放弃释放占用。独立预期为字面文本替换，不调用生产Patch实现。版本漂移、原文漂移、目标删除及重复目标组合明确为合法产出后的隔离存储故障，原不可改建议和触发器不移除；每次拒绝全库相等、原决定保留。并不声称真实AI生成了这些故障。

所有进程锁、服务生命周期、模型socket与受控服务器关闭均断言。wrapper保留source audit、stdout/stderr、退出码及运行前后源码哈希，不接受traceback或输入改变。测试库保留在忽略的output/product-flow，原始验证JSON提交。

历史失败与范围更正（全部原记录保留，不覆盖）：初版括号语法错误；旧探针误用requirement_revisions/transport_status及manual_edit_sessions.id，按正式DDL改为revisions/call_status/draft_id；iterdump使用PRAGMA被正式只读authorizer拒绝，改为独立原生只读连接取完整快照，authorizer不改；最早01/02共享库记录只算历史专项，17-02之后才独立；17-03卡片路径尚无native Barrier，17-05及以后才包含；17-15 APPLY夹具错误删掉模板段落空行，实际Patch补回合法分隔，随后保留原边界字节并继续逐字比对。其他历史通过记录按各自当时源码/覆盖解释，不作最新全矩阵替代。

本批仅新增独立工程验证工具及映射，业务/前端代码未改。799后端完整回归和259前端/生产构建记录保持，不把这些新断言加入原单元测试总数。373正式编号、07/08/09其他核心完整串联、真IME及真实Provider/效果继续逐行验收。


TC-E2E-05新增：四种OPEN/RESOLVED与ATTACHED/ORPHANED分别独立新库。BLOCK与SELECTION原引用由公开接口生成；真实人工删除区块→C06仅更新锚点，解析位置读取不写持久化。显式把同原身份的历史合法完整快照装入隔离库，读取location恢复ATTACHED而持久仍ORPHANED；实际公开草稿完成调用C06才恢复锚点，OPEN/RESOLVED及所有时间/原引用均保持。此历史快照是原文规定的定位夹具，不是新的跨会话撤销产品能力。公开评论解决/重开、有效评论MODIFY_FROM_COMMENT/C07 NO_CHANGE不自动解决、已失效来源拒绝，以及明确旧正文漂移时只提交单一anchor_status校正均验证；全库原生表逐字段比对，无消息/Run/成功领取/模型副作用。

TC-E2E-06新增：CANCEL_FIRST暂停已真实计数/Chat/完整可信输出之后、进入C07事务之前；实际HTTP取消提交/lease退休先赢，已实际SUCCEEDED的123输入/10输出用量保留，迟到签名回执独立重放被STATE_CONFLICT拒绝。PERSIST_FIRST在实际C07事务UPDATE后读取到PERSISTING再暂停，真实HTTP取消已进入C03且阻塞等待该写事务；放行真实校验/提交后仅一个助手与批次成立，取消409，CURRENT原样。这里的PERSISTING是在实际连接内观察，不声称公开GET读取了未提交状态。LATE_TCP在真实供应方本机HTTP已接收请求后暂停回复，取消提交/socket关闭后才尝试发送候选字节；迟到不可采用，未知usage保留为null。Windows测试服务器的ConnectionAbortedError/ConnectionResetError/BrokenPipeError仅在已确认提交取消后作为明确对端关闭证据记录，其余服务器错误仍拒绝；没有调查Node/Vite运行时。新键重复取消可新增自身唯一成功幂等回执，但整库除此新增行逐字相同，原ended_at不变。

TC-E2E-10新增：F-L全部41需求经实际公开创建，每项本机初始运行/生命周期；NEW/CHANGE、三状态、四工作状态均真实合法子对象，含COMPLETED下ASK等待。仅把前两条updated_at设置同时间作平局夹具，原号REQ000001/2与标题A%_甲/a甲。大小写/%/_字面匹配/编号/组合过滤/空结果/1—4页以独立字面参考列表核对；两轮共读全体需求。READS真实23版本、23条运行、公开评论多页、软删墓碑、真实批次和另一需求的草稿；每类Query真实HTTP往返/分页/详情/运行组合过滤。另建明确旧历史完整模板/序号1—45消息，包含合法卡片及损坏卡片/回答；窗口26—45→6—25→1—5→空，游标/has_more准确，损坏只保可读原文并禁用卡片、不暴露损坏结构。孤立评论以新身份旧记录插入，原不可改字段保护不删除；终态占用夹具显式将指针指向实际完成C07 Run，重复查询不运行恢复。所有Query前后全库iterdump及本机计数/Chat请求数完全相同。

后续失败与修正全部保留：查询夹具尝试修改comment.block_id触发IMMUTABLE_FIELD，改为新身份历史记录插入，保护规则未改；评论分页参考误写降序，重读原文L3685确认created_at ASC/id ASC后修正独立参考；重复取消的首次探针错误要求新键成功也不写回执，改为仅允许该一条正式成功回执而其余全库相等；迟到TCP首先将Windows正常关闭误算意外错误，原记录包含具体ConnectionAbortedError，修正为限定在已提交取消后的明确关闭分类且保留原始事实，未放宽意外错误或业务断言。

完整命令记录（含失败及不同历史范围；通过不自动代表最新21分支覆盖）：

| 原始命令证据 | 是否通过 |
| --- | --- |
| [product-flow-command-2026-10-06T16-50-20-354Z.json](product-flow-command-2026-10-06T16-50-20-354Z.json) | 失败（保留） |
| [product-flow-command-2026-10-06T16-50-28-594Z.json](product-flow-command-2026-10-06T16-50-28-594Z.json) | 失败（保留） |
| [product-flow-command-2026-10-06T16-51-09-187Z.json](product-flow-command-2026-10-06T16-51-09-187Z.json) | 通过 |
| [product-flow-command-2026-10-06T16-54-34-550Z.json](product-flow-command-2026-10-06T16-54-34-550Z.json) | 失败（保留） |
| [product-flow-command-2026-10-06T16-55-16-315Z.json](product-flow-command-2026-10-06T16-55-16-315Z.json) | 失败（保留） |
| [product-flow-command-2026-10-06T16-55-53-145Z.json](product-flow-command-2026-10-06T16-55-53-145Z.json) | 通过 |
| [product-flow-command-2026-10-06T16-57-55-234Z.json](product-flow-command-2026-10-06T16-57-55-234Z.json) | 通过 |
| [product-flow-command-2026-10-06T17-02-01-751Z.json](product-flow-command-2026-10-06T17-02-01-751Z.json) | 通过 |
| [product-flow-command-2026-10-06T17-03-56-651Z.json](product-flow-command-2026-10-06T17-03-56-651Z.json) | 通过 |
| [product-flow-command-2026-10-06T17-05-58-984Z.json](product-flow-command-2026-10-06T17-05-58-984Z.json) | 通过 |
| [product-flow-command-2026-10-06T17-15-19-334Z.json](product-flow-command-2026-10-06T17-15-19-334Z.json) | 失败（保留） |
| [product-flow-command-2026-10-06T17-17-08-337Z.json](product-flow-command-2026-10-06T17-17-08-337Z.json) | 通过 |
| [product-flow-command-2026-10-06T17-20-24-085Z.json](product-flow-command-2026-10-06T17-20-24-085Z.json) | 通过 |
| [product-flow-command-2026-10-06T17-25-37-912Z.json](product-flow-command-2026-10-06T17-25-37-912Z.json) | 通过 |
| [product-flow-command-2026-10-06T17-32-53-211Z.json](product-flow-command-2026-10-06T17-32-53-211Z.json) | 通过 |
| [product-flow-command-2026-10-06T17-37-49-343Z.json](product-flow-command-2026-10-06T17-37-49-343Z.json) | 通过 |
| [product-flow-command-2026-10-06T17-39-28-007Z.json](product-flow-command-2026-10-06T17-39-28-007Z.json) | 通过 |
| [product-flow-command-2026-10-06T17-43-18-800Z.json](product-flow-command-2026-10-06T17-43-18-800Z.json) | 失败（保留） |
| [product-flow-command-2026-10-06T17-45-03-702Z.json](product-flow-command-2026-10-06T17-45-03-702Z.json) | 失败（保留） |
| [product-flow-command-2026-10-06T17-46-37-279Z.json](product-flow-command-2026-10-06T17-46-37-279Z.json) | 通过 |
| [product-flow-command-2026-10-06T17-48-58-822Z.json](product-flow-command-2026-10-06T17-48-58-822Z.json) | 失败（保留） |
| [product-flow-command-2026-10-06T17-50-36-178Z.json](product-flow-command-2026-10-06T17-50-36-178Z.json) | 失败（保留） |
| [product-flow-command-2026-10-06T17-51-30-939Z.json](product-flow-command-2026-10-06T17-51-30-939Z.json) | 失败（保留） |
| [product-flow-command-2026-10-06T17-52-01-569Z.json](product-flow-command-2026-10-06T17-52-01-569Z.json) | 通过 |
| [product-flow-command-2026-10-06T17-52-47-984Z.json](product-flow-command-2026-10-06T17-52-47-984Z.json) | 通过 |
| [product-flow-command-2026-10-06T17-55-43-219Z.json](product-flow-command-2026-10-06T17-55-43-219Z.json) | 通过 |
| [product-flow-command-2026-10-06T17-57-44-124Z.json](product-flow-command-2026-10-06T17-57-44-124Z.json) | 通过 |


2026-10-07接续：TC-E2E-07/08/09补齐（最新矩阵见后续断点，原21分支记录保留）。

TC-E2E-07六分支：真实Chat在途审计updated_at作为T0，STARTUP的有效live_run_ids即使两小时仍不误中断；实际监测14:59全库相等、15:00恰好恢复一个Run/占用/未结束审计并关闭真实socket，重复扫描不刷新终态；串行锁竞争合并，记录实际扫描延迟，30秒周期不是15分钟完成上界。另以公开接口产出真实WAITING_USER卡片、人工草稿及PENDING批次，原生命周期关闭及新create_app/uvicorn启动均保留原对象、时间、正文、审计和回执。独占旧owner下实际C01接受后退出且未调度、遗留PROCESSING领取模拟启动前中断；实际启动屏障证明C09完成前尚未建立HTTP runtime/admission，另一OS锁竞争者被拒绝。先清理旧PROCESSING再INTERRUPTED，不重发模型。原成功回执在新epoch下仍回放原接受快照。

TRUSTED以实际C07完成Run/PENDING批次为基础，明确把终态指针设置为旧GUIDE_ACTIVE；实际启动只更新该root为SUGGESTION_REVIEWING/唯一批次，其余全库逐字不变。MISSING/CROSS/MULTIPLE为明确历史占用损坏，真实扫描及create_app启动均WORK_STATE_INCONSISTENT、整库不改、未admit HTTP且锁释放。MULTIPLE第二候选是从实际C07派生、另分配父Run/用户消息/批次/建议的完整历史夹具，不称第二合法签名输出；同Run唯一批次约束和原不可改保护保留。

TC-E2E-08二十分支：断连、真实本机读超时、429、503、非法JSON、完整Schema未知字段、越权区块输出分别失败后有限重试成功；所有真实出站由实际Gateway/ORCH完成，每尝试一LLMUse/一次新准确文本候选本机计数，System/User逐字对应。耗尽序列为JSON失败→Schema失败→503，call_no=1/attempt=1–3、最终MODEL_ERROR取最后失败，早期123输入/10输出真实返回用量仍保留。首个429后在实际ORCH退避点公开取消，后续不再计数/发送，无助手/正文/批次迟到采用。WAITING_USER前1/1–2，用户真实continue后2/1–2，历史整条审计不改。认证/权限/余额/配额/参数/未开模型/内容安全/上下文/未知供应方码/404十种不可重试各独立新库，一次计数和Chat即结束。

退避是明确私有诊断sleep依赖：记录实际ORCH决定的2/5秒并让出事件循环，不声称测试经过这些墙钟秒数。TIMEOUT仅将本机ForwardTransport实际read缩为50ms，原始观察请求仍冻结180秒及10/10/10其他超时；断开socket、每次零底层重试均实际发生。实际生产周期/退避配置原完整回归已覆盖，这些局部时间加速不启用生产兼容。

TC-E2E-09八分支：创建需求、创建草稿、整组卡片提交、批次完成各独立准备，两种未知模式分别新库。实际幂等领取提交之后、业务事务之前加暂停并继续原claim；公开原键/原输入重复409 REQUEST_IN_PROGRESS，原键改合法输入409 IDEMPOTENCY_CONFLICT，原生SQL BEFORE SUCCEEDED更新ABORT使业务对象/编号/审计/回执全部回滚、仅本领取释放，去触发器后与准备整库逐字相等。随后同原键成功：UNKNOWN_ACK把实际事务正常提交后抛CommitOutcomeUnknown，返回503但SUCCEEDED回执与业务对象已在磁盘；LOST_HTTP接收真实服务器成功状态与正文后在客户端交付前抛ReadError，未伪造服务端成功。先按实体GET复查再原键重放，原data/status不变、request_id新建，卡片仅一个正式响应/一次推进，批次CURRENT版本仅加1/同身份/独立字面预期，所有数量和全库对照证明不重复写。

八分支还关闭原OS owner，启动不同PID的Python子进程与正式create_app/uvicorn/HTTP，剥离WALLE_环境变量并以明确拒绝任何模型发送的诊断Gateway守门；该子进程从磁盘重放原成功，新的owner_epoch与request_id、模型发送尝试0、HTTP同status/data、退出后锁可再取得，前后整个SQLite原生iterdump相等。子进程原始stdout/stderr/结果完整嵌入场景JSON；不把同进程刷新当跨进程证明。另一次父进程新生命周期回放仍无效果。404不存在不是通用完成证明；软删除以GET保留deleted_at证明。DRAFT先证明重放后真实持久草稿与独占，再明确公开cancel释放后做独立评论墓碑测试；不静默清占用。

本批失败探针原记录全部保留：07编号枚举误写SUGGESTION_BATCH（正式值BATCH）；保护比对误把实际新增孤儿接受带来的合法sequences增长当恢复修改（现在分开证明C01分配与恢复不分配）；第二批次最初复用同父Run被真实UNIQUE拒绝（改另分配完整历史父对象，约束不改）；09决定建议漏Idempotency-Key被422拒绝（补合法新键）；在已证明的人工独占中创建评论被409拒绝（先明确公开cancel，不修改占用规则）。本批截至此处没有业务或前端实现改动，不重写原失败历史。


最新完整55分支断点（2026-10-07）：[product-flow-command-2026-10-07T01-56-27-420Z.json](product-flow-command-2026-10-07T01-56-27-420Z.json)，source audit及所有退出码通过，运行前后源码哈希相等，八个不同Python子进程重放成功且发送模型尝试0。

| 场景 | 断言数（含真实轮询） | 原始证据 |
| --- | --- | --- |
| TC-E2E-01 | 73 | [product-flow-2026-10-07T01-56-28-087801+00-00-TC-E2E-01.json](product-flow-2026-10-07T01-56-28-087801+00-00-TC-E2E-01.json) |
| TC-E2E-02 | 141 | [product-flow-2026-10-07T01-56-32-244059+00-00-TC-E2E-02.json](product-flow-2026-10-07T01-56-32-244059+00-00-TC-E2E-02.json) |
| TC-E2E-04 | 116 | [product-flow-2026-10-07T01-56-35-738761+00-00-TC-E2E-04.json](product-flow-2026-10-07T01-56-35-738761+00-00-TC-E2E-04.json) |
| TC-E2E-03-APPLY | 136 | [product-flow-2026-10-07T01-56-42-278864+00-00-TC-E2E-03-APPLY.json](product-flow-2026-10-07T01-56-42-278864+00-00-TC-E2E-03-APPLY.json) |
| TC-E2E-03-NOCHANGE | 112 | [product-flow-2026-10-07T01-56-46-979108+00-00-TC-E2E-03-NOCHANGE.json](product-flow-2026-10-07T01-56-46-979108+00-00-TC-E2E-03-NOCHANGE.json) |
| TC-E2E-03-PENDING | 114 | [product-flow-2026-10-07T01-56-50-785155+00-00-TC-E2E-03-PENDING.json](product-flow-2026-10-07T01-56-50-785155+00-00-TC-E2E-03-PENDING.json) |
| TC-E2E-03-VERSIONS | 118 | [product-flow-2026-10-07T01-56-54-705067+00-00-TC-E2E-03-VERSIONS.json](product-flow-2026-10-07T01-56-54-705067+00-00-TC-E2E-03-VERSIONS.json) |
| TC-E2E-03-STALE | 116 | [product-flow-2026-10-07T01-56-59-242819+00-00-TC-E2E-03-STALE.json](product-flow-2026-10-07T01-56-59-242819+00-00-TC-E2E-03-STALE.json) |
| TC-E2E-03-TARGET | 116 | [product-flow-2026-10-07T01-57-03-531929+00-00-TC-E2E-03-TARGET.json](product-flow-2026-10-07T01-57-03-531929+00-00-TC-E2E-03-TARGET.json) |
| TC-E2E-03-COMBINATION | 118 | [product-flow-2026-10-07T01-57-07-859856+00-00-TC-E2E-03-COMBINATION.json](product-flow-2026-10-07T01-57-07-859856+00-00-TC-E2E-03-COMBINATION.json) |
| TC-E2E-03-TABLE_ROW | 140 | [product-flow-2026-10-07T01-57-11-894765+00-00-TC-E2E-03-TABLE_ROW.json](product-flow-2026-10-07T01-57-11-894765+00-00-TC-E2E-03-TABLE_ROW.json) |
| TC-E2E-03-TABLE_APPEND | 140 | [product-flow-2026-10-07T01-57-15-885623+00-00-TC-E2E-03-TABLE_APPEND.json](product-flow-2026-10-07T01-57-15-885623+00-00-TC-E2E-03-TABLE_APPEND.json) |
| TC-E2E-05-OPEN-ATTACHED | 190 | [product-flow-2026-10-07T01-57-20-292362+00-00-TC-E2E-05-OPEN-ATTACHED.json](product-flow-2026-10-07T01-57-20-292362+00-00-TC-E2E-05-OPEN-ATTACHED.json) |
| TC-E2E-05-OPEN-ORPHANED | 180 | [product-flow-2026-10-07T01-57-24-914687+00-00-TC-E2E-05-OPEN-ORPHANED.json](product-flow-2026-10-07T01-57-24-914687+00-00-TC-E2E-05-OPEN-ORPHANED.json) |
| TC-E2E-05-RESOLVED-ATTACHED | 193 | [product-flow-2026-10-07T01-57-28-304355+00-00-TC-E2E-05-RESOLVED-ATTACHED.json](product-flow-2026-10-07T01-57-28-304355+00-00-TC-E2E-05-RESOLVED-ATTACHED.json) |
| TC-E2E-05-RESOLVED-ORPHANED | 182 | [product-flow-2026-10-07T01-57-32-973659+00-00-TC-E2E-05-RESOLVED-ORPHANED.json](product-flow-2026-10-07T01-57-32-973659+00-00-TC-E2E-05-RESOLVED-ORPHANED.json) |
| TC-E2E-10-LIST | 820 | [product-flow-2026-10-07T01-57-36-312792+00-00-TC-E2E-10-LIST.json](product-flow-2026-10-07T01-57-36-312792+00-00-TC-E2E-10-LIST.json) |
| TC-E2E-10-READS | 589 | [product-flow-2026-10-07T01-58-19-279507+00-00-TC-E2E-10-READS.json](product-flow-2026-10-07T01-58-19-279507+00-00-TC-E2E-10-READS.json) |
| TC-E2E-06-CANCEL_FIRST | 88 | [product-flow-2026-10-07T01-58-42-337483+00-00-TC-E2E-06-CANCEL_FIRST.json](product-flow-2026-10-07T01-58-42-337483+00-00-TC-E2E-06-CANCEL_FIRST.json) |
| TC-E2E-06-PERSIST_FIRST | 85 | [product-flow-2026-10-07T01-58-46-066123+00-00-TC-E2E-06-PERSIST_FIRST.json](product-flow-2026-10-07T01-58-46-066123+00-00-TC-E2E-06-PERSIST_FIRST.json) |
| TC-E2E-06-LATE_TCP | 87 | [product-flow-2026-10-07T01-58-49-903443+00-00-TC-E2E-06-LATE_TCP.json](product-flow-2026-10-07T01-58-49-903443+00-00-TC-E2E-06-LATE_TCP.json) |
| TC-E2E-07-TIMEOUT | 86 | [product-flow-2026-10-07T01-58-53-631654+00-00-TC-E2E-07-TIMEOUT.json](product-flow-2026-10-07T01-58-53-631654+00-00-TC-E2E-07-TIMEOUT.json) |
| TC-E2E-07-RESTART_KEEP | 132 | [product-flow-2026-10-07T01-58-57-365492+00-00-TC-E2E-07-RESTART_KEEP.json](product-flow-2026-10-07T01-58-57-365492+00-00-TC-E2E-07-RESTART_KEEP.json) |
| TC-E2E-07-TRUSTED | 90 | [product-flow-2026-10-07T01-59-04-354455+00-00-TC-E2E-07-TRUSTED.json](product-flow-2026-10-07T01-59-04-354455+00-00-TC-E2E-07-TRUSTED.json) |
| TC-E2E-07-MISSING | 89 | [product-flow-2026-10-07T01-59-08-503108+00-00-TC-E2E-07-MISSING.json](product-flow-2026-10-07T01-59-08-503108+00-00-TC-E2E-07-MISSING.json) |
| TC-E2E-07-CROSS | 99 | [product-flow-2026-10-07T01-59-12-240315+00-00-TC-E2E-07-CROSS.json](product-flow-2026-10-07T01-59-12-240315+00-00-TC-E2E-07-CROSS.json) |
| TC-E2E-07-MULTIPLE | 90 | [product-flow-2026-10-07T01-59-17-059341+00-00-TC-E2E-07-MULTIPLE.json](product-flow-2026-10-07T01-59-17-059341+00-00-TC-E2E-07-MULTIPLE.json) |
| TC-E2E-08-NETWORK | 92 | [product-flow-2026-10-07T01-59-21-018329+00-00-TC-E2E-08-NETWORK.json](product-flow-2026-10-07T01-59-21-018329+00-00-TC-E2E-08-NETWORK.json) |
| TC-E2E-08-TIMEOUT | 97 | [product-flow-2026-10-07T01-59-25-749885+00-00-TC-E2E-08-TIMEOUT.json](product-flow-2026-10-07T01-59-25-749885+00-00-TC-E2E-08-TIMEOUT.json) |
| TC-E2E-08-RATE_LIMIT | 95 | [product-flow-2026-10-07T01-59-30-363586+00-00-TC-E2E-08-RATE_LIMIT.json](product-flow-2026-10-07T01-59-30-363586+00-00-TC-E2E-08-RATE_LIMIT.json) |
| TC-E2E-08-TEMPORARY | 94 | [product-flow-2026-10-07T01-59-35-343285+00-00-TC-E2E-08-TEMPORARY.json](product-flow-2026-10-07T01-59-35-343285+00-00-TC-E2E-08-TEMPORARY.json) |
| TC-E2E-08-JSON | 96 | [product-flow-2026-10-07T01-59-40-010167+00-00-TC-E2E-08-JSON.json](product-flow-2026-10-07T01-59-40-010167+00-00-TC-E2E-08-JSON.json) |
| TC-E2E-08-SCHEMA | 98 | [product-flow-2026-10-07T01-59-44-548199+00-00-TC-E2E-08-SCHEMA.json](product-flow-2026-10-07T01-59-44-548199+00-00-TC-E2E-08-SCHEMA.json) |
| TC-E2E-08-AUTHORITY | 97 | [product-flow-2026-10-07T01-59-49-213294+00-00-TC-E2E-08-AUTHORITY.json](product-flow-2026-10-07T01-59-49-213294+00-00-TC-E2E-08-AUTHORITY.json) |
| TC-E2E-08-EXHAUST | 103 | [product-flow-2026-10-07T01-59-53-896364+00-00-TC-E2E-08-EXHAUST.json](product-flow-2026-10-07T01-59-53-896364+00-00-TC-E2E-08-EXHAUST.json) |
| TC-E2E-08-CANCEL_FIRST | 84 | [product-flow-2026-10-07T01-59-59-139182+00-00-TC-E2E-08-CANCEL_FIRST.json](product-flow-2026-10-07T01-59-59-139182+00-00-TC-E2E-08-CANCEL_FIRST.json) |
| TC-E2E-08-WAITING_CONTINUE | 110 | [product-flow-2026-10-07T02-00-02-686766+00-00-TC-E2E-08-WAITING_CONTINUE.json](product-flow-2026-10-07T02-00-02-686766+00-00-TC-E2E-08-WAITING_CONTINUE.json) |
| TC-E2E-08-NO_RETRY-AUTHENTICATION | 88 | [product-flow-2026-10-07T02-00-08-905830+00-00-TC-E2E-08-NO_RETRY-AUTHENTICATION.json](product-flow-2026-10-07T02-00-08-905830+00-00-TC-E2E-08-NO_RETRY-AUTHENTICATION.json) |
| TC-E2E-08-NO_RETRY-PERMISSION | 88 | [product-flow-2026-10-07T02-00-12-447329+00-00-TC-E2E-08-NO_RETRY-PERMISSION.json](product-flow-2026-10-07T02-00-12-447329+00-00-TC-E2E-08-NO_RETRY-PERMISSION.json) |
| TC-E2E-08-NO_RETRY-BALANCE | 88 | [product-flow-2026-10-07T02-00-16-222919+00-00-TC-E2E-08-NO_RETRY-BALANCE.json](product-flow-2026-10-07T02-00-16-222919+00-00-TC-E2E-08-NO_RETRY-BALANCE.json) |
| TC-E2E-08-NO_RETRY-QUOTA | 88 | [product-flow-2026-10-07T02-00-20-022491+00-00-TC-E2E-08-NO_RETRY-QUOTA.json](product-flow-2026-10-07T02-00-20-022491+00-00-TC-E2E-08-NO_RETRY-QUOTA.json) |
| TC-E2E-08-NO_RETRY-PARAMETER | 88 | [product-flow-2026-10-07T02-00-23-873361+00-00-TC-E2E-08-NO_RETRY-PARAMETER.json](product-flow-2026-10-07T02-00-23-873361+00-00-TC-E2E-08-NO_RETRY-PARAMETER.json) |
| TC-E2E-08-NO_RETRY-MODEL | 87 | [product-flow-2026-10-07T02-00-27-446358+00-00-TC-E2E-08-NO_RETRY-MODEL.json](product-flow-2026-10-07T02-00-27-446358+00-00-TC-E2E-08-NO_RETRY-MODEL.json) |
| TC-E2E-08-NO_RETRY-CONTENT_FILTER | 89 | [product-flow-2026-10-07T02-00-31-334362+00-00-TC-E2E-08-NO_RETRY-CONTENT_FILTER.json](product-flow-2026-10-07T02-00-31-334362+00-00-TC-E2E-08-NO_RETRY-CONTENT_FILTER.json) |
| TC-E2E-08-NO_RETRY-CONTEXT_LIMIT | 89 | [product-flow-2026-10-07T02-00-35-140397+00-00-TC-E2E-08-NO_RETRY-CONTEXT_LIMIT.json](product-flow-2026-10-07T02-00-35-140397+00-00-TC-E2E-08-NO_RETRY-CONTEXT_LIMIT.json) |
| TC-E2E-08-NO_RETRY-UNKNOWN | 88 | [product-flow-2026-10-07T02-00-38-907788+00-00-TC-E2E-08-NO_RETRY-UNKNOWN.json](product-flow-2026-10-07T02-00-38-907788+00-00-TC-E2E-08-NO_RETRY-UNKNOWN.json) |
| TC-E2E-08-NO_RETRY-HTTP404 | 88 | [product-flow-2026-10-07T02-00-42-943191+00-00-TC-E2E-08-NO_RETRY-HTTP404.json](product-flow-2026-10-07T02-00-42-943191+00-00-TC-E2E-08-NO_RETRY-HTTP404.json) |
| TC-E2E-09-CREATE-UNKNOWN_ACK | 115 | [product-flow-2026-10-07T02-00-46-573611+00-00-TC-E2E-09-CREATE-UNKNOWN_ACK.json](product-flow-2026-10-07T02-00-46-573611+00-00-TC-E2E-09-CREATE-UNKNOWN_ACK.json) |
| TC-E2E-09-DRAFT-UNKNOWN_ACK | 114 | [product-flow-2026-10-07T02-00-53-292143+00-00-TC-E2E-09-DRAFT-UNKNOWN_ACK.json](product-flow-2026-10-07T02-00-53-292143+00-00-TC-E2E-09-DRAFT-UNKNOWN_ACK.json) |
| TC-E2E-09-CARDS-UNKNOWN_ACK | 121 | [product-flow-2026-10-07T02-00-58-779444+00-00-TC-E2E-09-CARDS-UNKNOWN_ACK.json](product-flow-2026-10-07T02-00-58-779444+00-00-TC-E2E-09-CARDS-UNKNOWN_ACK.json) |
| TC-E2E-09-BATCH-UNKNOWN_ACK | 120 | [product-flow-2026-10-07T02-01-06-593533+00-00-TC-E2E-09-BATCH-UNKNOWN_ACK.json](product-flow-2026-10-07T02-01-06-593533+00-00-TC-E2E-09-BATCH-UNKNOWN_ACK.json) |
| TC-E2E-09-CREATE-LOST_HTTP | 111 | [product-flow-2026-10-07T02-01-12-818640+00-00-TC-E2E-09-CREATE-LOST_HTTP.json](product-flow-2026-10-07T02-01-12-818640+00-00-TC-E2E-09-CREATE-LOST_HTTP.json) |
| TC-E2E-09-DRAFT-LOST_HTTP | 113 | [product-flow-2026-10-07T02-01-19-388441+00-00-TC-E2E-09-DRAFT-LOST_HTTP.json](product-flow-2026-10-07T02-01-19-388441+00-00-TC-E2E-09-DRAFT-LOST_HTTP.json) |
| TC-E2E-09-CARDS-LOST_HTTP | 119 | [product-flow-2026-10-07T02-01-25-440759+00-00-TC-E2E-09-CARDS-LOST_HTTP.json](product-flow-2026-10-07T02-01-25-440759+00-00-TC-E2E-09-CARDS-LOST_HTTP.json) |
| TC-E2E-09-BATCH-LOST_HTTP | 120 | [product-flow-2026-10-07T02-01-33-042510+00-00-TC-E2E-09-BATCH-LOST_HTTP.json](product-flow-2026-10-07T02-01-33-042510+00-00-TC-E2E-09-BATCH-LOST_HTTP.json) |

本日命令历史（失败亦保留，不以局部通过冒充55整轮）：

| 命令证据 | 结果 |
| --- | --- |
| [product-flow-command-2026-10-07T01-41-33-499Z.json](product-flow-command-2026-10-07T01-41-33-499Z.json) | 失败（保留） |
| [product-flow-command-2026-10-07T01-42-21-952Z.json](product-flow-command-2026-10-07T01-42-21-952Z.json) | 失败（保留） |
| [product-flow-command-2026-10-07T01-43-32-308Z.json](product-flow-command-2026-10-07T01-43-32-308Z.json) | 通过 |
| [product-flow-command-2026-10-07T01-44-43-890Z.json](product-flow-command-2026-10-07T01-44-43-890Z.json) | 通过 |
| [product-flow-command-2026-10-07T01-47-47-748Z.json](product-flow-command-2026-10-07T01-47-47-748Z.json) | 失败（保留） |
| [product-flow-command-2026-10-07T01-48-59-808Z.json](product-flow-command-2026-10-07T01-48-59-808Z.json) | 通过 |
| [product-flow-command-2026-10-07T01-49-51-421Z.json](product-flow-command-2026-10-07T01-49-51-421Z.json) | 通过 |
| [product-flow-command-2026-10-07T01-55-11-871Z.json](product-flow-command-2026-10-07T01-55-11-871Z.json) | 通过 |
| [product-flow-command-2026-10-07T01-56-27-420Z.json](product-flow-command-2026-10-07T01-56-27-420Z.json) | 通过 |
