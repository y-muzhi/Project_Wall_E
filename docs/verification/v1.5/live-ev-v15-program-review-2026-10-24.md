# V1.5 资源批次v15真实EV程序复核

2026-10-24（Asia/Hong_Kong）。26个独立正常库以SQLite mode=ro读取，逐一校验所有实际计数收据模型／文本／请求摘要、同release、实际usage／gap及正常终态。无新API、业务写入或模型裁判。

EV实际合计：cases=26, Chat=24, root_IDLE=24, input=207872, output=47091, total=254963, cache=139264, parse_SUCCEEDED=22, validation_SUCCEEDED=22, finish_stop=22, counts=28, parse_FAILED=2, validation_NOT_STARTED=2, finish_length=2, root_SUGGESTION_REVIEWING=2。加技术观测1计数／1Chat／输入8408／输出2244／总10652／缓存0后，整批计数29／Chat25，输入216280／输出49335／总265615／缓存139264，均在授权预算，零重试。

| 样本 | 计数批 | Chat | 解析 | 校验／错误 | finish | 主结果 | 进度 | 运行／根状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| laboratory/analysis-local-impact | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| laboratory/analysis-old-new | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| laboratory/analysis-required-over-budget | 2 | 0 | N/A | CONTEXT_LIMIT_EXCEEDED | N/A | N/A | N/A | FAILED／IDLE |
| laboratory/discuss-correction | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| laboratory/discuss-decline | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| laboratory/discuss-initial | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| laboratory/discuss-long-preference | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| laboratory/document-generate | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | APPLIED | COMPLETED／IDLE |
| laboratory/document-local-revise | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | APPLIED | COMPLETED／IDLE |
| laboratory/document-long-specification | 1 | 1 | FAILED | NOT_STARTED | length | NOT_APPLIED | NOT_REQUESTED | COMPLETED／IDLE |
| laboratory/proposals-stale-original | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | NOT_REQUESTED | COMPLETED／SUGGESTION_REVIEWING |
| laboratory/proposals-table-row | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | APPLIED | COMPLETED／IDLE |
| laboratory/proposals-user-edit | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | APPLIED | COMPLETED／IDLE |
| movie/analysis-local-impact | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| movie/analysis-old-new | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| movie/analysis-required-over-budget | 2 | 0 | N/A | CONTEXT_LIMIT_EXCEEDED | N/A | N/A | N/A | FAILED／IDLE |
| movie/discuss-correction | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| movie/discuss-decline | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| movie/discuss-initial | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| movie/discuss-long-preference | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | NOT_REQUESTED | APPLIED | COMPLETED／IDLE |
| movie/document-generate | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | APPLIED | COMPLETED／IDLE |
| movie/document-local-revise | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | APPLIED | COMPLETED／IDLE |
| movie/document-long-specification | 1 | 1 | FAILED | NOT_STARTED | length | NOT_APPLIED | NOT_REQUESTED | COMPLETED／IDLE |
| movie/proposals-stale-original | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | APPLIED | COMPLETED／SUGGESTION_REVIEWING |
| movie/proposals-table-row | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | APPLIED | COMPLETED／IDLE |
| movie/proposals-user-edit | 1 | 1 | SUCCEEDED | SUCCEEDED | stop | APPLIED | APPLIED | COMPLETED／IDLE |

必要全文预计输入候选：laboratory/analysis-required-over-budget=[158950, 158922]; movie/analysis-required-over-budget=[158947, 158919]。各2个不同候选是按规则移除可选历史，不是重试。两长规格实际length／8192，正文NOT_APPLIED；六个候选后处理ACCEPTED／EDITED／TARGET_STALE各两领域PASSED，原审阅占用在陈旧目标时保留。所有GuideRun无RUNNING。

v14此前三项分量拒绝在本次对应样本均validation SUCCEEDED，生成正文／进度和澄清卡片均按实际保存。此为程序校验结果，不代替人工语义通过。所有适用语义仍PENDING HUMAN REVIEW，真实异常负向样本不伪称完整生成成功。

正常证据112文件聚合SHA256=d6c73a4bbc8c98049d34cec887757bd947eb2cfbd311d8071653a73a754ecc92（项目相对POSIX路径排序，路径UTF-8＋文件SHA二进制）。原响应／正文只保留正常库，不复制JSON或原始日志进报告。
