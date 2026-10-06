# AI 普通文本发送及 CURRENT 范围单元

接续58b7cf1。重读FE DT-OP01/03/06/09–11/28及DT-AI输入/范围/隐藏与未知规则，BE完整APP-GUIDE-CMD-C01/C02（2319–2498）/I14/I15（5039–5128）、原有读取/接口/实际文档父级和已确认公共B的Scope/Selection及公共D的范围选择器定义。原输入未改；历史全文读取账本仍完整。本单元新增guide/scope.ts、composer.ts、composer-view.tsx，并补回CreateGuide类型漏掉的INITIALIZE。

GuideTarget由实际有效CURRENT编辑器的完整Markdown与元数据配对产生，绑定document_id/content_version；DOCUMENT是正式全文，BLOCK是真实区块ID，当前SECTION向前找到真实标题，SELECTION只接受一个区块内完整事件并核验码点范围/原文/上下文/唯一匹配。重复/重叠候选均拒绝，不trim、截断选区或扩大范围。根据已完成的同需求REVIEW修改时重新绑定最新CURRENT；原SECTION标题改变类型不能退到别的祖先章节，原选区缺失或歧义不能降为全文。用户可明确改选范围；来源始终独立保留，不直接采用旧补丁。正式REVIEW产生/效果及整页后续修改链未由此次端口测试验收。

范围下拉与实际DocumentOwner导航/选择事件相连，失效项禁用并解释；显示此次原范围。正文版本或当前区块/选区变化不会静默更换已有范围，可显式“采用当前范围”，保留输入。操作按生命周期列INITIALIZE或ASK/REVIEW/MODIFY；等待期间只补充同一实际活动Run。正文历史/人工/窄屏或真正隐藏由父级setAvailable保护；瞬时父级采用busy只禁用控件，不等同隐藏，避免自身确认后读取被误取消。无Enter提交，组合输入期间发送不可用。

未发送文字不生成ConversationMessage。普通指令标准化后1–10000 Unicode码点/允许换行；错误保原文本。一次明确发送冻结CREATE的当前版本/action/scope/source/指令或CONTINUE的原WAITING Run/指令，并只准备一次不透明动作。INITIALIZING+IDLE走I14 INITIALIZE后续轮；ACTIVE或COMPLETED依动作许可走I14；实际ASK/REVIEW/MODIFY WAITING owner走I15同ID，仅instruction，不另建Run或把普通文字转换成卡片答案。

UNKNOWN时禁止换原输入/范围/版本/动作；先完整实际详情及I35，继续场景另读原I16，再原键原body重放。读失败不重发，matching GET不证明自己的提交；REQUEST_IN_PROGRESS保UNKNOWN，确定状态/范围/版本/来源冲突须真实重读并显式修正。HTTP接受只确认正式用户消息与运行身份，不表示模型完成。正向回执保持CONFIRMED；真实接收、完整父级采用及正式消息刷新均完成才清输入，失败后仅读恢复且已确认接收不重复。真正隐藏与退休抑制晚读/后续采用，退休前排队不发送。正式卡片草稿/EXPIRED清理由后续卡片单元接入，不能把普通文本路径当作完整DT-OP03卡片交互验收。

12个新增Node端口检查涵盖10000/10001码点、Unicode/CRLF/空与非法代理项、旧版本显式重选、未知不可换请求、I15同ID、确认后读取失败仅读、源REVIEW门禁、REQUEST_IN_PROGRESS/外来回执、退休/隐藏晚读、重叠原文、完整选择事件私有字段和旧章节类型变化不扩大。最终[201项前端及TS](frontend-2026-10-06T04-28-58-596Z.json)通过，178输入哈希不变。

最终[实际编译诊断浏览器/API/SQLite](composer-browser-2026-10-06T04-30-28-073Z.json)通过，403输入哈希不变，preview健康、自有CLI/服务正常关闭（正式服务退出0）。实际人工I10/I11/I12先把“真实范围😀甲乙”保存到CURRENT2/v2并分配区块26；随后生产控件I14依次DOCUMENT ASK、BLOCK26 ASK、SECTION标题24 REVIEW、DOM完整😀选区MODIFY（CP[4,5)，原前文“真实范围”、后文“甲乙”）。每次真实202首次丢弃，按原键原body重放，独立Run/真实USER消息各一次。DOCUMENT场景跨隐藏/展开、一次观察失败不重发，确认后一次正式消息读取失败仅重读恢复，不重复接收。

I15成功前置使用**明确私有隔离的持久WAITING夹具**：仅--composer传--seed-waiting-ask-fixture；名为“真实等待回复夹具”的首个ASK后台dispatch在隔离库设置已知状态前提，不创建助手问题、LLMUse或trusted_output，不声称该WAITING由生产编排/模型产生。其继续dispatch运行正式ORCH，因缺配置实际FAILED。测试预置状态与真实I15事务/幂等/正式USER消息/UI回执/同ID恢复分开记录；一般测试及生产服务无该夹具。真实I15在Run7继续，普通文本规范为“明确😀\n边界”，body仅instruction，原键重放仍Run7，不创建第八条需求2运行。需求1再用真正I14发送INITIALIZE后续轮，使用当前v1且只创建Run8。

七次动作各prepare1/send2，完整14条真实POST都有相同原键/body配对，冻结data逐字相同。需求2共6条Run（含原初始化）及7消息（一次继续而非重试复制），需求1共2Run/2消息。最终CURRENT1/v1及2/v2全文、身份、区块全部元数据逐字不变。持久事实2需求/2文档/1版本/0评论/8Run/0LLMUse；正式模型配置剥离，未出站或付费。

保留所有原失败而非覆盖为通过：04-21-21因断言把输入CRLF与浏览器文本域实际LF直接比较；确认原始DOM值完整保留后改为发送前后DOM对比，不改普通文本规则。04-22-35为诊断父级把自身采用busy当隐藏，导致CONFIRMED刷新被阻断；修正调用关系，控件busy保护与真实隐藏保护均保留。04-24-25为真实实现缺陷：将完整SelectionEvent展开到公共ScopeRef触发未知字段拒绝；显式提取三段文本并新增完整事件检查后修正。04-26-24已全链通过及04-27-10的200检查保留。增加旧REVIEW章节类型变化检查后04-28-47在bootstrap时Node/Vite preview异常退出0xC0000409，I08 TCP读取失败；正式API退出0，无源码哈希变化，无JS stderr/诊断文件。此Windows运行时问题尚未根治；原样新隔离库04-30-28全链通过，不把进程故障当业务通过。

已查看实际范围输入控件局部截图，不宣称完整页面视觉/产品根构建。后端生产代码未改，730项是历史证据；373/P8、Provider兼容/字段预算/真实模型效果/付费授权仍开放。当前完整断点是本发送/范围单元已验证；下一单元重读BND-CARDS/SHR-CARDS/I36/APP-GUIDE-CMD-C06，接正式交互卡片整组校验、sessionStorage、状态投影与未知恢复；随后建议批次、完整父级/根入口/正式构建与最终验收。没有遗留自有服务。
