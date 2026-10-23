# V1.5验收证据核对

2026-10-23阶段核对；以正式后端A15、前端8章为准，本表只映射实际证据，不定义新规格。完整后端联合检查尚未通过；下述专项证据不等于整版验收。真实模型全部待新授权。

| 场景 | 现有程序证据 | 实际浏览器证据 | 剩余边界 |
| --- | --- | --- | --- |
| A15-01 零文档创建 | foundation／service／双业务HTTP | 三字段创建后零文档／运行／调用 | 无真实供应方依赖 |
| A15-02 长期讨论 | context跨10条窗口／pending、progress、双业务讨论 | 电影讨论及建议 | EV-DISCUSS真实语义效果未执行 |
| A15-03 明确生成 | acceptance／execution／cards／双业务 | 出稿卡片明确接受后直接V1 | 真实生成质量未执行 |
| A15-04 明确修订 | local_revision／execution／双业务BLOCK | 未执行局部AI修订UI | SECTION／SELECTION程序专项不冒充UI |
| A15-05 候选同步 | batches含固定A／B、精确表格行、EDITED；comment_guides | 候选EDITED及ACCEPTED完成V2／V3 | 跨文档表格与评论UI尚未执行 |
| A15-06 分析及预算 | counting／context／model_calls／双业务COMPARE与REVIEW | 请求8分区及预算展示 | 超限UI、分析新UI和EV-ANALYSIS未执行 |
| A15-07 确认及历史 | documents／history／editing／execution／batches | V1确认，V2—V4未确认，旧确认保留 | 历史恢复UI未执行 |
| A15-08 人工五态 | foundation25组合／在途关闭、双业务CLOSED | 已显示五态选择，未逐项切换 | 全前端355项含五态独立权限 |
| A15-09 并发取消恢复 | acceptance／execution／recovery／worker租约竞争 | 原批次key重放无重复版本 | 双标签页原生竞态未执行 |
| A15-10 人工编辑 | editing／history；manual／autosave前端 | 本地恢复、自动保存、完成V4、读B编辑A、取消、窄窗 | 断网及历史回退组合UI未全部执行 |
| A15-11 卡片程序 | cards／fact_confirmation、前端整组及来源 | 出稿卡片及正式回答基本路径 | PHASE／FACT程序动作UI未执行 |
| A15-12 去重及只读 | context／counting／来源读取 | 来源展开、请求详情查看不增加调用 | 长上下文语义效果未执行 |
| A15-13 异常输出用量 | execution／counting原文／独立增量 | 历史失败读取基本检查 | 供应方异常total原值／SUSPENDED待补；真实截断未执行 |
| A15-14 原能力复用 | 七类根／原owner／HTTP；38前端绑定＋3服务端保留路由 | 不适用 | 继续静态核对旧未调用分支 |
| A15-15 新数据 | schema150／新库拒绝旧库／Worker启动关闭 | 独立临时新库 | 未创建／迁移用户业务库 |
| A15-16 布局 | detail-layout／reading-position／355前端专项 | 1024／1100／1280／1440／1920、1000保存保护 | 完整焦点／长表格／独立滚动组合未逐项执行 |

浏览器过程、临时进程归属和清理见recovery-browser-2026-10-23.md；最新读取／前端检查见contracts-frontend-2026-10-23.md。EV-DISCUSS／DOCUMENT／PROPOSALS／ANALYSIS均仍待执行；资源OFFLINE_READY不放行普通真实请求。

2026-10-23追加：资源准入／隔离观测链路已接并离线专项验证；完整24文件156项通过。阶段卡片PROGRAM确认、历史REVIEW完整Analysis展示及检查标签已有browser-phase-analysis记录；实际历史消息详情500已按保存alias修复，4项HTTP／读取专项通过。上述不扩展为事实确认／全浏览器或真实EV通过。
