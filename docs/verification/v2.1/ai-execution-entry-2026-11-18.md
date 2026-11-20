# V2.1真实准入执行入口

日期：2026-11-18。当前用户已明确授权默认deepseek-v2/v27：最多60 Chat、120批必要八项计数、Chat合计8355840 Token、0重试；结果不明确即停止。单次输入131072/输出8192/总139264。不包含长输出组，不重发用户Run1。

## 实现及已执行检查

新入口tools/run-v21-evaluation.py与formation_evaluation_execution.py：固定默认清单原始摘要，完整重建60样本120候选后才读凭据；发送前再次核对Profile、候选及私有basis/实际请求摘要、源码和清单字节。每次计数/Chat先在Markdown flush/fsync记录INTENT，占用全局次数与Chat最坏Token额度，不退款。输出新目录禁止重复启动，异常/usage不明停止。首例原私有Observation，后续只有本轮真实源证据可导入隔离库。不会自行导入用户库、改变全局LIVE或更新服务。

检查入口：固定SQLite tools/python-v20.py＋tools/quality_python.py，父级quality_gate.environment与TemporaryDirectory，禁止外网/本地密钥/正常data。范围为tools/tests/test_v21_execution_budget.py和backend/tests/formation/test_v21_execution_allowance.py。

最新11项通过，25.15秒，1条既有Starlette/httpx弃用告警；临时目录清理通过。覆盖：计数/Chat前持久认领、错误候选/未计数不发送、计数120/Chat60/Token上限、每样本一次、异常不退款不补发、坏usage回归正常审计并停后续、源码变更拦截；真实Schema210 C01/C07以离线Counter/Gateway核对首例观察→保存证据→普通第二例，失败停止及正文/Revision/步骤/Closure保持。没有真实供应方证明。

初轮因单元夹具wire不是JSON，9项在setUp拒绝、2项实际链路通过；改为合法空对象后11项通过25.04秒。再补全全局Chat60检查及执行期间manifest字节核对后，最新11项通过25.15秒。一次受限入口的asyncio本地通信卡住，只停止核实的检查Python进程，前后端未操作；切回已验证隔离入口。一次自动审批超时未启动检查，按工具许可重试一次后通过，无剩余审批阻塞。

四个新源码Ruff F/I/B及format通过；默认入口元数据校对通过，凭据读取/供应方调用均0。输入配方未改变。旧V1.5脚本未用于本轮。

## 本轮真实执行唯一槽

预定data/v21-ai-admission-20261118-01及docs/verification/v2.1/ai-admission-default-2026-11-18.md；真实状态以该报告及正常隔离DB/计数审计为准。执行命令明确给定--execute、--allow-chat-calls 60、--allow-count-batches 120、--max-total-tokens 8355840及现有绝对凭据路径。目录一旦认领不能再用；未知时先读正常审计，不重发。

报告中的正常DB/count-audit为实际应用调用证据，必须保留。其余只留派生Markdown，不另存原始测试JSON/日志/截图。人工评价另列两份PENDING，不由本代理代填或自动授予正式AI启用。
