# V2.1详细设计第三轮审查

日期：2026-11-14（Asia/Hong_Kong）。对象：前后端0.1-draft-3／DRAFT。范围为静态设计审查，结合两轮修正后的执行依据／历史投影／前端显示规则；两份设计不改，不执行产品、业务库、浏览器、模型／计数、服务或Git提交推送。

结论：本轮未确认新的P1问题；发现3项P2契约缺口，需要在实施前明确。上轮临时域、发布／采用分期、未建线读取、历史子项拆分和替代链唯一性修正继续保留。这里的结论不等于实现／性能／供应商通过，也不将已声明的执行件待办当作新缺陷。

## R23-01 [P2] 撤回调整时原binding与新执行校验证据未分清

位置：后端702行APP-FORM-PROPOSAL、1001行DTO-PROPOSAL、1184行formation_proposal_index；前端495／504行。

4.3写“清标记并记录新执行依据事件，原payload／binding不改”，6.2却要求“从当前真实状态取得新binding及审计事件”。当前持久化只有一个binding_json，事件快照只给binding_digest，没有区分原发布binding、撤回时的校验凭证、当前执行binding的身份／选择规则。

如果新binding仅指临时重算且摘要相同，应明确保存的是校验事实而不是替换原binding；如果指新的持久执行依据，则应定义不可变版本与当前指针及恢复规则。否则实现者可能选择始终用旧依据或覆盖唯一binding_json，两者会产生不同审计／撤回行为。此处没有断言当前撤回必然失败，而是两处“binding”的语义未唯一化。

建议：原payload／原模型basis继续不可变；给发布绑定与撤回复核凭证不同名字和精确字段，明确apply读哪份、撤回核实什么、事件保存什么及未知结果重放如何定位。提案自身needs_revision／处置标志应明确属于独立许可判断，避免把暂时禁用状态混入“用途是否仍相同”的指纹。补无关F变化、相关依据变化、撤回成功后刷新／重放的场景。

## R23-02 [P2] 成果替代关系没有进入明确的历史变化契约

位置：后端1048／1059／1066行EntityChangeView／ARTIFACT快照／MemberDelta，1191行formation_artifact_reviews，1026行LineagePage。

物理表已保存reviewed_artifact_ref→replacement_artifact_ref，并限制唯一后继。但公开事件变化的entity_kind没有REVIEW／REPLACEMENT类型，ARTIFACT标量快照也不含替代边，MemberDelta集合及MemberValue不允许ArtifactRef；LineagePage是当前F的读取，条目不含建立关系的event_id或源消息。

因此a1→a2虽真实持久化，独立读取／重放公开的CHANGES／MEMBERS协议无法直接恢复该条关系及其当时来源。不能因此说数据库丢了关系；缺的是“历史记录页面怎样获得确定替代边”的显式读契约。目前前端只能再查询当前Artifact详情并推导，规范未定义这种拼接及其历史边界。

建议：将不可变ArtifactReview作为有界事件快照／关系变化，或增加按固定event_id读取的Review明细；明确其真实消息／Revision／来源、当前链与历史事件的区别。补a1→a2→a3后只读第一个替代事件、以及不依赖当前freshness重建旧关系的场景。

## R23-03 [P2] AI建议缺少与评估相同的当前性规则

位置：后端1019行RecommendationView、1183行formation_recommendations、StepView.recommendation；前端411行概览“AI最新判断／建议”。

Assessment已有Goal／步骤定义／覆盖与CURRENT/STALE规则，但RecommendationView只有动作、目标、说明、来源及消息；存储按最新event_id取建议。Goal改版、成果要求变更或建议目标被取消后，规范没有规定旧建议何时隐藏、标为历史或重新核实。

反例：AI在定义1下建议COMPLETE_STEP，用户随后增加一个CONTENT成果成为定义2，没有新讨论；前端仍可取得“最新”旧结束建议，而旁边的Assessment已标陈旧。程序的COMPLETE合法性及允许带遗留结束并无错误，问题是建议在新定义下没有被重新形成，却可能仍按当前有效建议展示。

建议：从原GuideRun／事件绑定建议的Goal、所属步骤定义及实际依赖目标，定义RecommendationView的有效性／原因或明确服务端何时返回null；前端分开“最新历史建议”和“当前可参考建议”。不能用全局F变化就使所有建议过期，也不能因旧建议让程序自动重开／结束。补仅切焦点仍有效、相关定义变化陈旧、目标取消及新建议替代的场景。

## 本轮证据与边界

已静态对读上述类型、应用处理、持久化和前端消费段落，并对照当前验收覆盖；没有调用产品接口、实际数据库或模型验证。额外核对了现有HTTP客户端对INTERNAL_ERROR／STORAGE_UNAVAILABLE的未知结果处理，未将已有保护误报成新缺陷。上述三项属于设计澄清／补齐，未证明产品已有运行故障。

三项均只记录、未修。建议在继续审定前集中澄清，之后再核对执行／历史／显示的一致性。历史R21／R22报告与修正记录保持原时点。

本轮输入SHA256：后端`766db1a705d751f80371fb7404a2ec958c0430abad6f8343a50a6076d1f7e819`；前端`3e47339200dbb0bd04926d57ac8650ad527e085fb5937161b4fb285f32a47703`，本轮两份设计原字节不变。
