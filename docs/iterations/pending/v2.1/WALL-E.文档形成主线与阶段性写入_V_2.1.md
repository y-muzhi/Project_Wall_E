# WALL-E V2.1 文档形成主线与阶段性写入

日期：2026-11-06；更新：2026-11-08（Asia/Hong_Kong）。任务：M21-FORMATION-01。修订：0.9／DRAFT；状态：设计中，未实现、未产品验证、未合入正式设计。


当前R01结论：[自动首步与自由切换](WALL-E.文档形成主线整体评审记录_V_2.1.md)，优先于此前首步和焦点规则；当前接入Schema为v3。

当前评审入口：[设计总览0.8](WALL-E.文档形成主线设计总览_V_2.1.md)及[交互与接入收口](WALL-E.文档形成主线交互与接入收口_V_2.1.md)。业务／交互／数据设计已形成完整评审稿。0.8补齐成果逐项映射、完成时支线处置、提案发布后执行依据及失败结果语义；当前严格结构采用接入Schema v2。前期章节的阶段性“下一轮／待评审”由第33章及总览接续；本地V2.0兼容仍为实施前核对项。

## 1. 已确认方向与本轮建议的边界

用户已明确并认可：主线属于单份文档，描述文档如何形成，兼顾未来规划与历史；支线可讨论但要记录出处和返回关系，不能无意识地替代主线；路径随理解变化可调整；阶段性内容可由AI建议、用户确认后及时写入；后续以文档实际内容为成果基准。项目级文档依赖与对齐目前由用户负责，不增加自动跨文档同步。

用户已认可的状态分离：步骤状态、AI成果评估、下一步建议分别保存；“可进入下一步”不作为步骤状态；切换焦点不等于完成；写入一次不等于完成。2026-11-07用户进一步明确：AI判断并建议，用户一键结束步骤；并认可0.4路线原型整体方案。

本文第3章之后是为继续评审提出的具体设计，其中用户一键收束步骤及原型整体交互已确认；联合写入并完成、具体支线命令、并发和程序直接应用提案的技术细节仍为设计建议，不能追记为用户已逐项确认。用户授权本轮推进设计与必要静态检查，不代表实施代码、变更数据库、运行产品验证、真实模型调用、服务操作或Git提交推送。

用户明确将本功能归入目标软件V2.1；文档修订为0.9／DRAFT，尚未实现或形成V2.1正式规格。以下V1.5设计仅作为现有实现基线：[后端设计](../../../design/v1.5/WALL-E.后端设计文档_V_1.5.md)和[前端设计](../../../design/v1.5/WALL-E.前端设计文档_V_1.5.md)。

## 2. 基线、已有承载与真实缺口

云端检出HEAD：8c5df4c6683e10c265e2f719a4fdc09ba4210ea0。未同步的本地V2.0资料不在本轮范围。

| 已有位置 | 实际能力 | 本轮需要扩展的部分 |
| --- | --- | --- |
| `requirements/discussion.py`、`requirement_documents.discussion_state_json` | 文档级阶段、主题、依据、pending、绑定及下一步；discussion_version并发控制 | 增加文档形成路径；主题继续承载讨论，不直接更名为主线步骤 |
| `guide/progress_application.py`、`collaboration_context.py` | 有来源的AI进展增量、确定选材及私有依据 | 形成步骤与主题／支线关系、成果评估、路径调整及当前文档材料装配 |
| `messages`、`guide/card_commands.py` | 不可变卡片／正式回答、模型与程序动作分派 | 明确的收束／调整操作；保存精确正文提案并原样应用的程序分派 |
| `documents/content.py`、Revision、DocumentEffect | 原子内容提交、版本、来源、模板与范围校验 | 文档变化与主线落地记录的同事务关联；受影响成果复核 |
| `document_change_audits` | 不可变审计及DISCUSSION_UPDATED等固定事件类型 | 形成事件的版本化payload及分页投影；先复用既有事件类型，不假定任意新类型可直接存入 |
| `requirements/discussion-view.tsx`、`guide/composer*` | 现有进展面板、操作卡片与UNKNOWN恢复 | 显示路径／成果／支线／历史及真实命令状态，不另建任务看板 |

所有实现路径均相对backend/app或frontend/src。当前DOCUMENT_ACTION接受可产生新的模型运行，不具备本文“预览精确内容后无第二次Chat应用”的完整语义。commit_content也只接受既有来源与占用证明，不能直接从新按钮调用或绕过guard。上述均是真实扩展项，不声称现有功能已支持。

## 3. 数据分层与身份

每份文档一个FormationState，逻辑上与文档级讨论协同，0.5建议物理保存为同文档记录的独立可空JSON列，具体见第26章；不新建项目任务根或独立编排服务。旧phase仍是讨论指导资源，不能成为形成步骤的固定枚举或完成门禁。步骤围绕成果动态生成，不必与章节一一对应。

| 数据 | 建议字段及含义 | 写入责任 |
| --- | --- | --- |
| FormationState | schema_version、version、goal（含目标版本）、current_step_ref、active_branch_ref、ordered_step_refs、steps、branches、issues、artifacts、counters | 程序验证并提交；version只在形成状态实际变化时递增 |
| Step | step_ref、definition_version、title、expected_results、dependencies、status、topic_refs、issue_refs、artifact_refs、assessment、recommendation、closure_event_ref | AI可建议规划与评估；状态命令按第4章分派 |
| Assessment | verdict=SUFFICIENT／GAPS_REMAIN／UNCERTAIN、reason、evaluated_step_version、evaluated_revision_id、source_refs | AI评估，显式标注；不能冒充用户确认或程序内容完整性证明 |
| Recommendation | action、reason、step_ref、source_refs | AI建议，可被后续建议替代；不构成执行队列 |
| Branch | branch_ref、origin_step_ref、return_step_ref、question、relevance、status、topic_refs、result_source_refs、disposition_event_ref | AI登记／提出结果；用户处置依据必须真实 |
| Issue | issue_ref、description、source_refs、blocking、disposition、reason | 区分未解决、已解决及用户允许保留的缺口，不用空数组伪装已解决 |
| ArtifactLink | artifact_ref、step_ref、source_event_ref、origin_revision_id、origin_block_ids、当前匹配区块、内容摘要、freshness、checked_against_revision_id | 仅程序依据实际Revision／写入事件生成；AI只能引用已有记录 |
| FormationEvent | event_id、document_id、formation_version、actor、action、原因、before／after差异、消息／卡片引用、相关Revision | 程序追加到审计；不把全部历史塞入状态JSON |
| WriteProposal | 身份=assistant_message_id＋card_key；step_ref＋definition_version、目标、base_content_version、base_revision_id、精确补丁、范围、原文、来源、预览摘要 | 不可变卡片内保存；客户端不能用确认请求替换正文 |

引用均核实同需求＋同所属文档；文档内s1／b1等引用不能跨文档使用。关系必须存在、无循环；步骤删除使用取消／替代事件保留旧身份，不回收编号。正文永远来自真实Revision或明确未写入提案，不能从评估摘要重建。

ArtifactLink.source_event_ref引用真实内容提交事件，或将已有正文关联到主线的EXISTING_CONTENT_ASSOCIATED事件；已有正文不得伪装成本轮写入。artifacts集中存放这些记录，Step.artifact_refs只存引用。counters为step／branch／issue／artifact分别提供递增的本地编号，均由程序分配；模型新增项使用临时引用，经验证后映射，不能指定已分配身份或回退计数。

Formation.version用于规划投影与历史定位，不能替代discussion_version的命令并发控制。形成状态变化与discussion_version同事务更新；纯聊天若没有形成增量，不增加Formation.version。内容版本仍只因真实正文提交变化。

## 4. 步骤状态、评估与焦点

### 4.1 状态只表示实际过程

建议生命周期：PLANNED（未开始）、IN_PROGRESS（进行中）、PAUSED（已暂停）、COMPLETED（已完成）、CANCELLED（界面显示“已放弃”）。不使用READY或“可进入下一步”表示状态。完成不等于文档整体确认，也不等于所有内容永久不可修改。

| 当前状态 | 明确动作 | 结果状态 | 焦点与保留内容 |
| --- | --- | --- | --- |
| PLANNED | START_STEP | IN_PROGRESS | 成为当前步骤，保留初始规划事件 |
| IN_PROGRESS | 用户明确PAUSE_STEP | PAUSED | 记录缺口／原因，焦点转向指定步骤或为空 |
| PAUSED | RESUME_STEP | IN_PROGRESS | 回到该步骤；旧暂停原因与期间文档变化仍可查 |
| IN_PROGRESS | COMPLETE_STEP | COMPLETED | 记录第4.2节的收束快照；可原子启动指定下一步或置空 |
| PLANNED／IN_PROGRESS／PAUSED | CANCEL_STEP（放弃节点） | CANCELLED | 记录不再需要的原因和替代步骤；不删除正文或历史 |
| COMPLETED | REOPEN_STEP | IN_PROGRESS | 记录为何重开；旧完成事件与旧成果保留 |
| CANCELLED | 按新的目的重新规划 | 新建步骤 | 建立replaces关系，不复活旧身份覆盖取消事实 |

R01状态不变量：current_step_ref为空或同文档存在的讨论节点，可含历史节点；它与生命周期独立，IN_PROGRESS不再要求唯一；取消／完成当前步骤时必须同时清空或转移焦点。active_branch_ref非空时必须指向OPEN支线且return_step_ref等于当前步骤（0.7明确：origin保留最初出处）；支线暂停／结束或父步骤切换时原子清除支线焦点，保留未完支线记录。不得出现“当前步骤已完成但仍显示正在推进”的组合。

R01保持唯一当前讨论焦点；切换只更新该指针，不暂停、完成或重开任何步骤。依赖可作提示，不阻止选择，也不要求填写原因。首次建线直接进入第一步，下一次真实讨论按用户所选节点冻结上下文。

### 4.2 已确认：用户收束决定结束，完整性主要提示（R07更新）

2026-11-07用户明确选择“AI判断并建议，用户一键结束步骤”。完成权限按此规则；这不是确认写入文档的替代操作。

“一键”指AI已准备好可检查的收束建议：展示实际成果、明确遗留事项与建议下一步，用户无需手填已有稳定数据即可结束；不再弹出相同的第二次确认。有未写成果或其他缺口时清楚提示，用户仍可结束；程序保留OUTSTANDING／KEEP_OPEN，不暗中放弃要求或强制先改范围。

AI判断成果足够时只保存Assessment并提出完成建议。用户点“结束本步骤”或“结束并继续下一步”才提交COMPLETE_STEP，不额外弹出第二次相同确认。自由文本“继续”默认不解释为完成；必须有明确绑定原步骤的操作语义。

完成命令至少冻结：step_ref／definition_version、当前discussion_version、当前Revision、成果逐项处置、遗留问题处置、真实操作者、选定下一步。完成收据记录：哪些expected_result已有文档内容支持，哪些属于材料整理／核对且无需正文，哪些经用户明确缩小范围转为后续事项。

程序核实记录和版本，不能自动证明语义充分。AI评估SUFFICIENT不强制用户完成；评估GAPS_REMAIN时用户也可以明确处理缺口并收束。R07允许用户在内容未写入／遗留尚未处置时结束；未写内容保留为待处理，不能被声明已落地，也不强制用户先改目标。可核实的成果才记录真实依据，无法核实的记OUTSTANDING。

暂停与完成始终不同：R01切去别处保留原status，只有明确暂停才记PAUSED，不伪造范围缩小。已完成步骤后来出现新内容，先记录需复核；不自动抹掉过去完成事实或重开步骤。用户明确重开，或接受包含重开的路径调整后，才发生REOPEN_STEP。

### 4.3 规划调整与成果决定分开

AI可在正常回复中提出／维护步骤拆分、排序、依赖、支线关联与评估，但每次需来源和变更原因。不得通过结构调整把IN_PROGRESS变成COMPLETED、删除用户决定、把必需成果变为不需要。改变文档目标、取消既定步骤或重开已完成步骤采用明确用户操作。每次规划变化均留事件；无需用户批准每次标题优化或顺序整理。

expected_results／目标／依赖的实质变化增加definition_version并使旧Assessment待复评；仅展示标题修正或排序不机械使所有卡片失效。写入提案绑定的目的／目标／范围变化才失效，不能仅因又聊了几轮或另一步重排而作废。Goal.version变更也须使旧用途待复核，具体字段见第17章。

## 5. 支线如何进入、结束与返回

建议支线状态：OPEN（未收束）、RESOLVED（形成结果）、DEFERRED（暂缓）、DROPPED（不再采用）。焦点是否位于支线另由active_branch_ref表达，OPEN不等于正在讨论。RESOLVED只表示已有讨论结果，不表示结果已经写入正文。

| 操作 | 保存变化 | 返回行为 |
| --- | --- | --- |
| AI识别值得跟踪的问题 | 新建支线，保存origin／return步骤、相关消息及为何影响成果 | 可进入该支线；一般解释不必每次建支线 |
| 有明确结果 | 保存结果与来源，标RESOLVED；形成适合写入的内容可提出卡片 | 正常回复说明影响并回到原步骤，不自动写入 |
| 用户暂缓／不采用 | 保存真实处置消息，标DEFERRED／DROPPED及未决影响 | 清除active_branch_ref，回原步骤 |
| 用户先返回主线 | 保持OPEN，记录返回动作 | 清除active_branch_ref，不伪造已解决 |
| 支线改变主线前提 | 保存发现并提出有差异预览的路径调整 | 不静默扩范围或改变文档；是否重开／取消按第4章 |

不设置机械“聊三轮强制返回”；用户可明确继续深入。AI收束时依据与成果关系，不能为完成主线忽略真实阻塞。原步骤已取消或路径调整后，先核实return_step_ref；无有效返回点则显示选择，不跳到猜测步骤。

## 6. 阶段性写入提案的操作与状态

### 6.1 两条不同的写入路径

用户主动发起现有GENERATE／REVISE，继续当前直接保存机制。本迭代增加的是：普通讨论中AI提出精确内容→用户看过并确认→程序原样应用。讨论产生提案本身不授权正文写入，也不抢占SUGGESTION_REVIEWING阻止继续聊天。它与用户主动请求PROPOSE_CHANGES的整批候选审阅保持不同完成范围，复用底层补丁校验，不复制一套业务实现。

卡片显示明确目标／基准版本／作用范围、完整拟写内容或可展开差异、关联步骤，以及“确认写入／继续调整／暂不写入”。只含意图而没有精确正文的建议，必须标“生成后保存”并进入原REVISE，不得用同一个确认文案暗中再生成不同文字。

### 6.2 持久状态与前端等待分开

提案处置投影：PENDING（待决定）、APPLIED（实际写入）、NO_CHANGE（内容未变）、DEFERRED（用户暂不写入）、SUPERSEDED（新提案替代）、INVALIDATED（目标／目的失效）。真实用户处置来自不可变卡片和动作审计；目标／目的失效亦可按当前版本推导，不能在业务拒绝时偷写成功记录，不修改原卡片内容。点击“暂不写入”才产生DEFERRED；关闭卡片无此含义。重新启用需明确操作并重新检查版本。

SUBMITTING／UNKNOWN／ERROR是前端命令状态；EXECUTING不作为提案持久状态，当前同步短事务也不凭空建立长期运行。请求失败通常保留PENDING及错误，用户可在核实后重试；只有确认版本／范围已不适用才INVALIDATED。原UNKNOWN命令只能核实同一method／path／body／key，不能换内容继续用旧key。

提案调整生成新的不可变卡片；只有新卡片成功保存时才记旧提案SUPERSEDED。用户提出调整但模型失败时，保留旧记录并标需重新核对，不继续诱导用户执行已明确反对的旧提案。

### 6.3 确认写入的事务

建议扩展现有responses程序分派，新purpose暂定STAGED_WRITE，具体请求及有效性见第12—14章；不新建公用任意写接口。命令输入包含原message_id／card_key、当前discussion_version、动作及Idempotency-Key，不接受客户端替换原补丁。

1. 在需求级原互斥与进程锁下，核实同所属文档、卡片来源、未处理状态、步骤仍存在且定义适用。
2. 核实base_content_version／Revision、目标原文、写入范围、来源与模板保护。第一版目标内容版本变更即要求重准备，不自动重基；无关规划重排不等于内容版本变更。
3. 从卡片读取原精确补丁，复用patch校验和commit_content；必须显式扩展后者对原生程序动作的来源／权限证明，不能假装成GUIDE_RUN或绕过guard。
4. 同一短事务写正式内容与Revision、用户动作、真实DocumentEffect、ArtifactLink、提案处置和形成事件；失败整体回滚，无“已保存但主线永久漏记”的中间提交。
5. 返回ProgramReceipt，不制造LLMUse、不再Chat。一般确认写入不自动完成步骤。

“写入并结束本步骤”是后续可选联合动作，卡片必须同时展示拟写入与收束结果。校验全部成功才一起提交；收束条件失败不得先写正文。首版可只提供两个分开操作，避免未经评审引入额外组合路径。

## 7. 文档变化与成果复核

AI不能把对话摘要直接当文档成果。ArtifactLink引用真实历史Revision及范围，历史“曾写入”不可改写。freshness建议CURRENT／NEEDS_REVIEW／REMOVED，表示与当前正文的可追溯匹配程度，不是语义完成率。

人工编辑、原REVISE、候选应用、历史恢复及本提案写入，都在正式内容提交时核对受影响范围：区块被改、删除、分拆合并或无法证明对应关系则需复核；完全无关区域变化不让全主线失效。新版本编号本身不等于全部成果变化。

旧完成事件保持，UI同时显示“已完成／关联内容需复核”。下一轮AI对照最新正文及原成果要求给评估；若内容变化需要重新推进，提出重开。程序仅凭文字变化不能声称已满足成果要求，也不能用旧聊天覆盖用户人工修改。

新讨论与正文冲突作为未写回变更列出来源；可以继续推演但标明尚未落地，不把待写回文字显示成当前文档事实。单独确认一项设计想法也不自动写文档。

## 8. 端到端状态轨迹及界面

以下V表示content_version，F表示Formation.version，属于示例，不是现有接口输出。discussion_version另按真实命令递增。

| 用户／AI动作 | 主线与卡片状态 | 正文 | 事件 |
| --- | --- | --- | --- |
| 初次讨论形成路径 | s1推进中、s2待推进；AI说明规划依据 | V1不变 | PATH_INITIALIZED |
| s1已有目标范围，提出写入w1 | s1仍推进中；w1=PENDING | V1不变 | WRITE_PROPOSED |
| 用户确认w1，首次请求回执丢失 | 前端UNKNOWN；服务端可能已APPLIED，不能据UI重复生成 | 实际事务若成功为V2 | CONTENT_LINKED及真实动作审计 |
| 原key核实成功 | 展示w1=APPLIED、关联V2；s1仍推进中 | V2 | 重放不重复写事件 |
| AI评估足够并建议进入s2 | s1仍推进中；Assessment=SUFFICIENT | V2 | ASSESSMENT_UPDATED |
| 用户点结束并继续 | s1完成，closure绑定V2；s2推进中，焦点s2 | V2不变 | STEP_COMPLETED与STEP_STARTED |
| s2引出好友推荐 | b1=OPEN，origin／return=s2；s2仍推进中 | V2不变 | BRANCH_OPENED |
| 用户暂缓好友推荐 | b1=DEFERRED，active_branch清空，返回s2 | V2不变 | BRANCH_DEFERRED |
| s2未完成，用户先看异常情况s3 | s2暂停，s3推进中；不替s2记完成 | V2不变 | STEP_PAUSED／STEP_STARTED |
| 用户恢复s2并确认写入反馈规则 | s2恢复推进中；w2=APPLIED，增加成果关联 | V3 | STEP_RESUMED／CONTENT_LINKED |
| 用户人工改了V2所对应目标区块 | s1仍保留完成历史，成果NEEDS_REVIEW | V4 | ARTIFACT_REVIEW_REQUIRED |
| 用户接受重开s1 | s1推进中，原完成记录可查；原s2按明确跳转暂停 | V4不变 | STEP_REOPENED |

事件名为payload中的动作标识建议，不是直接写入当前受限event_type列的新枚举。新增必要数据约束／资源版本的具体发布方式在实现前决定。

进展面板的步骤行只展示步骤状态；展开后分区显示预期成果、当前文档内容关联、待写回内容、AI评估、建议及支线。操作提供开始／暂停／恢复／结束／重开与调整路线，按实际状态显示。完成建议可一键“结束并继续”，不强制每次额外弹窗；没有建议时仍允许用户主动结束并说明成果处置。历史按事件分页查看，不整段重放聊天。

切到支线时显示“正在讨论b1，返回s2”，提供返回按钮；返回不等于解决。卡片属于消息流并可从对应步骤定位，不另建写入管理中心。切文档、隐藏面板、关闭弹层不丢原请求、不取消后台工作；命令晚到只作用原文档。请求错误与原业务状态分开显示。

## 9. AI输出与程序权限

正常一轮回复在现有结果中扩展形成增量／评估／操作建议，单次原调用完成，不另加摘要或规划Chat。保持自然阐述自由，不要求每轮卡片、路径变化或正文提案。Schema和Prompt使用新冻结资源版本；不得改写v15／v16及旧调用证据。

AI可建议：增加／排序步骤、关联支线、补充问题和来源、评估成果、建议下一步与写入。程序生成：实际版本／时间、用户操作身份、写入落地、提案处置、完成与重开等用户命令事件。不能接受模型宣称“已写入Vn”的字段作为事实。

上下文以最新正文的相关范围、当前形成步骤、有效相关依据、待写入提案、当前支线及必要历史变化为基础；仍保留pending和确定性预算。不能声称全文核对却只带局部，也不能因本功能将所有历史和整本文档每轮重发。人工正文变更与旧讨论冲突要并列标识，不能丢掉用户新修正。

讨论进展／形成增量语义校验失败时，保留原回复并显示未更新原因，不自动修复Chat；正文明确任务继续沿现有独立结果规则。涉及用户原生写入命令的内容与落地关联则必须同事务，不能套用“形成关联失败但正文先成功”的方式提交半个联合命令。

## 10. 建议命令与检查范围（尚未实现）

逻辑命令建议：INITIALIZE_PATH、ADJUST_PATH、START_STEP、PAUSE_STEP、RESUME_STEP、SWITCH_STEP、COMPLETE_STEP、REOPEN_STEP、CANCEL_STEP、RETURN_FROM_BRANCH、DISPOSE_BRANCH、APPLY_WRITE_PROPOSAL、DEFER_WRITE_PROPOSAL、RESUME_WRITE_PROPOSAL。可复用原讨论PATCH及卡片responses入口，但需新增严格联合输入、白名单错误和对应投影；不能声称现有接口已接受这些字段。

检查重点：状态与评估独立；跳转不完成；暂停恢复保留缺口；一次／多次写入不自动完成；成果无正文的核对节点有真实结果；未写出稿内容不被隐式收束；支线返回与暂缓不同；路径重排不机械作废提案；目标版本变更拒绝旧提案；同key重放一次落地；取消／重开／手工修改保留历史；正文与落地关联事务回滚；A文档晚到不改B；无第二次Chat；不把AI评估当用户选择。

真实模型行为需以后另定样本、次数和预算验证；当前没有新调用授权。现有schema151及冻结资源不能未经新设计直接扩充；是否需要schema升级、保留已有数据的升级方式及旧运行读取兼容须在实施前明确，不能沿用历史清库许可。

## 11. 当前断点与后续评审

已形成概念区分、数据职责、状态表、完成／重开规则、支线流转、两类写入路径、并发与事务、示例及候选检查清单。未写代码、运行资源、数据库或正式规格；不是实现完成或验收通过。

步骤完成采用用户收束事件已于0.5确认。仍需评审：②第一版使用独立写入与独立结束，暂不加入联合按钮；③无正文核对类成果与有待写内容的出稿类成果如何展示；④支线结果如何带回步骤。随后细化字段完整Schema、原接口具体扩展、容量／分页、资源准入及存储升级，未定项不假装已具备可执行协议。

本轮文档静态检查见[设计检查](../../../verification/v2.1/document-formation-design-2026-11-06.md)。


## 12. 操作契约草案：版本、命令与回执（0.2补充）

日期：2026-11-07。以下是本轮建议的接口／数据流设计，不是已实现API；URL继续使用项目现有/api/v1前缀，软件V2.1不等于HTTP版本v2.1。第4章“完成需用户收束”已于0.5获得用户明确确认；是否提供联合按钮仍待评审，不因本章细化视为已确认。

### 12.1 三类版本与幂等检查顺序

| 标识 | 控制范围 | 何时变化 |
| --- | --- | --- |
| discussion_version（D） | 所属文档讨论及用户命令的并发快照 | 按现有规则变化；所有形成状态写入同时更新它，每个成功事务至多加1 |
| formation.version（F） | 形成路径的当前投影／历史序号 | 一次事务中规划、评估、支线、成果关联或提案处置有实际变化时加1；同一事务含多项变化仍只加1 |
| content_version（V）及Revision | 当前文档正文 | 实际内容提交产生Vn+1；纯规划／状态命令不增加正文版本 |
| Step.definition_version | 特定步骤的目的／成果定义 | 定义实质改变时加1；排序和纯展示改名不变；状态改变本身不增加定义版本 |

D不能从F或V推算。例如某轮只接受用户输入、没有形成增量，D会变化，F和V可以不变。现有写命令若使某成果需复核，也应在同一内容事务更新形成投影及D；这是需要扩展的真实调用链。

每个用户写请求使用现有Idempotency-Key：先以注册能力＋真实目标身份＋key查找同输入成功回执，命中即重放；再对未完成的新请求检查版本及当前权限。不能先因版本变了拒绝已经成功的原请求。相同key不同body拒绝；只有成功事务保存成功回执，业务拒绝／数据库失败不伪造成功记录。异常后重放只核实原动作，不创建新Chat。

用户命令中的D必须是最新已读取的D。旧提案卡片的“生成时D”仅供历史追溯，不作为永远不变的可用条件；其正文V、步骤定义及真实来源仍逐项检查。新规则只适用于新purpose，不能削弱原澄清／阶段／事实卡片的既有过期逻辑。

### 12.2 原入口的扩展分工

| 拟议操作 | 拟用入口 | 服务器行为／回执 |
| --- | --- | --- |
| 查看当前主线 | GET /api/v1/requirements/{requirement_id}?document_id={document_id}&expand=discussion | 扩展详情投影返回独立formation，概要返回formation_summary；只读，不调用模型，不建立路径 |
| 调整、暂停、恢复、收束、支线处置、提案暂缓／恢复 | PATCH /api/v1/requirements/{requirement_id} | 扩展discussion_command联合；200返回真实讨论／形成状态及事件ID，不创建GuideRun |
| 日常讨论／形成提案／调整提案 | POST /api/v1/requirements/{requirement_id}/guide-runs | 原DISCUSS接受与202；冻结所属文档、原输入及关联提案；新资源返回形成增量／可选写入卡片 |
| 确认精确内容写入 | POST /api/v1/conversation-messages/{message_id}/responses | 新STAGED_WRITE purpose程序分派；200 ProgramReceipt；最多消费该组一次，0Chat |
| 查看形成历史 | 拟新增GET /api/v1/documents/{document_id}/formation-events | 现有审计的有界只读投影；当前无客户端可用的完整形成事件读取，故需补这一读入口 |

新purpose暂定STAGED_WRITE，每组仅一个精确写入提案，不与整组澄清题混装。前端“暂不写入”走原讨论PATCH扩展，而非提交一次性正式卡片回答；以后恢复再确认仍保留一次正式应用机会。只有实际APPLY／NO_CHANGE消耗正式回答，已经成功处理的卡片不能用另一key再执行。普通“继续调整”需要在原DISCUSS输入中明确associated_proposal身份及adjust目的，不能靠搜索用户文字猜关联对象。

严格输入拒绝未知字段、跨文档身份、重复引用、非法枚举与循环依赖。所有命令保留原需求级IDLE／写互斥；另一文档有活动工作也不新增跨文档并行写。纯查看和选择展开可用；忙时不提交计划／内容命令，界面说明具体占用。

### 12.3 当前命令示例：将讨论焦点从s2切到s3（R01更新）

以下JSON为拟议请求体示例，后端从路径绑定requirement_id，从鉴权上下文记录操作者，不信任客户端填写actor／时间。请求带新的Idempotency-Key。

```json
{
  "document_id": 42,
  "expected_discussion_version": 18,
  "discussion_command": {
    "type": "FORMATION",
    "action": "SWITCH_STEP",
    "step_ref": "s3"
  }
}
```

R01的SWITCH_STEP只核实s3是同文档存在的节点，更新讨论焦点并清除不匹配的支线焦点；不改变s2或s3状态，不要求依赖完成或填写原因，不写正文。成功示例前后值：

```json
{
  "before": {
    "discussion_version": 18,
    "formation_version": 7,
    "content_version": 3,
    "current_step_ref": "s2"
  },
  "after": {
    "discussion_version": 19,
    "formation_version": 8,
    "content_version": 3,
    "current_step_ref": "s3"
  },
  "changes": [
    {
      "field": "current_step_ref",
      "from": "s2",
      "to": "s3"
    }
  ]
}
```

这些数值属于说明，实际HTTP仍包在原success／data／error／meta壳内。若第二个状态转换或事件保存失败，整次回滚，不能只保存半份焦点／支线变化。

### 12.4 具体命令示例：完成步骤与收束依据

Step.expected_results细化为稳定的result_ref、description、kind=CONTENT／ANALYSIS，其中CONTENT要求关联当前文档实际内容；ANALYSIS用于来源核对等无需写正文的成果。类型不是AI在完成时临时改成“无需正文”的逃生口。改变既定kind或取消成果按明确路径调整处理。

```json
{
  "document_id": 42,
  "expected_discussion_version": 22,
  "discussion_command": {
    "type": "FORMATION",
    "action": "COMPLETE_STEP",
    "step_ref": "s2",
    "expected_definition_version": 1,
    "expected_content_version": 4,
    "result_dispositions": [
      {
        "result_ref": "s2.o1",
        "disposition": "IN_DOCUMENT",
        "artifact_refs": [
          "a4"
        ],
        "source_refs": []
      }
    ],
    "issue_dispositions": [
      {
        "issue_ref": "i3",
        "disposition": "DEFERRED",
        "reason": "冷启动细节单列到异常处理",
        "followup_step_ref": "s3"
      }
    ],
    "next_step_ref": "s3",
    "expected_goal_version": 1,
    "branch_dispositions": []
  }
}
```

R07程序检查：允许空提交列表，并依据实际状态补齐全部预期成果及未处置问题快照；a4属于同文档且对应成果定义，其当前内容关联可核实；遗留阻塞不能默默消失；next_step不是原步骤且可开始／恢复。IN_DOCUMENT只证明指定内容真实存在且关联有效，语义充分由用户本次收束负责。没有a4或它已NEEDS_REVIEW时保守记为OUTSTANDING，不以此阻止用户结束。

对ANALYSIS成果使用ANALYZED并带真实来源及结果记录；不得拿它覆盖CONTENT成果。用户决定把一个CONTENT成果整体留到后续时，先明确调整成果归属／范围，保存definition_version变化；旧完成动作不得在不展示这种变化的情况下顺便改变要求。由此区分“暂停原工作”与“明确调整范围后完成”。

完成事务保存Closure：步骤定义快照、当时Revision、逐项成果／问题处置、用户操作来源与选定下一步。s2变COMPLETED，s3按需进入IN_PROGRESS，D和F各加1、V不变，返回event_ids。没有next_step时焦点为空；无待推进节点不自动确认整本文档或切换需求状态。

### 12.5 程序回执的最小事实

PATCH与STAGED_WRITE的成功data建议都包含：processing=PROGRAM、requirement_id、document_id、discussion_version、formation_version、content_version、effects、event_ids。按0.6收口采用最小事实回执，最新全状态由原GET取得；effects区分formation_changed、document_effect、proposal_effect。复用既有DocumentEffect结构，不用模型文字推断保存；body不让客户端提交“成功”字段。

NO_CHANGE动作不增加状态版本，不创建重复形成事件或Revision，但可保存幂等成功回执。重放回执表示原事务已成功，不保证它仍是最新状态；客户端随后按原观察／核实机制刷新，不能用旧回执覆盖更新的文档。

## 13. 精确写入提案：从模型输出到程序保存

### 13.1 不可变内容与可变处置

提案内容存于单一STAGED_WRITE卡片：proposal身份仍是message_id＋card_key，不另建顶层Task／Proposal服务。字段至少包含document_id、step_ref、definition_version、goal_version、result_refs、base_revision_id、base_content_version、write_kind、scope、exact_content／patches、source_refs及change_summary；每种write_kind使用互斥字段，不能同时带多种正文。没有result_refs则不能把本次写入自动算到某个成果，需先明确关联。

可变处置沿审计投影。PENDING／DEFERRED／SUPERSEDED／APPLIED／NO_CHANGE来自真实动作；INVALIDATED及有效性原因可由当前目标版本、步骤定义和来源状态计算，不能为了返回一个409偷偷提交独立状态变更。正文变更或用户路径调整等已有成功事务可同时记录相关失效事件；只读检查不产生审计。

有效性投影返回can_apply、reasons与current_content_version，供UI禁用并解释；它不是另一个提案完成状态。调整提案请求一经实际接受，就记录needs_revision=true并禁用旧内容应用，避免模型失败后仍诱导接受已反对的文字。新提案成功保存后才产生SUPERSEDED；调整失败可以继续调整，用户明确撤回调整且版本仍匹配时才恢复旧提案可用。

### 13.2 首次写空文档与修改已有文档

普通INSERT_BEFORE／INSERT_AFTER需要真实区块，空白文档无锚点，因此不能声称直接复用现有补丁就足够。建议区分：

| write_kind | 前提与内容 | 验证与结果 |
| --- | --- | --- |
| FILL_EMPTY | 现有CURRENT经过真实解析无业务区块；卡片带该版本完整拟写Markdown | 服务端再次检查基准版本和空状态，解析正文／分配身份，形成同文档的新Revision；不是创建另一份文档 |
| PATCH_EXISTING | 有真实区块／章节，提案带原范围及精确补丁 | 复用现有补丁原文、位置、范围和模板保护；拒绝范围外变化 |

固定框架有标题和占位内容时不属于FILL_EMPTY，须按真实区块操作且保留锁定标题。第一版不提供“覆盖整篇以便追加小段”的兜底；无法精确表达的写入先提出较小范围方案。两条路径仍需要给原生程序命令建立明确权限证明，不能伪造AI运行或绕过commit_content检查。

### 13.3 确认／暂缓／恢复的请求区别

已保存的卡片身份为message=103、card=w1。确认应用的拟议responses body如下；不含客户端正文或由客户端重选的范围。

```json
{
  "schema_version": 1,
  "expected_discussion_version": 25,
  "responses": [
    {"card_key": "w1", "selected_option_keys": ["apply"], "custom_answer": null, "skipped": false}
  ],
  "execution_selection": null
}
```

组内只有w1，消息本身绑定所属文档。后端新purpose分派核实未正式消费、最新D、当前V及步骤定义后执行精确内容。所示回答字段沿用现有形式，purpose／action_payload仍须新Schema，不能把新选项直接塞进旧资源。

暂缓用PATCH的FORMATION／DEFER_WRITE_PROPOSAL，携带原message_id＋card_key及reason；恢复用RESUME_WRITE_PROPOSAL，先重新检查目标版本和用途。两者不插入一次性CARD_RESPONSE，因此不会提前耗尽“确认应用”机会。恢复不会自动生成新内容；目标V已变时恢复失败并显示重新准备入口。

### 13.4 原样写入的事务顺序

成功幂等回执优先重放 → 锁与同所属关系 → IDLE与最新D → 新purpose／精确卡片身份和未消费状态 → 基准V／Revision、步骤定义／result_refs与来源 → 全部补丁／模板／容量校验 → 正文与Revision＋用户动作／CARD_RESPONSE＋处置＋ArtifactLink＋形成事件＋新状态＋成功回执，同事务提交。

返回200且processing=PROGRAM；不插LLMUse，不再Chat。正文没变化则NO_CHANGE，不造新Revision；若本次建立了此前缺失的合法成果关联，D／F仍可变化；是否变化依据实际差异，不把NO_CHANGE文案误当所有投影都不变。普通确认应用不完成步骤，不插STEP_COMPLETED。

假设执行前D25／F9／V3，补丁有真实变化：提交后D26／F10／V4，w1=APPLIED，s2仍IN_PROGRESS。若目标V已经是4且原key没有成功记录，则拒绝旧提案；客户端不能把base_version改成4后直接重发原补丁。

## 14. 并发、失效、失败与恢复

| 场景 | 服务端事实 | 用户界面与下一步 |
| --- | --- | --- |
| 又聊了一轮，卡片生成时D已旧，但文档V和步骤定义未变 | 提案可仍有效；本次应用需提交新读到的D | 刷新命令依据，保留原精确预览；不自动再生成或补Chat |
| 另一页改了正文 | 原提案基准V失配，不能应用 | 显示原V与当前V，重新准备并展示新提案；不静默重基 |
| 模型回复晚到 | 沿运行租约／冻结D／取消规则核实，不能覆盖新规划 | 保留可读返回与未应用原因；不把旧建议当最新主线 |
| 接受调整提案后模型失败 | 旧提案仍存但needs_revision，不能应用；无新提案 | 保留用户输入，允许继续调整或明确撤回调整 |
| 提案已成功写入，HTTP超时 | 成功记录及正文已同事务提交 | UNKNOWN保留原body／key，重放得到原成功；不重复写 |
| 写入过程中校验失败／数据库失败 | 不提交正文、正式回答、成果关联或伪成功处置 | 显示具体失败并保留提案；业务错误不强制INVALIDATED写事务 |
| 步骤重排但目的不变 | definition_version不变，原提案可仍有效 | 更新路径顺序；不要求重做所有预览 |
| 目标／成果要求改变、步骤取消 | 原提案用途失效 | 禁用并解释，原提案／旧路径历史可查 |
| 用户改了另一份文档 | 不混用D／F／V和局部引用；原需求互斥仍核实 | 晚到回执只更新原文档缓存，不清另一文档输入或选择 |

业务拒绝后若需改变body／基准版本，应先确定原动作未成功，再建立新的明确动作和key；UNKNOWN期间不能这样做。同一事务多个形成事件共享F，靠event_id排序，不要求F每个事件增加一次。每次事务为原子状态迁移，前端不发布只含一半焦点变更的快照。

## 15. 从用户动作到界面更新

### 15.1 起步、讨论与主线初始化

读取空主线不自动调用模型。用户已经为当前文档发起形成／讨论工作时，第一轮正常回复可同时提出路径；经结构、来源和状态核验后建立路径及当前步骤，保存actor=AI的规划事件，不伪装为用户批准全部方案。R01已确认建线后自动将第一步设IN_PROGRESS及当前讨论，不再要求用户额外开始。无论采用哪种起步方式，都不能给已有路径的步骤自动记完成。

用户只在查看旧文档、问一个无关解释或缺少文档目的时，不为了填满面板自动创建整套路线。已有正文建立主线时，AI指出已有成果的真实位置，程序只接受实际材料中可验证的引用；不能标成“本轮写入”。这种EXISTING_CONTENT_ASSOCIATED事件与CONTENT_LINKED区分。

主线面板为步骤列表；当前行展开，展示预期成果、真实文档位置／版本、待写入提案、未解决问题、支线及AI评估。正常讨论保持自由表达；AI无需每轮返回路线变化或卡片。位置引用可定位当前正文；原内容变化时能查看历史，并显示需复核，不把旧快照冒充当前正文。

### 15.2 明确点击动作

| 入口 | 前端动作 | 实际请求与完成条件 |
| --- | --- | --- |
| “在此讨论” | 即时选择讨论节点，必要时标下一轮目标，不改生命周期 | 空闲写回或下轮接受时冻结；不暂停／完成原步骤，不额外Chat |
| “返回主线” | 保留当前支线信息 | RETURN_FROM_BRANCH成功清支线焦点，支线仍可OPEN |
| “暂缓这条支线” | 输入或沿明确上下文带入原因 | DISPOSE_BRANCH=DEFERRED成功后返回主线，不改正文 |
| “结束并继续” | 展示成果及遗留处置，同一次操作提交 | COMPLETE_STEP成功后更新状态和焦点；缺依据就地说明，不先标完成 |
| “确认写入” | 冻结原卡片身份、最新D及key | 200 PROGRAM才展示实际版本与落地位置；UNKNOWN保留原动作 |
| “继续调整” | 把原提案关联到当前输入，用户继续说明 | 明确发送DISCUSS才产生运行；仅打开输入不废弃旧提案 |
| “暂不写入”／“恢复提案” | 不触发模型 | 原生PATCH成功更新处置／可用性；恢复需目标仍匹配 |

状态建议：客户端READY→SUBMITTING→CONFIRMED后刷新真实投影；网络不确定进入UNKNOWN；200回执后读取失败仍保留CONFIRMED“操作成功，显示待刷新”，不再次执行业务。不把后续GET失败显示成正文保存失败。隐藏面板／切文档不丢命令，成功回执不抢走用户当前阅读位置。

### 15.3 历史查看

拟议只读历史入口按document_id校验归属、before_event_id游标、limit默认20／最大100，按event_id倒序返回。每条包含actor、action、reason、相关step／branch／proposal、D／F／V前后值、真实来源和Revision链接；不返回凭据、私有授权或完整模型请求。

事件payload带formation schema版本及可解释差异，实体定义变化保留前后快照。界面可按步骤过滤并分页追溯；不通过重放模型回复重新计算事实。当前形成状态和审计同事务保存，旧历史不随当前路径调整覆盖。

## 16. 本轮设计完成范围与未决事项

0.2补齐D／F／V关系、能力幂等顺序、既有入口具体扩展、三类请求示例、阶段性精确内容应用、空白文档首写、提案暂缓／恢复与一次性回答关系、错误恢复和界面数据流。本轮仍是契约草案，尚未写可执行JSON Schema或实现任何接口。

完成步骤需用户一键收束已于0.5确认。下一轮优先：明确默认独立写入／结束的交互；确定状态规模与容量预算、完整字段Schema、新资源协议和旧运行读取边界、数据库升级策略。数据库实际新增字段／约束、新purpose白名单与私有program_binding精确字段尚需专项定义，不能凭本章示例直接部署。原有9根输出字段／冻结Schema不允许原地塞新字段；可以在新发布的progress_delta／cards Schema扩展，须与资源准入及审计一起验证。

本轮文档检查见[0.2静态记录](../../../verification/v2.1/document-formation-contract-design-2026-11-07.md)。


## 17. 逻辑数据字典（0.3补充）

日期：2026-11-07。目标软件V2.1，草案修订0.3。以下明确本轮建议的对象字段及写入责任；仍非可执行Schema或既有接口，用户未逐项确认的取舍继续待评审。

### 17.1 旧阶段维度与新文档路径的关系

现有GuideDefinition.mainlines是阶段指导维度（如目标、场景、主流程），topic.mainline_ref引用它。它不是文档形成步骤，不能直接改名或复制为steps；Step.topic_refs把一个或多个实际讨论主题关联到形成步骤。一个步骤可以涉及多个阶段维度或在阶段改变后继续，阶段切换不使它自动完成。

用户界面“文档形成主线”专指FormationState；旧阶段维度只作为AI指引或讨论分类。新资源模型输入中建议使用stage_overview表达旧阶段总览、formation表达新路径，避免把两者同名混用；旧冻结Wire继续按旧协议读取，不原地改字段。

### 17.2 公共类型与空值

ID为1—9007199254740991安全整数，版本从1递增；UTC时间由程序生成。LocalRef按类型为sN／bN／iN／aN，成果引用为sN.oK，仅在所属文档内有效。Result编号由每个Step.next_result_no分配，不因删除复用。事件ID引用现有审计身份。

SourceRef沿现有消息／正式答案／Revision／运行结果／不可变材料联合结构。模型中的source_refs是本轮实际携带的短别名，保存前必须解析回真实SourceRef，不能把m201或模型自填SQL ID直接作为已核实关系保存。

下表列出的字段默认全部必传；可空字段必须明确null，无内容集合为[]，不能用省略字段隐含默认。新文档formation=null表示尚未建立路径，与存在但无当前步骤的FormationState不同。集合按数组保存，引用唯一、语义关系与状态不变量由程序检查，JSON类型检查不能代替关系校验。

### 17.3 当前状态字段

| 对象 | 字段与类型 | 初始值／限制与责任 |
| --- | --- | --- |
| FormationState | schema_version:int、version:int、goal:Goal、current_step_ref:StepRef或null、active_branch_ref:BranchRef或null、ordered_step_refs:StepRef[]、steps:Step[]、branches:Branch[]、issues:Issue[]、artifacts:ArtifactLink[]、counters:Counters | schema_version=1；首次version=1；历史在审计，不复制所有历史快照到此对象 |
| Goal | version:int、text:Text、source_refs:SourceRef[] | 描述文档用途／预期成果；首次1；实质目标变化须明确用户动作并加1，不能用AI规划整理暗改 |
| Counters | next_step_no:int、next_branch_no:int、next_issue_no:int、next_artifact_no:int | 均由程序维护，始终大于已分配编号；初始1；映射模型临时引用后递增 |
| Step | step_ref、definition_version:int、title:Text、expected_results:ExpectedResult[]、next_result_no:int、dependencies:StepRef[]、status:StepStatus、topic_refs:TopicRef[]、issue_refs:IssueRef[]、artifact_refs:ArtifactRef[]、replaces_step_refs:StepRef[]、assessment:Assessment或null、recommendation:Recommendation或null、closure_event_ref:EventID或null | 新步骤PLANNED，定义版本1，必须至少一个成果要求；首轮实际启动例外见15.1；status由合法过程事件变更 |
| ExpectedResult | result_ref、description:Text、kind:CONTENT或ANALYSIS | 成果要求有稳定身份；CONTENT必须以正文承载；调整要求／kind增加步骤定义版本并留差异 |
| Branch | branch_ref、origin_step_ref、origin_event_ref:EventID、return_step_ref、question:Text、relevance:Text、status:BranchStatus、topic_refs:TopicRef[]、result_summary:Text或null、result_source_refs:SourceRef[]、disposition_event_ref:EventID或null | 初始OPEN，结果空；RESOLVED须有结果及来源，DEFERRED／DROPPED须有真实用户处置；结果不能冒充正文 |
| Issue | issue_ref、step_ref、branch_ref:BranchRef或null、description:Text、source_refs:SourceRef[]、blocking:bool、disposition:OPEN／RESOLVED／DEFERRED／DROPPED、reason:Text或null、resolution_source_refs:SourceRef[]、disposition_event_ref:EventID或null | 初始OPEN；blocking是对当前成果的影响判断，不自动锁住整个需求；暂缓／排除须保存用户处置及影响 |

ordered_step_refs含所有未取消步骤的顺序，不包含CANCELLED；steps保留取消对象以支持旧引用，UI在历史区展示。dependencies允许引用已完成但未取消步骤；取消被依赖步骤须在同一明确路径调整中处理依赖，否则拒绝产生悬空关系。replaces只引用真实旧步骤且不形成循环，不能删除旧步骤替代历史。

Goal.version变化使全部旧提案用途待重新核对，不能仅因Step.definition_version未变继续应用。WriteProposal新增goal_version快照。旧评估绑定goal版本不匹配即陈旧，不能拿来代表新目标已经足够。

### 17.4 成果、评估与建议

| 对象 | 完整逻辑字段 | 程序保证 |
| --- | --- | --- |
| ArtifactLink | artifact_ref、step_ref、result_refs:ResultRef[]、source_event_ref、origin_revision_id、origin_block_ids:BlockID[]、origin_content_digest:Digest、summary:Text、checked_against_revision_id、current_block_ids:BlockID[]、freshness:CURRENT／NEEDS_REVIEW／REMOVED | 由真实正文及验证结果生成；origin字段固定，后续只更新当前匹配投影；保留来源事件，不伪造本轮写入 |
| Assessment | verdict:SUFFICIENT／GAPS_REMAIN／UNCERTAIN、reason:Text、goal_version:int、evaluated_step_version:int、evaluated_revision_id、coverage_block_ids:BlockID[]、source_refs:SourceRef[]、assistant_message_id | AI形成判断；程序绑定本轮实际Revision／覆盖／消息，禁止模型自填未读取区域为已覆盖 |
| Recommendation | action、step_ref:StepRef或null、reason:Text、source_refs:SourceRef[]、assistant_message_id | action建议为DISCUSS／WRITE／RESOLVE_BRANCH／REVIEW_CONTENT／COMPLETE_STEP／SWITCH_STEP／NEED_MATERIAL；只是建议，不执行对应命令 |

ArtifactLink.result_refs至少一项且属于该步骤；同一实际内容可以关联多个成果，但不能以多次关联制造多次写入。初次关联既有内容也要经过程序核实，用EXISTING_CONTENT_ASSOCIATED事件；模型只能提议关联，不能直接生成ArtifactLink、Digest、Revision或“已写入”事实。

当目标范围原文及身份在新版本中仍匹配时，程序可将checked_against_revision_id更新为新Revision，CURRENT只代表可追溯内容仍在，不证明语义充分。原块变更／部分丢失／身份无法证明时为NEEDS_REVIEW；全部关联内容消失才REMOVED。历史恢复也按真实新版本核对，不能仅凭相同文本恢复已删除的区块身份。

评估的is_current及stale_reasons是读取投影，不修改AI原判断：目标版本或步骤定义改变则陈旧；正文V变化但覆盖范围完全未变且程序能证明时可标“覆盖内容未变”，同时保留原evaluated_revision_id，不能声称AI评估过新全文。无法证明则需要复评；不自动清除旧评估或重开步骤。

### 17.5 提案与事件补充

WriteProposal内容字段在13章基础上固定为：schema_version=1、document_id、step_ref、definition_version、goal_version、result_refs、base_revision_id、base_content_version、write_kind、scope、markdown_content、patches、source_refs、change_summary。FILL_EMPTY使用markdown_content，patches=[]、scope=DOCUMENT；PATCH_EXISTING使用patches且markdown_content=null，scope必须精确指定。补丁格式复用当前已核实算法的版本化定义，不允许裸字符串补丁或客户端提交BlockState。

proposal身份从外层message_id＋card_key取得，不让模型指定。预览从exact markdown／patches生成，change_summary不能代替真实差异。处置与can_apply／needs_revision是独立投影，应用成功绑定实际ProgramReceipt和content事件。提案不在FormationState内重复保存全文；Step只按消息／卡片关系查询关联提案，防止正文在多份状态间漂移。

FormationEvent字段按0.6收口统一为schema="formation_event_v1"、event_id、document_id、batch_ref、ordinal、batch_size、actor=USER／AI／PROGRAM、action、reason、related_refs、source_refs、version_before／version_after、changes、closure、created_at。actor表示谁提出该业务变化，不是网络请求来自哪个进程：AI规划为AI，用户收束为USER，文档变化触发的关联复核为PROGRAM；所有身份／时间由程序填写，并保留来源消息／真实命令。事件可一组共享F；当前视图与事件同事务提交。

## 18. AI每轮读取的材料与权限边界

### 18.1 “最新文档”具体指什么

接受用户请求时，程序从同一数据库快照冻结D／F、目标版本、文档原文、当前步骤、用户输入及相关材料。执行装配使用这份已接受快照，不在Chat中途重新读取不同版本的正文；提交时再核实执行权和版本。当前文档是接受时最新的已保存正文，不是把历史摘要当正文，也不是让迟到回复覆盖后来的版本。

私有Canonical／ContextBasis保留完整状态、引用解析和写入权限，模型只收所需材料。模型可见的路径信息建议放新资源的project_position.formation，旧指导维度另作stage_overview；正文仍只有DOCUMENTS的一份原文，其他区域使用引用，不复制全文到每个步骤里。

### 18.2 确定选材规则

| 区域 | 本轮默认材料 | 可以省略什么／不能声称什么 |
| --- | --- | --- |
| 文档用途与约束 | Goal及当前有效GLOBAL依据、本轮显式指令 | 不把AI建议当用户决定；已推翻／争议信息分别标注 |
| 路径定位 | 步骤顺序、身份、标题、状态短总览；当前步骤完整定义与评估；直接依赖／建议下一步定义 | 全路径总览不是全步骤详情，不能据此声称逐项验收 |
| 当前内容 | 当前步骤关联的当前正文、选定工作范围及明确来源；附Revision与FULL／PARTIAL覆盖 | 导航标题与成果摘要不等于已读正文；缺必要范围应明确提出补读 |
| 支线／缺口 | 当前支线、归属步骤的未决问题、关键阻塞与明确处置 | 其他支线只给有界摘要／引用，不能擅自标解决 |
| 待写回 | 当前步骤有效提案摘要；正在调整的提案带精确内容及原始用户修正 | 已保存正文与拟写内容分开标；不把旧提案当当前事实 |
| 历史与来源 | 用户明确提供来源、有效长期依据、当前步骤最近的重要形成事件、原pending、原近期历史规则 | 不每轮重发全部形成事件；摘要保留来源，不替代原始证据 |

选材由程序按身份、步骤关系、来源和状态确定，不额外调用模型排序相关性。用户跳到另一步时，选材随真实焦点／关联调整，不能只改界面却仍发送旧步骤材料。无当前步骤时携带Goal、路径总览、未处置关键问题及用户输入，AI可建议开始／恢复步骤，不猜测完成状态。

模型需要未携带的必要内容时，输出NEED_MATERIAL建议，列出已知引用、用途及所需范围；由用户明确继续的下一次工作补齐。它不触发隐藏补读Chat或自动读取整库。操作涉及的对象必须在实际材料清单中；只见身份／标题可以建议进一步读取，不能修改未读定义或据此做完成评估。

## 19. AI返回哪些变化、程序如何接收

### 19.1 保持原回复自由，新增有限结构

新发布资源在progress_delta内增加formation_delta（无更新时null）。九个现有输出根字段的职责保持，只有新资源Schema接受新增子字段；旧资源／旧请求原字节读取。卡片按需要返回，普通阐述不要求产生计划事件。

formation_delta必填basis和changes；basis包含formation_version、goal_version、document_revision_id、content_version。新路径尚不存在时前两项为null；只能使用INITIALIZE_PATH型增量，不能借null跳过已存在路径的检查。每项变化有明确type和与该type对应的严格字段，不接受任意整对象覆盖或自由JSON Patch。

| 模型变化类型 | 允许作用 | 明确不允许 |
| --- | --- | --- |
| INITIALIZE_PATH | 有实际形成工作且尚无路径时提出目标、步骤、成果与首次焦点；用户原输入为来源 | 无用户材料创造目标；把全部新步骤标完成 |
| ADD_STEP／UPDATE_STEP／MOVE_STEP | 规划新步骤、细化未确认的描述和依赖、调整排序；检查影响及实际来源 | 自行取消步骤、重开已完成步骤、缩小既定成果kind或目标；影响取舍须用户动作建议 |
| ADD_ISSUE／UPDATE_ISSUE | 登记缺口、说明影响或有依据的解决结果 | 伪造用户暂缓／排除；自动降低关键约束来使步骤完成 |
| ADD_BRANCH／UPDATE_BRANCH／SET_BRANCH_FOCUS | 登记支线、补充结果、在当前步骤下进入／返回讨论位置 | 代用户作DEFERRED／DROPPED处置；无结果标RESOLVED；把别的步骤支线默默搬来 |
| ASSESS_STEP／RECOMMEND | 评估实际携带的成果与覆盖、提出下一步 | 写步骤状态COMPLETED、改变需求状态或声称正式确认 |
| ASSOCIATE_CONTENT | 建议将实际读取的当前文档区块关联到指定成果 | 直接填写ArtifactLink、历史写入事件或“已写入Vn”；引用未读取区域 |

INITIALIZE_PATH和已有路径的动作使用互斥结构。AI提出需用户接受的目标／范围变更可以通过新资源的操作建议承载，原生接受后才产生对应状态变更；不能在普通formation_delta中先应用再让用户追认。其他步骤的进展不得仅因AI建议下一步而自动开始，遵守第4章已确认的用户收束规则。

UPDATE_STEP按0.6严格使用title、add_results、dependencies、topic_refs白名单，add_results只追加成果、不替换既定成果数组；旧值差异有记录；若涉及既定目标／成果取消或已完成步骤内容，转为用户操作建议。MOVE_STEP用step_ref及before_step_ref或null，不能用遗漏旧步骤的新全量列表造成隐式删除。

### 19.2 新引用与来源的校验顺序

1. 从本轮冻结材料建立已知步骤／支线／问题、已携带文档区块和消息的白名单；校验basis与冻结D／F／V及Goal一致。
2. 检查变化类型／字段集合／容量；同一字段同轮多次冲突写入拒绝，不按最后一项偷偷覆盖。
3. 模型新增项只能使用new_step_N、new_result_N、new_branch_N、new_issue_N临时引用；程序先在内存规划完整映射，再解决依赖与交叉引用。无效增量不耗用持久编号。
4. 在内存旧状态副本上应用全部变化，检查引用、归属、无循环、单当前步骤、支线焦点及用户动作权限；校验所有source别名真的已发送。
5. 关联内容由程序从真实Revision验证，分配ArtifactRef并构造事件。AI评估绑定本轮实际覆盖、Goal与步骤定义，模型提供的已读声明不能扩大覆盖。
6. 通过后才在原结果事务内保存消息、状态与事件，D／F按真实变化各加1；V不变。模型未生成或未执行正文提案时没有内容提交。

原progress_delta与formation_delta可以交叉引用主题／依据，因此构成一个完整进展语义单元：先共同验证再原子应用；不能只写一半留下悬空关系。验证失败保留原始可读回复，进展投影整体保持原值；该次已接受用户输入仍留pending，不因失败标成已处理。用户已明确的独立GENERATE／REVISE结果仍沿既有独立内容校验，不被无效进展强行丢掉。

有效STAGED_WRITE卡片必须有已存在且用途匹配的步骤／成果，或与同轮有效增量创建的步骤绑定。若其依赖的增量被拒绝，该卡片不能显示可执行，保留说明与原因；不以可读正文伪造可点击写入动作。独立有效卡片能否保存按实际绑定核验，不用整条回复成功图标概括所有分量。

### 19.3 一轮完整示例：提出支线但不修改文档

初始：D30／F12／V4，当前s2=IN_PROGRESS，讨论主题焦点为空，Goal.version=1，当前正文Revision401，branch下一个编号4。用户输入message201：“要不要让好友帮忙推荐？”接受讨论后D31／F12／V4，201加入pending，随后冻结本轮材料。实际携带m201，以及当前流程的区块别名d42v4b12。

以下是拟议九根输出完整示例；它不是当前v15协议可直接接受的返回：

```json
{
  "schema_version": 1,
  "response_type": "DISCUSSION",
  "message": "好友推荐可能扩大个人使用的范围。可以先探索它解决什么问题，再决定是否纳入本版；当前推荐流程保持不变。",
  "basis_ref": {"discussion_version": 31, "phase_ref": "p1", "guide_key": "collaboration.discovery", "guide_version": "v1"},
  "progress_delta": {
    "topic_changes": [],
    "evidence_changes": [],
    "focus_topic_ref": null,
    "next_step": {"action": "ASK_DECISION", "topic_ref": null, "reason": "先明确好友参与的必要性", "unresolved_impacts": ["可能扩大使用范围"]},
    "processed_user_message_ids": [201],
    "formation_delta": {
      "basis": {"formation_version": 12, "goal_version": 1, "document_revision_id": 401, "content_version": 4},
      "changes": [
        {"type": "ADD_BRANCH", "temp_ref": "new_branch_1", "origin_step_ref": "s2", "return_step_ref": "s2", "question": "是否需要好友参与推荐", "relevance": "可能扩大个人使用范围", "topic_refs": [], "source_refs": ["m201"]},
        {"type": "SET_BRANCH_FOCUS", "branch_ref": "new_branch_1", "reason": "探索本轮明确提出的问题"},
        {"type": "ASSESS_STEP", "step_ref": "s2", "definition_version": 1, "verdict": "GAPS_REMAIN", "reason": "当前流程已存在，新增范围问题尚待处理", "document_refs": ["d42v4b12"], "source_refs": ["m201"]}
      ]
    }
  },
  "cards": null,
  "document_result": null,
  "suggestions": null,
  "analysis": null
}
```

程序通过后将new_branch_1映射b4，真实m201解析到MESSAGE／201；保存AI规划事件与评估。最终D32／F13／V4：s2仍IN_PROGRESS，b4=OPEN，active_branch_ref=b4；201从pending移出，但原消息和支线来源永久保留，不表示需求已采用，也没有写文档。三项变化只使F加1，不加3。

下一次用户点“暂缓支线”，原生命令核实D32后D33／F14／V4，b4=DEFERRED、焦点回s2；无新Chat，无正文写入。只有后续明确确认写入内容，才走第13章内容事务。若上述示例引用未携带区块，则拒绝整个进展单元：D保持接受后的31，F12／V4不变，201仍pending，回复可读且显示“主线未更新”。

## 20. 容量、失效与本轮待评审范围

以下为设计建议值，尚无本项目负载验证，不作为当前已生效限制：每文档最多200步骤、1000支线、1000问题、2000个成果关联；每步骤20项预期成果；状态JSON序列化UTF-8整体不超过1MiB，同时满足现有调用／审计及Token预算。title建议120码点、description／reason等短文本1000码点、成果摘要240码点；来源数组每项最多50引用。精确正文提案继续受原文档／补丁／审计容量约束，不塞入1MiB的主线状态。

每次AI形成增量建议最多20项变化、整体64KiB。用户原生命令沿各命令范围校验，无变化不制造事件。超过条数／字节上限整段拒绝且明确说明，不默默截断后半或删除历史；历史事件另存、分页查阅，不受当前状态1MiB限制。已有合法状态仍可读，不能为凑容量自动取消步骤或清理证据；扩容／显式归档机制在实施前另定，不用隐藏后台摘要替代。

进入模型前按第18章先去重、选择；预算不足优先移除可选近期历史、非当前的可选背景。当前用户输入、明确硬约束、当前步骤必要定义、拟评估／拟修改的必需正文不能被裁掉后仍宣称完成。必要输入仍超限则不Chat，向用户说明实际缺口与缩小范围／分批选择；不以字数估算放行。旧有计数上限及真实准入不因本草案自动改变。

状态无效、模型进展被拒绝、卡片不可执行、正文未写入、正文已写入但显示待刷新分别投影，前端不能用一个通用失败／成功标识混淆。对用户拒绝或修正的内容，后续选材保留其处置和来源，不把“提案已暂缓”当作已采用决定。

0.3完成逻辑数据字典、AI读写边界与一轮输入到落库的设计示例；没有实现Schema、存储或模型效果验证。下一轮应收束设计取舍并补可执行协议／新旧资源与存储升级方案，不能把章节增加当作已解决全部未决事项。其中“步骤完成需用户收束”已于0.5确认；是否自动启动首步、默认独立写入／结束、容量建议值仍待评审。

本轮静态记录见[0.3数据与AI流转核对](../../../verification/v2.1/document-formation-data-design-2026-11-07.md)。


## 21. 路线节点交互与视觉方案（0.4补充）

日期：2026-11-07。用户新增明确要求：路线节点要明确、好看且易用；清楚知道什么事件触发与完成；能够查看已放弃节点；支线清楚表达来自哪里。这些是已确认交互目标；用户随后认可0.4原型整体方案。精确尺寸、样式细节及真实集成仍需检查，不能视为所有参数已获逐项批准。

[可点击离线原型](previews/formation-route-v04.html)使用虚构电影推荐示例，可查看节点、支线、事件、文档快照及已放弃记录；不连接项目、模型或外网，不更新真实业务。它是独立HTML设计附件，不是前端已实现功能；未实现原生命令提交／编辑路径，不能用原型可点击证明后端可用。

### 21.1 默认纵向路线，展开视图看细节

复用所属文档“进展”面板承载“文档形成路线”，不另加常驻整页或把内容叠在对话输入上下。默认单列：有顺序的节点＋连续主线；当前步骤明确标“进行中”，已完成用图标与文字双重表达；查看选择与业务焦点分开。

```text
文档形成路线                         [展开视图]
[ ] 已放弃节点 2    [✓] 支线       [定位当前步骤]

✓  1 明确目标与首版范围                         已完成
│    你结束本步骤 · 成果见 V2
│    └─ 评分方式                               已暂缓
│       来自 ① 目标与首版范围
●  2 形成推荐与反馈流程                         进行中
│    由上一步“结束并继续”触发
│    └─ 好友是否参与推荐                         讨论中
│       来自 ② 推荐与反馈流程
○  3 补齐异常情况与边界                         未开始
│    尚无开始事件
○  4 核对全文与遗留问题                         未开始
```

常态面板沿现有360px最小／420px偏好，不为路线挤压正文。点击节点在同面板展开详情，每次只展开一个；明示“查看”不改current_step_ref。展开视图复用原详情逻辑，在空间允许时左路线／右详情；狭窄环境回到单列，不压成横向小图。保留选中节点、页签、展开偏好和滚动；关闭展开视图不丢业务输入或改变步骤。

不采用横向超长流程条／可拖动画布作为默认界面，避免小面板平移缩放才能看清。路径顺序用连线与编号，支线用缩进和侧向虚线；仅显示一层归属，支线内继续深入仍记录消息和主题，不凭空制造无限层级图。

### 21.2 节点内的最少可见信息

| 位置 | 内容 | 真实来源 |
| --- | --- | --- |
| 左侧标记与编号 | 当前／完成／未开始的图形，当前路径序号 | status与ordered_step_refs；序号不是稳定身份，改序不改step_ref |
| 标题与状态 | 可读成果标题、状态文字 | 节点定义与状态事实；AI评估不能代替状态徽标 |
| 第二行 | 最近关键过程：谁开始／完成／暂停，或尚无开始事件 | 程序事件摘要；不能从last_step推荐猜测 |
| 支线入口 | 支线标题、状态、来源步骤名称／序号 | Branch.origin_step_ref及来源事件 |
| 特别提醒 | 关联内容需复核、有效待写入提案等少量标记 | 真实成果匹配／提案投影；不把所有内部计数堆在标题上 |

首屏强调正在形成哪部分与前后顺序，不显示D／F或内部引用号。步骤标题允许两行，过长可展开全文，状态不被挤掉。事件来源／未决问题是内容，不堆积重复标签；没有完成事件时明确“尚未完成”，不拿模型最近一条消息填“完成原因”。

### 21.3 选择、定位与实际推进是不同操作

点击节点／支线只展开详情；“定位当前步骤”仅滚到真实当前节点并选中，不改任何业务状态。检查未来步骤、历史节点或返回详情，不能顺便暂停当前工作。

实际状态命令在节点详情操作区独立出现：开始此步骤／暂停／恢复／结束／重开／放弃。按状态与占用核实可用性，禁用有具体理由；写入提案不因查看而执行。操作文本中明确对象；无必要不二次弹确认，改变目标或放弃节点时展示原因与影响，再按明确动作提交。

查看支线可定位其来源节点，也可查看产生它的消息。若要把讨论转到该支线，需要明确“讨论此支线”动作，核实当前父步骤与原权限；只展开一个历史支线不改变active_branch_ref。原型只实现查看，不模拟这些业务命令成功。

## 22. 创建、开始、写入、完成与放弃的事件证据

### 22.1 节点详情分为概览／事件记录／关联内容

| 页签 | 展示内容 | 点击行为 |
| --- | --- | --- |
| 概览 | 预期成果、当前落地／未决、状态原因、创建／开始依据、支线来源与返回点 | 展开具体来源或定位父节点；不修改路径 |
| 事件记录 | 按时间倒序的真实变化：谁、何时、做了什么、理由与触发来源 | 打开不可变消息／程序命令／路线调整差异，不只展示无出处摘要 |
| 关联内容 | 真实版本与范围、曾写入或关联已有内容、当前是否仍匹配 | 定位当前正文或查看历史快照，清楚区分版本；不是点击后覆盖正文 |

完成节点至少能查看创建、开始、完成三个不同事件；过程中可有多次写入与支线。未开始节点只有创建／规划，不能伪造开始与完成。暂停节点显示暂停原因及未完事项。写入事件表达“何处保存了哪些内容”；完成事件表达“谁依据什么收束步骤”，两者分别显示。

“AI建议结束”标作建议，不画成完成事件。事件角色来自真实记录，显示“你／AI／系统”；时间用用户时区，本地化显示，存储继续UTC。阅读旧事件使用当时标题与版本快照，同时提供当前对应节点入口，避免改名后历史原因变得不可理解。

### 22.2 为事件交互补充只读投影

节点列表读取增加由服务端生成的event_summary：created_event_ref、started_event_ref、last_transition_event_ref、closure_event_ref／cancellation_event_ref及短摘要。当前状态字段仍按真实事件形成，不允许客户端或模型自填这些事实。可按事件查询生成或保存可核验索引，不能维护第二套独立业务状态。

Branch补origin_event_ref，关联原消息、当时origin_step_ref／节点标题与返回点；不是仅有question和一个不可点击“来自某处”的标签。上述事件引用在当前文档内核实；读取时批量取摘要，不为每个节点单独发起历史GET。完整详情再按节点／支线过滤事件分页读取，沿15.3入口增加step_ref或branch_ref过滤，返回原事件身份而非复制记录。

来源无法读取时保留“来源不可用”及具体身份／原因，不用当前文本伪造原话；历史分页失败只影响事件区，不把已有路线清空。事件查询只读，不重新运行模型，不核算Token。

## 23. 已放弃节点与支线来源

### 23.1 “已放弃”是可见历史，不是被删除

CANCELLED在V2.1界面统一显示“已放弃”，服务端动作名CANCEL_STEP可以保持；不是新增业务状态。PAUSED仍为“已暂停”，Branch.DEFERRED为“已暂缓”，不得一起塞进已放弃列表。

路线顶部提供“已放弃节点 N”开关，数量来自同文档完整摘要而非已加载页条数。默认隐藏已放弃正文卡片但保留数量；打开后显示历史卡片：标题、已放弃、操作者／时间、简短原因和当时所在位置。视觉用弱化虚线与明确文字，不只降低透明度，也不把历史卡片继续接在有效路线实线上。

放弃事件记录order_before、当时前后节点引用／标题及replaces关系，能解释原来处于哪一步。原型在对应历史位置附近插入虚线卡片；若前后节点也已消失，放到“历史路线”分组并展示原位置说明，不能猜测插入当前流程。打开历史卡片不会自动恢复或重开它。

详情能查看：为何创建、为何放弃、放弃前形成过什么、由什么路线替代、相关讨论和内容去向。放弃节点本身不删正文或撤销Revision。重新采用按原设计新建关联旧节点的新步骤，不把原取消记录改成从未发生；具体重新规划提交交互需后续评审，不在原型制造成功回执。

### 23.2 支线始终有来处和返回点

每条支线在来源节点下挂接，入口行直接显示“来自② 推荐与反馈流程”，不要求点开才知道归属。详情顶部提供“来源步骤 > 支线”面包屑、产生原因与触发原消息，以及清楚的返回位置。若发起消息实际属于同一次讨论，引用该消息和AI登记事件，不能把AI登记说成用户已同意其结果。

支线状态明确标注讨论中／已有结果／已暂缓／已放弃；RESOLVED界面用“已有结果”，避免与主线步骤完成或文档写入混淆。有结果但未写入时明确指出未落地。暂停父步骤不取消支线；原节点被放弃后，其支线仍可在该节点历史中查看，不能悄悄改挂到替代节点。

点击“来源步骤”是查看定位；“返回主线继续讨论”才是原生RETURN_FROM_BRANCH命令。来源和return_step_ref可能因明确路线调整而不同，详情分别显示；如果返回点失效，说明原因并让用户选择，不能跳到列表第一项。

## 24. 视觉、可访问性与原型证据

视觉沿现有公共白底／细边界、蓝色操作与当前状态、绿色完成。主线圆点与线条连续，支线局部缩进，已放弃卡片有独立历史轮廓；节点标题、状态、触发说明、事件详情形成明确层级。颜色必须辅以图标／文字，状态不能只靠圆点区别。首屏不展开所有历史或画出复杂依赖网；依赖可在详情明确查看并定位。

实现建议：节点标题约14—16px、正文说明12—14px、状态与来源不靠难辨的淡灰小字承载关键含义；普通节点间距约20—24px，主要点击行至少约40px高，图标按钮有中文可访问名称。具体参数须在实际面板及宽窄布局中核对，不因本表直接认为视觉验收通过。

路线以有序列表＋原生按钮构成，不用未实现方向键语义的tree角色。选中详情与当前业务步骤在可访问名称中分开；详情页签、来源对话框支持键盘、Esc与返焦点。仅悬停不能作为唯一入口。动画短促且支持减少动态效果；新增路线事件不抢焦点、不自动滚走正在查看的历史，可提示“路线有更新”让用户主动定位。

面板／展开视图独立滚动，正文与对话输入保持；阅读无额外轮询，继续沿可见性与实际版本刷新。加载／错误留在对应区域，当前路线或详情读取失败不伪造空节点；数据过期保留最近事实与重试。400px左右面板优先单列、宽视图分栏；不恢复全页面多层滚动或挤压正文到不可读宽度。

离线原型已覆盖：节点选择、来源／版本弹层、事件页签、支线挂接、已放弃卡片及原位置、展开／收起视图和定位当前；它不含真实状态操作或消息发送。浏览器检查范围及首轮失败／修正见[0.4交互记录](../../../verification/v2.1/document-formation-route-interaction-2026-11-07.md)。产品多浏览器、真实用户数据、实际编辑和命令恢复尚未验证。


## 25. 0.5确认记录与本轮设计修正

日期：2026-11-07。用户认可0.4路线原型整体方案并要求继续；原型布局／节点交互方向据此作为当前方案，精确样式及真实产品集成仍需验证。用户在本轮明确选择：**AI判断并建议，用户一键结束步骤**。第4.2节不再列为待选择方案；单独写入仍需用户明确确认，一键结束不隐含写入。

以下存储、升级、读投影、原生写入授权与发布方案为本轮设计建议，不因上述两项确认自动成为用户已逐项批准。首步启动方式、联合写入并结束、容量值仍保留原待评审范围。

本轮修正早期“Formation直接嵌入已存Discussion JSON”的物理存储建议：建议改为同一文档记录上的独立可空formation_state_json列。业务归属、统一D并发与同事务规则不变；原因是当前Discussion／Canonical／Wire和历史调用按冻结Schema严格验证，将新字段直接写入旧对象会扩大兼容影响。逻辑上主线仍属于文档级助手，不能因此新建平行项目服务。

## 26. 实际存放位置与读取投影

### 26.1 当前值、原始内容与历史分别保存

| 数据 | 建议存放位置 | 不变量 |
| --- | --- | --- |
| 当前FormationState | requirement_documents新增formation_state_json | 仅CURRENT可非空；MANUAL_DRAFT保持NULL；F只存在JSON.version，不再另存一个可独立变化的F列 |
| 旧讨论状态／版本 | 原discussion_state_json及discussion_version | 旧JSON结构不原地塞formation字段；D仍保护当前文档的讨论与主线共同快照 |
| 文档正文及版本 | 原markdown_content／BlockState、Revision | 不从主线摘要生成正文；形成主线前已有的版本保持真实身份 |
| 原始写入提案 | 原不可变ASSISTANT INTERACTION_CARDS消息的新purpose | 原提案内容不可改，变更产生新卡片；只保存已校验的提案，不是已授予写权限 |
| 提案处置、形成事件、完成／放弃依据 | 原document_change_audits的DISCUSSION_UPDATED类型，新增版本化formation payload | 不为状态变化更新旧消息，不把未知event_type直接插进现有CHECK枚举 |
| 内容已提交事实 | 原CONTENT_COMMITTED审计与Revision | 与形成关联同事务；原有事件字段和历史记录不改写 |
| 成功操作重放 | 原idempotency_records | 沿能力／真实目标／key及原成功回执；不保存假MODEL处理或复制模型调用 |

formation_state_json初值NULL，表示没有形成路径；首次有效建线才写schema_version=1及F1。放弃全部节点也不重置NULL，保留当前目标、身份计数及历史；没有当前步骤使用current_step_ref=null表达。新列建议有JSON对象／版本／CURRENT归属检查，复杂引用和语义由程序核实，不假定SQL CHECK能证明规划充分。

新增列需要新的完整目标Schema和显式升级入口，不能往旧v1_5.sql追加字段后仍使用151及原checksum。新数据库版本号须结合未同步的V2.0本地基线核定，不凭软件V2.1就擅自占用某个数字。当前文件／数据库完全未改。

### 26.2 同一详情读取，区分物理对象与界面对象

原I03概要新增formation_summary，给出exists、formation_version、当前步骤／支线摘要及未处置提案数量；来自同一实际读取快照，不能只统计已加载的前20条记录。没有路径时exists=false、formation_version=null，不能伪造F0业务对象。

请求expand=discussion的扩展详情同时返回原discussion和独立formation字段：formation=null表示已读取且尚未建线；非空为实际FormationState。未请求展开的概要不带完整formation，该响应形状由原请求明确区分，不能将未读误显示成没有路径。这里以第26章取代第12章“formation嵌到discussion投影”的早期笼统说法。

新前端严格解码新响应联合；后台旧Discussion验证仍接收原旧结构，不能把合并后的界面对象直接扔给冻结旧Schema。新AI资源的Canonical可以新增独立formation快照，新Wire继续按第18章选择project_position.formation材料；旧快照读取不补新字段、不按当前状态重新编译。

当前状态JSON损坏或与事件索引冲突时，形成区域明确报错，禁止依赖该状态的写入，不把错误降级成null并重新生成路径。读取其他可核实正文不因此伪造失败或空文档；具体HTTP错误投影需纳入新协议。

## 27. 形成事件的落库与节点追溯

### 27.1 复用审计，补充明确payload

DISCUSSION_UPDATED的payload建议采用明确版本／域标识：schema="formation_event_v1"、document_id、batch_ref、ordinal、batch_size、actor、action、reason、related_refs、source_refs、version_before／after、changes。旧审计payload不重写，新读取器按域及版本分派，不能把原普通讨论更新误显示成主线事件。

同一事务可有多个形成事件（如暂停s2＋开始s3）。在事务内先分配现有审计ID，以第一条ID作为batch_ref；ordinal从1到batch_size。所有事件共享同一次D／F前后值，不重复增加F。节点开始／完成／取消引用真实相应事件ID；不能因为客户端恰好先收到其中一条就显示半个新状态。

创建／放弃事件保留当时的标题、顺序、前后节点以及源消息；完成事件保留Closure及Revision；ArtifactLink引用实际内容事件或已有内容关联事件。字段来源与actor按第17章，不接受客户端伪造时间或角色。相关消息在同事务创建时，先分配身份、再建引用，统一提交，不能事后异步补来源。

为节点历史、支线历史、特定提案的最新处置增加必要索引／查询分派，索引表达式或物化读索引属于新Schema核对范围。提案索引可由原卡片和相关事件重建，不能成为第二套可写处置事实。第一版优先批量查询所需身份，不能每个节点发一条GET或每次刷新扫描全部正文与所有调用。

当前FormationState是快速读取的当前值；事件用于依据和追溯，不要求每次打开面板从第一条重放全部历史。启动也不能通过旧AI回复重建权限或完成事实。检测缺失来源／不完整事件批次时只报告损坏并进入明确修复流程，不自行重算为成功。

### 27.2 一个写入动作产生哪些不同事件

用户确认提案w1后，在同一事务产生：真实USER CARD_RESPONSE → USER的确认操作记录 → PROGRAM的CONTENT_COMMITTED → PROGRAM的CONTENT_LINKED／提案应用记录 → 新FormationState和成功回执。实际相同内容不创建新Revision，按第13章NO_CHANGE处理。程序保存行为与用户决定可区分显示，不把两者都署名为AI。

用户结束步骤则是USER的STEP_COMPLETED／Closure及可选下一步开始事件，不产生CONTENT_COMMITTED。AI建议结束只产生AI评估／建议更新。这三条路径分别对应界面的“确认写入”“结束步骤”“查看AI建议”，不得合成一个无法说明原因的成功状态。

## 28. 讨论中提案与确认后写权限的边界

### 28.1 保存提案并未取得正文写权限

DISCUSS本来不能写正文，其ContextBasis不能因为出现提案就被修改成已有REVISE授权。保存STAGED_WRITE卡片时，程序检查提案所属文档、实际读取的原文、拟议范围、来源、结构及容量；保存的是一个可供用户决定的提案。模型的scope只是拟议范围，不能自行成为可执行权限。

用户点击确认后，原生应用命令从不可变卡片重建**本次、同文档、精确范围**的内部授权，核实当前D／V、步骤定义、Goal.version、原文及来源，再复用真实补丁／内容提交。新授权来自用户实际选择和程序核验，不复制旧讨论的空写权限，也不接受模型补填allowed_targets。

当前commit_content按GUIDE_RUN／MANUAL_EDIT／SUGGESTION_BATCH核查占用；需要显式增加受信任原生卡片动作的内部来源分支。source_id应指向本次真实用户回答／命令，持有进程锁并在同一写事务核实IDLE与卡片，不伪造GuideRun或永久占用，不对公共接口暴露“跳过guard”参数。补丁和模板／区块身份／审计的既有保证不变。

所有正文提交入口都要维护ArtifactLink匹配状态：手工完成、原REVISE、批次应用、历史恢复和新卡片应用。共享提交层收集实际影响，调用形成关联更新并随事务保存；不能只在新按钮链路处理、导致用户手工改文档后主线仍显示旧成果CURRENT。

### 28.2 事务边界建议

| 入口 | 在一个短写事务中提交 | 事务外的工作 |
| --- | --- | --- |
| 原生主线命令 | 幂等认领／合法状态检查、用户动作、形成状态及事件、成功回执 | 可读预览准备；不得事务内调用模型 |
| DISCUSS接受 | 用户原消息／pending、冻结执行依据、原运行占用及202回执 | 原Worker装配、计数与单次Chat |
| 讨论结果处理 | 助手消息／有效提案、统一progress＋formation增量、相关事件与运行终态 | 已保存的原供应方请求／返回；不为修复结构再Chat |
| 确认精确写入 | 用户回答、正文／Revision、形成落地与失效关联、卡片处置、事件、成功回执 | 无Chat；预览在确认前可读，不临时重生成 |

出现CommitOutcomeUnknown不能断言未提交，先按原key及记录核实；数据库不确定不是另一次模型重试理由。无成功提交就没有成功回执或半份当前状态。用户看到的确认内容与最终应用必须一致；基准变化需要新准备，不靠增加确认框绕过校验。

## 29. V1.5数据保留与V2.1发布边界

### 29.1 建议采用独立目标库的显式升级

这是未来实施方案，不是本轮执行指令或删除授权。建议先保留原库，在独立V2.1目标库建立完整新Schema，再在受控离线过程中复制原业务数据，验证成功后才由用户明确选择切换；不把升级藏在正常服务启动或一次GET中。

1. 核实源版本、Schema及完整性；源若为本地V2.0或未知版本，先取得其真实结构再设计路径，不能套用云端151假设。
2. 核实源没有活动AI／人工会话／候选占用及未知写结果。若有则先由用户按原流程解决，升级工具不得自动取消或丢弃。待回答卡片不是活动AI，但仍需完整保留。
3. 保留可恢复的源快照／原库，建立明确不存在的目标临时库；从新Schema创建表／触发器并在受控事务复制，按依赖与延迟外键策略验证。当前精确sqlite_master校验不能靠简单ALTER后继续沿旧checksum绕过，目标完整DDL及升级器都需实现。
4. 保持真实实体ID、文档版本、时间、原Markdown／BlockState、消息／卡片、Revision、运行／LLMUse原快照、原审计和幂等成功回执；不重新序列化原始JSON或修改来源摘要。旧Schema元数据不冒充新Schema记录，目标初始化及升级过程另有真实版本记录。
5. 所有CURRENT的formation_state_json初始NULL，草稿也为NULL。不从文档标题、确认状态或旧主题自动推断主线已完成。用户后续明确形成工作时可关联已有内容，事件标“关联已有内容”，不是迁移时伪造写入。
6. 验证行数、逐条关键内容／字节摘要、主外键、计数器高水位、现有Revision归属、旧成功回执及新Schema；失败保留源不动，不切服务。工具输出只保留必要脱敏摘要，不把正文或密钥写日志。

新服务仅接受核实过的目标Schema，旧服务不回写新目标库。保留源库可恢复原时点，但V2.1启用后产生的新数据不会自动回到源库；若需回退，要先保全新库并明确差异，不能把“保留源”说成无损双向回滚。

本地浏览器旧缓存不清空。V2.1主线浏览偏好与待确认命令采用版本／文档隔离；旧未发送正文／聊天草稿仍保留在原命名空间，跨版本带入需明确校验或用户选择，不能静默套用旧UNKNOWN请求或ID复用草稿。

### 29.2 冻结模型资源与旧运行读取

旧资源、历史请求、计数与审计原字节保留。新形成Canonical／Wire／Output／STAGED_WRITE及程序绑定使用完整新资源发布，按真实release标识分派，不原地给v15／v16塞字段。

升级成功不等于新模型协议准入成功。未取得新资源有效准入前，可以验证原生程序操作、只读及离线路径，但不能借旧LIVE标志放行新的Chat。复制旧准入配置不构成新release证据；冻结技术证据源文件保持原位置及只读身份，是否能合法复用须按具体release／数据库绑定核实，不能改路径或哈希让检查通过。

历史运行详情按当时冻结release恢复；不注入新formation字段，也不创建新的计数或Chat。旧卡片保留原purpose及过期条件，不自动转换成STAGED_WRITE；新主线操作若改变D使旧卡片过期，界面说明原因并保留旧问题／答案，不自动重发。

新旧幂等成功回执原样保存。新协议解码按真实命令类型区分，不在原回执中补字段宣称它曾更新主线；必要的新状态从真实GET取得。不能因旧回执缺formation就伪装为执行失败并重复应用。

## 30. 0.5完成范围与进入实施前的收口项

已确定用户一键收束步骤及0.4原型整体交互方向；本轮补了物理存储建议、审计事件组织、读投影、原生写权限、统一内容提交关联、保留源数据的升级与资源分派。只是设计，未写DDL、升级器或服务代码，也未访问正常业务库。

进入代码实施前仍须完成：完整可执行Schema／错误白名单／读写DTO、未决首步启动与联合动作选择、实际V2.0基线核对、新旧Schema升级／回退演练计划、新资源准入及明确实施范围。容量建议值需负载验证，不能因本草案已写值就声称可靠性已证明。用户未授权时不自动合入正式规格或开始迁移／调用。

后续优先把完整协议及验收用例按已有数据／操作映射收束为可检查的实施输入，不继续增加平行功能。静态核对见[0.5存储与兼容设计记录](../../../verification/v2.1/document-formation-storage-design-2026-11-07.md)。


## 31. 0.6核心契约与验收输入收口

新增[实施契约与验收清单](WALL-E.文档形成主线实施契约与验收清单_V_2.1.md)及[设计Schema](schemas/formation-contract.v1.schema.json)，属于本独立迭代附件，未接入应用／资源发布。Schema覆盖66个定义、10个根DTO、15种原生命令、12种AI变化；附件补齐逐项转移、错误白名单映射、程序不变量、30条未来产品验收场景和B1—B5实施顺序。用户收束步骤的已确认权限保持不变。

本次明确修正：事件落库／公共投影统一schema和actor命名，以第27章及本附件为准；最小ProgramReceipt返回事实，最新全状态由GET取得；AI UPDATE_STEP使用add_results，不覆盖既定成果数组。新增ENTER_BRANCH／RESUME_BRANCH／WITHDRAW_PROPOSAL_ADJUSTMENT的精确语义，仍是技术设计建议。MVP建议不提供静默成果删除，改为明确放弃原步骤及新建关联替代步骤。

本轮建议独立写入／结束、首步显式开始；自动首步、联合按钮、容量负载和真实V2.0基线仍待核实／评审。完整新资源／purpose／私有binding和目标DDL尚未全部形成可执行发布包，不能把核心Schema存在表述为全部协议或兼容验证完成。

50个结构用例通过（22个接受、28个拒绝），其中3个有意接受的例子说明引用存在性／实际材料／版本算术仍须程序核实；这不是产品验收。初轮发现环境默认未启用有效日期时间format检查，补显式标准库日期校验后末轮通过。验收表A01—A30全部未执行；实际范围见[0.6核对记录](../../../verification/v2.1/document-formation-contract-review-2026-11-07.md)。


## 32. 0.7设计收口与当前规则

新增[交互与接入收口附件](WALL-E.文档形成主线交互与接入收口_V_2.1.md)及[接入设计Schema](schemas/formation-integration.v1.schema.json)。完成首次路线与显式开始、独立写入／结束、路线编辑／拆分／合并／放弃影响预览、成果复用／问题／支线去向、AI路线提案、新binding／回执、完整模型布局扩展及读投影、CARD_RESPONSE可信来源和首版容量规则。保留0.6核心Schema不变，0.7接入定义承载当前扩展。

15种原生命令中ADJUST_PATH扩展到13种严格变化；支线origin不可改，return可明确调整并作为当前讨论归属。新增纯读取预览和提案分页入口，复用原生调整算法／原消息／审计，不引入平行任务服务。新回执记录真实用户动作和临时身份映射；新资源使用独立布局／编译器／发布身份，旧冻结资源保留。

首版默认值为本设计采用的方案，不冒充用户此前逐项答复；已确认的AI建议、用户一键结束规则保持。业务／交互与接入扩展设计已形成整体评审稿，未自动合入正式规格。未同步V2.0的真实代码／数据库／资源基线需要在实施前核对，才能生成最终目标DDL和适配；资源发布组装、供应方准入、升级演练及A01—A40均为后续实施／验证，当前未执行。

本轮47个接入结构用例通过，覆盖完整布局、模型／存储卡片区别、原子调整输入／预览、新回执及可信来源枚举；不代表程序守卫或产品已验证。[0.7证据](../../../verification/v2.1/document-formation-design-closeout-2026-11-07.md)记录边界。


## 33. 0.8完整性复核与整体评审入口

复核0.7发现三个具体缺口：只有步骤级替代无法保存逐项成果去向、完成凭据缺未完支线处置、提案发布引起F变化却仍按发布前F执行。本次在[交互与接入附件](WALL-E.文档形成主线交互与接入收口_V_2.1.md)第9—12节补足，当前Schema为[接入v2](schemas/formation-integration.v2.schema.json)，192个定义／13个根DTO；核心v1及前一接入v1保留原字节。

逐项result_routes明确承接／不再要求并写事件；COMPLETE_STEP冻结Goal并保存全部OPEN返回支线的去向；问题转交保持身份并更新双向归属。提案payload保留模型来源快照，binding绑定发布提交后的F，明确撤回以真实PROPOSAL_BASIS事件续期，不能重写旧卡或凭空重基。模型结构单元统一准备后提交；执行结束、结构被拒绝和正文保存分别展示，历史选材带程序核实的effect_state。

新增[设计总览](WALL-E.文档形成主线设计总览_V_2.1.md)，作为单一整体阅读入口；本章12.4请求示例已补当前新增Goal／支线字段。当前设计可供整体评审与实施排期，旧管理接续归入版本历史，未更改正式规格／产品实现。外部V2.0适配、完整目标DDL与发布资源的组装、准入／升级及A01—A50产品验证仍属实施前置或后续实施，不在云端猜测完成。

77个v2结构用例通过（38接受／39拒绝，含适配后的47个前版结构回归及30个新增）；其中明确验证结构不能证明处置覆盖或真实摘要一致，仍需程序守卫。[0.8证据](../../../verification/v2.1/document-formation-design-consistency-2026-11-07.md)保留真实边界。


## 34. 整体评审R01：自动首步与独立讨论焦点

用户明确建立路线后直接进入第一步，允许自由切换节点，仅需让AI知道当前节点。[R01记录](WALL-E.文档形成主线整体评审记录_V_2.1.md)保存确认原意及具体数据／在途回复规则；[接入v3](schemas/formation-integration.v3.schema.json)为当前结构，v1／v2保留原字节。

首次焦点由程序从有序首节点推导，不由模型指定；SWITCH_STEP简化为step_ref，生命周期与焦点独立。DISCUSS明确discussion_step_ref，在途旧轮保持原上下文，新选择影响下一轮。纯焦点切换不改变正文／成果或提案用途；v3语义摘要排除根版本与两项焦点指针，当前D及正文／用途核实仍保留。完成和写入继续由用户明确操作。

此处为整体评审第1项结论，不表示其余设计全部获批。未实施产品、正式合并或模型调用；接续下一项正常讨论与阶段性写入。


## 35. R07／Q01：允许带遗留结束

2026-11-08用户确认完整性检查主要提示，用户保留结束决定权；未写／未决如实保留，不算已落地。当前以[整体评审R07](WALL-E.文档形成主线整体评审记录_V_2.1.md)和[接入v4](schemas/formation-integration.v4.schema.json)为准。请求可不提供完成成果／处置覆盖，程序补齐OUTSTANDING／KEEP_OPEN快照；原要求、来源和历史不丢失，未处理项不自动转交／暂缓／放弃。

原完整性不足拒绝结束、结束前必须重整范围／遗留等约束已替代。身份／版本／证明真实性／幂等及事务保护继续，已结束节点后续补写沿真实用途核实，原Closure不回写。Q02—Q04仍待评审，不因Q01答复而自动批准。
