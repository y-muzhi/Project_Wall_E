# V2.1当前读取与共享正文维护（2026-11-16）

环境：隔离HEAD a0f4059＋未提交实现，固定SQLite3.54.1；新core db20-r52（manifest b022d946727bbd94b469f2d6b8ab13e295ae8457241eb1954ed80e392718c9b5）及Schema210/db21-r3（contract f3f29931a176cbb64effa63fad516280120711a472f4e59a246a9683df9e0b78，manifest b1ef4039b051e32f66909883f0bc4fc76b22219ae470a362dd07b03b278caada）。r51/r2原字节保留；DDL与合同不变，本次重新发布因collaboration_admission新增210只读验证、源pin变化。未升级任何产品库。

实现：
- requirements原GET在真实Schema210且明确document_id/expand=discussion时返回严格formation_summary；无头部exists=false与有头部同键，计数来自全量SQL。旧Schema151/200契约保持原形状。
- 当前步骤／支线／问题／成果分页、步骤及成果详情、六类关系、ORIGIN/CURRENT范围、追溯链读取；上限100，精确过滤与固定F游标。已取消步骤展示位置从原不可变取消事实恢复；“最后事件”是最新相关事实，不强行显示生命周期事件。追溯链单根已验证，多次真实AI替代链仍待B4。
- RecommendationBasis程序捕获及精确当前性子层：Goal、owner定义/状态、target、覆盖、来源、实体与完整关系集合；只变D/F/焦点或无关区域不失效。历史basis不改写。真实AI建议登记尚未接入，不称模型已支持。
- 共享commit_content加入全部受影响活动Artifact维护，完成步骤同样覆盖；更新CURRENT范围与检查头，内容改变待复核、全部消失REMOVED；不复活旧身份、不改原ORIGIN/Closure/生命周期。FormationTransaction复用同事务原D/F，正文、Revision、范围、事件、回执一起提交／回滚。
- 旧版REVISE实际接受→冻结→离线计数/网关→审计→C07进展/正文→成果维护已接通；补齐原evidence_database对Schema210的严格只读识别，不能用Mock绕过原审计检查。

检查：
- 扩大回归formation目录＋requirements/test_v15_foundation.py＋documents/test_v15_editing.py：199 passed、1 failed，386.38秒。唯一失败是跨文档历史夹具的第二文档未建主线，按设计先返回409 FORMATION_NOT_INITIALIZED；补齐其独立主线后，该项定向1 passed，4.94秒。未声称原一次运行200全通过。该次收集不含后加model_contracts专项。
- 当前列表原14项中13通过，取消节点“最后事件”预期修正后定向通过；关系/建议等8项中7通过，正文夹具补齐后与两个受影响项合计3通过（13.48秒）；这些随后均被上述扩大回归覆盖。
- 正文维护6 passed，29.80秒：无关区域、改动范围、删除后恢复新ID、已结束Closure保留、维护后故障注入及相同key恢复、105个活动关联一次维护。初次5项因夹具把换行后的文本意外变成新段落且未增加身份而失败，修正夹具后6项通过；强化的范围/状态及失败key回滚随后纳入扩大回归。
- 真实旧版修订集成2 passed，20.59秒，分别含/不含同轮进展。各1个离线计数替身批与1个离线网关，真实GuideRun/LLMUse/C07；D不重复增长、F一次。起初实际链路在210只读审计识别失败，修复并重新发布r52/r3后通过。不是新2.1模型协议或供应方证据。
- model_contracts12型普通模型增量纯解析20 passed，0.08秒；拒绝取消/结束/重开等用户决定及自填程序basis；尚未接入新资源与模型链。
- Ruff格式截至本批556源码文件通过；最终格式/静态未使用项检查在后续批再记录。
- 命令使用.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py，-q -p no:cacheprovider --tb=short --basetemp独占临时目录，quality_gate.environment离线保护；所有临时DB、计数/审计产物在临时目录内，进程结束后清理。仅保留本Markdown。

未覆盖：完整新用途卡发布与CARD_RESPONSE、模型V2.1 Canonical/Wire/新release、普通formation_delta实际应用/初始化/AI复核、提案列表及有效新卡事务、路线预览（继续实施）、生产注册/升级、前端/浏览器与真实供应方。无真实Chat/计数、用户服务/正常库更新、Git提交推送、正式设计合并。
