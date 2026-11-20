# V2.1结构化输出计数补齐离线验证

日期2026-11-18（Asia/Hong_Kong），工作区codex/v2.1-design-review，HEAD a0f40592702cb702ed928849ac540479c22c224f；保留既有改动，未提交/推送或合并正式设计。依据[独立迭代](../../iterations/pending/v2.1/WALL-E.结构化输出计数补齐迭代_V_2.1.md)与[本次单例实际结果](ai-compatibility-default-2026-11-18-v3-summary.md)。

## 实际失败与修复

本次真实授权只使用1 Chat/1批必要计数、0重试，输入26483/输出864/总27347，旧文本计数15049+1002，差10432>1024，未超139264总硬上限。供应方接受SDK json_schema/strict，完整OutputDiscuss与basis_ref事后只读核对通过；实际usage门槛失败后未采用，原正文/Revision/步骤/Closure保护PASS，余59 NOT_RUN。新真实额度尚未授权，没有用剩余计数批数补测或自动发送第二次。

新资源v33/v34的CountingDefinition.system_text=system_plus_output_schema_v1明确第一项计数文本：实际system + 一个换行 + SDK response_format.json_schema.schema的compact JSON；其余7项及1024门槛/全部预算不变。第一项的SHA不再等于实际system消息SHA：评测Counter用完整八文本SHA绑定全部计数文本，Gateway仍按原System/完整SDK请求/私有依据等冻结行核对，不能换请求。旧字段不存在时仍按旧system计算；非DISCUSS无SDK Schema时仍是原system。未知计数策略或冻结摘要不符失败关闭。

实现：backend/app/infrastructure/collaboration_format.py/counting_system_text、guide/collaboration_context.py/texts、formation/resource_schema.py、资源加载器；tools/build-formation-resources.py、formation_evaluation.py、formation_evaluation_execution.py。没有新增Chat message、修改发给模型的正文或Schema，没有放宽实际usage检查/原framing门槛，没有改固定构建源或DDL。private admission的counted_system_tokens按所绑定计数资源表示第1项合计，新旧语义由冻结system_text/ref/digest区分，不能用新策略重解释旧审计。

## 固定资源及输入

| 配置 | manifest SHA256 | release SHA256 |
| --- | --- | --- |
| 默认v33 | cebba2a6deb7a6084584272624ad21ab29760d369a9f8449e84679b22b6f3c24 | ecc667d6b3a61af5db4ef27b8d93b4eb3ecbba95772c0c1b3eb83f3aaaa629c3 |
| 长输出v34 | a3ff49a7787d8f81de2827152fff45896f3c86e84c9b50bef6b3b804169b1f26 | f3fa6a9f542f600c42102b0e8d3f709087669ead339ad3a00f914bf915caa6d9 |

Prompt仍v10、输出Schema/实际SDK内容保持，Wire/layout与Schema210-r7/core-r54不变。均OFFLINE_READY，未导入旧release的LIVE。

- [默认v4清单](evaluation-inputs-default-2026-11-18-v4.md)：原SHA ae62fd4ade0e1c16e500b4fe7709acb5856cc4f3ce0f4619466e5df40b53515a，cohort aa3940680468b36c195e5f110bf1f66c1e0c3db864c2630053fead0d23e8d346。
- [长组v4清单](evaluation-inputs-long-2026-11-18-v4.md)：原SHA ac136f3f8b5fd4d7086f88093eab147a40a13e5f9316fe4acdcb23e7a9695da3，cohort c590d0e478dd865cd01ed123659218f7508912a4482189d2a28552d842303fec。
- 共同Recipe bde482773e25faf476d4e20a703bb7a5587914936b35fb3b72e1ce38702acaa1。各60样本/120候选生成及--verify完整重建全部一致，Tokenization=0/Chat=0/cleanup=True。
- 新六份v4准备attempts/reviewer各60行，均NOT_RUN/PENDING/UNASSIGNED。v3真实报告/尝试及数据槽保留原样，不能当v4实际效果。

## 检查结果

Windows/Python3.14，固定SQLite，tools/python-v20.py → tools/quality_python.py，外网及正常data/.env有程序隔离，TemporaryDirectory在成功/失败后自动清理。未新增原始测试JSON、日志或截图。

先跑计数/运输/预算专项36 passed、3 subtests passed，51.62秒；随后完整受影响组session59099 exit0：**98 passed、16 subtests passed，389.18秒，cleanup=True**。36项与完整组有重叠，不累加独立项。1条既有Starlette/httpx弃用提示，不是失败。

完整组文件：tools/tests/test_v21_execution_budget.py；backend/tests/formation/test_v21_model_transport.py、test_v21_resource_release.py；tools/tests/test_v21_evaluation.py、test_v21_evaluation_transport.py；backend/tests/formation/test_v21_observation_driver.py、test_v21_evaluation_bootstrap.py、test_v21_execution_allowance.py、test_v21_live_fix_examples.py。参数-q -p no:cacheprovider --tb=short --basetemp <本轮临时目录>，通过项目quality环境运行，未使用用户库或真实供应方。

覆盖新第1计数文本/实际SDK Schema逐字绑定、原8项维度、SDK不新增消息、未知策略/摘要失配拒绝、新旧SDK请求字节一致、旧v31仍计旧system；资源/精确历史选择、C01/C07及技术观察/后续准入、五类输出/负例、额度/首拒停止/只发一次/余59保留。实际usage门槛仍须当前真实计数与Chat证明，本组替身不能作为供应方兼容。

另只读还原两轮-01/-02及本次-03的全部121条真实原请求，按原v27/v29/v31资源restore_counted一致，原system计数文本及SDK字节未变。没有修改、重发或重标旧结果。8枚原设计/Schema/旧资源pin与v27—v34全部资源文件字节核对通过。589个app格式、改动F/I/B/format、diff检查通过，默认执行器metadata匹配且0凭据/0调用，清理工具dry-run JSON=0/screenshots=0。

## 当前边界与下一步

正常库只读需求1/文档1/LLMUse0/在途0，原Run1/2仍FAILED；8001/PID460396、5174/PID311404保持，原8000/5173不操作。准备AI启动脚本未执行，正式AI未启用；没有页面修改/浏览器新结论，未提交推送。

新计数规则尚未真实兼容，不能宣称漏计开销已通过供应方验证。建议另定默认v33单例1 Chat/2必要计数/139264总Token、0自动重试，未知/结构拒绝/计数偏差/预算不符立即停止，不继续59条、不含长输出。拟新槽data/v21-ai-compat-04、报告ai-compatibility-default-2026-11-18-v4.md，当前不存在且尚无许可。成功仍不能替代完整60样本效果或双人独立人工评价。目标尚未完成。
