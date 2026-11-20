# V2.1 R23三项契约补齐核对

日期：2026-11-14（Asia/Hong_Kong）。工作区codex/v2.1-design-review，代码HEAD21651c3。用户要求先补齐第三轮审查三项；本轮只设计及静态契约核对，不实施产品。

当前[后端](../../iterations/pending/v2.1/WALL-E.后端设计文档_V_2.1.md)和[前端](../../iterations/pending/v2.1/WALL-E.前端设计文档_V_2.1.md)均0.1-draft-4／DRAFT。大纲0.12、八份采用来源及旧轮次证据保持原字节／原时点；[第三轮审查](detailed-design-third-review-2026-11-14.md)中的“未修”描述其当时状态，不覆盖本次补齐。

| 条目 | 已明确的唯一规则与同步位置 | 验证边界 |
| --- | --- | --- |
| R23-01 | PublicationBinding权威不可变，protected_semantic_digest只保护实际用途／来源；本卡调整标记／焦点／D/F等独立许可不污染指纹。撤回只生成WithdrawalCheckProof及PROPOSAL_CHECK历史，原绑定不换；apply每次重新核实原绑定和当下许可，不以凭证缓存授权 | 后端APP-PROPOSAL／DTO-PROPOSAL／事件快照／表binding字段，前端卡片／回执与重放；TC-FORM-R23-01及REPLAY、FE21均是待执行设计场景 |
| R23-02 | ARTIFACT_REVIEW是严格有界历史快照，与review物理行同事务一一对应。CHANGES固定event_id直接给边／消息／Revision／来源，当前Artifact／Lineage用review_event_id导航，不反推旧事实 | 事件kind／Snapshot、唯一约束、持久化及前端记录页同步；TC-FORM-R23-02及ROLLBACK、FE22；尚无真实SQL／页面证据 |
| R23-03 | 程序绑定不可变RecommendationBasis，含Goal、owner定义／状态、实际覆盖、目标、实体／关系集合及来源摘要；查询按相关变化派生CURRENT/STALE，历史不写派生标签，null只表示从未建议。旧建议不禁用独立手动操作、不额外Chat | 对象／模型接收／View／历史Snapshot／表basis列与前端概览同步；TC-FORM-R23-03及NEW、FE23；模型不允许自行填basis/validity |

建议当前性按明确优先级给出原因，仅切焦点／无关D/F及未影响真实覆盖的V变化不使建议失效。新建议不回退旧条目；同轮新建对象的绑定以完整结构验证后的待提交状态生成，模型原冻结输入basis不改写。表仍21张，无新业务库或额外服务。

## 本轮实际静态检查

PowerShell内Python内存脚本执行，无产品模块导入、无原始JSON／测试日志留存：

- 两份均八章／0.1-draft-4；表格列数、显式锚点唯一及全部3个JSON示例解析通过。A01—A76编号及独立预期逐条与大纲一致；前端23项，R23共享6个场景变体登记齐全，均未执行产品验收。
- 纯数据反例检查：在同一原绑定下变化焦点／调整标记不更换原绑定；Goal、V、Revision、步骤定义四种相关改变各导致受保护摘要不匹配。此为声明投影的静态推演，不是生产权限校验器测试。
- 固定E1(a1→a2)、E2(a2→a3)的review字典按六字段形状核对；只重放E1仅一条边，处理E2后两条，E1摘要不变；核对新事件类型／Source读取契约，不能替代实际事务／历史接口执行。
- 从规范文本检查建议basis由程序生成、模型RECOMMEND原字段不接受basis/validity、历史Snapshot排除派生标签；确认三项规则在生产许可／历史事实／当前显示三个范围没有互相替代。
- 大纲SHA256保持3774e919a16cd09e18a548ee06227836f73cddea64fe1c89ea516caa441ff6a1，八份来源摘要一致。git diff --check退出0；已跟踪backend／frontend／resources／docs/design／docs/templates没有差异。

当前版本、导航、计划、映射及[断点](../../project/v2.1/实现进度_V_2.1.md)同步；旧审查和验证正文未改。保存通过同目录临时文件、flush/fsync、原字节并发比较、权限保持及os.replace，临时文件成功／失败清理。

结论：R23-01—03在设计层补齐并完成本轮静态复核。未修改产品代码、运行Schema／资源／DDL，未访问业务库／浏览器存储、运行产品测试／构建／浏览器／模型／计数、操作服务或Git提交推送。执行件、真实V2.0全量基线和实际事务／浏览器／供应商证据仍在实施阶段取得；不将本次静态通过表述为实现或产品验收完成，不自动正式合并或EFFECTIVE。

相对链接范围：42份Markdown、260条链接通过。

当前原字节SHA256：后端`4049f8d3b5d01bd704dd0439b8c0730155cec813f3f5ef8ef7ad8c5ba5b5b197`；前端`0f54539980b07dab5abae33d679339e1bef898c651882a774f1aa25dc58d9cee`。
