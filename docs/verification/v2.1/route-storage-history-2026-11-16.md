# V2.1路线基础、关联及历史成员专项（2026-11-16）

基线a0f4059加本轮未提交源码，仍使用db20-r51／Schema210 db21-r2。冻结包及正式设计未改。测试均由当前.venv、tools/python-v20.py固定SQLite及tools/quality_python.py离线／数据保护执行，--no cacheprovider、独占临时目录并清理；只保留Markdown，没有模型／计数调用。

## 实现与实际结果

- path_plan：14型路线完整符号图计算；全批前向引用、取消成果同kind完整承接、开放问题／支线／依赖去向、Goal／定义版本、真实顺序和匹配焦点；同批每Step定义至多+1。path_facts逐实体标量／逐成员变化及逐节点ORDER，不嵌整条路线。完整图5000节点检查未设历史累计门槛，定义及关系先按Step归组，避免逐Step扫描全部结果／边。
- route_storage：事务内分配真实Step／Result身份、复核正式图、暂占负rank后按唯一索引恢复最终有效顺序，结果／关系／处置写入及一次F；调用方仍须负责完整事件批、用户来源、D及回执。不能把此层SQL保存当完整ADJUST_PATH入口已接通。
- artifact_links：复用真实Snapshot／DocumentSources，核实当前Revision及实际区块；同事务实际CONTENT_ASSOCIATED来源、冻结ORIGIN／CURRENT范围／摘要、实际成果归属。预览核实不能移交另一事务。只关联，正文／V／Revision不变。
- events.record_change：成员两遍流式摘要与校验，按100行批量插入但不分事务提交，任意变化或失败整体回滚。1100条真实同文档依赖逐行保存，不内嵌历史数组。
- 恢复Issue按对象规则清空当前disposition_event_ref，原恢复事件仍进历史；没有把新恢复事件错当当前暂缓处置。手动路线Ref集合仅受本批预算／全图约束，不套用模型相关材料100项上限。

命令范围及结果（-q -p no:cacheprovider --tb=short --basetemp <临时>/pytest）：

| 范围 | 实际结果 |
| --- | --- |
| backend/tests/formation＋infrastructure/test_idempotency.py、test_v20_command_receipts.py、test_v20_schema_state.py、test_v20_schema_release.py | 109通过、16子测试通过、1既有弃用警告，67.24秒；此轮执行在随后events流式增强之前启动，不把它覆盖到后加代码 |
| formation/test_v21_route_storage.py＋test_v21_artifact_links.py | 8通过，24.81秒；正式映射／重排唯一／回滚／成果编号／不可转交预览／真实区块／来源与摘要 |
| formation/test_v21_event_members.py＋test_v21_state_commands.py（流式增强后） | 10通过，31.80秒；1100成员计数／digest、流变化回滚、真实原生支线恢复保留旧来源，原有回执／原子事务回归 |
| formation/test_v21_path_facts.py＋test_v21_path_plan.py（线性归组优化后） | 17通过，1.29秒；逐事实不重复、ORDER、取消正序历史、真实Ref、5000节点完整图 |
| formation/test_v21_contracts.py | 24通过，0.09秒；包括Unicode／LF／保留空白及200依赖Ref集 |

中间1项新增文本测试把实际CR/LF误写成字面反斜杠，夹具修正后24项通过；没有改变正文标准化规则。前次批量回归100通过／1夹具失败不是实现断言失败，已由上表109项实际通过替代。

## 接续边界

完整ADJUST_PATH的原用户／事件批／D/F／回执尚需串联，基于旧提案的来源／SUPERSEDED也待接入；没有注册HTTP或页面。Closure、提案、精确写入、成果维护／复核、AI资源与执行、完整读分页、前端及浏览器仍待后续实现。组件专项不冒充整个V2.1已可用。旧run9存储异常与SYSTEM Guard暂停继续保留。
