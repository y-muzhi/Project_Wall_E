# V1.5 v14技术及26EV实际汇总

2026-10-24（Asia/Hong_Kong）。本批授权已完整结束，不重复或续用未花费上限。原技术正常库及26独立EV正常库／审计保留，用户库／服务／Git未修改，无模型裁判。

技术：1计数／1Chat，LIVE_VERIFIED，parse／validation成功，progress APPLIED；输入8287／输出1965／总10252／缓存0／gap3。

EV：26固定样本，28计数（全部成功）／24Chat；22份stop中19 validation成功、3失败，另2份真实length／8192输出、parse FAILED且正文NOT_APPLIED。两份必要全文经2个不同候选计数仍超131072，0Chat；6个表格行后处理实际PASSED。共24根IDLE，2个陈旧原文样本保留SUGGESTION_REVIEWING，所有GuideRun无RUNNING。

整批合计29计数／25Chat，实际输入213255／输出52317／总265572／缓存133760，所有用量及framing在授权硬限内，零重试、无自动修复。剩余上限不代表可再执行。

保留的三项实际失败：

- laboratory/discuss-initial：CLARIFICATION卡片省略必填action_payload=null，卡片拒绝，已验证进度仍APPLIED，原文保留。
- laboratory/document-generate：进度把自由文本来源标为USER_DECISION，原来源保护拒绝，正文独立APPLIED。
- movie/document-generate：进度把自由文本来源标为USER_DECISION，原来源保护拒绝，正文独立APPLIED。

两份长规格真实截断与两份超预算否决是负向边界实际证据，不伪称完整生成成功。19校验成功也不代替人工语义评测：所有EV-DISCUSS／DOCUMENT／PROPOSALS／ANALYSIS适用指标仍按正式BE8.3逐项审阅，不宣布整版验收通过。

正常证据112个SQLite／审计／准入JSON聚合SHA256=ee4f872ee31e81f832ec16546dae3b7980f083a51dee8bd8f3bbde7b416f3d0b（项目相对POSIX路径排序，路径UTF-8＋文件SHA二进制）。原始正文／响应只留正常数据库及审计；Markdown简要记录实际范围，详细程序表见live-ev-v14-program-review-2026-10-24.md、原逐项记录live-ev-v14-once-2026-10-24.md。当前资源v14冻结文件仍OFFLINE_READY，技术LIVE为隔离库的正常准入证据，未导入用户库。
