# V2.1默认模型单次兼容观察结果

2026-11-18（Asia/Hong_Kong），独立新授权1 Chat/2必要八项计数/139264 Chat Token、0自动重试；未知/结构拒绝/计数偏差即停止，不继续59条、不含长输出。本次许可已用完，不再发模型或计数请求。

唯一执行session65773，启动器32656/实际102824，启动2026-11-18 16:47:49；现exit1，表示按门槛停止，不重启。源码/冻结清单未在运行中改变。v31 release a76797d1988bf81f518933ae46f571ee13c5b67db5b2de7b94cd9ba6b526bd21，默认v3输入原SHA b96887c785b8d6dcb8206b558c47f1e8bf58ce4a4609faffb1f302a670542b9d。预检60样本/120候选重建一致才读取凭据和发送，唯一数据槽data/v21-ai-compat-03，正常DB/count-audit与[自动报告](ai-compatibility-default-2026-11-18-v3.md)保留。

## 实际结果

| 项目 | 结果 |
| --- | --- |
| 模型请求/必要计数 | 1/1，0重试，call_no=attempt_no=1 |
| 真实输入/输出/合计 | 26483 / 864 / 27347 Token，usage全已知；缓存输入2048 |
| 原system/Wire计数 | 15049 / 1002 |
| 发送前预计（含1024余量） | 17075 |
| 实际输入减两项计数 | 10432，大于1024 |
| 传输及结束 | call_status=SUCCEEDED，finish_reason=stop，SDK确实发送json_schema/strict |
| 实际采用 | 未采用，Run FAILED/CONFIG_INVALID，validation_status=NOT_STARTED |
| 正文/Revision/步骤生命周期/原Closure | PASS，未更改 |
| 其余59条 | NOT_RUN，整个槽遍历LLMUse合计1、计数prepared/finished配对1 |
| 正式AI | 未启用，双人人工未执行 |

真实请求未超139264总Token硬上限，失败是原先文本计数遗漏SDK输出Schema的输入开销，实际usage不满足原framing门槛。不能把10432直接提高为通用固定余量，也不能用字符估算替代Token计数。

自动报告的STRUCTURED_REJECTED是执行器对非已接受调用的通用标签，不等于输出JSON结构非法。事后只读restore_counted、完整OutputDiscuss Schema及basis_ref核对均通过；重复纯validate_collaboration_usage明确报Observed framing exceeds the admitted reserve。没有通过这些离线检查倒填本轮采用、LIVE或效果通过。

## 后续修复及范围

先写[计数补齐迭代](../../iterations/pending/v2.1/WALL-E.结构化输出计数补齐迭代_V_2.1.md)，新资源保留8文本维度，在计数资源中声明第1项包含实际system及SDK输出Schema，保留1024门槛、所有总量限制和旧审计语义；先做离线实现与新冻结，不重用本次单例额度。不改本次v31原资源或v3原清单，不自动降级、补发或放宽验证。

正常用户库/服务未操作，原业务Run1/2没有重放。原始正常调用/计数审计必须保留；未新增测试JSON/日志/截图，没有费用金额估算。
