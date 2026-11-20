# V2.1提案契约及原生接口专项（2026-11-16）

代码：HEAD a0f4059，隔离工作区未提交；Schema210/db21-r2＋core/db20-r51。正式pending设计未改，真实供应方／用户服务／正常业务库未操作。

- 流式PublicationBinding：test_v21_proposal_binding.py，6 passed，24.52s；临时目录自动清理。
- 提案严格契约：test_v21_proposal_contracts.py，17 passed，61.57s。STAGED_WRITE与FORMATION_PATH_CHANGE严格区分，固定单选apply；未知／私有字段、错属成果、临时写目标、bool版本、含糊选项、非法全文／补丁组合拒绝。正文CRLF与空白原字节保留；路线未来符号仍原值，纯解析不建实体。该层不替代真实图／来源与发布核实。
- 原PATCH集成：test_v21_native_http.py，8 passed，29.38s。真实requirements路由、HttpRuntime、共享Idempotency及Schema210；成功／重放／NO_CHANGE、错误归属／过期D／输入拒绝；严格成功投影不删私有字段蒙混通过。无GuideRun／LLMUse。
- 命令：.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py 上述文件 -q -p no:cacheprovider --tb=short --basetemp 独占临时目录。tools.quality_gate.environment离线审计保护。接口专项使用进程执行许可；所有数据位于临时目录并在完成后清理。
- 一条既有FastAPI TestClient依赖弃用提示，不影响结果，未升级依赖。

未覆盖：新卡真实发布／正式回答精确采用、生产注册及Schema升级、AI资源／供应方、浏览器及前端。未称V2.1全量验收。格式及共享回归在当前批后执行。
