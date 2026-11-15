# Coding 运行中控制配置应用验证

日期：2026-11-11。本轮香港 17:28 启动，master 28a7c9e，既有其他任务修改保留；BE 0.17-draft-17／FE 0.16-draft-16，Schema200 db20-r44，不修改正式设计或 Schema。六类控制限制先登记独立 pending 后实施；原生权限合并／在途写入受控停止不在本分支完成范围。

## 授权和环境

仅源码、隔离离线 Windows／SQLite／ASGI／原生本地 HTTP、必要 Chrome 与静态检查。锁定 .venv Python，经 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short，在 tools.quality_gate.environment 自有 TemporaryDirectory 下执行，结束清理目录。无真实模型／计数、用户库写入、用户服务启停、SYSTEM／WFP 安装、Git 提交／推送。两小时本轮持续推进，不因保存断点停下。

## 原回归

LIVEBASELINE：test_task_configuration_apply.py、test_task_session_replacement.py、test_task_role_chain.py，37 项通过（34.42 秒）。仅证明原启动前 C39／原来源和角色边界未破坏，不冒充运行中配置已验证。

## 新场景当前记录

接收先冻结原实例／会话／CLOSED 窗口与旧组，并绑定新授权为待应用；Task WAITING／CONFIGURATION 阻断新活动。成功须原 Guard／会话空闲及实际 config／providers／权限同组只读观察后，一次事务采用新组并保存不可变步骤事实。原 START 和实例 effective_profile_version_id 不改；有效控制组沿同一 C39 历史验证，未知不显示已采用；成功也不自动 RESUME。

快速 SQLite／ASGI 夹具最初误把配置内容传给接收资源目录而非 fixture_snapshot，发布 INVALID_INPUT；修正夹具资源输入。随后完整 TaskView 读取暴露旧快速候选没有实际封存步骤，未放宽产品封存校验，快速场景仅明确替代该只读包检查，实际 NTFS／MinGit 联合另补。未知观察误用只允许对象的 canonical_input 序列化原因数组，已改确定 json 数组；原整数／状态检查保持。初始夹具 test-runtime 不是正式运行包引用，现仅此模块在创建原配置前使用版本化 fixture 引用，不改已保存配置或放宽 InitialConfigurationObservation。最新批中 success／unknown／stop 三场景已运行至结案；native 参数又暴露新秘密引用未发布的夹具错误，改为已登记的不同运行包负向。该整组尚未最终通过，不提前标验证完成。

前端已接 WAITING 收据、动态原四步骤、配置等待和最新有效组；strict 首次提示缺少新等待类型的映射，已补该映射后通过。本轮页面及完整实际文件／Guard 联合仍待执行。

## 首批完整分支、原回归及实际文件

- LIVECONTROLSEVENTH：test_task_live_configuration.py 最终 5 项通过（52.56 秒），成功、未知后原 ID 只读恢复、STOP 受理栅栏、需重载及非六类控制变化拒绝。后续新增 repeat 连续两次应用，扩大联合先得到六个参数通过；紧接原启动前终态 GET 暴露本轮投影覆盖了终态按钮原因，已使 STOPPING／TERMINATED／COMPLETED 保持原投影。
- LIVECONTROLINITIAL2：test_task_configuration_apply.py 与 test_v20_opencode_instance_control.py 最终 54 项通过（48.87 秒）。五个新增真实本地 HTTP 场景核对原 config／providers／会话、权限／metadata／配置／Guard 变化，新增请求全部 GET、原创建 POST 1 次；也复验原启动前 C39 终态。
- LIVECONTROLNTFS3：test_task_capture_quiescence.py 的 live-control-configuration 参数最终 1 项通过（44.38 秒）。实际 NTFS／MinGit／SQLite／ASGI，原候选完成封存后，沿原 fail_unprepared_project_check 结案缺环境检查，再接 C39；采用后 TaskView 和原 C30 精确字节读取通过。前两轮先正确拒绝尚未结案 CHECK 的 OPERATION_CONFLICT，再因夹具漏 at 参数失败；没有放宽产品门槛。原生配置／消息为定向夹具，真实本地 HTTP 另分项证明。
- 代码按职责拆为 task_configuration_effective.py（有效组来源链）、task_configuration_live_records.py（原记录与公开投影）、task_live_configuration.py（原 C39 接收及后台采用）。ControlConfigurationObservation 与原 CaptureTurnEvidence 同在原生适配，不令 driver 依赖业务 runtime。

## 页面

已有 Playwright CLI（本轮核对 npx）、自有 Chrome、临时 Vite 构建／HTTP 的 coding-live-configuration 最终通过：360／1280，取消保留草稿，丢 202 后刷新核对原请求，PENDING 不显示生效，UNKNOWN 保留原请求，同组 APPLIED／EFFECTIVE 后才显示生效，POST=1。输出 V20_LIVE_CONFIGURATION_PASSED 和 OWNED_JOB_EMPTY_AND_BROWSER_OUTPUT_CLEANED。首轮最终读取按钮因异步原进度观察已完成而被移除、页面已正确采用；夹具仅在有效事实已显示时接受该已完成观察，不忽略未知或未生效，也不重发。

## 正在联合

LIVECONTROLGUARD 于香港 18:16 启动，完整 PROJECT_CHECK_HANDOFF 在 BACKEND 修复替换后插入 C39，再用新组对同候选真实重新检查，随后接原角色／修复／取消／发布及停止范围。未出最终结果，不计通过。新辅助校验的 effective_config_application_id 已定位 code_environment_records，而非 Verification。实际 Guard／项目命令、NTFS／MinGit、SQLite／HTTP 与原生配置／消息夹具分开；正式部署、供应方及最终真实 TASK 原生收尾尚未覆盖。


## 停止、来源及实际限制补齐

LIVECONTROLSTOP：运行中配置 7 参数通过（87.92 秒），包含核对前 STOP／只读途中 STOP，均沿原隔离停止至 TERMINATED／cleanup VERIFIED，旧组保留、新授权 APPLY_FAILED／原 C39 CANCELLED，无本轮目录残留。Guard 回执是夹具，与真实 TASK 原生收尾分开。

新增来源负向起初试图用 SAVEPOINT，项目授权器正确拒绝；改原事务异常回滚。修改成功操作又被 TERMINAL_OPERATION_IS_FIXED 拒绝；最终检验同代次／会话移植拒绝、数据库终态操作与步骤不可改，以及退休授权不构成有效链，来源参数已通过。最初将 profile 输出上限降到固定 model binding 以下，发布正确 INVALID_INPUT；保持固定 models、profile 上限合法，用新授权缩小输出到50，模型准入参数已通过，不削弱 profile 校验。

完整联合 LIVECONTROLGUARD 第一次结束输出在上下文切换时未可靠保留，不计通过；LIVECONTROLGUARD2 失败207.60秒：隔离手工 FastAPI 未注册发布配置入口（404），未到 C39。现补该隔离应用的配置／授权／C39／重新检查正式路由，LIVECONTROLGUARD3 重新运行，待结果。未改变产品路由或缩减 Guard 边界。

实际入口发现 queue_wait_seconds 原未接入，已先补 pending 说明后修正。HTTP收包15秒与消息确认队列期限分离，按本任务配置和授权较小值一次冻结，超时不调用供应商。首次实际监听器暴露初始 QUEUED 的 active_session_id 尚未采用，不能拿 OPEN 条件提前要求；现沿原 read_original_window_state 在同事务证明 START／QUEUED 来源，保留初始未采用会话的合法时序。该专项继续，不提前记通过。

前端 strict、Prettier 及原创建／请求回执／恢复3个Node文件19项通过；后端478生产文件格式和本轮新模块／测试lint通过。模型准入／队列新修正后仍需最终检查。


队列 QUEUEWAIT2 最终4项通过（44.06秒）：真实本地 socket，profile=1／grant=1及profile=3／grant=1两参数均按1秒上限取消本入口，仍 QUEUED 时0次派发／0次来源验证／0 LLMUse；原消息随后确认也不自动重发。后续单独明确本地请求按OPEN通行。原启动等候和旧连接跨继续窗口拒绝一并回归。

LIVECONTROLGUARD3 失败196.68秒：隔离历史夹具直接写入的原授权部分限制超过已配置profile（scope.limits RELATION），正式新批准入口正确拒绝。修正原夹具在创建前对每项取不大于原profile的范围，未修改存量数据或产品授权检查。下一轮继续从原真实检查联合重跑。


## 关联回归与交接投影定位

LIVECONTROLSHARED 最终39项通过（475.20秒）：原问题、权限响应、继续执行、原停止、模型网关／账本，以及新的错误Guard观察不采用、worker中途取消保留PENDING再明确恢复。供应商为HTTPX MockTransport，无真实模型或计数API。

LIVECONTROLGUARD4 失败291.61秒，新C39采用及按新配置真实重新检查已完成，原角色交接阶段TaskView 500。第5轮诊断失败250.98秒，直接沿原TaskDetailRequest／read_code_task／TaskDetailResponse取到RoleChainUnavailable('ROLE_CHAIN_UNKNOWN')：配置动作投影在已有HANDOFF_ROLE未完成时提前读取原来源。现将其他active operation优先显示OPERATION_IN_PROGRESS，不读取该未完成来源，不捕获或忽略角色链错误，也不放宽交接资格。新增HANDOFF_ROLE／VERIFY_CANDIDATE／REPAIR三过渡负向；完整联合待再次验证。诊断第5轮已加载修复前函数，trace行号与磁盘后续编辑差异不算新错误。

原START授权链又补齐无C39历史的基线比较，不能只因profile与实例相同就允许Task更换authorization_id。新增同profile仅新授权路径及原来源负向；所有源码按原子规则保存。


## 限定分支最终状态组及实际HTTP页面

LIVECONTROLFINALSTATE 最终20项通过（263.02秒）：12个原C39控制／来源参数、3个过渡互斥、原START授权来源负向、实际本地socket两参数、原初始等待、旧连接跨继续窗口拒绝。包含同配置仅新授权、模型准入新授权较小输出、连续应用、坏Guard观察、worker取消、两种STOP收尾。后来仅修正快速逻辑候选夹具在形成QUIESCE时同步updated_at／last_observed_at，未改产品或放宽时序。

实际HTTP页面最初4轮均不计通过：自有Job刻意只继承SystemRoot/TEMP，首次未显式传WALLE_CHECK_TEMP被本轮目录校验拒绝；第2轮页面无配置按钮，补可读原错误后第3／4轮定位逻辑候选夹具QUIESCE时间新于task.last_observed_at，实际TaskView严格拒绝。已修正该夹具创建时的原时间配套，移除临时产品投影诊断，不放宽校验。

LIVECONTROLHTTPBROWSER5 最终1项通过（23.65秒）：已有Playwright CLI、真实Chrome、临时生产SPA构建、实际FastAPI HTTP／SQLite及原TaskView／C39／幂等读取／动态步骤；丢202、刷新核原请求、PENDING旧组、UNKNOWN旧组、APPLIED与新授权EFFECTIVE一致后显示生效，取消草稿、360／1280无溢出、C39 POST总数1、LLMUse总数0，原候选／会话／代次未改。原生观察为离线定向夹具；该浏览器使用显式逻辑候选，真实封存包／C30已由NTFS专项分项证明，不能称浏览器真实封存全链。自有HTTP线程／Job／Chrome及构建、CLI JSON／日志目录全部随TemporaryDirectory清理。

LIVECONTROLGUARD6 于香港18:57重新启动完整原多角色联合，包含配置后真实项目检查和后续原交接／修复／取消／发布／停止；正在执行，仍未计通过。


## C40与前后端过渡事实

C39核对中明确增加预算，原版本变化先放弃该次采用、保留PENDING，下一次沿同操作重新观察后采用。首次并发专项1项17.59秒通过，同时核对到原C40 TaskView生产只带基础等待，漏最新C39应用／active operation；已补原配置投影，并在前后端严格要求WAITING／CONFIGURATION与原活动C39成组。修正后LIVECONTROLBUDGET2原预算4参数加并发1参数共5项通过（62.90秒）；最终LIVECONTROLLASTCONTRACT来源缺组／预算并发2项通过（33.82秒）。前端TaskView新过渡互斥和缺组拒绝连原创建共9项通过，不放宽无活动操作时的占用原因。实际HTTP Chrome已扩展到配置等待期间用真实预算表单追加一次，最后随页面复查。


## 完整Guard联合最终结果

LIVECONTROLGUARD6 最终1项通过（817.97秒）：真实认证Guard／命名管道／MinGit／NTFS／SQLite／受控项目命令，在BACKEND已归档修复替换后明确C39，只读核实新组并对同候选按新profile及effective_config_application_id重新检查，再接原两次角色交接、同角色修复／取消／再捕获、三阶段检查、Testing发布／重新检查和原停止范围。实例启动profile及原START不改，五个会话／三角色、原实例代次1及停止代次6保持。第4／5轮实际暴露的TaskView过渡投影已在最终联合修复确认；没有缩减角色链或忽略原错误。

原生消息／配置和SYSTEM／WFP准入及TASK末端停止回执仍为定向夹具；该通过不代替真实供应方、正式CHECK_DRIVER或真实OpenCode TASK完整STOP／CLEANUP证明。所有临时目录和自有进程随工具清理，无用户服务更新。


## 最终页面、静态及现场

LIVECONTROLHTTPBROWSERFINAL 最终1项通过（20.85秒）：在第5轮真实HTTP页面基础上，用实际预算表单增加到0.200000，配置等待仍保留原C39／应用；预算POST=1、配置POST=1，前端decoder接收原C40完整TaskView，未知保留旧组、最后同组生效；新增运行中可用变更范围说明的360／1280布局正常。原候选为逻辑夹具及native观察离线的边界不变。

最后前端strict、Prettier、相关3个Node文件21项通过；后端19个本批变更生产模块及4个新测试／辅助lint、478生产文件加7个关联测试共485文件Ruff格式通过，新CLI入口node --check通过。额外检查两个旧大型测试／worker文件发现既有SIM117（其他Git恢复分支）及旧测试未用control变量；只修正本轮增加的两个导入顺序，保留无关旧分支，不称这些额外全文件lint全部通过。

19:09／19:12核对：HEAD仍master 28a7c9e；正式设计摘要与开轮相同；8000／5173／5174无监听；产物dry-run JSON=0、screenshots=0。本轮4份新增／当前Markdown链接均存在。该时点既有tasks浏览器与现场清理仍在收口；后续实际结果见下节。


## 既有tasks页面扩大回归最终结果

首次既有tasks CLI在全局Coding导航／旧C39通过后，原生问题场景仍被本地RESUME占用，未记全过。定位到resume-control.tsx的终态effect：原操作先SUCCEEDED、本地原收据仍未ACCEPTED时提前记settledOperation，后续再核收据不会结清。先补pending说明，修正为ledgerReady且同一原operation_id／ACCEPTED后才持久结清；不清IDB、不代关闭原请求、不重发。

修复后同一完整tasks CLI通过，输出V20_GLOBAL_CODING_NAVIGATION_PASSED、V20_C39_CONFIGURATION_PASSED、V20_TASK_PAGE_PASSED，覆盖空／有数据／缺失／筛选空、创建与占用、草稿／失败恢复、起点与候选历史、UTF8分块／差异、自检／用例重试分页、原角色／发布、启动未知、模型账本、预算／继续原请求、原问题／答复／权限、文档交接、隐藏／聚焦恢复和原停止清理。实际写入creates=1、budgets=1、resumes=1、starts=1、stops=1；360／1280，导航另360／1024，旧C39独立POST1。API为隔离确定夹具，与上方实际HTTP／Guard证据分开。输出OWNED_BROWSER_CLOSED和OWNED_JOB_EMPTY_AND_BROWSER_OUTPUT_CLEANED。最终strict／Prettier／3文件21项Node在该源码修正后再次通过。

本限定分支实现／必要隔离检查完成。仍未执行真实供应方、正式CHECK_DRIVER／SYSTEM／WFP／用户部署和真实OpenCode TASK最终收尾；C39非六类控制变更仍留后续。

## 最终生产源码状态定点

本轮19个后端／5个前端生产文件，共24个；以下路径排序后逐行以“路径 空格 文件SHA256 换行”拼接UTF-8，再算SHA256：7799c4afe0bc7b991821e6333dc96f0f4ca809debc08b221c6c0e8a6bf403b78。仅作本轮生产源码现场复核，不覆盖测试／文档，也不等于Git提交。

```
backend/app/code_tasks/coding_model_listener.py
backend/app/code_tasks/coding_model_wait.py
backend/app/code_tasks/repository_registration_worker.py
backend/app/code_tasks/task_budget.py
backend/app/code_tasks/task_check_api.py
backend/app/code_tasks/task_configuration_apply.py
backend/app/code_tasks/task_configuration_effective.py
backend/app/code_tasks/task_configuration_live_records.py
backend/app/code_tasks/task_configuration_progress.py
backend/app/code_tasks/task_initial_configuration.py
backend/app/code_tasks/task_instance_driver.py
backend/app/code_tasks/task_live_configuration.py
backend/app/code_tasks/task_model_ingress.py
backend/app/code_tasks/task_native_issues.py
backend/app/code_tasks/task_project_check.py
backend/app/code_tasks/task_read_api.py
backend/app/code_tasks/task_runtime_stop.py
backend/app/code_tasks/task_start_session.py
backend/app/code_tasks/task_verification_reads.py
frontend/src/api/code-task-configuration.ts
frontend/src/api/code-task-creation.ts
frontend/src/code-tasks/configuration-control.tsx
frontend/src/code-tasks/resume-control.tsx
frontend/src/code-tasks/workspace.tsx
```


## 收口补验

最后配置服务未就绪提示先发生一次自动审批超时（未执行，按工具允许重试一次成功启动）；首次执行35.67秒未通过，因为原C39本地记录尚待读取原操作，界面正确优先提示核对原请求。专项改为先GET核对该原操作并结清本地记录，再改变隔离worker就绪状态，不清IDB、不忽略断言；LIVECONTROLDISABLED2最终1项25.62秒通过。实际HTTP配置／预算、UNKNOWN／APPLIED、服务未就绪禁用及title、恢复服务和360／1280均覆盖，C39／预算各POST1、LLMUse0。

最后生产源码／必要专项均已保存；strict／Prettier、Ruff格式485文件及变更模块lint通过，Git diff --check通过（仅既有application-router.test.mjs换行提示），六份本轮Markdown本地链接无缺失，源码原子临时文件0，非__init__零字节源码0，产物dry-run JSON=0／截图0。正式设计摘要、master／28a7c9e保持；正常服务未更新。当前限定分支完成，未覆盖范围保留于映射及当前断点。


19:28最终服务复核使用Windows原生netstat -ano -p tcp，8000／5173／5174的LISTENING数量为0。此前PowerShell CIM静默输出不能独立作无监听证据；补试socket在沙箱为10013、隔离放行为10035，均未作为“端口关闭”证明，最终以原生TCP清单为准。未发送HTTP请求或启停服务。本轮17:28—19:28连续约两小时，代码／文档和断点已保存。
