# 真实运行取消与失败重试操作单元

接续 f14dccd，完整重读 FE DT-OP29/30（1249–1290）及5.5相关失败/隐藏规则（1458–1491），BE APP-GUIDE-CMD-C03/C04（2499–2649）及I17/I18（5173–5260），现有实际接口、读取控制器与权限定义。原始输入不变，历史全文阅读账本仍完整。本单元新增 `frontend/src/guide/run-actions.ts`、`run-controls.tsx`；发送、范围选择、INITIALIZE续轮、I15文本继续、正式卡片及建议批次另有后续单元。

一个需求保留一个运行操作意图，包含实际原 Run 的独立快照、CANCEL/RETRY 操作以及只准备一次的不透明动作。实际页父级必须提供详情读取、采用和真实运行接收回调；控件重挂、切换查看的 Run、收起或暂停不会改变未知请求，也不会触发取消。支持宽度/当前文档模式的父级通过 setAvailable 接入权限；完整产品父级尚待整合。取消仅实际活动 owner 的 RUNNING/WAITING_USER 且非 PERSISTING；重试仅 FAILED、实际 IDLE 与当前生命周期允许原动作。权限不是服务端事务检查的替代。

I17/I18 均无请求体/Content-Type，新的明确动作生成新键，未知结果保留原键。未知先实际完整详情、原 Run I16、最新消息窗口 I35，资源读取失败不重发。得到 matching GET 不会确认自己的操作或制造新运行；只有原请求正向回执确认 CANCELLED/FINISHED 或独立 RUNNING/PREPARING 的 retry_of 新 Run。REQUEST_IN_PROGRESS 保留 UNKNOWN，安全已知失败保留原失败/运行信息；显式重读可更新实际阶段，PERSISTING 禁用取消并继续由既有读取器跟踪。未知期间别的历史选择无法替换原意图；晚到/隐藏再展开的旧观察不采用。退休前排队不发送，退休后不做父级采用。

正向回执保持 CONFIRMED，先交付真实运行接收方，再读取并采用实际完整详情。已确认后的读取/采用失败只重试该步骤，不重新发送；已获得接收方确认时不重复交付，未确认接收方用同一回执重试且接收方须按 Run ID 幂等。HTTP202仅接受，最终模型状态由I16读取；原失败 Run 不改回 RUNNING，不复制用户消息或应用旧正文/建议。

10个新增 Node 端口检查覆盖生命周期/占用/历史/PERSISTING许可、唯一新身份、未知读失败/原动作、WAITING取消回执恢复、确认后读取失败、接收确认边界、REQUEST_IN_PROGRESS与来源拒绝、串行/退休、隐藏晚读、取消与提交竞争后的实际阶段及外来回执/损坏来源。这是端口证据，WAITING成功取消和PERSISTING拒绝不据此宣称新的整体验收已执行。

最终 [189项前端/TS](frontend-2026-10-06T04-07-36-112Z.json)通过，173个输入哈希保持。最终[编译诊断页与实际浏览器/API/SQLite](run-actions-browser-2026-10-06T04-07-27-608Z.json)通过，398个输入哈希保持，preview健康，CLI及自有服务正常关闭（生产服务退出0）。前序187项及首次浏览器通过证据 `frontend-2026-10-06T04-04-46-423Z.json` / `run-actions-browser-2026-10-06T04-04-57-653Z.json` 保留；后续补充来源与取消阶段检查、可见性保护和实际冻结回执/取消时间对比后完成最终复验。本单元未发生失败的冻结验证。

真实浏览器使用生产 create_app/37路由/事务/SQLite，不制造业务成功。为稳定取消边界，**仅此专项**以显式私有 `--hold-review-dispatch` 注入 GuideWorker 子类：REVIEW接受后在正式编排前等待调度屏障，原持久 RUNNING/PREPARING 与占用真实；取消仍通过正式 I17，调用后的实际任务/lease取消及关闭均由生产Worker处理。INITIALIZE/ASK和失败重试仍执行正式编排并因缺模型配置真实 FAILED/CONFIG_INVALID。屏障不是等待问题的业务产出、Provider结果或生产实现替代；一般专项不启用。测试IPC没有公共新路由，数据库限定全新 output/playwright 测试路径，模型环境被剥离。

需求2的真实 ASK Run3首次失败，I18第一次真实202被丢弃，本地UNKNOWN没有先选新Run。查看历史初始化Run2、收起/展开后原操作仍保留；一次观察读取失败未重发，第二次使用原键收到同一新Run4，随后实际采用失败保CONFIRMED。只读重试后真实I16显示Run4 FAILED，接收一次，原Run3完整查询模型逐字不变。真实 REVIEW Run5在调度屏障下保持RUNNING；I17真实200丢失后仍待核实，原键重放确认同一CANCELLED。两项各prepare1/send2，无Body/Content-Type，回执data逐字相同；Run5第一次取消后的实际完整I16与最终I16逐字相同，ended_at/updated_at没有再次改写。

两操作实际接收共2次、完整父级读取16次（其中一次显式失败）、采用3次（含一次显式失败）。需求2只有4条真实运行历史、3条真实消息（初始化/ASK/REVIEW，没有重试复制用户消息）；Current2/v1全文、身份和所有元数据逐字不变。正常关闭持久事实 requirements=2、documents=2、revisions=1、comments=0、guide_runs=5、llm_uses=0。已查看取消状态与真实历史的两张诊断截图；这不代表完整产品页面、根入口构建或全页视觉验收。

后端生产代码未改，730项后端为历史证据，没有无目的重跑。373正式场景、Provider兼容/预算/真实效果及完整根构建仍开放。下一单元读取FE DT-OP01/03/06/09–11/28、范围选择与共同Scope，BE C01/C02/I14/I15及已确认公共B，实施真正发送与范围控制。已检查 `frontend/src/api/walle.ts` 的 CreateGuide.action_type 当前仅 ASK/REVIEW/MODIFY，**遗漏设计明确允许的 INITIALIZE**；下一单元需连同正式I14初始续轮绑定和实网证据修正，当前不把它标为完成。没有遗留自有服务或Provider付费调用。
