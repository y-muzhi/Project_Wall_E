# D-015 正式 AI 可用性专项记录

日期：2026-10-08。基于 master `087c309` 的本批改动。用户已确认实用预算方案、限定一轮观测及 AI 离线专项；批准原文、边界和精确输入身份见 [D-015 采用记录](../deepseek-availability-adoption-v1.json)。不恢复完整验收或浏览器/Windows 崩溃专项。

## 已完成的检查

首批命令：

```powershell
.venv\Scripts\python.exe -X utf8 -m unittest backend.tests.infrastructure.test_deepseek_availability backend.tests.infrastructure.test_deepseek_adoption backend.tests.infrastructure.test_framing_probe
```

结果：41 项通过，65.838 秒。覆盖旧配置/审计恢复、新旧模型计划授权隔离、精确计数、本机 TCP/SQLite 的 v3 编排与 C07、实际用量超限不解析/不采用/不重试、产出前独立用量复核、中断名额不可重跑及 Markdown 保留。使用的是明确本机受控模型与合成计数，不能当作供应方效果证明。该轮之后又补了用量失败的独立审计标记和两个 DeepSeek 六任务观测用例，进入接续专项。

真实调用命令（本轮已结束，禁止重跑）：

```powershell
.venv\Scripts\python.exe -X utf8 tools/deepseek-observation.py --execute --authorized-plan-sha256 13c5657288a54ffad593a6e66d6097d5273af3e0771d7f429eecc8eec41a4e7a
```

实际结果：6 次计数＋6 次 Chat 全部成功，0 重试。六个精确模型响应、usage、分项/总预算与完整冻结输出 Schema 均通过；各样本封装差值为 3 token。Chat 实际输入合计 30,067 token，实际输出合计 4,034 token；不据此估算费用。逐任务结果见 [唯一执行记录](deepseek-observation-13c5657288a54ffad593a6e66d6097d5273af3e0771d7f429eecc8eec41a4e7a.md)。本轮许可已经用完，没有正常业务库访问或真实 C07 采用，没有新增第二轮调用。有限样本不证明全输入封装上界。

## 接续专项

使用 `unittest` 标准输出运行以下模块，只把摘要记入本文件；不写结果 JSON、截图或原始日志。仅将 asyncio 慢回调警告调到 ERROR，unittest 失败与异常仍正常输出。

```text
backend.tests.infrastructure.test_deepseek_availability
backend.tests.infrastructure.test_model_gateway
backend.tests.infrastructure.test_tokenization
backend.tests.infrastructure.test_model_profile_audit_data
backend.tests.infrastructure.test_counting_journal
backend.tests.infrastructure.test_audit_repository
backend.tests.guide.test_counted_context
backend.tests.guide.test_counted_orchestrator
backend.tests.guide.test_counted_worker
backend.tests.guide.test_orchestrator
backend.tests.guide.test_trusted_output
backend.tests.guide.test_result_persistence
backend.tests.test_service
```

结果：148 项通过，184.366 秒，退出码 0。包含新增用量失败审计标记、全部六种 DeepSeek Schema 的本机 TCP 观测与首失败停止、默认服务生命周期；临时测试资源随清理释放。这一数字是本次模块集合的执行用例数，与首批 41 项存在交集，不相加为独立覆盖数。

六任务真实观测及离线专项满足 D-015 准入条件，接续生成独立固定准入资源。策略本身的 `production_enabled=false` 表示它不能单独授权调用；v3 开放由另一个经代码 SHA-256 固定的 `admission.json` 决定，旧 v1/v2 继续关闭，`provider_compatibility_proved` 始终 false。

未覆盖：真实模型业务采用/完整事实效果评估、浏览器、新增前端静态修补验证、全项目回归及 373 项验收。测试使用临时目录，计数审计 JSON 随各用例清理；真实观测原始响应仅在内存中处理。正常业务审计的保留规则没有变更。
