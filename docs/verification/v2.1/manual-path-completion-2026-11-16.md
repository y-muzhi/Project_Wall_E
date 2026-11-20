# V2.1手动路线及步骤结束事务（2026-11-16）

基线a0f4059加未提交代码；Schema200/db20-r51与Schema210/db21-r2。正式前后端0.1-draft-4未修改。固定SQLite及quality_python离线／业务数据保护；独占临时目录清理，无真实供应方／计数、用户服务／业务库或Git提交推送。

## 实现

手动ADJUST_PATH已串联原成功回执、真实用户操作消息、事件批、正式Ref、标量／成员及ORDER、实际关联与一次D/F，V不变。reference_map按声明顺序；取消读真实正序历史。based_on_proposal只核实原AI卡／index／payload摘要作为人工来源，仍严格D/F/V，不授权执行原payload；有效新用途卡来源链等待B4实际发布管道补证据。

RequirementRepository.advance_discussion只CAS递增D，保留旧discussion_state_json原字节。用户操作消息用业务名称，完整命令留审计及回执输入。

closure_sources／closure_snapshot按同连接规范化、SQL去重来源；Closure标量项及Evidence逐行冻结，复核计数／流式digest，不装终身JSON。COMPLETE_STEP可从PLANNED结束，缺证据OUTSTANDING、遗留KEEP_OPEN；真实转交／处置保留事件与来源；非当前焦点保持，next明确转移且不开始下一步。不写正文／确认文档或改需求业务状态。结束及子动作共享D/F和批次，旧Closure不改。

shared/http_errors登记形成错误和严格STATE_CONFLICT原因；CONTENT_VERSION_CONFLICT沿旧null详情；图校验业务拒绝为FORMATION_INVALID。嵌套ProposalRef复制，私有basis不返回。CardKey保留身份原文及有效Unicode。

## 检查

命令入口：当前.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py；参数-q -p no:cacheprovider --tb=short --basetemp <独占临时目录>/pytest；环境用quality_gate.environment。

| 范围 | 实际结果 |
| --- | --- |
| formation/test_v21_path_commands.py＋test_v21_state_commands.py | 13通过、1夹具失败，46.01秒；夹具把旧建文档审计当形成事件，改按formation_event_type筛选后whole_route单项1通过／6未选，4.72秒。实现调用本身成功 |
| formation/test_v21_closure_snapshot.py | 4通过，24.62秒；PLANNED结束、1005遗留及来源逐行保存、重开保留旧快照、失败回滚 |
| formation/test_v21_completion_commands.py | 6通过，22.40秒；原回执重放、非当前焦点、遗留不设门槛、完整双OPEN转交＋明确next、旧定义／不完整转交全拒绝、故障全部回滚 |
| formation/test_v21_http_errors.py＋shared/test_http_errors.py＋formation/test_v21_contracts.py | 33通过、22子测试通过，0.15秒；新错误／旧封装及严格契约 |
| ruff format --no-cache --check backend/app；git diff --check | 均通过，537个后端源码文件 |

之前109项及后续分批结果保留原范围，不把早先回归覆盖到后加源码。本批测试进程均结束，临时产物清理。

## 未完成

12／15原生命令内部实现；3类提案动作、完整绑定当前性／撤回凭证、CARD_RESPONSE精确写入、所有正文路径成果维护／正常讨论复核／替代链、RecommendationBasis、完整读取／预览／分页、新AI执行资源及原调用链接入、HTTP／前端／IndexedDB及浏览器待继续。没有注册半套生产入口，不代表整版可用。有效新用途卡人工来源／SUPERSEDED链等待新资源真实发布专项，不造假GuideRun。旧run9异常与SYSTEM Guard暂停继续保留。
