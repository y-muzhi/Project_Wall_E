# 实际卡片正式回答与可见错误焦点（2026-10-07）

重读前端 OP02 L732–747、卡片/对话 L1325–1356、UI原则 L109–163，后端 SHR-CARDS L446–487、C06 L2734–2830、I36 L5969–6018及批准公共决策稿D。真实五卡根页暴露首个错误字段虽聚焦却被消息阅读锚点移出可见区。cards-view.tsx 现在等待新增错误及 ResizeObserver 两帧稳定，校验仍有效字段后主动聚焦并居中滚动；退休或禁用时取消回调。没有改答案、状态、成功焦点、快捷键、80px新消息规则或公共资源。legacy组件探针等待同样稳定帧后保持原焦点断言，根页另加入实际视口几何断言。

最终固定五根分别见 card-answers-root-browser-2026-10-07T15-51-49-838Z-a47b72a5d9db.json（四支）和 card-answers-root-browser-2026-10-07T15-51-59-988Z-45b5f3f55b3f.json（五卡）；独立关闭SQLite审计分别为 card-answers-root-post-audit-2026-10-07T15-55-19.969757+00-00.json、15-53-53.770120+00-00.json，两套452输入完全相同且前后不变。组合 card-answers-root-combined-2026-10-07.json：5需求/5CURRENT/5Baseline/10Run/10LLMUse/10本机Chat/0建议/0付费。实际ORCH/v2审计/C07产生原卡片，无SQL安装输出。私有worker仅在明确flag/隔离新库识别实际同Run、原助手卡片及call_no1可信输出一致的CARD_RESPONSE，继而执行真正第二轮ANSWER；normal服务无此替代。扩大私有编译预算及兼容回调不当正式Provider计数或效果证明。

ANSWERS-normal/unknown/five真正I36保存唯一CARD_RESPONSE；普通TEXT/CARDS经I15继续同Run，普通文字不猜成选项，原卡片真实EXPIRED后才清本地。每例五条正式消息，call_no1/2各attempt1，来源、scope、协议保持，完整CURRENT3及Baseline不变，最后IDLE，无批次。五卡包含单选、自定义、多选组合、确认、显式非必答跳过及末项；不默认选推荐，未完成多选时0HTTP写。最终错误field651.65625–664.65625，message viewport477.875–837.875，实际焦点与可见性均真。C06摘要、structured答案、原组reply关系、第二轮formal_responses/历史与Manifest全部闭库逐字核对；原问题进入Manifest关系，未选推荐不会进入普通用户历史。

UNKNOWN首次实际202提交后明确丢回执，原稿保留。最终再明确丢一次实际GET需求读回执（真实200已读取后抛私有传输故障）：第一核实只读且不重发、保原稿，第二次明确点击核实取得实际状态后原键/原body/原data重放；仍唯一正式答案、两次模型调用，无自动无限循环。此前15-34失败在首轮恢复碰到真实GUIDE_ACTIVE→IDLE，RequirementDetailRead拒绝混合多接口状态；独立负向证据 card-answers-root-recovery-read-race-2026-10-07T15-47-21.541303+00-00.json 证明已答/模型完成且0恢复POST。保留整套失败，未将失败改成通过，未修改这种安全读取行为。最终固定测试最多两次明确恢复点击并记录每次读/写；审计强制首轮一条真实200未交付GET、无POST，第二轮成功才原请求重放。

关联四卡实际控件/滚动回归 cards-browser-2026-10-07T15-34-01-380Z.json 及 cards-regression-post-audit-2026-10-07T15-46-53.898298+00-00.json 通过，457输入稳定、451共同输入与最终根相同。该前置为明确持久卡片夹具，后续真实I36/I15/I35及SQLite，0LLMUse，不冒作C07。原阅读锚点偏移7.5625→7.390625px、异步来源展开距底保持0；正式答案唯一/不同键409/后续CONFIG_INVALID仍已回答等回归保持。修正后的 frontend-2026-10-07T15-31-40-945Z.json：263＋独立4development、TypeScript/依赖全部退出0，209输入与当前代码一致。正常生产构建及8000只读页面/I01、HTML==dist、用户数据库SHA不变，见 card-answers-root-current-preview-2026-10-07T15-35-36.086617+00-00.json；未重启正常服务、未载.env或模型密钥。

全部阶段保留。14-56五卡受控响应复制了其余四卡历史快照，真正业务校验拒绝，三个有界尝试后FAILED/IDLE且无正式卡片；负向实库及四处源不等价证据分别five-rejection/five-source-evidence。修正全部五卡引用真正当前区块，不放宽校验。15-09完整命令意外退出1只留下five passed/部分图片，无最终矩阵报告，command-interruption明确不当通过；加外层固定分组选项命令捕获，不调查Node崩溃。15-14/15-15只是改焦点前通过，15-27可见性增强实际复现focused真/visible假（field960.65625–973.65625、area478.875–838.875），修正后15-31及最终15-51几何通过。15-50/15-51新增读故障regex被CLI嵌套转义导致SyntaxError、0模型请求；实际失败保留，换无转义路径判断后重跑，不改业务预期。所有成功/失败/中断的74张原图及SHA保存 card-answers-root-media/manifest.json；最终五卡错误及读取失败画面已查看，较早五卡/正常画面亦保留。

373原始六列/身份保留，OP02和TC-UI-CARDS接续当前范围仍实现中；44已验证/311未开始/18实现中，不等于功能进度。既有814后端/55核心沿原证据范围，未冒称本批重跑。剩余初始化实际卡片、REVIEW/MODIFY等待及完整正式回答/拒绝/取消/迟到、PERSISTING竞争/根重试与其余正式场景、人工IME/键盘、正式DeepSeek计数兼容和真实效果继续，不新增付费，不宣布整体完成。

下一单元已完整补读后端C02 L2426–2497、I15 L5089–5129，核对REVIEW/MODIFY输出oneOf及现ControlledScope/Waiting实现；完整Schema最初大段输出截断，只按实际完整分支阅读定位，不宣称重新全文读Schema。继续真实REVIEW文字等待→同Run REVIEW_RESULT、REVIEW卡片正式回答；MODIFY卡片普通替代/正式回答→NO_CHANGE，以及各自冻结function/上下文/AllowedTargets/终态的独立关闭库审计。需先重读FE OP10/11及BE C07/ORCH对应效果完整定义，再扩展私有worker，不改normal/批准资源。之后PERSISTING取消/根重试：前者在实际C07同写事务内更新，外部I16不能观测未提交步骤；验证须真实事务竞争证据，不能SQL伪造。
