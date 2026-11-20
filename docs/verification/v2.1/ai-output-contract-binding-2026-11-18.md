# V2.1输出合同接口绑定修复与离线复核

日期：2026-11-18（Asia/Hong_Kong）。工作区codex/v2.1-design-review，HEAD a0f40592702cb702ed928849ac540479c22c224f，保留既有脏工作区；未提交/推送，正式前后端文档未合并。接续[第二轮实际结果](ai-revalidation-v2-summary-2026-11-18.md)及[独立迭代](../../iterations/pending/v2.1/WALL-E.输出合同接口绑定修复迭代_V_2.1.md)。

## 改动与不变量

- 新资源v31/v32、Prompt v10，默认2.1入口选择新组，旧v27—v30全部原字节及精确历史选择保留。新release.model_transport仅对DISCUSS附加response_format.json_schema/strict；其他操作与旧release请求保持原格式。模型、温度、输出上限、原8文本和1024余量不变。
- FormationBlockAliasRef限定真实扁平区块别名d42v2b12，document_refs单独引用此类型；通用source_refs不收紧为区块。Prompt完整区分普通ADD_STEP.temp_ref/expected_results[].temp_ref与路线temp_step_ref/expected_results[].temp_result_ref。
- collaboration_format从冻结Canonical.resources中的release和Output Schema取摘要核对后的原文；只以实际Wire当前目标Revision的已发送块做枚举，空块评估覆盖固定[]、移除不可执行的ASSOCIATE_CONTENT分支。不扩读数据库或添加隐藏材料，不把ContextBasis发给模型。
- 供应方投影按明确语法白名单保留类型/属性/required/enum/const/本地引用等，未知语法失败关闭。范围/长度/模式/条件等仍由本地完整权威Schema校验。去掉互斥pattern后，原oneOf在语法投影中用anyOf，避免两个字符串分支重叠导致合法身份无法满足；程序端仍执行原oneOf与全部语义/权限/事务校验。未修改D-011原始完整Schema派生算法。
- SDK完整请求包含投影Schema并保存正常审计，Context恢复从冻结资源重建相同请求。没有自动修复返回、弱化本地合同、静默退回旧格式或补发。
- 执行器仅接受独立明确的1 Chat/2计数/139264 Token观察，或60/120/8355840整组额度；在I/O前认领且无退款重试。首个明确拒绝/失败/保护破坏即停止，仍保留60分母及NOT_RUN；单次观察结束标OBSERVATION_FINISHED，不能记整组验收或启用。

实际源码：backend/app/formation/resource_schema.py、guide/collaboration_context.py、infrastructure/collaboration_format.py、model_profile.py、collaboration_resources.py、resources.py；tools/build-formation-resources.py、formation_evaluation.py、formation_evaluation_execution.py。未修改固定构建源collaboration_admission.py或ai-service.py，Schema210/db21-r7/core-r54保持。

## 资源与固定输入

| 配置 | 资源manifest SHA256 | release SHA256 |
| --- | --- | --- |
| 默认v31 | 19fc9e798a9bfb9027638f5e581bc54d7090615a4e71a449f51f1ab45736b046 | a76797d1988bf81f518933ae46f571ee13c5b67db5b2de7b94cd9ba6b526bd21 |
| 长输出v32 | 2dae5d4a369eadb8556165c8867abe2a83f5f8bb1e20b58b4a537161b5d7f468 | 85681e4d26dc6baf30150c601d663a144b18496bdd3c576d1bd6df6b641044f4 |

两组均OFFLINE_READY，无真实新release证据。共同Recipe aede21a8c2b7a2333dfba09b7a7b17ac85570fa58c89f7227e4c975a8c9c2553。

- [默认新冻结](evaluation-inputs-default-2026-11-18-v3.md)：原SHA b96887c785b8d6dcb8206b558c47f1e8bf58ce4a4609faffb1f302a670542b9d；cohort ae529100c79ef98f5fc6fa8c223810d9cffa1febbe4e3de6b817450ca06fd57e。
- [长输出新冻结](evaluation-inputs-long-2026-11-18-v3.md)：原SHA e98a81fe27c3b84964d0e484cad62e2efc9b0d76efa5cef15acf68244e1def64；cohort dc43c0c6115487f862f590beffe843f50efffcb7044b56419931dea3f06cc367。
- 各60样本/120候选首次生成、随后--verify完整重建全部一致，均Tokenization=0/Chat=0/cleanup=True。旧v2/r2清单及两轮真实证据未改。
- 六份新attempts/reviewer准备文档均校验60行；NOT_RUN/PENDING/UNASSIGNED，没有代填真实人工结果。实际执行时使用新报告自动生成的实际尝试表。

## 检查与修正过程

固定SQLite，Windows/Python3.14；离线子进程经tools/python-v20.py及quality_python.py启动，外部网络、正常data/.env访问有程序防护；所有测试使用TemporaryDirectory，成功/失败后清理为True，无原始测试JSON/日志/截图留存。

主要最终分组命令为固定运行时下quality_python.py，指定：
tools/tests/test_v21_execution_budget.py；
backend/tests/formation/test_v21_model_transport.py、test_v21_observation_driver.py、test_v21_evaluation_bootstrap.py、test_v21_execution_allowance.py、test_v21_live_fix_examples.py；
参数-q -p no:cacheprovider --tb=short --basetemp <本轮临时目录>。

本组首次61项通过、1项测试目录保护配置失败，3 subtests通过，370.55秒；失败项没有发送真实请求。测试把执行器ROOT重定向后遗漏共享Markdown写入器ROOT，补齐同一隔离根；随后因Windows测试目录太长，换用短隔离子目录，不改生产路径保护或准入源码。修正后的test_v21_observation_driver.py单项1 passed，12.61秒，cleanup=True。因此上述62项已分别通过，未把原失败批次写成整批exit0；生产代码在该最终分组及单项修正之间没有变化。

早一组在投影修正前71项通过、8项新语法测试失败，16 subtests通过，356.30秒；保留失败事实，不称整组通过。其中资源发布/旧选择、评测工具及原HTTP传输测试通过。8项失败定位为去除pattern后的oneOf分支重叠及空文档关联样例误用了评估夹具，修正如上。中途一次300秒执行器超时不是产品验收失败；核对本轮进程已结束、临时目录不存在后提高检查时间上限继续，不停用户服务。

新检查覆盖：空/非空当前区块枚举、五类合法任务、全文/未读/旧Revision别名拒绝、路线成果temp_ref错字段拒绝、本地长度及模式继续严格、字面量键与Schema语法分离、未知语法/冻结摘要失配失败关闭、非DISCUSS原格式、实际MockTransport SDK字节/0重试、历史原请求、单次额度不发送第二例、两种准入路径及C01/C07保护。

另外只读遍历首轮-01及第二轮-02所有正常LLMUse：120/120按各自原v27/v29资源restore_counted成功，profile.request与原snapshot.request一致，response_format仍None。只读检查使用mode=ro，没有重新发送、重标通过或修改审计。

静态检查：589个backend/app格式通过；改动文件Ruff F/I/B及format通过；git diff --check通过。8枚原设计/Schema/旧资源pin及v27—v32全部资源文件字节核对通过。run-v21-evaluation.py默认模式DEFAULT_EV60_METADATA_MATCH，credentials_read=0/provider_calls=0。cleanup-test-artifacts.py --dry-run为JSON=0/screenshots=0，未运行无必要删除。

## 服务现场及未覆盖

8001/PID460396与5174/PID311404保持，两个/api/v1/requirements GET均success=True/items1。正常库只读：需求1/requirement_documents1/LLMUse0/在途0；原Run1/2仍FAILED，未重放。原8000/5173未操作。准备的AI启动脚本未执行，当前服务仍未启用AI；本次没有页面改动或浏览器验收。

两轮60 Chat授权均用完；本修复没有第三轮真实许可，模型/计数新增调用0。供应方文档只支持实现方向，不能替代当前release的兼容证明。附加Schema是否影响实际输入usage和1024 framing门槛未知，不能假定免费或任意放宽。下一步推荐独立1 Chat/2计数/139264 Token/0重试观察默认首例；未知、格式拒绝、计数偏差或预算不符即停止，不继续59条，不包含长输出。不产生费用金额估算。

即使单例兼容成功，仍不代表60样本效果或双人独立人工评审完成；正式AI保持关闭。完整目标尚未达成。
