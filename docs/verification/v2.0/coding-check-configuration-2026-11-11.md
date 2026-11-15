# Coding运行中检查标准应用验证

2026-11-11香港21:38启动新两小时任务。master／28a7c9e，Git工作区421条折叠记录，保留其他修改。BE／FE摘要与上轮相同，DRAFT与Schema200 db20-r44状态不变；24个上轮生产文件聚合摘要7799c4afe0bc7b991821e6333dc96f0f4ca809debc08b221c6c0e8a6bf403b78与上轮记录一致，未据历史通过代替新结果。原生netstat确认8000／5173／5174无LISTENING项。

先完整接续AGENTS、当前断点／计划／映射，读取本批APP-CODE-CONDITIONS、检查标准／结果失效、角色前缀、7.6和FE配置规则及原检查选择／项目准入／C39调用路径。先写独立pending；新增实现尚未验证。相关离线专项沿自有TemporaryDirectory、tools.quality_gate.environment和tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short，结束清理。真实供应方、正常服务／库、SYSTEM／WFP及Git提交推送均未授权。

## 已完成的首批检查（香港21:55起）

- 原配置基线（CHECKCFGBASE，改动前）：原C39接收及连续采用5项，51.37秒通过。
- CHECKCFGNEW5：新CheckSet六参数、CheckSet完整内容及原C39接收共87项，97.96秒通过。覆盖新版本采用、UNKNOWN同原操作恢复、资源撤回恢复、无实际准入／空集合／仅未来角色拒绝且授权不绑定。逻辑候选及原生只读驱动是离线夹具；不是实际封存包／供应方证据。
- 实施时发现严格canonical_input不接受dataclass的嵌套tuple；实际修复将项目准入快照中的runtime_refs和argument_template显式投影为数组。未放宽确定序列化，也未假造EFFECTIVE授权。此前失败及夹具完整定义序列化修正不计通过。
- 新发布后恢复／前端展示保存后strict与npm run format:check通过；后续修改仍需最终核对。真实Guard与原状态回归正在独立临时目录执行，尚未有结果，不提前标通过。

## 后续结果（香港22:12）

- CHECKCFGREG：新检查配置及原C39接收／13类活动配置状态回归，27项281.87秒通过。
- CHECKCFGBOUNDARY：新检查配置9参数102.40秒通过，新增实际部署准入manifest摘要变化、核对前／中STOP；两STOP均终止清理核实、原C39取消、新授权APPLY_FAILED。STOP的原生清理仍为专用驱动夹具，不替代正式Guard任务停止。
- CHECKCFGGUARD：PROJECT_CHECK_HANDOFF 1项704.80秒通过。真实Windows认证Guard／固定命令／NTFS／SQLite，初次采用新CheckSet后重新检查保存新profile／CheckSet／配置应用证据；原两次角色交接、同角色修复／取消／捕获、Integration发布后再采用新CheckSet、原三阶段项目检查成功回AWAITING_TESTING。当前候选／原发布操作及发布时间完全不变；未增加Testing任务。模型原生消息仍是定向离线夹具，未调用真实供应方。
- 前端契约3文件21项通过，新增待测试／待接收配置动作合法与错误身份／原因码拒绝。首轮沙箱执行测试全过但清理外部临时目录遇WinError5；后续精确核对该本轮目录已不存在，在完整隔离权限下复跑21项正常退出并确认TemporaryDirectory清理。不把首轮整体命令记通过。
- 后端479生产文件Ruff格式通过；新改7个生产模块／3个测试辅助lint通过。扩大到旧Guard大型辅助时发现原有SIM117，不修改该无关区块，不声称旧文件整份lint已过。
- 正式7.2内容策略完整复读确认：capture_rules及容量沿固定内容版本，普通运行配置不能更换；维持原C39拒绝，不将它当成待随意放开的热换能力。后续仍需核对非内容检查限制及原生权限／在写受控停止。

## 检查输出限制与固定内容（香港22:21）

- 首次实际HTTP／CLI Chrome旧控制／新CheckSet双参数：2项39.89秒通过。实际SPA临时构建、FastAPI／Schema200、C39／C40／回执，丢202刷新恢复、UNKNOWN及一次POST、工作进程未就绪提示、目标检查版本已显示；原生观测和逻辑候选是夹具。关闭Chrome／Job／本地HTTP及删除临时构建后结束。
- CHECKOUTPUT：新输出上限／仅授权收紧／空检查集，及旧检查标准、STOP、撤回／恢复、原C39接收共16项163.46秒通过。原步骤保存实际较小值，未知不采用，恢复保留原身份；只授权变化时原profile和CheckSet不变。
- FIXEDCONTENT：两项固定内容容量／选择规则拒绝及原未启动C39接收4项，共6项54.22秒通过。有效不适用配置返回409 PRECONDITION_FAILED，新授权保持APPROVED_UNBOUND。
- 新检查输出单元接入后strict／Prettier和相关Ruff通过；实际Guard追加“profile上限128、授权上限64，原CHECK claim冻结64”正在执行。前端追加有效上限及固定内容禁用提示后的Chrome3参数尚未执行，不沿用前次UI证据。

## 最新实际联通及共享修复（香港22:37）

- CHECKOUTPUTGUARD 1项692.21秒通过：profile128／授权64进入原实际CHECK claim，随后原角色／修复／发布重查链，尚未含后加的真实1字节输出超限和内容授权修复。
- CHECKOUTPUTCHROME 3参数57.69秒通过，实际目标检查／输出上限、固定内容变更禁用，后续原C39／C40／恢复全链；产物与进程清理。前述39.89秒是旧双参数，不替代最新结果。
- 内容授权修复首轮CONTENTGRANT：文件1字节实际被阻断，但检查仅匹配顶层错误文字失败，12.79秒。已改为核对底层原异常链，未改生产为允许超限。后续CONTENTGRANT2及最新Guard仍在执行。
- 发现旧正常NTFS／Guard夹具的授权清单／Git输出容量100低于预期完整包；其profile预先提高但授权未同步。正常夹具现明确批准对应固定内容容量，另保留1字节授权负例。产品原授权／数据库不调整，也不做profile回退。

## 23:05 中间保存

- CONTENTGRANT2真实NTFS三项64.52秒通过：文件／清单授权1字节拒绝，正常候选C39后原退役授权历史可读。随后把确定失败接原worker：CAPACITYFAILURE三项99.45秒通过，Task／Operation GET正常、无候选，原步骤SUCCEEDED／FAILED／CANCELLED／CANCELLED，无自动重试；正常原NTFS／C39历史仍通过。
- CONTENTREG候选提交／报告／交付事务／内容清单／修复来源46项148.02秒通过。CONTENTPROOF2原授权较小值／退役历史／归属／不可变事实7项69.78秒通过；首轮试图篡改成功来源被Schema ORIGINAL_FACT_IS_FIXED拒绝，修正测试为核实真实保护，未关闭触发器。
- CAPACITYCLASSIFY 7项1.10秒通过；可信容量类与映射可识别，普通OSError文本、未知读取、嵌套retained_owner及循环异常拒绝确定失败。新增版本／opaque seal／未知命令／STOP竞争的真实NTFS门槛正在执行。
- FINALC39REG 35项394.15秒通过，含原控制／新CheckSet／输出上限／固定内容拒绝／STOP及原未启动配置。四个前端相关Node文件31项通过，临时目录正常清理。
- CHECKOUTPUTLIMITGUARD 1项737.47秒通过：实际较小内容授权、新输出1字节的FAILED／OUTPUT_LIMIT及64字节恢复，再角色／修复／发布后重检；不包含后来Git单次deadline见证。
- CONTENTDEADLINEGUARD首轮101.54秒失败于夹具把另一个嵌套目录场景的11条命令数量套到当前平面文件。已改为必须实际观察到内容Git调用，每个调用仍严格验证deadline≤15.1秒，不改变产品15秒上限；CONTENTDEADLINEGUARD2执行中，未先记通过。
- 独立CHECK_DRIVER本轮仍无可信帧，详见[专项](testing-browser-driver-2026-11-11.md)，不借普通Chrome或清理成功替代正式准入。

## 23:13 补验

- CAPACITYFENCES 11项57.85秒通过：实际NTFS明确容量错误下，版本改变、opaque seal、UNKNOWN命令或STOP先到均不转确定失败；原未知操作保留、不得自动重读源。
- CAPACITYDTOS首轮13.48秒失败于Node --require相对路径被当模块名，前端断言未执行；已使用项目绝对预加载路径、固定Node及明确cwd，没有修改解码规则。
- CAPACITYDTOS2 7项87.37秒通过：真实Schema200／NTFS／MinGit容量失败及5类未知门槛，公开Task与原Operation HTTP返回由前端decodeTaskView／decodeCaptureOperation实际解码（JSON仅内存／stdin）；包含后台取消，确定失败后可明确终止且旧FAILED历史不改。没有另存JSON结果或放宽字段。
- 当前生产源码481文件格式及本批15个后端模块／5个相关测试辅助lint已通过。新失败收尾先核对原进程锁；缺开始时间、版本／代次／停止栅栏异常、未知命令／保留资源或封存标记均不做确定结案。

## 23:26 收口核对

- CONTENTDEADLINEGUARD2 1项783.38秒通过：真实内容Git调用逐项观察到deadline≤15.1秒，产品取授权15秒；后续完整原输出超限／恢复、角色／修复／发布后重检和收尾完成。之后仅增加本地失败／所有权的异常分支及其专项，不把该Guard当成所有后加故障场景的替代证据。
- 完整tasks CLI回归正常退出：全局Coding导航360／1024、原C39 360／1280及一次写入，任务页360／1280覆盖成功空态／失败重试／占用、原请求恢复、代码历史／UTF8、自检分页、预算、原继续与问题权限、角色发布及停止。API由离线夹具响应，不冒充实际Guard或真实供应方。OWNED_BROWSER_CLOSED、OWNED_JOB_EMPTY_AND_BROWSER_OUTPUT_CLEANED，未留原始JSON／截图／日志。
- CAPACITYOWNER2 10项37.53秒通过，含所有权断言失效时不得把原RUNNING改FAILED或UNKNOWN、确定失败、后台取消及分类。该所有权失效为隔离模拟，不是物理双进程接管验收。首次未保存完测试参数即执行的选择器报not found（2.08秒）保留为未执行该目标，不记通过；实际源码原子替换未留半文件。
- Python3.13.5／Node24.15.0／Ruff0.17.3、固定SQLite3.54.1；项目锁定依赖、Schema、正式资源未修改。前端strict／npm run format:check通过；相关生产模块及新测试辅助Ruff通过。扩大到旧capture大测试文件时，原有fixture F401／F811、旧导入顺序／闭包及SIM117未改；本次新增局部导入已修正，不删除pytest fixture，也不声称旧大文件整份lint全过。
- 原HEAD仍28a7c9e13c73a9d386081a6dd894244b51746a45，折叠Git状态421项（不能作为完成计数）；正式BE／FE摘要与开轮完全一致。原生netstat8000／5173／5174监听0，非__init__空源码0、原子临时文件0。新归档的一条同目录计划链接已重定位，待最后链接／产物核对。

## 当前保存代码摘要（23:32）

本轮原子写入涉及下列18个生产源码，聚合SHA256为e31a8189eb13ee8427cca729adb368b0ba1073bbdacd3e637939285daaa0d6e6。算法：按下列相对路径字典序排列，依次UTF-8路径、NUL、文件原字节、NUL后累计SHA256；保留原换行，不把18文件组与开轮24文件组作不同集合的完成对比。

| 实际源码 |
| --- |
| backend/app/code_tasks/coding_check_plan.py |
| backend/app/code_tasks/task_configuration_apply.py |
| backend/app/code_tasks/task_configuration_checks.py |
| backend/app/code_tasks/task_configuration_effective.py |
| backend/app/code_tasks/task_configuration_live_records.py |
| backend/app/code_tasks/task_live_configuration.py |
| backend/app/code_tasks/repository_registration_worker.py |
| backend/app/code_tasks/task_content_limits.py |
| backend/app/code_tasks/task_candidate_commit.py |
| backend/app/code_tasks/task_candidate_runtime.py |
| backend/app/code_tasks/task_delivery_plan_runtime.py |
| backend/app/code_tasks/task_delivery_reads.py |
| backend/app/code_tasks/task_candidate_git.py |
| backend/app/code_tasks/task_capture_failure.py |
| backend/app/code_tasks/task_candidate_worker.py |
| frontend/src/code-tasks/configuration-control.tsx |
| frontend/src/api/code-task-creation.ts |
| frontend/src/api/code-task-configuration.ts |

本轮10个相关测试／辅助源码聚合摘要47dd6e86147ed83e2bec2479a0217d21e7ee65dbbf03663e6fbb53dd8f7dc5f2，算法相同：backend/tests/code_tasks/下test_task_check_configuration.py、test_task_live_configuration.py、test_task_content_limits.py、test_task_capture_failure.py、test_task_capture_quiescence.py；backend/tests/infrastructure/下test_v20_live_control_http_browser.py、v20_live_configuration_worker.py、v20_guard_control_git_pipe_worker.py；frontend/tests/v20-code-task-creation.test.mjs；tools/verify-v20-live-control-http.mjs。额外测试导入排序仅排版，不改变业务断言。

最后静态核对：481个backend/app文件Ruff格式、前端npm run format:check及tracked git diff --check退出0；后者仅提示其他既有文件CRLF，下次Git处理可转LF，未为此改写该文件。工具dry-run JSON=0、screenshots=0。10份本轮管理／迭代／验证／归档文档内部链接缺失0，最新映射行均6列；本轮已知前缀的自有临时目录剩余0。未提交／推送、未更新正常服务／数据，所有失败与夹具边界按上述原记录保留。

## 23:37 最终保存

本轮自香港21:38推进至23:37，上述18个生产及10个测试辅助文件摘要均再次匹配，未新增源码变动。16份关联Markdown链接缺失0，最新映射8条业务行均6列，当前断点已列出已读设计、原生权限应用的具体调用缺口及尚未覆盖证据；旧映射的范围限定已注明由本轮条目补充。文档仍pending，不合并正式设计。最终自有原子临时文件0、工具dry-run JSON／截图0；没有运行中或待取结果的检查，不留半成品函数。其他既有改动保留，HEAD不变，正常服务及业务库未更新。
