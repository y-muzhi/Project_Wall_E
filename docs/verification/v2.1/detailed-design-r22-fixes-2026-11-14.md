# V2.1 R22五项问题修正收口

日期：2026-11-14（Asia/Hong_Kong）。工作区codex/v2.1-design-review，代码HEAD21651c3。用户要求解决再次审查全部问题；本轮只设计与静态核对，不进入产品实施。

当前[后端设计](../../iterations/pending/v2.1/WALL-E.后端设计文档_V_2.1.md)和[前端设计](../../iterations/pending/v2.1/WALL-E.前端设计文档_V_2.1.md)均0.1-draft-3／DRAFT。大纲0.12及八份采用来源字节不变；旧[再次审查](detailed-design-rereview-2026-11-14.md)及R21证据保留原时点，不能拿旧的“未修”覆盖本次修正，也不倒写旧检查已通过。

| 问题 | 本轮修正与闭环位置 | 验证依据及尚未执行 |
| --- | --- | --- |
| R22-01 | 统一PathChange.ADD_STEP的temp_step_ref／replaces_step_refs；分开TempStepRef／TempResultRef及PathStepRef／PathResultRef；全部声明先收集，逐字段解析，真实图校验后才分配；正式历史用ResolvedResultRoute | 完整ADJUST_PATH JSON正例、7个独立字段／类型反例；R22-01和FE17场景；不是运行接口验证 |
| R22-02 | CanonicalCardPayload按用途解析：来源和已生效实体真实化，路线卡未来声明仍局部临时；CARD_APPLY生成独立执行映射，不改原卡；LINK_CONTENT预览用ARTIFACT_LINK而不预分配ArtifactRef | 发布／预览／采用阶段静态串读，R22-02与真实同轮写卡对照场景；尚无模型／采用执行 |
| R22-03 | Summary先读，exists=true才读实体；直接无主线实体页409 STATE_CONFLICT／FORMATION_NOT_INITIALIZED，真缺文档404；前端重读Summary而非F0空页 | A01正反例、R22-03／FE18顺序与错误约定；未运行HTTP／浏览器 |
| R22-04 | 两个新增目标表formation_closure_evidence／formation_event_members；Closure根项只计数与digest，来源／关联／范围逐行冻结；ORDER逐节点，集合用MemberDelta；固定历史游标、确定排序与流式摘要 | 1001关联×每项2范围=3003独立证据行，页100时31页的独立规模推演；R22-04／FE19有成功、失败回滚、历史不回写预期；未验证实际SQLite／性能 |
| R22-05 | 复核只作用当前叶，旧review_of明确ARTIFACT_SUPERSEDED且不自动重定向；先原key重放；部分唯一索引限制每节点一个后继和前驱；当前／历史／LINEAGE及计数一致 | R22-05／FE20包括旧节点、并发连接竞争、正常a1→a2→a3、合并／环反例；仍需实际SQL与租约／事务取证 |

另对齐第4章与第6章事件名闭集，不保留PATH_ADJUSTED／BRANCH_FOCUSED等未登记wire别名；明确生产同需求单运行不因存储竞争用例获得并行模型权限。两份仍按原八章职责，不新增第三份共同规格。目标表共21张，新增读取边界同步到前端5／6／8章。

## 实际静态检查

PowerShell内Python内存脚本执行，没有保存测试脚本／JSON报告／原始日志，没有导入产品模块：

- 两份8章／0.1-draft-3、表格列数、唯一显式锚点、3个JSON示例解析通过；A01—A76连续且独立预期逐条等于大纲0.12；前端20项／共享R22五项场景均明确未执行。
- 完整路线请求按声明的严格字段与临时域检查通过；依次改错temp_step_ref／replaces_step_refs、错种类、重复声明、未声明成果、借用其他临时域、把源成果写为临时身份，7项均在独立形状／引用检查中拒绝。这只是协议正反例检查，不证明生产校验器已实现。
- 检查Closure根项不再包含证据数组、ORDER不再含step_refs数组；两个历史子页可覆盖3003条明细；唯一前驱／后继声明、只复核活动叶、未建线门禁及原R21状态／F策略／DB2屏障均保留。容量分页为静态数据推演，未测实际数据库或网络内存。
- 大纲SHA256保持3774e919a16cd09e18a548ee06227836f73cddea64fe1c89ea516caa441ff6a1，八份来源摘要一致。git diff --check退出0；已跟踪backend／frontend／resources／docs/design／docs/templates差异为空。

文档采用同目录临时文件、flush/fsync、权限保持、原字节并发比较及os.replace；成功／失败清理本轮临时文件。同步当前版本导航、映射、计划及[断点](../../project/v2.1/实现进度_V_2.1.md)。

结论：R22-01—05在设计层全部修正，连同旧R21修正完成本轮静态一致性复核。没有声称实际数据库唯一性、事务回滚、浏览器可用、模型效果或性能通过。执行Schema／完整DDL／新资源／decoder、真实V2.0全量兼容及产品证据仍按原技术待办接续；不自动EFFECTIVE、正式合并、代码实施、业务数据／浏览器存储／服务操作、真实调用、提交推送。

相对链接核对：40份当前Markdown、251条链接通过（历史验证仅检查链接，不修改正文）。

当前原字节SHA256：后端`766db1a705d751f80371fb7404a2ec958c0430abad6f8343a50a6076d1f7e819`；前端`3e47339200dbb0bd04926d57ac8650ad527e085fb5937161b4fb285f32a47703`。
