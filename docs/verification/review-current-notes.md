# 旧检查与最新正文的实际页面验收（2026-10-07）

重读 FE DT-OP09/10、BE APP-GUIDE-CMD-C01 完整单元及 D-004 公共稿范围规则。DT-OP10 明确允许原 Scope 或用户重新选择 Scope；历史检查只作来源，修改重新读取最新 CURRENT。

实际页面复现原选区删除后，原入口正确拒绝且保留未发送输入，但没有将旧检查绑定用户新范围的入口。补上“按本次范围根据检查修改”：以用户已选择的范围为依据，再从实际 CURRENT 校验定位；过时目标不可使用，失败不改范围或发送。原范围入口继续逐字定位原 Scope。

三支最终[主证据](review-current-browser-2026-10-07T11-16-29-019Z-24014b2d197a.json)及[独立关闭库审计](review-current-post-audit-2026-10-07T11-19-37.364827+00-00.json)通过：实际 v3 REVIEW，经真实人工编辑保存为 v4，再分别使用整篇、仍唯一有效的原选区、已删除原选区后显式选择 BLOCK。失效入口保留输入/动作，不写 HTTP，不绑定来源；新入口回显来源与范围后才发送。来源 reviewed_content_version=3，而新 Run 请求、完整模型读取、建议原文和 batch base_content_version 均为4，C07真实生成唯一助手消息/批次。生成及实际 I23 放弃不改完整 CURRENT 或既有 Baseline。3需求/3CURRENT/3Baseline/9Run/6LLMUse/3批次/3建议。

原四 Scope 入口[回归](guide-scope-browser-2026-10-07T11-15-33-640Z-449503c0c7f1.json)与[独立关闭库审计](guide-scope-post-audit-2026-10-07T11-18-44.926741+00-00.json)通过，包括选区丢202原键恢复与 DOCUMENT 明确改 BLOCK。4需求/4CURRENT/4Baseline/12Run/8LLMUse/4批次/4建议。两套452输入稳定，共451相同；对上轮运行输入仅 composer-view.tsx 变化，见 review-current-combined-2026-10-07.json。最终合计14次本机受控 Chat/14真实LLMUse、0付费；运输与隔离服务全部正常关闭。私有扩大预算/兼容回调仅用于程序链验证，不是正式DeepSeek计数或效果证明。

失败原样保留：11-11 首轮未选择重载后的历史 REVIEW，等待原入口超时，属于验收前置缺失；修正为实际运行记录选择。11-13 实际复现 Missing explicit selected-scope REVIEW source entry，随后修复页面。11-15 CLI一次退出127、0本机Chat，保留全部记录并使用同一完整脚本重跑，不进行Windows崩溃专项。五个session的12张原图及manifest SHA保留于 review-current-media；已查看最终失效选区输入与新正文选区建议原图。

263前端及另4 development、TypeScript/依赖通过：frontend-2026-10-07T11-15-02-377Z.json。正常dist构建与已有8000页面/I01只读200、HTML等于新dist及用户数据库SHA不变通过：review-current-preview-2026-10-07T11-18-20.549744+00-00.json。没有后端业务或批准资源变化，814后端/55核心沿原范围，未伪称本批重跑。

正式 TC-UI-DT-OP10 保持实现中，尚需真实WAITING、明确拒绝/取消/未知与其余负向完整闭合；373正式原身份/六列不变，44已验证/311未开始/18实现中。下一单元实际受控 C07 产生 WAITING_USER 后普通 I15 继续同Run、读取真实新消息/审计并验证卡片过期；之后PERSISTING竞争/完整重试及剩余正式验收。真实Provider计数/效果与人工IME/键盘仍独立待，不新增付费调用，不宣布整个目标完成。
