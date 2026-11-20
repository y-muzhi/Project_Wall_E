# V2.1默认AI第二轮真实复验结果

日期：2026-11-18。当前授权为修复后的默认deepseek-v2/v29：最多60 Chat、120批必要八项计数、Chat总上限8355840 Token，0自动重试、UNKNOWN停止；不含长输出。本轮已结束，60个Chat槽均已消耗，不能继续借本轮许可发请求。

## 实际结果

| 任务 | 程序接受 | 拒绝 |
| --- | --- | --- |
| 普通讨论 | 12/12 | 0/12 |
| 写入提案 | 11/12 | 1/12 |
| 路线提案 | 5/12 | 7/12 |
| 关联复核 | 9/12 | 3/12 |
| 充分性评估 | 0/12 | 12/12 |
| 合计 | 37/60 | 23/60 |

实际60 Chat、60/120计数批次，每样本call_no=attempt_no=1，0重试。输入946518、输出65395，合计1011913 Chat Token；usage全已知，framing gap均3，无超限/未知结果。60个正文、Revision、步骤生命周期及原Closure保护核对PASS。Chat预算最坏占用8355840 Token，不用实际差额退款补发；没有费用金额估算。

全部12个写入任务返回STAGED_WRITE，11个通过；全部12个路线任务返回FORMATION_PATH_CHANGE，5个通过。程序接受不等于独立人工可用性评价；双人仍PENDING，未达到正式启用标准。两轮输入不同（任务优先级/枚举/依赖方向已修），不可把37对36宣称同输入模型能力提升。

## 原始证据与新定位

- [本轮逐样本](ai-admission-default-2026-11-18-v2.md)、[实际尝试](ai-admission-default-2026-11-18-v2-attempts.md)；正常隔离DB/count-audit在data/v21-ai-admission-20261118-02，必须保留，不能重跑或删除。
- [本轮只读定位](ai-revalidation-v2-diagnosis-2026-11-18.md)：两种ADD_STEP的嵌套temp_ref/temp_result_ref混用；document_refs把完整文档别名当区块别名，评估任务尤为集中。程序按原合同拒绝，没有自动补字段或展开全文放行。
- 独立评价为ai-admission-default-2026-11-18-v2-reviewer-a/b.md，均未指定真实评审者，未代填结果。
- 源码核对发现ModelProfile.request的普通协作请求没有response_format，Output Schema目前只在system提示词描述；testing_request才设置json_object。不能把“system里包含Schema”称为接口已启用严格结构化输出。

## 后续方向与边界

用户目标仍是先修复再验收、达标后启用。考虑将新资源的输出合同绑定到供应方response_format.json_schema/strict；仍保留本地完整Schema及来源/权限/事务校验。只对新release生效，旧两轮请求体及历史还原保持原字节；不修改v29/v30或本轮冻结清单。先完成离线实现/检查，再单独明确真实兼容调用上限，不擅自再发一次。

接口支持语法、当前模型支持及输入Token/framing兼容性必须分别核对。官方资料只提供实现依据，不是本项目已成功调用证明；尤其不能假定附加schema不计输入Token，现有1024 framing余量仍须真实验证。程序不会在不兼容后静默降级、补发或调大预算。
