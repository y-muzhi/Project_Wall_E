# Coding模型调用授权显式应用（2026-11-12）

香港15:20（UTC07:20:43）启动，15:28用户中断；17:45收到“继续啊”后接续。中断时段不计工作量。master／28a7c9e13c73a9d386081a6dd894244b51746a45，Git折叠422条，保留其他任务改动。BE 0.17-draft-17 SHA256 1A8D277F25DE570CE72E74A73FF763BF73F622FCF94B61F0820B78A1A5C6FD37；FE 0.16-draft-16 SHA256 38557CEE854697044AB7DABA30F694738429BE1235264A153851E8FC808CF3A7，仍DRAFT且未合并。Schema200 db20-r44、固定SQLite3.54.1不改。15:20及17:45正常服务8000／5173／5174无监听，未启停用户服务。

## 范围、输入及运行方式

先保存[独立pending](../../iterations/pending/v2.0/WALL-E.Coding模型调用授权显式应用迭代V1_V_2.0.md)。仅编译原成功START授权范围内的model_profile_refs许可；原生配置／provider／运行包、目录／命令／网络、session permission不变。C39原步骤冻结编译事实、采用前及历史重核。实际受管入口每请求仍读当前EFFECTIVE授权；撤销不得进入账务及供应方，恢复不打开旧CLOSED窗口。真实供应方、普通业务库、SYSTEM／WFP、提交／推送不在本轮范围。

工具采用tools.quality_gate.environment，清除真实凭据和代理，WALLE_TEST_CONTROLLER_POSITIVE=1；独占TemporaryDirectory，tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short --basetemp <本轮临时目录> <以下目标>。所有已结束运行均清理自有目录；只留Markdown，无JSON报告／截图／原始日志。原生及供应方响应明确为离线夹具。

## 已执行

- 中断前68486在24.16秒失败：撤销／恢复接收与采用已执行，但正向恢复时覆盖了opened中已准备的MODEL／CAPABILITY／PRICE目录，真实入口正确hold。没有已知未取结果或重复执行。接续先取回该原结果，再修正隔离上下文；生产准入不放宽，撤销负例也必须在READY目录中拒绝，避免错误原因掩盖。
- 模型授权4场景及共享内容来源7场景：11通过／182.23秒。目标test_task_model_authorization.py、test_task_content_limits.py。
- 模型授权5场景（含实际CodingModelGateway对象零派发／零LLMUse及恢复不自动重开）：5通过／95.23秒。Mock供应方transport禁止进入，原字段／凭据来源为隔离夹具，不是供应方兼容证明。
- 原启动未批准、但profile合法声明的辅助模型，先正常批准提议再C39拒绝：1通过／19.57秒，AUTHORIZATION_NOT_APPLICABLE，Task版本／原授权不变，无新C39操作，提议保持APPROVED_UNBOUND。辅助目录注册为隔离测试数据，不是模型已准入。
- CLI实际SPA／FastAPI／SQLite四参数：4通过／134.82秒。目标test_v20_live_control_http_browser.py，controls／checks／output／models。models使用同profile的新授权撤销，验证真实提示、取消草稿、丢202后原请求恢复、UNKNOWN、预算追加、后台采用、历史、服务未就绪及360／1280布局；新字段不触发模型。固定内容禁用及原检查输出分支同轮回归。临时构建、HTTP线程和自有Chrome／Job由原夹具收尾并清理。
- 前端npm run format:check及strict通过，使用锁定Node／Prettier／TypeScript及quality_node预加载。首静态命令因NODE_OPTIONS中反斜线路径被解释而MODULE_NOT_FOUND，未执行产品检查；改为原路径as_posix后通过，不安装或升级依赖，不关闭检查。

## 后续专项及联合结果

原C39控制／未知／STOP、新模型编译及内容来源与配置准备四文件回归57014：37通过／633.33秒，自有临时目录清理。

- 代码与压缩两个固定别名的实际Gateway对象门槛：模型专项76337，7通过／128.56秒；均撤销后零transport／零LLMUse，恢复后旧CLOSED窗口不重开。
- 原明确继续及实际账务网关：test_task_resume.py、test_coding_model_gateway.py，24通过／344.25秒。原窗口／原操作、丢回执、STOP、实际本机socket与Mock供应方账务回归，非真实供应方兼容证据。
- 末次共享原授权来源修复：三项所有者ID用确定JSON比较，拒绝整数等值的浮点／布尔。源代码／新专项lint和格式通过；88559最终模型／内容来源专项15通过／249.87秒，包含三所有者ID浮点／布尔读取注入的拒绝及合法原来源恢复。隔离原事实未改写。
- 全backend/app 483文件Ruff格式通过；本轮生产及新专项／浏览器HTTP／共享worker lint通过。Guard大worker仅遗留未触碰的2881行SIM117，触及作用域的I001已原子排序；不为局部修改重写其他任务分支。git diff --check通过（既有frontend/tests/application-router.test.mjs换行提示保留）。

原PROJECT_CHECK_HANDOFF 59586失败131.78秒：首次候选捕获后项目检查worker.advance()返回False，尚未进入新增模型授权步骤；外层PIPE_IO_FAILED为子进程断言的后果，不能记作模型授权失败或通过。保留产品期限和权限，在原捕获夹具加入未知异常及前三步骤成功断言，诊断运行12766通过：1项／1162.19秒，自有临时目录清理；新模型撤销／恢复及明确重检、后续角色／修复／报告／计划与交付相关旧链全部走完。首次捕获失败未复现，无法唯一归因，保留本次失败，不声称已修复未知根因。最终共享来源精确类型收紧晚于该运行导入，由上述15项新专项覆盖；Guard合法整数来源行为不变。Guard为真实认证管道／NTFS／SQLite／固定项目命令，原生会话／模型是离线夹具，WFP及正式系统部署另列。

本轮仍不开放原生permission PATCH、目录／命令／网络扩权或全局配置重载。实际OS同组证据、第三步未知／前端独立解码以及正式CHECK_DRIVER／真实供应方／合格报告到交付仍待接续。


## 结算连续性及工具收尾

末次test_task_model_authorization.py::test_reauthorization_preserves_settled_task_cost_and_request_count：1通过／24.83秒。MockTransport实际走原Gateway／LLMUse／Reservation结算0.000118元后，原HTTP C39撤销和恢复均保持累计requests=1、settled=118微元、无预留／未知；原调用及预留完整行、公共预算不变。此为隔离算法数据，不是真实支付或供应方效果。

增加两次显式授权及实际项目检查后，Guard链已在旧1200秒外层看门狗内通过（1162.19秒）。仅该PROJECT_CHECK_HANDOFF测试外层等待改为1800秒，其他full_testing仍1200／普通240；固定项目、内容及单命令期限／授权不变。此测试调度分支随后静态语法／格式核对，不为等待上限修改机械重跑整链。


## 最终源码状态与可复核入口

本批生产8文件聚合SHA256：47495055c47e2ce675abfb11f05803e540d6a8743bb5eb3215473468f047768a。

| 生产源码 |
| --- |
| backend/app/code_tasks/task_start_authorization.py |
| backend/app/code_tasks/task_configuration_models.py |
| backend/app/code_tasks/task_content_limits.py |
| backend/app/code_tasks/task_configuration_effective.py |
| backend/app/code_tasks/task_configuration_apply.py |
| backend/app/code_tasks/task_configuration_live_records.py |
| backend/app/code_tasks/task_live_configuration.py |
| frontend/src/code-tasks/configuration-control.tsx |

本批测试／辅助7文件聚合SHA256：71b6112d5760fc2e62c0874d67fe91d84a7c942b74e4e65348e760fddb740f8c。

| 测试／辅助源码 |
| --- |
| backend/tests/code_tasks/test_task_model_authorization.py |
| backend/tests/code_tasks/test_task_live_configuration.py |
| backend/tests/infrastructure/test_v20_live_control_http_browser.py |
| backend/tests/infrastructure/v20_live_configuration_worker.py |
| backend/tests/infrastructure/v20_guard_control_git_pipe_worker.py |
| backend/tests/infrastructure/test_v20_guard_control_git_transport.py |
| tools/verify-v20-live-control-http.mjs |

聚合算法：相对路径字典序，依次UTF-8路径、NUL、文件原字节、NUL累计SHA256。上轮原生生产3文件仍ca5f148b747b271392b76b267856370444751d67652b9f6e688c27363f9028b2，没有把旧协议改动重新计为本轮实现。最后selected lint、MJS node --check、Guard调度语法／格式及git diff --check通过。正式BE／FE摘要再次与起点匹配，Schema／资源不改。18:23原生netstat8000／5173／5174无监听，master／HEAD及Git折叠422条保持；未启停用户服务。

Guard复核的精确目标为backend/tests/infrastructure/test_v20_guard_control_git_transport.py::test_authenticated_project_check_transfers_input_runs_and_releases_original_job[PROJECT_CHECK_HANDOFF]，仍经上述tools/python-v20.py／quality_python.py及隔离环境执行，不直接裸跑或调用供应方。所有本轮运行已取回结束结果；当前无未知测试会话或未完成源码函数。


## 末次在途撤销边界（18:29接续）

新增专项在MockTransport的原SENDING及RESERVED期间调用真实C39 HTTP：旧活动未静止时不得绑定新授权／新操作，原调用随后正常SETTLED。首轮21646失败17.53秒只见隐私折叠的hold；保留测试断言到网关外后10988失败19.19秒，定位测试误写409，实际产品按正式6.1及error_codes.py返回503 CONFIG_NOT_READY，生产边界正确。仅修正测试为既定503，39486通过1项／19.74秒，原调用正常结算且无新C39／授权绑定；不放宽产品／请求准入。新增动态夹具后，完整模型授权文件11528统一复核：10通过／147.37秒，已清理自有临时目录；覆盖撤销／恢复、未知、STOP、越原范围、两个实际别名、精确来源、已结算账务和在途调用拒绝。上节测试辅助摘要已按最后源码更新，生产摘要不变。测试异常回执只保留AssertionError，末次lint及格式通过；不修改生产网关隐私错误处理。


## 18:35 扩大整文件lint的差异

最后以python -m ruff check --no-cache --output-format concise检查test_v20_guard_control_git_transport.py与v20_guard_control_git_pipe_worker.py全文件，退出1，共30项：F401×4、F811×22、SIM117×2、I001×1、F821×1。均在本轮未修改的测试区域；F401／F811包含显式导入供pytest使用的fixture，不能直接ruff --fix删除。具体风险为transport测试2077行current未定义，位于旧执行资源恢复分支，未由本轮PROJECT_CHECK_HANDOFF场景执行；后续应按该原分支实际owner来源修复并专项验证，不猜变量或改写其他任务内容。worker的SIM117位于2881行，transport另有692行SIM117及1828行I001。本轮新增／直接实现模块与小专项selected lint通过，不代表上述两大型文件全lint通过。末次只读检查未改源码，15份源码最终摘要仍匹配。

源码原子临时文件0、8份关联文档链接缺失0、当前映射5条业务行同表6列；自有quality_python测试进程0、walle-v20-permission临时目录0，cleanup-test-artifacts.py --dry-run报告JSON=0／screenshots=0。18:34正常服务三端口仍无监听，Git HEAD及折叠422条保持。所有新专项均结束，无待取结果。


2026-11-12 18:36 本轮限定单元结束：所有测试结果已取回，最后新增10场景统一通过，源码及最终摘要保持，无待取／未知会话。15:28至17:45用户中断时段不计入推进时长。后续按当前断点接续，真实模型／系统／服务／提交权限不续用。
