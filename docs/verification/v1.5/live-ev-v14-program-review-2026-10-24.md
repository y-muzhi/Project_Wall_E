# V1.5 v14真实固定EV程序复核

2026-10-24（Asia/Hong_Kong）。26个正常隔离SQLite均以mode=ro读取；每份最多一次Chat，逐一核对所有计数模型／文本／请求摘要、实际usage及gap、同一release、正常终态。无新真实调用／重试／业务写入／模型裁判。

EV实际合计：cases=26, Chat=24, root_IDLE=24, input=204968, output=50352, total=255320, cache=133760, parse_SUCCEEDED=22, validation_SUCCEEDED=19, finish_stop=22, counts=28, validation_FAILED=3, parse_FAILED=2, validation_NOT_STARTED=2, finish_length=2, root_SUGGESTION_REVIEWING=2。加技术观测1计数／1Chat／输入8287／输出1965／总10252／缓存0，整批实际计数29／Chat25，输入213255／输出52317／总265572／缓存133760；均在授权上限，零重试。

每个必要全文为两个不同候选（移除可选历史后仍超限），不是重试，均0Chat；不能假定每例只有1批。两份陈旧原文样本在TARGET_STALE后保留SUGGESTION_REVIEWING及原审阅批次，不是AI仍在途；其余24根IDLE，所有GuideRun无RUNNING。初次额外核对脚本误按每例1批／全部IDLE断言，已按正式多候选及陈旧批次规则修订，未改产品或原结果。

| 样本 | 计数批 | Chat | 解析 | 校验 | finish | 主结果 | 进度 | 运行／根状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| laboratory/analysis-local-impact | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| laboratory/analysis-old-new | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| laboratory/analysis-required-over-budget | 2 | 0 | N/A | CONTEXT_LIMIT_EXCEEDED | N/A | N/A | N/A | FAILED／IDLE |
| laboratory/discuss-correction | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| laboratory/discuss-decline | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| laboratory/discuss-initial | 1 | 1 | SUCCEEDED | FAILED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| laboratory/discuss-long-preference | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| laboratory/document-generate | 1 | 1 | SUCCEEDED | FAILED | stop | APPLIED | REJECTED | COMPLETED／IDLE |
| laboratory/document-local-revise | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | APPLIED | COMPLETED／IDLE |
| laboratory/document-long-specification | 1 | 1 | FAILED | NOT_STARTED | length | NOT_APPLIED | NOT_REQUESTED | COMPLETED／IDLE |
| laboratory/proposals-stale-original | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | NOT_REQUESTED | COMPLETED／SUGGESTION_REVIEWING |
| laboratory/proposals-table-row | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | NOT_REQUESTED | COMPLETED／IDLE |
| laboratory/proposals-user-edit | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | APPLIED | COMPLETED／IDLE |
| movie/analysis-local-impact | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| movie/analysis-old-new | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| movie/analysis-required-over-budget | 2 | 0 | N/A | CONTEXT_LIMIT_EXCEEDED | N/A | N/A | N/A | FAILED／IDLE |
| movie/discuss-correction | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| movie/discuss-decline | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| movie/discuss-initial | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| movie/discuss-long-preference | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| movie/document-generate | 1 | 1 | SUCCEEDED | FAILED | stop | APPLIED | REJECTED | COMPLETED／IDLE |
| movie/document-local-revise | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | APPLIED | COMPLETED／IDLE |
| movie/document-long-specification | 1 | 1 | FAILED | NOT_STARTED | length | NOT_APPLIED | NOT_REQUESTED | COMPLETED／IDLE |
| movie/proposals-stale-original | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | NOT_REQUESTED | COMPLETED／SUGGESTION_REVIEWING |
| movie/proposals-table-row | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | APPLIED | COMPLETED／IDLE |
| movie/proposals-user-edit | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | NOT_REQUESTED | COMPLETED／IDLE |

两份必要全文实际候选预计输入：laboratory/analysis-required-over-budget=[158829, 158801]; movie/analysis-required-over-budget=[158826, 158798]。两份长规格均实际length／8192输出，parse FAILED、正文NOT_APPLIED，无半写、不补调用。三种候选后处理每领域均由原执行器记录实际PASSED（正常ACCEPTED、EDITED及TARGET_STALE），不把此程序结果称人工语义通过。

movie/document-generate主结果APPLIED，进度因把自由文本当USER_DECISION被原保护拒绝，原validation FAILED保留。除此以外的差异按上表实际状态，不删除失败或以平均分抵消。所有语义维度仍PENDING HUMAN REVIEW；原正文／原始模型返回只留正常数据库和审计，不复制进此Markdown。
