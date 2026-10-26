# V1.5 v12真实有限批次核对与离线诊断

2026-10-24（Asia/Hong_Kong）。26固定样本已单次执行结束，退出0仅表示执行器完成，不代表产品／EV通过。全部原正常SQLite／计数审计保留；本记录以mode=ro事务读取，不改原结果、不重计数／Chat，无模型裁判。

## 实际用量与程序状态

Chat=24；cache=119808；count_batches=26；counts_FAILED=2；counts_SUCCEEDED=24；finish_stop=24；input=176737；output=32893；primary_APPLIED=4；primary_NOT_APPLIED=8；primary_NOT_REQUESTED=12；primary_None=2；progress_APPLIED=9；progress_NOT_REQUESTED=6；progress_None=2；progress_REJECTED=9；total=209630；validation_FAILED=14；validation_SUCCEEDED=10。

加技术观测共计数27批、Chat25次，实际Chat输入184149、输出35550、总量219699、缓存123904。所有逐次及全局预算内，零重试；所有Chat finish=stop。各独占槽均结束，无未知在途。

| 样本 | 运行 | 校验 | 正文／进度 | 输入／输出／总token |
| --- | --- | --- | --- | --- |
| laboratory/analysis-local-impact | COMPLETED | SUCCEEDED | NOT_REQUESTED／NOT_REQUESTED | 3977/1273/5250 |
| laboratory/analysis-old-new | COMPLETED | FAILED | NOT_REQUESTED／REJECTED | 4371/1646/6017 |
| laboratory/analysis-required-over-budget | FAILED | 无Chat | None／None | — |
| laboratory/discuss-correction | COMPLETED | SUCCEEDED | NOT_REQUESTED／APPLIED | 7435/1772/9207 |
| laboratory/discuss-decline | COMPLETED | SUCCEEDED | NOT_REQUESTED／APPLIED | 7546/2231/9777 |
| laboratory/discuss-initial | COMPLETED | SUCCEEDED | NOT_REQUESTED／APPLIED | 7420/2110/9530 |
| laboratory/discuss-long-preference | COMPLETED | FAILED | NOT_REQUESTED／REJECTED | 8144/2167/10311 |
| laboratory/document-generate | COMPLETED | FAILED | APPLIED／REJECTED | 3969/1410/5379 |
| laboratory/document-local-revise | COMPLETED | FAILED | APPLIED／REJECTED | 4427/404/4831 |
| laboratory/document-long-specification | COMPLETED | SUCCEEDED | NOT_APPLIED／APPLIED | 25315/1592/26907 |
| laboratory/proposals-stale-original | COMPLETED | FAILED | NOT_APPLIED／NOT_REQUESTED | 5268/498/5766 |
| laboratory/proposals-table-row | COMPLETED | FAILED | NOT_APPLIED／NOT_REQUESTED | 5268/667/5935 |
| laboratory/proposals-user-edit | COMPLETED | FAILED | NOT_APPLIED／REJECTED | 5268/1068/6336 |
| movie/analysis-local-impact | COMPLETED | FAILED | NOT_REQUESTED／NOT_REQUESTED | 3970/1316/5286 |
| movie/analysis-old-new | COMPLETED | FAILED | NOT_REQUESTED／REJECTED | 4360/1354/5714 |
| movie/analysis-required-over-budget | FAILED | 无Chat | None／None | — |
| movie/discuss-correction | COMPLETED | SUCCEEDED | NOT_REQUESTED／APPLIED | 7433/1359/8792 |
| movie/discuss-decline | COMPLETED | SUCCEEDED | NOT_REQUESTED／APPLIED | 7543/2265/9808 |
| movie/discuss-initial | COMPLETED | SUCCEEDED | NOT_REQUESTED／APPLIED | 7417/1972/9389 |
| movie/discuss-long-preference | COMPLETED | SUCCEEDED | NOT_REQUESTED／APPLIED | 8137/1318/9455 |
| movie/document-generate | COMPLETED | FAILED | APPLIED／REJECTED | 3960/1907/5867 |
| movie/document-local-revise | COMPLETED | FAILED | APPLIED／REJECTED | 4419/350/4769 |
| movie/document-long-specification | COMPLETED | SUCCEEDED | NOT_APPLIED／APPLIED | 25310/1967/27277 |
| movie/proposals-stale-original | COMPLETED | FAILED | NOT_APPLIED／NOT_REQUESTED | 5260/620/5880 |
| movie/proposals-table-row | COMPLETED | FAILED | NOT_APPLIED／REJECTED | 5260/1022/6282 |
| movie/proposals-user-edit | COMPLETED | FAILED | NOT_APPLIED／NOT_REQUESTED | 5260/605/5865 |

## 首次结果问题定位

### laboratory/analysis-old-new

纯进度重放：AI proposal cannot become a user decision。

### laboratory/analysis-required-over-budget

计数FAILED／CONFIG_INVALID，未保存精确计数；供应方状态／容量等根因无已存证据，不能推断超预算通过。

### laboratory/discuss-long-preference

纯进度重放：AI proposal cannot become a user decision。

### laboratory/document-generate

纯进度重放：AI proposal cannot become a user decision。

### laboratory/document-local-revise

纯进度重放：Discussion delta failed structural or reference validation。

### laboratory/document-long-specification

实际ANALYSIS／NEED_EVIDENCE，无正文；finish=stop，未触达真实截断。

### laboratory/proposals-stale-original

仅预检未执行commit：TargetStale／表格行原文已变化。

### laboratory/proposals-table-row

仅预检未执行commit：TargetStale／表格行原文已变化。

### laboratory/proposals-user-edit

纯进度重放：AI proposal cannot become a user decision；仅预检未执行commit：TargetStale／表格行原文已变化。

### movie/analysis-local-impact

已携带章节导航引用未注册为来源：d1v2s3。

### movie/analysis-old-new

纯进度重放：AI proposal cannot become a user decision。

### movie/analysis-required-over-budget

计数FAILED／CONFIG_INVALID，未保存精确计数；供应方状态／容量等根因无已存证据，不能推断超预算通过。

### movie/document-generate

纯进度重放：AI proposal cannot become a user decision。

### movie/document-local-revise

纯进度重放：AI proposal cannot become a user decision。

### movie/document-long-specification

实际ANALYSIS／NEED_EVIDENCE，无正文；finish=stop，未触达真实截断。

### movie/proposals-stale-original

仅预检未执行commit：TargetStale／表格行原文已变化。

### movie/proposals-table-row

纯进度重放：AI proposal cannot become a user decision；仅预检未执行commit：TargetStale／表格行原文已变化。

### movie/proposals-user-edit

仅预检未执行commit：TargetStale／表格行原文已变化。

## 边界及后续

四份明确生成／局部修订实际APPLIED，进度失败不撤销有效正文；六份表格候选全部NOT_APPLIED，未建立批次，因此ACCEPTED／EDITED／陈旧原文三个后处理未触达，不能记真实验证通过。两份长规格实际以NEED_EVIDENCE返回，未触达真实截断；两份必要全文计数失败、0Chat，不能称实测超预算拒绝。人工语义逐项尚待审阅，不能用10份结构成功平均抵消其余失败。

本次有限许可已消耗并结束；不以未用计数额度续跑，不自动换版本／补样本。下一步在已授权离线范围修复实际来源解析及模型可见规则，保留v12原资源／输入／失败，针对受影响单元检查。修复后任何真实重测必须另获新明确许可。用户业务库／服务均未更新。
