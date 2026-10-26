# WALL-E V1.5 计数字节容量与负向收据实施修复

2026-10-24。正式前后端1.0／EFFECTIVE基线的B7兼容修复，不修改模型Prompt／Schema／八段布局或Chat预算。

原因：新独占结构兼容诊断实际1批Tokenization／HTTP400、0Chat。正常私有错误说明确认当前北京端点DeepSeek模型单批text UTF-8合计上限800000，实际1074366；离线重算一致。JSON请求体1092341字节是另一指标，不能用来解释此阈值。仅本次证据成立，旧v12失败原因不改写；报告不复制原错误说明。原许可已结束。

最终规则已合入正式BE AI-RESOURCE第7项：

- 特定已验证模型在网络及额度消耗之前检查UTF-8总字节；本地超限PROVIDER_INPUT_LIMIT、无HTTP状态、0计数发送／0Chat，正常失败审计及运行释放仍执行。
- 原4MiB持久审计不扩大。计数响应最多8MiB内存读取并完整校验数组；过大原始收据只能留下固定精确事实及规范响应摘要，用于超预算否决。预算内候选无完整原始收据一律停止；重放及准入同样执行，不能用摘要放行Chat。
- 旧8000行固定输入生成器以原始字节保留在sources/v1.5（SHA256 6b0de89db48479ef770d6cbc9d4df00a10ff0f748548359f8c72402d4066bdd3）。新计划固定4000行，未声称真实Token超限；需新授权后实际计数。旧正常库及失败结果保留。

实现位置：infrastructure/tokenization.py／counting_journal.py／collaboration_observation.py、guide/collaboration_counting.py／collaboration_execution.py／orchestrator.py、tools/prepare-v15-evaluation.py／run-v15-evaluation.py／count-v15-evaluation-once.py及相关专项。优先复用TokenCounts、restore_measurement、measurement_summary及原失败／取消路径，不新增业务表、HTTP字段或平行计数服务。

最终检查：11文件扩大联合87 passed／1 failed／24子场景（478.72秒），唯一失败为私有计数fixture仍按旧长度识别HIGH；改为识别固定来源标记，生产代码不变。该项含完整26输入及新增实际4—8MiB数组loopback、正常编排本地超限释放3 passed（151.02秒）。模型设计源1 passed，全部v9—v13资源与原108正常证据字节核对通过。完整命令及边界见verification/v1.5/count-byte-capacity-offline-2026-10-24.md；不声称完整11文件再次重跑。真实新输入计数、v13技术Chat／EV及人工语义审阅未执行；无用户库／用户服务／Git写操作。
