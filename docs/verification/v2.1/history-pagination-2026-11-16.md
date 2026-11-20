# V2.1历史摘要与有界查询（2026-11-16）

环境：HEAD a0f4059＋隔离未提交源码；core/db20-r51、Schema210/db21-r2。无真实模型／计数、用户服务或正常业务数据操作。

本批发现并修复的实际偏差：原成员／Closure摘要使用逐行JSON＋换行，原Closure类别为BRANCH/ISSUE/RESULT，和正式待实施基线6.2的canonical完整数组及RESULT/ISSUE/BRANCH不符。digests.ArrayDigest现以流式方括号／逗号计算完整canonical数组，空集为SHA256([])。Closure根类别与证据范围排序修正；MemberDelta强制集合声明顺序及UTF-8 member_key顺序，关联范围事实按对应key排序。没有既有产品库形成数据；冻结Schema发布包及设计原文未改。

检查：
- test_v21_history_digests.py＋test_v21_history_queries.py：17 passed，54.61s。独立标准json.dumps摘要对照空／单项／1005项；真实用户结束的完整根／证据／成员；真实有界事件／变化／成员／Closure／证据及ASGI错误。
- 同时相关写入回归：先执行event_members／closure_snapshot／completion_commands／path_commands，20 passed；新摘要断言初次因测试将数组传入只接受对象的canonical_input失败（4项），测试改为独立标准数组序列化，后与历史读合并17项全部通过。没有为通过而放松产品数组规则。
- 随后发布依据＋原生HTTP：15 passed，53.76s（共享source_semantics抽取前），新增发布阶段Step.definition_version及独立生命周期核实；发布与复用都重新走最新全图。抽取后的受影响回归待后续本批执行。
- Ruff format backend/app：546 files already formatted，git diff --check通过（当前列表／建议读取新增之前）。
- 命令：.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py 上述对应专项 -q -p no:cacheprovider --tb=short --basetemp 独占临时目录；quality_gate.environment离线保护，临时数据自动清理。

已实现history_contracts、cursors、history_queries及formation/api历史路由；首事件页固定upper_event_id，后续新事件不混入；同批引用筛选扩展同批事件；旧Closure不依赖当前F。所有页最多100项，total/digest来自全量不可变记录，不由当前页冒充。未知过滤／重复参数／跨文档游标／缺失事件明确错误，不暴露私有绑定。

未覆盖：生产路由注册／Schema210服务切换、当前实体页（继续实施中）、路线预览、新卡发布／CARD_RESPONSE、前端与真实供应方。不是整版验收。
