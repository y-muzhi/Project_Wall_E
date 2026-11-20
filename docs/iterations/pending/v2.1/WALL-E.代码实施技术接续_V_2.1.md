# V2.1代码实施技术接续

2026-11-15；依据前后端0.1-draft-4及用户“构建2.1版本代码”“保留已知事项，继续实施V2.1”。本文件记录实施分配，不自动合并正式设计。

## 存储发布分配

真实源固定a0f4059、Schema200/db20-r50，r48与r50 fresh SQL相同。为原库内21张业务表及严格发布元数据分配Schema210、schemas/v2_1/db21-r1候选；数值210是本轮对固定源的正式技术分配，不是此前设计中猜测的201。新增formation_schema_state仅记录发布／来源，不是额外业务根。源72表及冻结r50不变，目标合计94表；目标与源使用同一Database连接和事务，不用旁库。

FormationDatabase继承既有Database，重用连接、事务、进程锁及commit未知分类；覆盖严格全Schema检查和显式新库初始化。既有CodeSchemaState保留schema_version=200及原始来源含义；目标总版本由SchemaMigrations210和FormationSchemaState共同证明。不向Schema200检查器伪装含额外表的库。正常启动拒绝未知／旧库，不自动迁移；升级另用显式源只读→新目标流程，用户业务库及服务切换未获本轮授权。

新逻辑事件复用document_change_audits的真实ID，外层event_type保持既有DISCUSSION_UPDATED，payload中的formation_event_type使用设计闭集；公开EventView.type取该严格字段。这样保留全部旧审计、源CHECK及来源，实体历史子表复用真实audit外键。新索引为audit／消息提供同文档复合FK目标；事件payload、标量changes、members与业务同事务。后续若修改共同源文件，生成新源pin，不改历史r50包。

候选须验证固定SQLite、fresh／extension结构等价、全部对象及列／外键／索引／触发器、manifest与源码摘要；没有实际发布和专项证据前不得称运行能力完成。当前只在隔离临时新库验证，不做正常库升级。


## 关联摘要（2026-11-16）

区块digest统一为原始ParsedBlock.markdown的UTF-8 SHA256，保留正文空白及行尾；同一关联按文档真实区块顺序排列，每项{block_id,block_digest}，origin_content_digest为canonical JSON对象{ranges:[上述各项]}的SHA256。单独Revision／Block来源另列，不把摘要相同等同来源权限或AI充分性。当前块核实复用validate_snapshot／DocumentSources，不重写正文。预览验证不产生身份／审计；实际保存重新在同一事务核实真实当前Revision、区块、归属及实际audit。


## 当前发布与历史成员摘要（2026-11-16）

共同Scope登记形成能力后，源pin为db20-r51，目标pin为db21-r2；r50和首个r1保留原字节。Schema200 SQL／合同未改，target合同仍f3f29931a176cbb64effa63fad516280120711a472f4e59a246a9683df9e0b78。新业务子层持续实现不自动修改冻结包。

原实现曾使用逐条追加LF摘要，已在本轮按设计纠正、不得沿用：成员digest对ordinal正序的完整MemberDelta组成canonical JSON数组再SHA256；流式写入左方括号、逗号分隔的完整对象、右方括号，空集是SHA256([]的UTF-8字节)。两遍计数／摘要须相同，逐100行写入仍一个外层事务，不分批提交。ORDER每节点一条；同一批每实体标量／成员事实只存一次，多事件共享版本及批次，不能把整张路线复制进每个事件。

## 2026-11-16共享内容事务与读边界

- FormationTransaction是调用者真实连接内的显式版本基线；C07在进展前捕获，正文hook复用，保证同轮进展和成果维护的D/F各最多一次。无头部/旧Schema不初始化主线、不升级库；NoChange正文不造Revision或关联维护事件。
- 正文维护用连接TEMP索引定位被改动/删除的CURRENT范围，逐关联更新并写一个PROGRAM事件（source_id为同事务真实CONTENT_COMMITTED事件）；原ORIGIN、Closure和生命周期不变。影响105个关联已验证，失败连正文一起回滚。
- 原只读审计validator新增精确Schema210识别；因此发布core/r52与target/r3新pin，旧包不改、DDL不变，不代表已升级业务库或给予新release真实准入。
- 当前/历史读取分离：当前F绑定游标，历史固定event/上界；全量canonical数组摘要与协议类别顺序已修正。未建头部仅Summary返回false，其余formation读409；跨文档归属先核实实际范围。
- 新卡发布/精确采用、新模型Canonical/Wire/release及前端产品UI仍待后续真实接入；不把本轮旧版REVISE的离线网关证据当新用途或真实供应方证据。

## 2026-11-16前端读取实现选择

复用原ApiClient／WalleApi／DetailReadScope，Formation变量分页只在注册的读路径生效，旧分页不放宽；Preview POST只读不生成key、不进入写命令账本。Summary从原requirements GET实际返回读取，无该字段是读取错误，不推断未初始化。FormationReadOwner为固定文档纯内存读取子owner，选择／焦点／AI目标不混用，不新增持久化库；晚到页面与详情用独立epoch丢弃，陈旧版本恢复最多一次，失败保留上次数据。此项不代替完整FormationViewState、命令owner及同账本DB2/记录5实施。

历史同样复用原DetailReadScope，EVENTS／CHANGES／MEMBERS／CLOSURE／EVIDENCE各固定真实文档／事件／分区／项身份，不上传当前F。13型标量快照及11类成员严格联合，PUBLIC只含digest或独立Proof、不含PublicationBinding。当前／历史查询先保存原始只读快照再等待写屏障与响应，避免外部对象改动令key／请求／解码相互漂移；首轮读取不替用户修改任何正文或正式状态。

## 2026-11-16三小时会话：真实接受与模型投影

新执行资源起初选v21/v22（本轮最终显式选择v27/v28），v19/v20为本轮已生成的前期候选保留原字节。新形成输入由原C01进入，按formation.discuss及需求/文档身份幂等；先完成目标状态和冻结材料再一次INSERT GuideRun，不更新任何冻结列、不改SQL保护。真实用户来源事件同事务延后到Run存在后写入。Canonical仍留完整私有身份，Wire原八根，形成材料放project_position，原调整卡用goal_and_decisions内PROPOSAL材料且不裁剪；无新的模型角色或旁路计数。纯序号计算与完整图持久化抽给实际人工和AI共用，模型20项/64KiB限制施加原始changes，内部展开不冒充另一个用户请求。新提案首次发布将以原审计AI回复/索引固定来源，不伪造开始/采用事件；其D/F必须与同轮其他真实变化协调。

### 原设计允许的支线主题维护事件（2026-11-16，实施补齐）

普通UPDATE_BRANCH允许只更新topic_refs，既有事件清单缺少不带结果的支线维护类型。增加严格BRANCH_UPDATED（同步前后端EventAction），仅用于真实支线定义/主题维护，不用BRANCH_RESULT_RECORDED或恢复事件冒充。该项不增加模型业务权限，只补原白名单行为的真实审计分类；独立技术接续保留，不自动合入原正式设计。


## 2026-11-16 显式Schema210启动接入（子层已实现验证）

接续既有APP-FORM-UPGRADE／INF-FORM-STORE，新增启动参数schema_version及命令行--schema-version（200／210，默认仍200）。选210时只验证并打开已存在的独立Schema210库，加载精确固定的形成资源和formation_router；缺库、错版、错误资源均拒绝，不初始化、不迁移、不切换正常用户服务。旧Schema200服务的默认路径、资源及路由保持。此项只是启动适配，不替代源只读→全新目标的升级／切换工具，也不授予新资源LIVE。

生产factory、backend.app入口与ai-service离线准入展示一并对齐，变更后新发core及Schema210来源pin，保留旧release字节。隔离测试必须运行真正factory／worker生命周期、严格HTTP响应与退出后锁释放，不手工替代业务runtime。前端整版UI及IndexedDB升级仍独立待实现。


## 2026-11-16 新来源与独立文档操作接续（已实现，REVISE／重试路径已验证）

复查发现：V2.1提案采用后正文含真实CARD_RESPONSE来源，若独立REVISE／REVIEW等新运行退回旧资源，会被旧Schema明确拒绝。因此Schema210运行中的独立非DISCUSS操作继续使用显式新release，接受时只冻结只读形成依据、来源和消息效果，不消费步骤／支线选择，不生成formation_request，不授予新的形成操作权限。历史运行仍按原release回放。独立操作的主文档结果保持原有独立接受策略；返回formation_delta或新用途卡不在该入口应用，不能反向撤销合法文档结果。重试保留原operation，后续继续讨论才转新DISCUSS。

该修正沿既定“共同来源统一、独立文档效果不被讨论增量反向撤销”规则，需补真实发布→采用→REVISE／失败后显式重试专项，不能只靠Schema可以解析判完成。旧缺来源支持的历史release仍明确拒绝，不改冻结资源字节。


## 2026-11-16 18:28当前最终实施分配

显式形成资源v27／v28；CARD_RESPONSE元数据、原支线触发SourceRefs／相关OPEN支线及调整用途所需定义与相关阻塞／活动成果均冻结。hard集合先于soft，超过100整次拒绝；不把遗漏或私有摘要当模型已读。路线发布可引用已携带的依赖身份，但涉及定义／成果修改、取消／关联及既有成果承接时须有完整已发送定义，防止仅凭依赖ID扩大模型权限。

C07与原C06实际发布／精确采用、3提案动作及调整替代已接通；CARD_RESPONSE实际来源由程序核实原message／card_key／response，块署名USER，Revision存真实原消息及CARD_ANSWER，审计另存完整描述。没有另建Run或第二次Chat。非DISCUSS只读形成快照不会授予增量权限；其非法formation_delta／新用途卡不在该入口应用，主正文独立保存。

启动源码变化后core/db20-r53＋target/db21-r4；目标SQL合同不变，旧release原字节保留。新旧离线准入入口0凭据／0数据库／0调用／0服务；显式210只验证既有库。实际验证见[执行记录](../../../verification/v2.1/formation-execution-2026-11-16.md)。完整产品前端、同账本DB2／记录5、源只读复制升级及供应方仍未完成。本独立迭代未自动合入正式设计。


### 提案占用与失效分离（2026-11-16）

检查发现新用途消息态把临时工作占用直接投影成EXPIRED，原卡片owner按失效清除本地选择，造成占用结束后输入丢失。修正仅影响新purpose：card_state由正式消费／处置／调整／用途保护决定，临时占用只在ProposalView availability与实际C06／前端allowed中禁止提交，不使语义仍有效的卡永久失效。原旧purpose规则不变。需覆盖真实AI占用／取消、禁止C06、不制造回答、恢复后原选择保留。


## 2026-11-16 18:50新三小时会话：规范收口与实际前端

沿用当前BE／FE 0.1-draft-4／大纲0.12，不自动合并正式设计。本会话先清上轮24条：移除events仅测试使用的摘要转出、明确事件集合／未使用解包／SQL括号及启动导入；读取层只映射已分类的预期数据／程序异常，其他未分类异常交给既有shared.http_boundary安全INTERNAL_ERROR，事务照常退出。公开HTTP码／安全详情／占用与回滚不变，不记录SQL／正文或关闭lint规则。启动源修改后新发core与target pin，旧包不改。

后续接前端LOAD／TARGET／NATIVE／PROPOSAL／RECOVER，先完整核对当前详情／对话owner／账本及FE7.4规则，复用已有ApiClient与单账本，避免平行命令机制。实际每单元保存及隔离检查；正常数据／服务／真实调用／提交推送仍不在本轮范围。

## 本轮前端冷恢复绑定（2026-11-16）

前端selection_epoch是只用于比较相等的本地唯一身份，采用UUID；每次显式SEND冻结目标时建立新的动作身份，并把它作为该次FORMATION记录5的intent_key。显式next_target草稿原样持久同身份，跟随server_focus仍保持next_target=null。任何后续人工选择产生另一身份，UNKNOWN重放不再造身份、不改原body/key。这样冷重载后可由原记录intent_key与现存目标草稿身份核对，只有同一选择的202接受才能把RESUME归一为ENTER；新选择即使指向同一支线也不被旧回执消费。不增加账本字段、物理库或后端对象，不按D/F/V变动自动派生动作；仅技术实现，正式设计不自动合入。


## 显式复制升级技术接续（2026-11-16）

按既有APP-FORM-UPGRADE实际实现源只读、新目标独立复制及inspect。源r48／r54固定manifest白名单，其完整DDL／资源字节与当前core/r54相同，旧源码不执行；target/r6固定9个构建／维护入口。新父目录复用原operator-only包创建，拒绝已有目录／目标且不修其ACL。SQLite backup后短事务添加210，typed rows＋原迁移历史＋审计／引用／高水位核验；仅输出Markdown。inspect不继续DDL，区分200副本与已提交210。此为原设计实施选择，不改变数据规则，不自动合入正式设计或授权正常现场维护。实际证据见docs/verification/v2.1/copy-upgrade-2026-11-16.md。


## 前端最后接续（2026-11-16）

原C01、原生支线继续、结束并明确继续目标共用“既有intent_key＝当次选择UUID”的关联。原生命令显式影响选择时先产生新的选择身份并持久保存，成功／冷恢复只消费该身份；后来的同支线或别的目标不覆盖。沿DB2／schema5原字段，不从D/F/V拼新业务意图，不自动重发。当前回复直接读GuideRun公开accepted_target，不维护另一份长期Run目标缓存。

历史CHANGES／MEMBERS按不可变event_id；当前RANGES／LINEAGE按F，分别分页及来源。普通结束一键执行，明确继续／高级遗留处理才展开；跨页明确选中项保留，未选项保持开放。泛型列表按记录身份而非行号复用，失败保留上次记录并明确提示。上述是既有设计实施补齐，未自动写回正式设计。

明确未收口：ANALYSIS成果独立依据与高级result_dispositions完整交互仍须按原详细设计审查接入；本轮不将其当成纯测试待办。

## 2026-11-16 22:18 两小时接续：成果依据及结束处置

依据仍为前后端0.1-draft-4及大纲0.12，不修改设计规则／正式文档。本批先完成APP-FE-DISPOSITION及BND-FE-WORKBENCH缺失的实际输入／读取交互：CONTENT只能选择本步骤实际关联请求核实LANDED；ANALYSIS显式选择真实来源请求核实ANALYZED；未选仍默认OUTSTANDING，普通一键结束不增加表单或完成门槛。

复用原消息20项游标、文档版本20项分页、既有步骤来源和评估来源，以及原SourceReference只读查看。来源选择只是本地草稿，不运行Chat／计数、不修改正文；跨页选择保留，撤选后允许直接结束。实际结论仍由后端完成事务核实，客户端不把声明直接改成事实。成果页独立显示分析要求、步骤评估依据及结束时不可变证据，明确评估当前性；历史证据固定event_id，不能拿当前来源替换旧事实。

提交前检查本次打开表单时的D/F/V/定义/目标版本；现场变化时保留选择、说明需重新核对，不把旧选择静默绑定新版本。发送后使用原同库durable命令恢复原body/key，关闭或切换不撤销已发送请求。必要浏览器检查只在自有临时API/Vite/Chrome和隔离数据库；结果稍后按实际写验证记录。

输入／输出／不变量：输入为真实StepDetail和用户显式选项；输出仅原COMPLETE_STEP的result_dispositions及原ProgramReceipt；每项种类匹配、引用去重、来源最多100、未选择不伪造已完成，正文V不变、普通结束仍可带缺口。首先检查专项／类型，再真实隔离交互及失败恢复，最后同步映射与断点。未运行检查不提前记通过。

### 成果处置的已知冲突重读入口

静态检查发现：结束表单已知版本冲突后，若只能关闭再从主线刷新，重新打开会清空选择。沿既有“失败保留输入／明确重新核对”规则，在表单内补只读刷新；保留原选择，不自动更新提交依据。读取发现版本变化时，用户可以明确按新版本保留选择再核对，也可以明确清空重选；被删除或改种类的成果仍由resultProblem拦截，程序在最终事务检查真实关联／归属。UNKNOWN仍只能处理原持久请求，不把刷新当取消或允许第二次提交。

### 两窗口实际发现并修复的读取生命周期缺口

实际另一窗口START后，本窗口结束收到旧D冲突；表单内刷新使FormationReadOwner.observeSummary按F变化清空detail，导致Overview卸载、未提交选择丢失。读取owner继续保持严格“新F未读不能为READY”的规范；不把旧数据塞回规范状态。页面仅保留同一已选步骤的一份最近成功详情用于显示，明确正在读取／上次结果及失败，所有依赖详情的写操作在新详情READY前禁用；选择另一步／另一文档不复用旧详情。这样表单在同身份重读中保持，原请求、正文及其他文档隔离规则不变。随后必须实际重跑双窗口与空错态验证，不能只凭类型宣布修复。

### 固定Revision来源入口的完整字段修正

来源链路复查发现三处新形成UI构造REVISION SourceRef漏传必须字段block_ids：成果原始正文、路线选择版本原文、历史复核当时核实版本。公共SourceRef严格要求全篇也显式block_ids=null，因此原链接在本地校验阶段失败。只补齐这三个真实调用方的空范围字段，不放宽SourceRef或readSource校验；已有区块引用仍携带实际block_ids。随后用实际完整产品读取三个入口，不能用单独GET成功替代。

### AI判断／建议来源与当前性显示补齐

按BND-FE-WORKBENCH／5.1既有要求，概览补原评估／建议的实际来源与触发回复入口、具体stale_reason及建议动作。使用原SourceReference按展开只读，不新增AI调用、不把建议变成命令；旧建议继续保留原说明和来源。独立人工操作不因建议STALE而禁用，仍只认程序availability／当前权限与版本。只读依据按本地有界来源20项显示，同一SourceRef去重；分析页保留自己的要求／依据／结束证据职责。

### 多项取消草稿的成果去向归属修正

组合审查后新增两条行为回归先取得实际失败：第二个CANCEL_STEP默认暂选同一步，改选或删除时会移除第一项仍需要的result_routes。修正为按其他仍存在的取消操作核对归属；仅最后一个引用旧步骤的取消被移走／删除时才清其去向。清空目标同时清本项旧详情，删除操作清自身读取／详情，不展示旧步骤为新目标，不累积已删条目。保留严格整批重复目标、完整去向及同kind后端校验，不让暂态重复草稿成为正式重复取消。输入为多项草稿及异步完整成果读取；输出仍是原ADJUST_PATH，已保存正文／来源／服务不变。

### 展开主线的原生summary键盘边界

实际Chrome复现：在展开主线的“结束并继续”上按Tab，焦点直接回顶部“返回AI对话”，后面的关系／来源summary无法从正常顺序到达。公共trapModalTab的可聚焦集合遗漏原生summary，误判了最后控件。沿已有公共modal栈最小补入summary（显式tabindex=-1仍排除），不新建焦点管理器；复核展开及嵌套Confirmation的Tab／ShiftTab／Escape与返回原入口，无业务写入。

### 嵌套弹窗Esc取消事件的传播修正

实际键盘复验定位到第二个问题：下层Confirmation取消事件沿React portal传播到ExpandedFormation，两个dialog均消失，焦点落到“工作台”。下层Confirmation及同样通过portal挂载的路线编辑dialog在onCancel先stopPropagation，再按原busy／关闭规则处理；上层不接收下层取消。发送中关闭保护仍由原busy和durable命令负责，不改变程序取消或已发送请求。复验包含嵌套Tab、Esc、焦点返回及临时命令回执延迟时的忙态。

### 成功后原入口消失的焦点回落

嵌套临时COMPLETE成功后，“结束并继续”原入口按状态消失，原Confirmation只在main中找回退控件，外层主线portal不在main，实际焦点落BODY。沿既有activeModal栈，原入口不可聚焦时先回当前上层dialog（其tabIndex=-1），再沿原普通页面回退；不新建栈。结束表单cancel同时读取owner实时SENDING，防止渲染前后的小窗口绕过原忙态关闭保护。检查明确区分“按钮因其他原因禁用”和实际aria-busy提交态，原生open／inert／可见性用于判断弹窗是否被关闭。

### 收起展开主线后的焦点时序

外层Esc复验发现ExpandedFormation卸载清理立即查询普通面板的展开入口，此时普通面板尚未提交挂载，焦点没有恢复。回到同一document的展开入口安排在当前提交之后的microtask，并核对connected／hidden／inert／实际布局；切换文档或隐藏进展时跳过，避免抢走后续焦点。取消不发送业务操作，不改变已发送请求。

### 折叠交互目标尺寸

按原前端5.1的至少32px交互目标，形成主线、结束表单及路线编辑中的summary补32px最小高度与流式换行，保留原生标记与键盘行为；不改全站其他模块。最终检查在实际展开容器量取尺寸，不为样式另建镜像测试。

### 2026-11-17分页范围变更的恢复核对

本批静态追踪发现FormationPage的scope已随F／实体变化，但cursor和previous仍单独保留旧范围；当前页可能把旧F的cursor发给新F，导致PATH_CHANGED恢复后仍停在旧游标错误。步骤依据本地分页也未对候选缩减做页码约束。先在实际容器复现，再按已有分页／空态规则修正：游标与历史必须绑定scope，范围变化从合法首页读取；同范围失败保留旧成功页及恢复入口；本地依据候选缩减显示仍存在的合法页，保留已选项，不写正文或转移焦点。不是新增业务规则，仍不合入正式设计。

实际复核结论：31支线的F更新经当前主线刷新会正常重建首页，通用FormationPage本轮未复现旧游标故障，保持原实现。结束表单的同身份保留使31依据第二页缩减为2条后确实显示0行；仅修复evidence-picker当前页约束，原选择和明确重核不变。证据见2026-11-17并发与提交入口记录，不把最初静态怀疑写成已证实的通用缺陷。

### 精确提案的单区块范围显示

窄窗精确提案检查追踪到FormationPayloadDetails将所有非DOCUMENT范围都按SECTION读取heading_block_id，BLOCK实际只有block_id，因而会显示“章节区块 undefined”。后端严格BLOCK与精确采用已在本批真实事务通过；这里只补齐原展示分支，DOCUMENT整篇、SECTION章节区块、BLOCK区块分别按原字段显示，未知范围不伪造成整篇。先以真实C07卡片复现，再验证原C06丢回执核实及只写一次；不改权限、Schema或原payload。

## 2026-11-17 消息读取协议复用

实际窄窗精确补丁提案读取等待超时；独立进程堆栈定位到消息HTTP结果校验重复构造完整ResourceCatalog，进入reading_protocol的形成用途回退。相同消息经程序投影、结果及HTTP校验多次执行，旧结构协议已有进程内缓存，而形成用途回退每次重新加载全部固定资源。输入为已存储卡片、已有协议；输出仍为同一固定v27校验器；保持用途选择、严格校验、availability与业务事务不变。按既有_structure_protocol模式缓存形成用途回退协议，实际请求已有formation_driven协议时继续直接复用。缓存只针对固定不可变资源，不缓存业务状态、卡片可用性或用户消息；不得绕过Schema和字节准入。先跑实际浏览器原路径及消息专项，再记录结果。


### 本批最终实际结果

2026-11-17上述分页、范围显示与协议复用已实施及检查。范围展示经现有wireScope严格解析，SECTION沿原heading_block_id规范化、BLOCK显示实际block_id、SELECTION显示区块内选中文本；不修改原payload。消息复用只缓存同一固定协议，业务状态仍实时读取。新增48项分组、受影响9/12项回归、前端650、13例最终串行与跨文档追加单例通过。该范围原文先前按SECTION字段读取的代码缺陷已静态确认，修正后真实BLOCK卡片显示与原C06丢回执恢复通过；没有将修复前未成功显示的页面虚写成一次完整UI复现。完整证据与保留限制见[11-17检查记录](../../../verification/v2.1/concurrency-entry-2026-11-17.md)，正式设计未自动合并。


## V2.1离线检查入口（2026-11-17）

最终核对发现现有workflow与tools/check-v15-offline.py明确只选择V1.5后端，不能据此证明V2.1。新增V2.1入口，复用quality_gate的隔离环境、执行/取消/超时、前端命令和内存摘要；按完整文件库存分frontend/core/programs/ai及显式load。standard不含两项长负载并明确列出；all包含load，单组报告不冒称整版通过，空库存/缺结果/运行中源码变化/清理失败均不通过。

新版本workflow独立声明V2.1，日常分组与手动长负载分别执行；没有推送或启动GitHub运行。本轮先保存入口/库存及报告边界检查，再运行一个实际后端分组；既有长负载证据不重算为新入口整组结果。只留Markdown汇总，固定SQLite入口和禁止外网/正常库边界保持，正式设计原字节不改。

V2.1离线入口实际回收：4项边界通过，core81/frontend650及类型/格式/临时构建通过；两份独立Markdown报告已进入验证导航。新workflow未推送或触发；programs/ai/load未经新入口重跑，不称新standard/all整套通过。原始/正式设计继续保持待合并边界。
