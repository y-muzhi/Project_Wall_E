# 实际等待、普通续轮和卡片过期（2026-10-07）

重读 FE DT-OP03/28、BE APP-GUIDE-CMD-C02/C07 完整单元；未修改原设计、批准资源或生产业务代码。新增独立互斥 --controlled-waiting-model 私有边界：仅明确验收 ASK 首次请求返回 CLARIFY_TEXT/CLARIFY_CARDS；后续普通续轮仍走受控 Scope Worker 的 ANSWER，初始化仍是普通缺配置失败。实际 TCP、ORCH、v2完整解析/Schema/证据等价、审计和 C07 建立 WAITING/助手卡片，不用 SQL 安装等待状态或结果。实际卡片原文来自 CURRENT，完整正文和 Frozen Schema 不弱化。

[最终三根](waiting-root-browser-2026-10-07T13-52-53-796Z-513f7638ee1e.json)及[独立关闭SQLite审计](waiting-root-post-audit-2026-10-07T13-59-52.707510+00-00.json)通过：文字追问正常续轮、卡片普通文字替代、卡片续轮202真实丢失后的原键恢复。推荐没有默认勾选，本地自定义原稿在未知时保留；实际 I35 推导 EXPIRED 后清对应 sessionStorage，原卡片不可提交。普通补充仅 TEXT，没有猜选项或生成 CARD_RESPONSE。每需求只有原初始化 Run 和原 ASK Run，续轮保持ID/动作/Scope/来源/冻结协议，真实 call_no=1/2 各一次，唯一USER/助手序号1–5。未知重放原键/原body/原data，不额外调用模型。完整CURRENT v3与Baseline不变，最终IDLE，0建议、0评论。3需求/3CURRENT/3Baseline/6Run/6真实LLMUse/6本机Chat，正常关闭运输/服务，0付费；私有扩大预算与兼容回调不是正式DeepSeek证明。

审计按批准C03核对未选择卡片推荐不能进入历史；只有TEXT/CARD_RESPONSE是可读历史。本批没有正式卡片答案，所以第二轮卡片案例的Manifest不含卡片助手消息，普通补充的 formal_responses=null。原始v2输出/助手结构化内容/卡片逐字等价、真实相关原文、模型参数、完整读取块及持久 I14/I15 回执均独立核对，数据库文件字节不变。452输入稳定，与上一批451共同输入仅 tools/api-browser-service.py变化，生产输入保持不变，见 waiting-root-combined-2026-10-07.json。

失败原样保留：11-26首轮文字支通过，卡片自定义框的实际可访问名称含长度帮助文本，测试器错误要求精确“自定义回答”而超时；依实际快照修正定位器，未改业务。13-57审计器误写ASK内部函数名；已批准 Function 是 ANSWER_REQUIREMENT。13-58审计器误将未选择卡片纳入历史；按C03完整规则核对TEXT/CARD_RESPONSE精确集合后通过，不放宽结果断言。两轮共10张原图和manifest SHA保留 waiting-root-media，已查看未知与完成图。未知图的生产器使用字面诊断文件名，唯一unknown支原字节已按session明确归档；后续修正这个私有诊断命名时重跑对应验证，不把重命名当新的页面结果。

生产代码无新增变化；263前端＋独立4 development/TS/依赖、正常dist/8000来自本日上一批有效范围，814后端/55核心按既有证据，不伪称本批重跑。373原六列与身份保留，OP03/28仍实现中；44已验证/311未开始/18实现中。后续继续REVIEW/MODIFY实际等待与正式整组答案、拒绝/取消/迟到/未知、PERSISTING竞争及完整根重试；卡片正文/结构化展示与降级、人工IME/键盘、独立Provider计数/效果亦待。没有新付费授权或崩溃专项，没有宣称整体目标完成。
