# 2026-10-06 统一 AI 操作父级与实际接收

核对 FE 右侧面板/DT-AI、普通文字替代卡片、DT-OP09–14/28–30、1343–1358完整会话规则、BND-CARDS/SUGGESTIONS及已批准D-004；复核 BE I14/I15/I18/I36、既有控制器的完整条件与原请求恢复以及本轮已读I20–23。原设计与生产后端未修改。

`guide/conversation-owner.ts` 在一个需求生命周期中组合实际读取、普通composer、Run操作、独立卡片组及按真实batch ID保留的批次owner。共享同一实际运行接收与完整父级采用。正在提交/核实/UNKNOWN/CONFIRMED的原流保有权限，其他AI写入口禁用；隐藏/历史保护只关闭可用性和查询，保留原请求、卡片与普通输入，不发送取消或放弃。临时DocOwner采用busy不改变原流epoch，视图可以独立禁输入。

CardGroups新增可选命令guard，默认行为不变；权限重算只处理可用性，不反复采用详情/读取来源/改草稿。保留全部已创建owner中的待确认流，即使消息结构损坏后交互槽隐藏，也不释放未知请求。真实活动BATCH优先显示；原未知批次保持原owner；历史选择与当前范围独立。AiRead在实际BATCH初始/采用时只选择来源身份，然后真正I16读取完整Run，不伪造已完成运行。该来源读取失败时保上次对应批次，正式完成后保来源运行的批次关联。

6新增Node父级检查：普通文字UNKNOWN/同接收与实际EXPIRED清稿，卡片UNKNOWN跨父级刷新保同owner/阻止竞争写，CONFIRMED纯读/历史及隐藏输入保留，原批次意图跨不同活动仍原ID，历史选择不造批次，退休所有owner无新增提交。原8卡片集合检查再次通过。前序 `frontend-2026-10-06T06-49-30-307Z.json`、最终 `frontend-2026-10-06T06-53-17-191Z.json` 均246前端检查/TypeScript/依赖通过；最终197输入稳定，和后续所有浏览器的相关源hash一致。

`conversation-browser-2026-10-06T06-56-44-887Z.json`：426hash稳定，真实现有AiReadPanel/CardMessage/GuideComposer/RunControls在统一生产owner下执行按钮：

- 初始化卡片3有本地未提交答案，普通I14丢202保原文字/草稿并禁卡片提交；隐藏后复查失败不发，再原键恢复。真正I35推导EXPIRED才清对应草稿，正式TEXT全文未映射选项；真正新Run4 FAILED配置错误，正文不变。
- 等待来源Run5普通I15丢202恢复，原ID5继续并实际FAILED，I35过期清稿，无CARD_RESPONSE，需求2仅原初始化及Run5两运行。正文完整不变。
- 来源Run6整组I36丢202时composer禁发、保原未提交文字；原键正式回答继续同6，实际ANSWERED/正式CARD_RESPONSE只读、本地草稿清理，普通文字仍留输入区。
- Run6失败后I18丢202恢复创建唯一新Run7/retry_of6，旧Run与正式用户消息保留，原普通输入不丢。

四组实际原key/body200或202重放，8次操作发送+3次明确私有I14前置共11条相关wire；continue仅instruction，retry无Body/Content-Type。初始化读7/采用4；等待文字6/4；卡片回答6/4；回答后含重试总9/6（包括实际背景重读）。两个CURRENT全文/完整元数据/版本不变，正常关闭2需求/2文档/1版本/0评论/7Run/0LLMUse，服务退出0。已查看初始化、过期、重试三张局部诊断截图，长页面诊断的截图滚动位置不作为产品布局通过证明。

`conversation-suggestions-browser-2026-10-06T06-54-42-841Z.json`：同426hash稳定，真正统一owner的原批次和I16来源关联，已有SuggestionPanel整套原/新只读、安全HTML、表26定位、高亮、固定批次区、确认/取消/UNKNOWN/CONFIRMED恢复再验；3批15项、15prepare/19send/4冻结回执结构等价、34完整读/25采用。实际v2→v3/DocOwner与PM刷新；NO_CHANGE及DISCARDED完整CURRENT不变。完成后统一owner仍同batch且实际来源Run的suggestion_batch_id一致。正常关闭2/2/1/0/5Run/0LLMUse/3批15项，服务0。

`ai-read-browser-2026-10-06T06-58-16-750Z.json` 独立真实读取回归同426hash稳定：消息旧游标失败保旧/重试锚点、新消息阅读位置/回底，Run历史分页与筛选、评论AI实际接收、隐藏暂停/展开实读保持通过。正常关闭2需求/2文档/1版本/1评论/26Run/0LLMUse，服务0。生产后端未改，730仍历史检查；没有执行真实Provider或付费请求。

保留失败：`conversation-browser-06-49-18` 的四段实际按钮均执行，最终汇总把I36路径写成不存在的card-responses，漏一组；实际正确路径是responses，修正选择器后完整再次通过。`conversation-suggestions-06-52-57` 的layout命令CLI退出127且输出为空，其后诊断显示真实服务/页面正常、已有来源Run/原batch匹配；长命令拆分后通过，未声称一般Windows运行时问题已根治。Node预检一次parameter property不被strip-only支持，改显式字段；两个夹具错误（正式回答文本非正式算法、decided_at缺失）改为契约值，保原生产校验；瞬时读失败曾被合法背景读取消费，改隔离期间持续故障再显式恢复，未减弱“失败不重发”断言。

本单元完成统一AI控制器及其真实局部交互，**尚未创建完整产品GuideConversation布局/RequirementDetail根父级、DetailFrame窄屏/历史/站内离开与各业务统一竞争、产品路由/index/正式build/start说明、全页视觉或373/P8最终验收**。两类生成前置仍明确私有持久夹具，非C07/可信模型效果；Provider兼容/字段预算/效果问题继续开放。没有半函数或生产假成功替代，下一单元按上述自然边界继续接线。
