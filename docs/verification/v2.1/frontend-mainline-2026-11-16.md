# V2.1 前端主线接续检查（2026-11-16）

本轮10:50 UTC／18:50开始，HEAD a0f4059，独立工作区未提交；仅隔离离线、类型／格式／必要浏览器，不调用真实供应方、不更新正常库和用户服务。前轮结果仍保持历史边界。

## 规范及读取边界单元

- Ruff check --no-cache --config ruff.toml backend/app/formation backend/app/service.py backend/app/__main__.py tools/ai-service.py：All checks passed，24条提示收口为0。
- 固定Python入口 tools/python-v20.py tools/quality_python.py 执行 test_v21_read_boundaries.py、test_v21_event_members.py、test_v21_history_queries.py、test_v21_path_preview.py：30 passed，110.15秒。读取层三面×两种故障实际HTTP安全500，无私有SQL／正文泄露，库不变；相关历史／事件／预览回归通过。
- 同入口 test_v21_startup.py、test_v20_startup.py：5 passed，49.82秒。原200及新210实际factory／worker／进程入口。
- 每次使用TemporaryDirectory及quality_gate.environment，临时数据库／审计／输出已清；无原始日志或JSON留存。
- core db20-r54 manifest：3d48be65e3ad6e549c3b73b831456459537adb1e03c765ef6f28ad9ce6eeedc7；target db21-r5：05dc250e7a5ba3af9b2939b86fe1c17c39540c6874f3a603089be9519e9bc2d1；target合同f3f29931a176cbb64effa63fad516280120711a472f4e59a246a9683df9e0b78。
- FastAPI TestClient现有StarletteDeprecationWarning一条；没有新增失败。本批不代表新前端页面或供应方验收。

## 同库恢复基础单元

- 共享连接／严格事务从原CommandRecoveryStore抽出，仍用原同名两仓库及索引；新bundle open(name,2)，DB1升级不改旧行。FORMATION仅schema5，旧Coding／Testing仍schema4，分别解码和恢复；全库100条／128MiB共用，完整body8MiB与元数据64KiB分开。
- node --test tests/formation-command-model.test.mjs tests/v20-command-recovery-model.test.mjs：9 passed。实际类型检查通过；预备恢复使用原冻结字节与key，native方法重新建立输入／回执decoder，不从存储执行函数。
- 本轮自有临时Chrome＋Vite 5187：formation-ledger实际IndexedDB5组通过，覆盖DB1→DB2保留旧字节／旧bundle VersionError、混合owner／双连接CAS、UNKNOWN不可未执行取消、blocked后中止升级、冷恢复原body/key与202确认终态、全库共享100条容量。
- 同浏览器原V2.0 storageProbe8组及ownerProbe5组通过，覆盖旧query／close／202异步／冷QUERY_ONLY、不改原恢复规则；诊断工具读取版本已随物理DB2调整，主动versionchange测试改为升DB3。未执行boundsProbe的128MiB压力本轮尚未重跑。
- 只操作隔离浏览器随机前缀测试库。finally关闭全部测试连接／删除fixture库，退出Chrome、自有Vite、临时daemon／profile全清。启动页Console显示1条，尚需后续页面检查辨明来源，未冒称零控制台错误。
- 尚未挂实际页面／Composer；此处仅恢复基础单元证据，主线交互仍继续实施。

## 实际产品主线首次接入

- 最新全量前端619 passed，4.26秒；Node strip-only不支持参数属性的问题已展开成明确字段赋值。两个旧读取隔离mock补齐native snapshot接口后回归通过，未放宽真实产品校验；相关composer／conversation48项通过。
- 真实RequirementDetail／Milkdown／WalleApi＋隔离Schema210 ASGI：31步骤完整total、当前20项、纯查看0写操作且原输入保留；实际START成功。注入PATCH服务已成功后客户端丢回执，UNKNOWN保留1条；原key/body恢复后PAUSED，待核实为0，两个请求字节／key一致。
- 五个实际详情分类读取：关联成果有效、问题／支线业务空态、历史3项；展开宽1120、布局320+750、页面1440无横溢，截图仅在临时目录查看后清理。此为完整产品组件实测，未使用第二套UI实现。
- 最初一次定位器把aria-hidden的序号算进按钮名而超时，检查脚本按实际可访问名称修正后通过；无产品故障归因。临时API8217、自有Vite5187／Chrome均已退出，临时fixture库及截图／日志自动清理。
- 最近增加Closure分页组件仅严格类型通过，尚未做其交互；完整C01在途目标与输入、结束、窄布局、所有恢复边界及路线编辑仍待后续检查。

## 完整目标及结束真实交互

- 新formation-target-composer.test.mjs：5 passed，覆盖旧回执不覆盖新目标／文字、RESUME在202即消费且模型FAILED不回退、UNKNOWN仍复用原目标、存储拒绝未发送ERROR、坏草稿／偏好保留原字节。
- 真实整个产品＋隔离ASGI：直接结束PLANNED步骤，默认处置数组全空、next=null，实际COMPLETED；完整Closure分页显示OUTSTANDING。结束和后续选择未重挂Milkdown正文DOM。
- 实际已结束s1讨论C01（只接受，测试API无worker／无模型执行），人为延迟HTTP回执；在已加载路线选择下一轮s2并编辑新文字后放回202：原body仍s1、只1次POST、新目标s2及新文字均保留，composer恢复READY，原正文DOM保持。控制台Errors0、Warnings0。
- 核对发现原“等待当前详情读完才能选下一轮”的入口受写栅栏阻塞。按基线在已加载真实路线行补直接讨论按钮，使用已读实体身份；在途只改本地next_target，不发额外PATCH／Chat。修正后上述真实用例通过。
- 所有临时API8217、Vite5187、Chrome及数据库／日志／截图已清理。早期独立ledger页1条尚未辨明；当前完整产品控制台为本批新实测，不覆盖旧页来源。

## 路线编辑与预览单元

- 新PathEditor已实际接产品入口：14类业务表单、当前／临时步骤成果选择、显式成果去向、目标与来源区块、完整关系分页、草稿保留、编辑即使预览过时、已知保存与未知恢复分开。未以JSON编辑框替代业务表单。
- 固定Python入口 tools/quality_python.py backend/tests/formation/test_v21_frontend_preview.py：1 passed，8.05秒。真实只读ASGI→生产WalleApi.previewFormationPath，opaque分页、完整DTO、变化摘要、临时标签、损坏前后实体／计数／游标拒绝，前后库快照相同；无key。
- 真实完整产品＋隔离ASGI：ADD_STEP预览仅无key POST；修改标题后保存禁用，重新预览后实际保存，temp映射到s32/s32.o1并定位，总数32，0模型请求。随后CANCEL_STEP完整读取该步成果并逐项NOT_REQUIRED说明，保存为CANCELLED，正文V1保持；两次实际PATCH，控制台0错误／0警告。
- 最初“调整类型”label包含select选项而未匹配精确名称，已补明确aria-label，并对处置／去向／Closure选择统一补齐；修正后上述真实交互通过。
- 最新全量Node624 passed（6.63秒）；严格类型通过。各14型表单仍需进一步边界／窄布局及来源选择检查，不将新增／取消两条实测扩大为全部验收。
- 原卡durable与提案列表／处置／调整入口已写，正在检查实际新卡源的产品读取；当前首次整合专项等待卡片超时，尚未定位，不宣称该部分通过。用户服务／正常库未变。

## 原卡与提案实际恢复

- 真实离线C01/C07发布的新STAGED_WRITE原卡作为fixture来源，随后完整产品暂缓／恢复两条原生PATCH通过，0新增Chat。真实C06写入后注入客户端丢回执，持久pending1；点击原卡核实，原body/key逐字一致，最终CARD_RESPONSE仅1、正文精确等于原payload（含前后空白及CRLF）、GuideRun1／LLMUse1均为fixture原轮未增加。控制台0错误／0警告。
- 首次把全部操作放在一个CLI调用超过60秒；拆成有明确结果的三个自然单元后通过。另直接核对真实消息／来源GET均200及原卡实际显示，没有归因为产品或存储故障。
- 本地selection_epoch改用UUID并与本次SEND的intent_key绑定，record5无新增字段。冷恢复同一目标归一ENTER的第6项状态专项通过；不再采取原“冷恢复一律要求重选”的临时实现，后续新选择仍保留。完整冷浏览器状态待扩展，不等于供应方效果。


## 目标冷恢复与编辑边界补查（20:48）

目标／composer专项最新9 passed；路线编辑新增6 passed；record5/native5项通过。取消步骤改选原来会残留旧步骤成果去向，现清理旧去向、取消旧读取并忽略其晚到结果；正文来源区块每页20且跨页选择保留，终态回执也按64KiB元数据上限验证，不丢弃事件身份。

实际产品复测：原C01接受期间新目标与新输入均保留，原正文DOM不重挂；结束可从第二页明确选择s21。PATCH成功后故意丢回执，再真正reload，显式恢复复用原请求完整body/key，服务器目标s21、待核实归零。检查工具自身holdGuide早释放的时序已修正，首轮等待超时未归因为产品故障。

最低支持桌面宽1024下真实展开主线：dialog client/scroll均990、列320+622，截图已查看，无横溢；Errors0／Warnings0。最初尝试620后确认旧产品DetailLayout本来要求>=1024，因此仅核对支持范围，不改旧响应式限制。一次检查脚本遗漏等待dialog及浏览器作用域变量也已修正，不计为产品通过项。

本批所有临时API8217／Vite5187／Chrome已退出；临时库、截图和日志已清理。


## 共享容量与本批整体验证

本轮真实Chrome boundsProbe两组通过：UTF-8正文超过8MiB拒绝；17个7.5MiB正文保留，第18个越过全库128MiB拒绝且不淘汰原记录；真实blocked升级后中止、原库不变。新ledger5组同步复测通过。控制台原1条现已定位为隔离检查页favicon.ico404，业务模块未报错；完整产品页0错误／警告的证据范围保持。测试库、profile和Vite均已清理。

本批截至20:49源码的全量前端634 passed（5.41秒）、类型1.45秒、前端格式3.41秒、Python格式0.17秒、临时生产构建1.11秒通过；输出只在TemporaryDirectory，已删除。本轮后续正按基线去除普通结束的重复确认并补高级遗留处置，因此不能把此结果冒充后续改动的最终检查。


## 历史、关联范围及遗留处置实际联动（21:07）

- 历史记录只在明确展开后请求CHANGES，再展开关联变化才读MEMBERS；当前成果范围及LINEAGE分别按20项请求，未预取全量。真实请求为events/4/changes、changes/1/members、artifacts/a1/ranges及lineage，0写请求，原Milkdown DOM保持。
- 已接13类原事件快照的人类可读前后值、ORDER原／新位置、原关联复核替代边／触发回复／当时核实Revision；历史只用固定event_id，不向当前LINEAGE拼过去事实。当前成果可显示已替代项，明确查看原始／当前范围、替代链及链边的原历史。当前只实测单根a1；多节点链及1001项极限仍待，不能称整组通过。
- 普通“结束本步骤”按基线直接COMPLETE，无重复确认，真实COMPLETED并保留原正文DOM；默认数组空／next=null。另有明确“结束并继续／处理遗留”面板，下一目标及高级遗留处理才在其中填写。
- 实际31个开放问题＋1支线：首项暂缓缺原因时确认禁用；补原因后翻第二页选i21放弃，再暂缓b1；一次PATCH仅传2问题／1支线，未选保持开放。实际Closure记录31问题及1支线，正文DOM不变，0新增模型调用，Errors0／Warnings0。
- 新completion/history专项4 passed：缺省保持开放、跨页处理上限20、转交目标与切换时清不兼容字段、Unicode按码点、ORDER及历史a1→a2不被当前a3替换。
- 发现无主线时“讨论整篇”原来误发SWITCH_STEP；已改成本地整篇选择，完整C01目标全null。目标专项最新10 passed，实际空主线打开0写、0formation子请求，再明确讨论只有1个C01 POST，202后READY。检查脚本原先等待尚未打开的按需状态、或在READY初始态过早读结果，均已按真实请求接受条件修正。
- 原proposal只读定位复用原receive/openPanel，未另造会话根或模型调用。AI调整／取消／撤回实际交互仍在补查，尚未宣称通过。


## 取消后确认读取及提案撤回

真实提案“请AI继续调整”保留原输入及原范围，只本地选择不发请求；明确发送才形成完整C01，带原proposal_ref／ADJUST_WRITE。C01接受后取消运行，needs_revision仍true；若立即切至进展，原运行操作处于CONFIRMED且读取被隐藏，RUN保护租约保留。此为原确认恢复规则，不强制清理或再次取消。界面禁用原因已明确指引返回AI对话查看进度。

返回AI对话使用原“重读已确认运行操作”完成读取后，再明确WITHDRAW_PROPOSAL_ADJUSTMENT：实际needs_revision=false、原apply可用，Run总数保持2、LLMUse保持1（仅fixture预先离线Gateway生成）、正式回答0。撤回没有新Run或Chat。本检查临时API不启动worker。

最初检查只等待run.status=CANCELLED就切走，触发了上述保护；另一次把已展开的提案区点击为收起。随后按真实保护／展开状态完成恢复和撤回，未绕过保护。普通产品页控制台错误仍为0，长列表后续检查继续单独记录。


## 本轮最终检查与接续边界

- 真实长列表：初页20、下一页2，翻页后没有沿用前行展开状态或自动请求另一事件子项；读取失败仍保留原行，明确提示上次结果，刷新恢复。支线显示开关已接，滚动锚点s4恢复scrollTop400；0写操作，Errors0／Warnings0，临时环境全部清理。
- 移除workspace中没有消费者的acceptedTargets终身内存缓存；请求行直接使用原GuideRun公开的不可变accepted_target。真实C01回执延迟时，下一轮已选s2／文字已更新，当前回复仍显示“本条回复：步骤 s1”；只有1个C01、原正文DOM保持，Errors0／Warnings0。
- 最后静态审查补齐原生RESUME_BRANCH／带next的COMPLETE_STEP冷恢复选择关联：复用既有intent_key，不新增记录字段；明确动作产生新的选择身份，同请求恢复仅消费匹配身份，晚到回执不覆盖后来新选择。新4项冷恢复专项通过，目标专项合计14项。
- 缓存移除后首轮全量的1个旧测试仍直接断言已删缓存，现改核对原Run目标及实际显示标签，保留原业务断言。最新全量643 passed，5.48秒；类型1.37秒、前端格式3.12秒、临时生产构建1.02秒；Python格式最近0.32秒，扩展Ruff0提示。原始产物仅临时目录，cleanup dry-run JSON0／截图0、git diff --check通过。
- 尚待补齐／审查的代码：ANALYSIS成果依据独立展示及高级result_dispositions的完整交互，不能把当前CONTENT关联页及默认空数组当全部分析成果操作完成。
- 尚未完整验收：全部14表单交互、复杂替代链／1001规模、全多窗口／空错态矩阵及A01—A76整组、真实供应方语义。无真实调用授权；正常现场升级／服务切换未做。


最后实际补验：先明确选择s2，再在结束面板第二页选next=s21；PATCH成功后丢回执，真正reload后原key/body核实，服务器focus和本地next_target均s21，pending=0。证明原生结束的选择身份关联已接生产durable链路，而非仅专项替身。检查脚本曾使用旧面板名称而超时，修正定位名称后通过；非产品故障。Errors0／Warnings0，所有自有进程及临时根已清理，端口5187／8217无监听。
