# 真实HTTP产品闭环验证

2026-10-07（Asia/Hong_Kong）。最新整轮命令：`product-flow-command-2026-10-06T17-57-44-124Z.json`。21个独立库分支全部通过，覆盖TC-E2E-01/02/03/04/05/06/10七条核心串联的本文范围。每个重新初始化SQLite，经正式create_app/lifespan、GuideWorker及公开HTTP创建需求；无前一场景数据依赖。8.1样例ID以实际创建回执绑定，不把样例ID硬编码到业务库。

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
