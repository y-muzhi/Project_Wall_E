# V2.1并发与提交入口验收接续

开始：2026-11-17 14:08（Asia/Hong_Kong）；用户要求继续三小时工作量。独立工作区codex/v2.1-design-review，HEAD a0f4059及连续未提交实现。范围为已有设计下的代码、隔离离线专项、类型／格式／临时构建及必要浏览器；不真实调用模型／计数，不操作正常业务库／服务，不合并正式设计，不提交推送。

输入：前后端0.1-draft-4／大纲0.12，沿上批固定SHA；优先A54、A64—A69，按具体行为核对，不以文件存在或整组通过冒充全部变体验收。旧run9与SYSTEM Guard事项继续保留。

当前结论：本批功能与必要离线/浏览器检查已完成，新增48项分组、前端650、最终13例串行加1例跨文档补查通过。版本仍待剩余产品验收及真实供应方证据。

## 批次计划

1. 原C01冻结／RESUME消费与C07成功、结构拒绝、模型失败、取消组合：核对当前支线、旧结果历史、父步骤生命周期、消息／版本／幂等与后续ENTER。
2. 核对六正文入口受影响／无关范围维护及事务；补缺口并实际执行相关专项。
3. 需要时补实际页面交互与可用状态；最后汇总实际证据、同步映射和持久断点。

以上为开工计划，实际已执行的范围及结果分节记录如下。

## 支线真实事务矩阵

新增test_v21_resume_terminal_matrix.py：2种支线状态（已有结果／暂缓）×3种父步骤（进行中／暂停／已结束）×4种本轮结局（有效返回／非法结构／模型失败／取消），共24 passed，197.70秒，1条既有Starlette弃用提示。旧结果由真实C01/C07建立，暂缓及父生命周期经原程序命令建立，没有直接伪造成功返回。

逐组检查：C01接受恢复后转ENTER且清当前结果；原不可变结果事件逐字保持；只有有效返回写新结果；失败、取消或结构拒绝不撤销已接受的恢复，不重开已结束父步骤、不增正文版本；同key重放无第二次影响，旧RESUME新key被拒绝，仍OPEN时下轮ENTER不再次清理。暂停父步骤在实际发送时按设计恢复，已结束保持已结束。全部临时数据清理。

首次受限方式子进程仅6.67秒CPU后停滞，核实所属PID195132后仅停止本轮测试子树，外层清理；改用本地连接可用环境并保留quality_python保护后上述完整通过。测试最初复用会断言AI_FINISHED的成功辅助函数，不适合模型失败分支，已改为直接调用生产execute_guide_run，未改变产品以配合测试。

## 既有正文入口的影响范围

新增test_v21_existing_entry_maintenance.py：事实确认及建议批次，各相关／无关区块共4 passed，33.58秒。走原C01、离线Counter/Gateway、C07、原卡确认或建议决定／完成；相关区块更新真实ARTIFACT_CHECKED并保持原始Revision，无关区块不增F、不改成果或范围；每项只有1个Run／LLMUse，提交原key重放无二次效果。

新增test_v21_revision_scope_maintenance.py：原REVISE在DOCUMENT／BLOCK范围各相关／无关，共4 passed，29.29秒。实际受影响成果才增F并待复核；无关范围保持成果及原范围，所有正文提交V1→V2，1个Run／LLMUse。上述为生产事务／离线集成证据，未换算成六入口全部浏览器组合通过。

## 后续范围与实际页面证据

原STAGED_WRITE的PATCH_EXISTING新增相关／无关两项，2 passed，50.51秒；原C01/C07形成卡片后按原精确内容采用，原关联只在实际受影响时待复核，原始Revision保持，原key重放不写第二次。计数及模型均为离线替身，每项1个Run／LLMUse。

1001节点读取夹具从a1／a501／a1001分别跨51页，共3 passed，28.35秒；每页≤20，前后继、唯一活动末端、计数与全链身份完整，未写业务状态。读取段分别7.273／3.851／3.864秒，仅本机一次观测。明确这是SQL前置读取夹具，不是1000轮真实C07／完整历史形成证明，前轮真实四节点链证据继续独立保留。

完整产品实际支线恢复后发送ENTER讨论，在Gateway暂留时选择s2、输入新文字；释放离线返回后，服务端直接轮询确认COMPLETED／APPLIED，原Run accepted_target仍s1/b1，页面next_target仍s2且新输入不丢。初次页面异步等待后读到RUNNING，因此未算通过，改用服务端终态与页面回执双核实后通过；不能把首次等待误判换算成产品业务故障。新检查工具保留为tools/verify-formation-concurrency.py。

实际支线RESUME丢回执→UNKNOWN→整页reload→原请求核实通过：原body/key逐字一致，pending0，本地意图ENTER、resume_basis=null。没有新Chat来核实原程序命令，临时环境全部退出清理。

双窗口支线变更：本地先明确继续，另一窗口真实暂缓后，首次发送因旧讨论绑定先在只读预检停止，显示重新读取状态且保留输入；明确刷新后仍按旧ENTER发送并被STATE_CONFLICT拒绝，没有隐式恢复。再次明确继续才恢复，输入保持，实际1条被拒绝POST、pending0。该用例预期冲突，不报告为零Console错误。初次脚本误把HTTP成功封装当带code的内部结果、误假设所有拒绝直接到POST及诊断window作用域，均只修正检查，未改产品迎合测试。

## 分页实际复现及修复

实际31支线列表从第二页11项遇到真实PAUSE后的F更新，再刷新主线：当前实现正常回到首页20项，未发旧游标／新F组合，未出现错误。最初静态怀疑的通用FormationPage游标问题在这一生产调用路径未复现，故没有改通用分页。该证据不扩大成所有调用方都无游标问题。

结束表单则已实际复现：31条步骤依据翻到第二页11项，选中1条后，另一窗口通过真实SET_GOAL将引用缩减为2条，表单明确重读保留选择；原页面显示共2条但0行。已在evidence-picker.tsx按当前候选数量约束显示页和前后页动作，保留原选择、不发送任何额外写入。相同完整产品复验显示2行、已选1／100；明确核对当前版本后选择仍在。初次脚本使用不存在的summary路径及错误展开参数，修正为原详情expand=discussion入口；没有新增产品接口。

修改后前端649 passed（6.89秒），类型1.50秒、格式3.29秒、临时生产构建1.38秒，全部通过且临时输出清理。未为简单页码公式新增镜像单测，保留真实复现／回归用例。

## 用户确认480px及窄窗实际接入

用户通过本轮问题回复明确选择“按2.1设计支持480px，复用现有单面板布局”。决定和实现边界见[独立接续](../../iterations/pending/v2.1/WALL-E.窄窗工作台实施接续_V_2.1.md)，未合入正式设计。

DetailLayout／DetailViewportGuard共用minimumDetailWidth=480；原即时冻结／保存、恢复后实际重读、失败及重试流程保持。更新原视口专项到479／480边界，新增单面板首选项保持专项；前端650 passed（6.11秒）、类型1.36秒、格式3.29秒、临时构建1.11秒通过。其后仅分栏CSS与检查工具改变，最终检查继续按影响补足。

实际480、899、900、932、964、965、966、1024、1440：所有观察尺寸均无页面／对话框横向溢出。修正前窗口900时可用内容834却已经双列；容器查询修正后内容899为单列、900为320＋16间隔＋564双列，契合5.1。长标题120字、目标1000字；窗口往返及479→480恢复保留新输入，0业务命令；实际人工保存的非空正文V2保持同一Milkdown DOM。480与966正常页面图片已实际查看，按钮和引用无重叠；图片及临时浏览器目录随后清理。第一次查看480图时读取仍在途，只按加载态使用；补等READY后的正常态另已查看。

480真实人工编辑：输入草稿即缩到479，实际后端草稿保存至版本2，恢复480后同一编辑器可继续且文字保持。明确取消后正式正文仍V2；浏览器只有POST开始、PUT草稿保存、DELETE取消，没有GuideRun／模型调用。首次脚本最后误从需求摘要读current而异常，改用原current-document入口后完整通过，未修改产品配合断言。

480真实历史：从文档记录查看V1，再读主线，讨论／结束禁用，title原因“正在查看历史内容”；退出后正式V2，0写。

真实Application路由／全局64px导航外壳另行复验：480视口，主内容416px，展开主线446px，整页480px无横向溢出，正式V2保持；不是只凭独立详情夹具推定应用外壳正常。

初次串行工具复验最后一步因复用同名CLI会话及未等页读取就定位而超时，工具改为每例独立随机会话、明确等实际读取，不把该轮宣称完整全绿。正在完成最终整组工具复验；其余等待及定位修正继续按实际范围保留。

## 补充原子目标边界与窄窗失败恢复

test_v21_target_boundaries.py最终8 passed，48.42秒：另一步骤焦点下接受完整OPEN／DEFERRED支线目标，只生成一个Run，F只增一次，另一未开始步骤保持；旧ENTER不能隐式恢复DEFERRED／DROPPED／真实C07已形成结果的RESOLVED；同状态不同state_event的旧RESUME以及返回点已变更均原子拒绝。拒绝前后完整业务、消息、Run、序列及幂等表均相同，无半开始／半恢复。初次夹具将MOVE_ISSUE字段误写step_ref，严格契约拒绝；改为既有to_step_ref后通过，不改生产契约。

窄窗读取恢复实际通过：消息列表失败不显示“暂无讨论”，刷新后恢复；真实conversation-messages来源读取注入一次失败，错误保留并可明确重读，已选1／100保持；对话框width=scroll=440，取消后0业务写入。初次定位到隐藏的“已选依据”来源及误注入/messages/，已按可见来源及真实conversation-messages路径修正检查。

原生200%缩放：独立临时Chrome profile建立default_zoom_level，观测DPR=2、outerWidth=1440、innerWidth=707、visualViewport.scale=1、CSS zoom=1；实际展开内容641px单列，对话框width=scroll=673，整页707，0业务写入。临时profile／配置及浏览器退出清理；没有改用户Chrome设置。最初选择未安装的Playwright Chromium，未下载安装，改用本机已有Chrome通道后通过。
缩放配置核对依据：[Chromium分区缩放首选项](https://chromium.googlesource.com/chromium/src/%2B/caa5e0d1c9d58de7bbcf686857034253d0a26ac8/chrome/browser/ui/zoom/chrome_zoom_level_prefs.cc)、[Blink缩放因子转换](https://chromium.googlesource.com/chromium/src/%2B/56612bfb3888402541aa5dfe7422425376f21b2e/third_party/blink/renderer/core/exported/web_view_impl.cc)。源码用于确定临时浏览器配置，产品结论仍来自上述实际观测。


## 完整业务旅程与最终消息读取修复

新增test_v21_complete_journey.py，1 passed，60.90秒：实际初始化并形成原STAGED_WRITE提案；仅向步骤2追加无关定义仍保持步骤1提案；原C06精确首写后结束步骤1并明确继续2；人工编辑使原成果待复核；对已结束步骤1进行原C01／离线C07重新关联，a1→a2；发布新精确补丁，纯焦点切回步骤2仍可对已结束步骤1原样采用，最后结束步骤2。最终正文V4、两步COMPLETED、需求PLANNING、文档未确认、两个Closure；旧Closure每行逐字保持，3个Run／3个LLMUse／3次离线Gateway。首次检查辅助函数处理原CRLF不当导致块数不符，改为保持原换行的定点替换后通过，没有修改产品迎合夹具。

窄窗精确补丁卡片进一步发现两处实际问题：提案范围显示把BLOCK当SECTION读取heading_block_id；消息结果投影的形成用途回退在每次校验重新构造完整ResourceCatalog，真实HTTP读取超时，进程堆栈停在固定资源加载及Schema校验。前者使用现有wireScope严格解析后分别显示整篇／章节／区块／选区；后者沿既有结构协议缓存模式，缓存同一固定形成协议，仍逐次验证卡片并实时核对可用性，不缓存业务结果或绕过字节准入。规则及不变量先记录到独立技术接续，未合入正式设计。

实际480px PATCH_EXISTING／BLOCK卡片已通过：显示“采用范围：区块 4”，选择单个apply没有提前发送；真实C06落库后注入丢回执，明确核实等待完整RESOLVED／非refreshing，原body/key逐字重放；正文只V2→V3一次，实际精确段落相符，卡组width=scroll=374、页面480。五个实际Vite模块均200、含关键实现与导出且非空。首次检查只等正式回答显示，早于恢复发送完成，误断言只有1个POST；补等真正RESOLVED后两个原请求一致。工具早前读取超时、进程诊断、此项等待修正均保留事实，不把失败轮算通过；临时环境finally清理。

消息复用新增test_v21_message_read_protocol.py两用途：连续20次回退只构造一次固定目录；原形成协议直接复用，旧FACT_CONFIRMATION协议保持；每次有效载荷严格校验，加入未登记权限仍拒绝。连同原model_publication及本批staged_scope_maintenance受影响回归，9 passed，98.27秒，1条既有Starlette提示。生产修改只有backend/app/messages/queries.py协议复用；没有修改正文事务或权限。

本批新增48项按独立分组通过（24＋4＋4＋2＋3＋8＋1＋2），不是一次48项整组结果，也不把前轮314加总为新的全量验证。最后一次前端全组650 passed，6.31秒；类型1.74、格式4.12、临时构建1.15秒，全部通过，临时输出清理。Python生产588文件Ruff格式检查通过；受影响Python代码F／I／B检查通过。固定前后端原设计／r54／r7／v27／v28六项原始SHA一致；生产资源加载器校验v27／v28全部内容及release摘要通过，仍OFFLINE_READY，旧v17／v18未修改。最终文档、产物与浏览器整组回收结果继续追加。


## 最终完整页面回收

最终代码下tools/verify-formation-concurrency.py --case all串行13例已完成，进程退出0，每例自有环境均清理；随后新增cross-document单例继续补验证，不把新增单例冒充已进入该13例整组。13例实际范围如下：

| 场景 | 最终结果 |
| --- | --- |
| late-result | 实际C07 COMPLETED/APPLIED，原s1/b1，新s2输入与目标保持 |
| stale-enter | 双窗口真实变更、旧ENTER拒绝、输入保持、明确继续，预期409单列 |
| cold-resume | UNKNOWN后reload，原body/key核实ENTER，pending0 |
| page-scope | 31支线页2经F变化正常首页20，不带旧游标 |
| picker-shrink | 31→2候选显示2行，已选1保持，模块完整 |
| viewport | 9尺寸480—1440，内容899单列/900双列、无溢出、同正文DOM、0写 |
| manual-viewport | 480输入→479即时保护，后端草稿版本2，恢复同编辑器，取消正式V2保持 |
| history-viewport | 正在查看历史内容为真实禁用原因，退出0写 |
| busy-viewport | 实际GUIDE_ACTIVE禁用原因、晚到原目标保持，同正文DOM，480无溢出 |
| full-shell | 实际Application路由含64px导航，480页面/416主内容/446弹窗无溢出 |
| narrow-errors | 消息与来源失败均显错、明确恢复、已选保持，440无溢出、0写 |
| zoom-200 | 原生DPR2/outer1440/inner707，641内容单列，673弹窗无溢出、0写 |
| narrow-patch | BLOCK编号4、UNKNOWN→真正RESOLVED，原body/key两次相同，只V2→V3一次 |

每例最终又读取5个实际开发模块，200、关键实现/导出完整、非空，内容长度分别34986/33240/32689/73252/9536。busy-viewport最后观察的composer为CONFIRMED，实际服务端已COMPLETED/APPLIED；检查范围为晚到目标/输入保持，不冒称该瞬间全部后续读取已READY。没有全程Console零错误声明，stale-enter的409是用例预期。

最终回收初次在C01尚未完成接受时GET新Run读到404，工具改为限时轮询等待真实记录建立；一次原支线未显式展开以及一次在打开进展前等待按需summary均为检查等待假设，已按实际页面先展开再等读取修正。保留这些未通过轮次，不把它们作为新产品业务故障，也不因此改动产品业务流程。最终13例完整通过来自上述同一串行运行。

新增检查代码清晰性复核修正两处赋值lambda为具名replay、zip列/值长度明确strict=True，受影响existing_entry_maintenance/target_boundaries共12 passed，99.97秒，1条既有Starlette提示；不是新增12条需求，也不重复计入新增48项。受影响生产/8个新增专项E/F/I/B检查通过，生产及相关检查文件591个Ruff格式通过。9份当前文档427个相对链接无缺失，验收表仍76个唯一条目。


## 跨文档补查与收口

cross-document最终独立退出0：原文档1的s1/b1讨论实际RUNNING后，经真实文档导航切到设计文档2，输入新文字；释放离线返回，程序核实原Run COMPLETED/APPLIED、document_id=1及原b1目标；当前页面仍doc2，新输入逐字保持，当前Run为null，doc2正文仍空/V1。全程仅原doc1的恢复及发送两个业务命令，无doc2写入，doc2 pending0。五个实际模块仍完整非空，自有环境已清理。此次为13例完整串行后的新增单例，合计14类场景，不称一次14例整组运行。

首轮误把夹具“设计”文档假设为id3，实际为id2，已按真实导航/身份修正；随后一轮在上述新文档/输入保持断言通过后，最后HTTP读取遇到本轮自有Vite连接拒绝。未定位这次服务退出原因，未恢复已取消的Windows Node崩溃专项、未改产品或启停用户服务；同场景完整复验通过不作为该退出原因已修复的证明。各临时环境均finally清理。

收口只保留Markdown摘要。最终源码/固定资源、相对链接、产物与自有进程核实结果按本节末记录；没有真实模型/计数调用、正常业务库修改、用户服务更新、Git提交推送或正式设计自动合并。整版剩余边界见当前实现进度及76项覆盖审计。


## 执行入口与最终现场

后端8个新增专项分别使用本项目tools/quality_gate.environment生成的隔离环境，TemporaryDirectory作为WALLE_CHECK_TEMP及pytest basetemp；实际子命令形式为：

```text
.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py backend/tests/formation/<本节对应test_v21文件>.py -q -x -p no:cacheprovider --tb=short --basetemp <本轮临时目录>/pytest
```

两个后续回归分别把message_read_protocol/model_publication/staged_scope_maintenance三个文件及existing_entry_maintenance/target_boundaries两个文件作为独立参数；实际9项/12项结果见上节。原48项各分组结果不合并冒充一次全量运行。所有pytest输出只在内存摘要，环境与临时目录在退出后清理。

前端实际通过tools/quality_gate.commands/run_stage的frontend/typecheck/format/build阶段，使用锁定Node和quality_node.cjs离线预载；分别为Node全组test（test-isolation=none）、tsc --noEmit、锁定Prettier --check src/**/*.{ts,tsx,css}、Vite build --outDir <临时目录>/frontend-build。没有覆盖现有8000静态资源或更新用户服务。浏览器实际命令是该工具的--case all（当时13例）与后续--case cross-document。

最终静态回收：597文件Ruff格式通过，受影响源码与专项E/F/I/B及工具F/I/B通过；git diff --check无输出；9份当前文档428条相对链接无缺失，76条验收身份唯一。cleanup-test-artifacts.py --dry-run为JSON0/截图0。只读进程核实：8217/5187无监听、自有API/Vite检查进程0、本轮w21-concurrency-browser临时Chrome/辅助进程0。未停止其他进程，测试资源全部清理。固定原设计与release核对结果见上节。

收口时间：2026-11-17 16:56（Asia/Hong_Kong）。本批已完成，V2.1整版验收继续按覆盖审计剩余条目推进。
