# 真实HTTP产品闭环验证

2026-10-07（Asia/Hong_Kong）。最新整轮命令：`product-flow-command-2026-10-06T17-32-53-211Z.json`。12个独立库分支全部通过。每个重新初始化SQLite，经正式create_app/lifespan、GuideWorker及公开HTTP创建需求；无前一场景数据依赖。8.1样例ID以实际创建回执绑定，不把样例ID硬编码到业务库。

| 场景 | 断言数（含真实轮询） | 原始证据 |
| --- | --- | --- |
| TC-E2E-01 | 73 | [product-flow-2026-10-06T17-32-53-843411+00-00-TC-E2E-01.json](product-flow-2026-10-06T17-32-53-843411+00-00-TC-E2E-01.json) |
| TC-E2E-02 | 140 | [product-flow-2026-10-06T17-32-57-755759+00-00-TC-E2E-02.json](product-flow-2026-10-06T17-32-57-755759+00-00-TC-E2E-02.json) |
| TC-E2E-04 | 117 | [product-flow-2026-10-06T17-33-01-042956+00-00-TC-E2E-04.json](product-flow-2026-10-06T17-33-01-042956+00-00-TC-E2E-04.json) |
| TC-E2E-03-APPLY | 136 | [product-flow-2026-10-06T17-33-07-051095+00-00-TC-E2E-03-APPLY.json](product-flow-2026-10-06T17-33-07-051095+00-00-TC-E2E-03-APPLY.json) |
| TC-E2E-03-NOCHANGE | 112 | [product-flow-2026-10-06T17-33-11-238179+00-00-TC-E2E-03-NOCHANGE.json](product-flow-2026-10-06T17-33-11-238179+00-00-TC-E2E-03-NOCHANGE.json) |
| TC-E2E-03-PENDING | 112 | [product-flow-2026-10-06T17-33-14-834081+00-00-TC-E2E-03-PENDING.json](product-flow-2026-10-06T17-33-14-834081+00-00-TC-E2E-03-PENDING.json) |
| TC-E2E-03-VERSIONS | 119 | [product-flow-2026-10-06T17-33-18-441330+00-00-TC-E2E-03-VERSIONS.json](product-flow-2026-10-06T17-33-18-441330+00-00-TC-E2E-03-VERSIONS.json) |
| TC-E2E-03-STALE | 115 | [product-flow-2026-10-06T17-33-22-228131+00-00-TC-E2E-03-STALE.json](product-flow-2026-10-06T17-33-22-228131+00-00-TC-E2E-03-STALE.json) |
| TC-E2E-03-TARGET | 115 | [product-flow-2026-10-06T17-33-25-781251+00-00-TC-E2E-03-TARGET.json](product-flow-2026-10-06T17-33-25-781251+00-00-TC-E2E-03-TARGET.json) |
| TC-E2E-03-COMBINATION | 120 | [product-flow-2026-10-06T17-33-29-425559+00-00-TC-E2E-03-COMBINATION.json](product-flow-2026-10-06T17-33-29-425559+00-00-TC-E2E-03-COMBINATION.json) |
| TC-E2E-03-TABLE_ROW | 141 | [product-flow-2026-10-06T17-33-33-180458+00-00-TC-E2E-03-TABLE_ROW.json](product-flow-2026-10-06T17-33-33-180458+00-00-TC-E2E-03-TABLE_ROW.json) |
| TC-E2E-03-TABLE_APPEND | 139 | [product-flow-2026-10-06T17-33-36-791813+00-00-TC-E2E-03-TABLE_APPEND.json](product-flow-2026-10-06T17-33-36-791813+00-00-TC-E2E-03-TABLE_APPEND.json) |

程序使用明确私有兼容回调、合成计数及受控本机Tokenization/Chat TCP；实际C03、ORCH、审计、完整v2签名校验、C07与所有HTTP/事务未替换。这证明可控模型下的程序链路，不证明火山准确计数、角色封装、真实效果或生产启用。付费请求0，不读取.env.local，不接触正常业务库。

TC-E2E-01：201受理屏障、明确用户声明事实、初始化COMPLETED/IDLE、BASELINE唯一/版本1且不更改CURRENT完整模型、创建及基线原键重放。TC-E2E-02：完整模板F-A CURRENT3、F-C区块/选区，独立取消、草稿1→2→CURRENT4；六个原生SQL ABORT阶段全库前后逐字相等；完成仅更新anchor_status而保评论业务状态/时间，保留最小编辑来源。

TC-E2E-04：原文F-K c1/c2，两路径各在真实能力入口以native Barrier竞争，真实HTTP成功响应在客户端读取后丢弃；原键恢复原202且request_id新建。必答缺失、重复键、非法选项、必答跳过整组拒绝。初始化另建Run，ASK继续原Run/call_no=2；实际3Run、2正式响应、4模型尝试及4次各本机计数/Chat。

TC-E2E-03：每分支先实际合法C07生成≥2项。逐项决定不更新正文；接受/编辑/删除只一次采用；拒绝NO_CHANGE完全不改CURRENT；表格行替换与整表追加保未选行/表头及来源；未决定拒绝、放弃释放占用。独立预期为字面文本替换，不调用生产Patch实现。版本漂移、原文漂移、目标删除及重复目标组合明确为合法产出后的隔离存储故障，原不可改建议和触发器不移除；每次拒绝全库相等、原决定保留。并不声称真实AI生成了这些故障。

所有进程锁、服务生命周期、模型socket与受控服务器关闭均断言。wrapper保留source audit、stdout/stderr、退出码及运行前后源码哈希，不接受traceback或输入改变。测试库保留在忽略的output/product-flow，原始验证JSON提交。

历史失败与范围更正（全部原记录保留，不覆盖）：初版括号语法错误；旧探针误用requirement_revisions/transport_status及manual_edit_sessions.id，按正式DDL改为revisions/call_status/draft_id；iterdump使用PRAGMA被正式只读authorizer拒绝，改为独立原生只读连接取完整快照，authorizer不改；最早01/02共享库记录只算历史专项，17-02之后才独立；17-03卡片路径尚无native Barrier，17-05及以后才包含；17-15 APPLY夹具错误删掉模板段落空行，实际Patch补回合法分隔，随后保留原边界字节并继续逐字比对。其他历史通过记录按各自当时源码/覆盖解释，不作最新全矩阵替代。

本批仅新增独立工程验证工具及映射，业务/前端代码未改。799后端完整回归和259前端/生产构建记录保持，不把这些新断言加入原单元测试总数。373正式编号、05—10其他核心串联、真IME及真实Provider/效果继续逐行验收。
