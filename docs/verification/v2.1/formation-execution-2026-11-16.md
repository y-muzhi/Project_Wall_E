# V2.1实际讨论保存、发布与精确采用

日期：2026-11-16；独立工作区HEAD a0f40592702cb702ed928849ac540479c22c224f及本轮未提交实现。固定Python3.13.5／SQLite3.54.1；本轮不触发真实模型／计数，不更新用户服务或正常业务库，不提交推送。

## 已完成的离线证据

所有Python专项用tools/python-v20.py tools/quality_python.py指定下列文件，参数-q -p no:cacheprovider --tb=short --basetemp独占临时目录；tools.quality_gate.environment隔离数据／缓存／计数审计。测试结束只留本Markdown。受限Windows异步事件循环曾超时，因此相关实际异步专项在正常本机权限下运行；仍仅临时数据库、离线Counter／Gateway。

| 实际范围 | 命令目标文件（backend/tests/formation/） | 最终结果 |
| --- | --- | --- |
| 纯模型规划／来源／临时域与完整图 | test_v21_model_plan.py | 8通过，37.37秒 |
| 原C01／共享人工路线与Closure回归 | test_v21_discuss_acceptance.py、test_v21_path_commands.py、test_v21_completion_commands.py | 23通过，94.65秒 |
| C07普通结构整组保存／拒绝／初始化／评估／建议 | test_v21_model_results.py | 与初版发布合跑12项中的7项全部通过；该次合跑10通过／2发布夹具问题，见下 |
| 真实新卡来源、未来路线不耗编号、全局D不使原卡失效、暂缓／恢复及重放 | test_v21_model_publication.py | 修正夹具后5通过，74.75秒 |
| 原C06精确写入／路线采用、真实正式回答、源码与审计来源、关联、成功重放及故障全回滚 | test_v21_card_apply.py | 4通过，80.58秒 |
| MATCHED／UNVERIFIED／REASSOCIATED实际关联复核与lineage | test_v21_model_associations.py | 3通过，29.68秒 |
| 实际ASGI→WalleApi／生产decoder，写入／路线两分支；原调整接受／取消保留／撤回凭证／成功新卡替代／失败保留 | test_v21_workflow_wire.py、test_v21_proposal_adjustment.py | 5通过，112.18秒 |
| 共享前端既有回归 | frontend npm test | 607通过，0失败，5.998秒；加入新workflow解码／来源／卡片controller后执行 |

第一次结果保存专项6通过／1夹具失败：夹具本有两份文档，改为仅核对目标文档Revision数。第一次发布合跑10通过／2夹具失败：旧辅助执行器固定Run1导致第二轮未执行；原生命令错用了command而非discussion_command。均改为实际Run ID及原严格输入后重跑通过。调整替代首轮还暴露实际选材遗漏：未显式选步骤时原提案目标定义未发送，现作为用途硬材料冻结；随后只剩D预期误算，修正为C01及C07各一次D后5项通过。前端首轮有循环初始化错误，改为调用时解析共享引用；之后607项通过。

## 实际行为

- 模型返回必须绑定真实已完成LLMUse／接受依据与计数快照。普通DISCUSS全九根、进展、主线和卡片先纯校验，非法整组拒绝；可读原返回及pending保留。独立旧GENERATE／REVISE规则保持。
- 纯规划不持久化、不耗实体序号；C07只用真实assistant与GuideRun记录事件来源。初始化F1，同事务D/F各最多一次。
- 新提案的原Markdown／补丁保留；STAGED_WRITE绑定同轮已实际建立的Step/Result。路线卡保留未来TempRef，采用才分配。PublicationBinding在独立不可变索引，不发模型或浏览器。
- 原C06新用途先分派，不用全局D／最新消息判失效。采用只接原正式回答，程序按原payload生成本次窄授权，沿共享commit_content和完整路线引擎，不创建虚构Run／Batch或新增Chat。
- CARD_RESPONSE块署名USER，source_id指向实际正式回答；服务端同文档核对原AI卡消息ID／card_key／response_message_id。Revision保留原消息及CARD_ANSWER来源，内容审计另有完整来源描述。前端来源类型支持卡片采用。
- 故障注入在正文提交后／关联保存前抛错，正式回答、正文、版本、关联、处置和回执均回滚；同原请求解除故障后成功。
- 原提案调整标记、撤回凭证及SUPERSEDED均真实事件；撤回不替换原binding，失败新卡不废弃原卡。

## 资源与后续检查

显式V2.1资源已从v23／v24演进到v25／v26（CARD_RESPONSE来源），当前继续v27／v28（支线原始触发来源及相关OPEN支线完整选材）。历史候选原字节保留，旧默认v17／v18保持。新资源均OFFLINE_READY，不能复用旧LIVE。当前最新继续／重试及v27／v28专项正在执行，未提前算通过；资源与最终摘要在后续追加。

本记录不表示完整UI、布局／按钮／浏览器、IndexedDB升级、服务切换、供应方兼容／语义效果或整版验收完成。旧run9异常及SYSTEM Guard暂停保留用户已接受边界。


## 后续最终专项（2026-11-16 18:28）

| 命令目标（后端文件均在backend/tests/） | 实际结果与边界 |
| --- | --- |
| formation/test_v21_discuss_continuation.py＋test_v21_model_results.py | 最新10通过96.86秒：采用后新来源、失败有／无原返回、原输入重用、初始化及整组拒绝，离线 |
| formation/test_v21_proposal_reads.py | 2项通过；完整total、内容失效、暂缓／恢复；与早期跨端夹具合跑时该两项通过 |
| formation/test_v21_workflow_wire.py | 最新2通过61.63秒；真实ASGI发布／采用／Run／消息／提案页经真实WalleApi解码 |
| formation/test_v21_card_apply.py＋test_v21_model_context.py | 11通过／2补丁夹具失败151.49秒；补丁修正后2通过91.43秒。旧helper固定Run1，已换实际第二个Run；PATCH_EXISTING及同正文分支验证区块身份、高水位、版本、关联、正式消费和原key重放 |
| context硬选材 | 上述context共7项通过；调整提案涉及的其他步骤，其阻塞事项／活动成果先于可省略材料入选；硬材料超限整次拒绝 |
| formation/test_v21_model_plan.py -k path_publication | 1通过5.87秒；依赖身份可引用，修改定义／成果／取消／关联须有完整已发送定义，不以依赖ID扩大权限 |
| formation/test_v21_independent_operations.py | 首轮2夹具失败／1重试通过69.68秒；按真实目标design修正误填brief后，其余2项通过56.29秒。真实发布→采用→REVISE，合法正文不被非法formation_delta撤销，retry保留原operation／用户消息，continue才转新讨论 |
| formation/test_v21_startup.py＋infrastructure/test_v20_startup.py | 原200入口及拒绝共3项通过39.12秒（该次合跑另1夹具失败）；显式210真实HTTP最后1通过10.33秒；原生新进程1通过7.39秒。修正夹具错误名／路径及FastAPI内部路由断言，改实际ASGI；产品规则未放宽 |
| formation/test_v21_resource_release.py＋guide/test_v15_cards.py | 25通过54.61秒；新资源与原卡回答／暂缓／独立写入／并发共享回归 |
| guide/test_v15_execution.py -k "revise_commits or invalid_main_result or retryable_transport_failure or document_storage_failure" | 4通过37.07秒；旧独立结果、合法进展、无隐式重试及存储全回滚保持 |
| frontend node --test tests/formation-workflow.test.mjs | 6通过489.74ms；body/key冻结、恢复归一化、损坏回执UNKNOWN、安全冲突、提案可用性和私有字段拒绝 |
| frontend npm test | 最新613通过、0失败、7.528秒 |
| frontend npm run format:check；npm run build -- --outDir 独占临时目录 | 通过；tsc严格检查＋1414模块构建成功；未覆盖frontend/dist或更新用户服务，临时构建清理；既有大chunk警告保留 |
| python -m ruff format --no-cache --check backend/app | 585文件通过；后续新增reference_context已原子保存并格式化，收口再查 |

Python专项仍用本页前述固定运行器、-q -p no:cacheprovider --tb=short及临时basetemp。不同轮次分别记结果，不合计冒充一次全量通过；保留早期失败及修正原因。

### 生产卡片组件的浏览器检查

已有缓存Playwright CLI0.1.23、本轮独占浏览器profile／daemon及本轮自有5187 Vite，未复用用户浏览器、5173或业务库。fixture位于frontend/tests/browser/formation-proposals.html，只提供UI状态；生产InteractionCardsView、真实WalleApi、Markdown parser和RequirementDocumentOwner实际运行，不把fixture当真实业务发布证据。

390×844及1440×900均document.scrollWidth等于窗口宽；正常按钮316×36，长正文／代码／三类补丁／表格匹配／删除说明／替代及ResultRoute承接可读。READY、人工占用禁用（显示原因）、SUBMITTING、历史RESOLVED无写按钮；模拟传输失败后实际UNKNOWN，原选择保留且显示原请求核实入口。页面0 Console error、1开发提示warning；截图已实际查看。自有浏览器／Vite及临时截图日志目录均自动清理，13478退出0。未覆盖整个新主线页面、全部空态、浏览器DB升级或真实HTTP浏览器联调。

### 资源、来源和显式启动

显式形成资源v27标准／v28长输出；旧v17／v18默认及v19—26候选原字节保留。全部新资源OFFLINE_READY，无LIVE／真实模型证据。v27 manifest=6afecca289a6369d94abe5d1a9c03ca7f6ff479d6cb4c2c25bff591fd1f3208c，release=e5e0860a49812006f72d6f0de3f7d3c06420d87b8e7a45f683d9e50d52769bfe；v28 manifest=2bc51b4e8b90602331dadcb750743ab4f835d3d6ed83c7e2a4048523df53cc44，release=9f6f94b4763b95c1424266acaa5cd0abbd7427d3e47ecd93d01132c9791d268a。

create_app(schema_version=210)及python -m backend.app --schema-version 210只选择并验证已存在目标；默认200不变，无自动初始化／升级／切服务。新core/db20-r53 manifest=9f1fecc38285362ec8fe5d45bbecf15ef1aa2b2c21f2081de1fd643799e238d4；target Schema210/db21-r4 manifest=819103b97a69857fa114cf15b8ecdc27d67d780d82b4d5d49bba43fbdd8a4400；target DDL合同f3f29931a176cbb64effa63fad516280120711a472f4e59a246a9683df9e0b78未变。旧包不改。

实际只执行python tools/ai-service.py及加--schema-version 210的两次无--start检查，均credentials_read=0／database_opened=0／provider_calls=0／service_started=0。新mode打印formation_context_v21_1与db21-r4，旧mode仍collaboration_context_v1。独立非DISCUSS已用新release修复新CARD_RESPONSE正文读取；旧历史release遇其仍明确拒绝。

仍待：新主线实际页面／完整显式目标和命令owner、同IndexedDB物理DB2／记录5恢复、源只读→全新目标升级／切换工具、整版性能／交互和供应方语义。旧UI的普通DISCUSS尚未切换TargetSelection。本组件及离线检查不表示整版完成。


## 收尾补查（2026-11-16 18:39）

- 独立修订收到新用途卡不得发布该卡、合法正文仍保存：test_v21_independent_operations.py -k proposal，1通过29.21秒。原card index未新增、assistant无结构卡、实际正文V3保留；后续继续仍为新DISCUSS。
- 发现并修复新提案临时占用被I35错误投影EXPIRED、导致前端清本地选择的问题。仅新用途移除“占用即失效”，原binding／实际C06及ProposalView availability仍拦截占用，不放宽写权限。test_v21_proposal_reads.py -k temporary_ai两用途最终2通过50.33秒；原轮误向cancel传catalog导致2夹具失败50.13秒，已改原命令参数，不改产品取消接口。
- frontend/tests/formation-workflow.test.mjs新增占用中禁止prepare、保留选择与本地记录、关闭重开及恢复后可用检查；专项最终7通过511.30ms。随后完整npm test：614通过、0失败、6.945秒。
- 后端585文件格式终检通过，git diff --check通过；七份本轮进度／映射／证据文件的相对链接无缺失。pending BE／FE SHA256仍分别4049f8d3b5d01bd704dd0439b8c0730155cec813f3f5ef8ef7ad8c5ba5b5b197／0f54539980b07dab5abae33d679339e1bef898c651882a774f1aa25dc58d9cee，未自动合并设计。
- core/r53及target/r4由实际load_release重新验证来源pin通过，合同未变；cleanup-test-artifacts.py --dry-run为JSON=0、screenshots=0。本轮自有5187无监听，浏览器及临时产物已清理；未修改正常库／用户服务或提交推送。


### 附加代码规范检查（18:43，未全绿）

执行python -m ruff check --no-cache --config ruff.toml backend/app/formation backend/app/service.py backend/app/__main__.py tools/ai-service.py。初始72项：46条I001、6条循环闭包B023及20条其他规范提示。已用同目录临时文件fsync／os.replace规范formation新包40个文件导入；native_contracts的kind、proposal_binding流式生成器的sql／parameters／name／ref显式绑定，未改业务计算或放宽检查。

补查还剩24条：I001=4（既有启动入口，涉及来源pin，不在本次末尾再机械发布），RUF059=7、ISC004=4、BLE001=3（公共读取边界返回安全INTERNAL_ERROR）、PLC0414/SIM905/TRY004/PERF102/UP035/C401各1。该扩展lint未通过，不把它写作静态全绿；本轮约定的Ruff format585文件、前端类型／格式／构建和已有业务专项是各自已通过结果。后续先完成规范清理、核对边界异常策略和所需新pin，再推进产品UI。未使用ignore／关闭规则或直接覆盖源码。


闭包／导入修正后的实际最终回归：formation/test_v21_proposal_binding.py、test_v21_contracts.py、test_v21_model_results.py共38通过、0失败，65.25秒；1394退出0。此后无业务源码修改。只读进程核查没有本轮匹配的Python／Node测试或5187服务遗留。扩展lint仍为上述24项，不覆盖或改写为通过。

本轮约三小时工作量于18:45（10:45 UTC）在完整单元收口，整版继续进行；当前无待回收专项、自有服务或临时测试产物。代码／计划／映射／独立技术迭代及断点已保存，未提交推送、未自动合并正式设计。
