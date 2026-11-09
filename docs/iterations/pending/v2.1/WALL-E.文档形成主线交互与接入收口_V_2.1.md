# WALL-E V2.1 文档形成主线交互与接入收口

日期：2026-11-07；更新：2026-11-08（Asia/Hong_Kong）；任务M21-FORMATION-01；修订0.9／DRAFT，设计评审稿。本文与[主设计](WALL-E.文档形成主线与阶段性写入_V_2.1.md)、[0.6核心契约](WALL-E.文档形成主线实施契约与验收清单_V_2.1.md)同属待合并迭代；不自动升为正式规格。当前完整阅读入口为[设计总览](WALL-E.文档形成主线设计总览_V_2.1.md)。本次复核补足成果去向、完成支线及提案版本依据，进入实施前仍需真实V2.0基线核对。

当前R01—R07用户结论见[整体评审记录](WALL-E.文档形成主线整体评审记录_V_2.1.md)，已覆盖本文件旧版首步／焦点／摘要限制；未涉及的业务写入与收束规则继续适用。

## 1. 首版采用的设计默认值

以下是本设计采用的默认方案，供完整评审；并非追记为用户已逐项确认。用户已明确的完成权限及认可的节点原型方向保持。

| 项目 | 首版规则 |
| --- | --- |
| 首次路线 | 用户为当前文档提出形成工作，AI建立可追溯路径；程序直接将第一步设为IN_PROGRESS及当前讨论节点，其余PLANNED；不再要求开始按钮 |
| 文档写入 | 用户检查精确内容后点“确认写入”；纯程序应用，不再生成文字 |
| 步骤完成 | AI建议，用户点“结束步骤”或“结束并继续”；不额外弹相同确认，不自动写入 |
| 联合按钮 | 首版不提供“写入并结束”，减少两种决定混在一个动作中 |
| 路线修改 | R04：AI在既定目标内补充／细化／重排可直接维护并留事件；重大调整及人工编辑走影响预览后保存 |
| 已完成步骤 | 历史完成保留；补充后续步骤或先明确重开再调整，不悄悄改写完成依据 |
| 被放弃步骤 | 永久保留历史，不复活同一身份；重新采用建立replaces关系的新步骤 |
| 范围 | 每份文档独立；跨文档先后关系仍由用户维护 |

“首版不提供”是本次范围决定，不是等待补全的设计洞。后续反馈可修订本草案；无需以增加可选功能作为本轮完成条件。

## 2. 从空白到开始第一步

未建线时，路线区域显示“还没有文档形成路线”；用户可以继续自由聊天。GET、打开面板、查看历史都不触发模型。用户点击“规划这份文档”时，在原讨论输入中带入当前文档和形成意图，由用户补充目的后明确发送一次DISCUSS；沿原运行与占用流程，不另造规划任务。

目的足够时，同一回复给出简短说明和INITIALIZE_PATH；程序保存AI规划来源及F1，同一事务自动进入第一步，其余步骤PLANNED。目的不足时，AI解释缺什么或提供必要选择，不为了填满面板编造路线。已有正文必须读取真实内容，关联事件标“关联已有内容”，不声称本轮写入。

路线首屏呈现目标、三至五个适当粒度的节点及每步要形成的成果；三至五是表达建议，不是硬凑数量。第一步直接显示当前讨论；任一节点可选择“在此讨论”，不要求前置完成或填写跳转原因。依赖仅作提示。切换仅改变焦点，不隐含完成、暂停、重开或写入。

建线自动进入首步不增加Chat，切换也不自动发送消息；原讨论输入保留，实际发送仍是用户行为。无模型可用时允许读取已有路线和原生操作，新建AI路线显示真实配置原因，原文档阅读／人工编辑继续沿既有入口。

## 3. 路线编辑器与影响预览

### 3.1 入口及操作布局

路线顶部“调整路线”打开可展开的编辑区，不挤占正文到不可读。左侧为有效节点顺序；右侧为选中节点的标题、预期成果、依赖和变化说明。窄屏为单列，编辑区内切换“步骤／成果去向／影响预览”。顶部始终显示“修改尚未保存”，底部固定于编辑区的“取消修改／预览调整”可达，不遮住最后一项。

本地编辑草稿按文档隔离，保存基准D／F／V及原始变更；关闭编辑区保留当前页草稿并提示未保存。离开文档时沿原未保存内容提示，可保留本地草稿或放弃；不将草稿视为已采纳路线，不触发模型。恢复草稿必须先读当前版本；不同则展示差异、允许复制后重新编辑，不静默重基后直接提交。浏览偏好与业务状态分开存储。

| 用户操作 | 编辑器表现 | 保存后的事实 |
| --- | --- | --- |
| 新增 | 在选定位置加临时节点，填写至少一个CONTENT或ANALYSIS成果 | 程序分配新身份，初始PLANNED |
| 改名／重排 | 就地编辑；提供上移／下移按钮，拖拽为辅助 | 纯展示修改不改变definition_version |
| 改成果要求／依赖 | 展示旧值和新值，以及受影响提案／评估 | 实质修改增加定义版本；既定成果不能静默删除 |
| 拆分 | 从一个节点生成多个草稿节点，逐项分配原成果、问题及支线 | 原未完成节点放弃，新节点建立replaces关系 |
| 合并 | 选定多个未完成节点，明确合并后的成果及依赖 | 原节点分别放弃，新节点关联所有原身份 |
| 缩小范围 | 展示被移走或不再要求的具体成果及原因 | 原步骤放弃并建立明确替代；旧内容不删 |
| 放弃 | 输入原因，逐项处理未决问题／支线并核对后续依赖 | 原节点CANCELLED且保留原位置、成果和来源 |

已完成步骤不直接出现在拆分／合并选择中；可“新增后续步骤”或“重开本步骤”。切回已完成步骤仅改变讨论焦点；明确重开也无需先暂停其他节点，不隐式改变其他步骤状态。已放弃步骤只读，通过“据此新建”创建关联身份。

### 3.2 成果、问题、支线分别处理

成果去向逐项显示：原要求、当前正文位置、是否已写入、替代节点／不再要求及原因。复制原预期成果到新步骤是重新定义要求；复用已有正文需要显式LINK_CONTENT，程序核实当前Revision和区块并新建关联，正文不变化。旧Artifact保留在旧步骤；新关联有自己的来源事件，不能把旧写入算作本轮新写。

未决问题必须选择移到哪个有效步骤，或明确暂缓／不再处理。MOVE_ISSUE保持issue_ref和原始source_refs，事件记录归属前后值；DISPOSE_ISSUE记录用户处置和原因。不得只在UI隐藏问题后把旧节点放弃。

支线保留不可变origin_step_ref和origin_event_ref；**return_step_ref表示当前处理／返回步骤**，可以经明确调整改到新节点。活动支线的return_step_ref必须等于当前讨论节点，current与节点生命周期独立；此处替代0.6要求“origin必须是当前步骤”的限制。来源步骤已放弃时仍显示“起于旧步骤，现返回新步骤”。当前处理步骤下显示同一支线的引用及“来自旧步骤”，点击可回溯最初节点；不复制一条新支线，也不因默认隐藏已放弃节点而隐藏当前待处理支线。新返回步骤可以在本批创建，提交时解析临时引用；回溯入口始终去真实来源。

对仍OPEN的支线，放弃父步骤前必须重设有效返回点，或明确暂缓／放弃。DISPOSE_BRANCH与问题处置可放在同一调整批次中。暂缓支线可保留原历史返回点，恢复前先指定有效返回点；DROPPED不恢复原身份。若移动问题还关联支线，当问题和支线都仍OPEN时，目标步骤须与该支线的新返回点一致，否则整批拒绝；已收束支线只保留历史来源关系。

后续未完成步骤的依赖若指向被放弃节点，必须显式改为替代步骤或明确移除。已完成节点保留当时关系与Closure，不为整理当前路线倒写历史；当前可执行依赖图不得循环。取消当前节点会清空焦点，新增替代步骤不会自动开始。

### 3.3 用户保存前必须看到的预览

预览分五部分：节点增删／顺序；成果新要求及已有正文复用；问题与支线去向；将失效的提案／评估；当前焦点是否清空。原来没有写入的内容明确标“仍未写入”，不能从方案卡片直接变为已落地成果。

“保存路线调整”是一次明确采用动作，不再弹内容相同的确认框；校验失败停留在对应项目，保留草稿。预览采用服务器当前快照核实，仅读不落库、不占写锁、不分配正式ID；临时节点继续显示new_step_N。服务器不能确定语义充分，但必须核实身份、归属、原文、图和处置完整。

保存时重新核对同一D／F／V并原子提交。任何一项失败整批回滚；版本变化时保留编辑内容并让用户重新检查预览，不换版本后自动保存。新身份通过ProgramReceipt.reference_map返回，前端可定位用户新建的节点；读取失败仍保持“保存成功，显示待刷新”。取消本地草稿无持久事件；提交成功的真实调整进入历史。

### 3.4 一次拆分的具体轨迹

原路线当前s2“推荐流程”，已有正文成果a4、未决问题i3及支线b2。用户拆为“主流程”和“冷启动”，将a4当前区块关联给新主流程，i3移到冷启动，b2保留origin=s2并把return改到冷启动；原后续s3的依赖改为新节点。旧s2将放弃，原待写提案w1不能直接换挂到新步骤。

预览基准D40／F12／V7，无持久变化。保存后新节点实际分配s5／s6，s2=CANCELLED，新增成果关联，i3归s6，b2.origin仍s2、return=s6，w1用途失效，当前焦点为空；同事务D41／F13／V7。随后用户选择开始s5才有下一次状态变化。文档正文始终V7，完成历史与旧提案均保留。

## 4. AI建议与操作卡片

R08已确认支线登记与回归原则：普通解释及当前成果内的问题直接讨论，已有步骤／支线优先复用；只有相关且值得独立跟踪的分支才登记，有实际结果再总结回归，不强制轮数。模型在同一DISCUSS中依据Goal／expected_results／实际材料判断并用既有增量输出；程序核实结构与来源，语义效果另以项目对话验证。具体判定规范见整体评审记录R08。

AI可以正常说明、提出多个可行方案或询问关键取舍；不强制每轮出卡片，也不替用户自动选择。一般讨论只维护有来源的规划细节、问题、支线及评估；变更目标、取消／替换步骤或处置用户决定必须明确操作。

| purpose | 模型提交 | 用户界面／正式回答 |
| --- | --- | --- |
| STAGED_WRITE | ModelWriteProposal，精确Markdown或补丁；source_refs为本轮材料别名 | 精确预览及“确认写入”；正式组内只有apply选项 |
| FORMATION_PATH_CHANGE | ModelPathProposal，完整调整批次、影响摘要及来源 | 复用路线影响预览；“采用路线调整”正式apply，原样执行 |

两种新purpose均为单组单卡、CONFIRM、required=true、selection_rule={min:1,max:1}、custom_answer关闭、recommendation=null。关闭卡片只是收起；“继续调整”进入原输入并明确发送DISCUSS，不能靠猜用户文字关联。按钮标题由程序按purpose固定，不让模型用“确认写入”掩盖再次生成。

STAGED_WRITE的暂缓／恢复仍沿原生提案命令，不耗正式回答。路线提案首版不增加持久“暂缓路线”状态，收起后仍待处理；新卡成功替代、用户采用或路线基准变化后分别展示真实处置／有效性。两种提案的调整接受都记录needs_revision；通用WITHDRAW_PROPOSAL_ADJUSTMENT可明确撤回，需用途和版本仍适用。写入的DEFER／RESUME命令只处理STAGED_WRITE。

路线提案所在回复不得同时带非空formation_delta，避免建议用户确认的路线在确认前已经改变；原topic／evidence进展可独立有效。阶段性写入卡也不得与同轮对目标步骤实质定义修改冲突。首次建线焦点由程序直接取第一步，模型INITIALIZE_PATH不再提交current_step_ref，不接受模型自行指定其他步骤。

存储前将来源别名解析为真实SourceRef；模型LINK_CONTENT使用document_refs别名，程序在本轮实际材料中解析为同文档Revision／V／block_ids，不能接受模型自填权限证明。对新步骤先声明临时身份，再核实所有去向；程序绑定仅来自冻结依据和真实卡片，模型字段不能覆盖它。

## 5. 接入契约与字段责任

新增[当前接入设计Schema v4](schemas/formation-integration.v4.schema.json)，包含192个定义、13个根DTO；内部全部本地引用。F_为0.6核心定义的设计副本，L_从云端v16契约派生；0.6核心文件及冻结v16均保持原字节。**当前0.8以接入Schema v4的命名DTO及当前R01—R07为准**；[0.7 Schema v1](schemas/formation-integration.v1.schema.json)保留原字节作为前一设计依据，不能继续使用旧ADJUST_PATH简写请求或旧ProgramReceipt解码新操作。

### 5.1 请求、预览和程序回执

| 入口 | 当前设计契约 |
| --- | --- |
| 原PATCH requirements/{id} | NativeRequest；其余13种动作沿核心，ADJUST_PATH用PathEditCommand，新增expected_formation_version、expected_content_version、based_on_proposal（可空）、result_routes |
| 新POST requirements/{id}/formation-preview | PathEditRequest，与真实调整同body；无Idempotency-Key要求；纯读取快照并返回PathPreview；不会消费卡片或保存草稿 |
| 原POST conversation-messages/{id}/responses | 两种新purpose均沿单卡apply请求；内容与调整从不可变卡读取，不接受客户端替换 |
| 原POST requirements/{id}/guide-runs | DISCUSS联合分支新增proposal_intent=ADJUST_WRITE／ADJUST_PATH或null，沿已有proposal_ref；非DISCUSS旧分支不因此增加必填字段 |

PathChange共13种：原8种SET_GOAL／ADD_STEP／RENAME_STEP／MOVE_STEP／SET_DEPENDENCIES／UPDATE_RESULT／ADD_RESULT／CANCEL_STEP，加LINK_CONTENT／MOVE_ISSUE／SET_BRANCH_RETURN／DISPOSE_ISSUE／DISPOSE_BRANCH。后五项用于同一次调整完整处理原成果和支线／问题；都不写正文。取消还有未处置遗留的节点时，独立CANCEL_STEP应拒绝并引导完整路线编辑，不自动替用户处置。

PathPreview包含result_routes、before_steps／after_steps（完整成果描述及临时身份）、content_links、issue_moves／issue_dispositions、branch_returns／branch_dispositions、invalidated_proposals、clears_current_focus、warnings、preview_digest。digest为规范化预览的摘要，供核对／诊断，不能当授权或绕过版本检查；保存重新验证相同输入。

成功回执扩展receipt_schema="formation_program_receipt_v1"、user_message_id或null、operation=NATIVE_FORMATION／STAGED_WRITE／FORMATION_PATH_CHANGE、result=APPLIED／NO_CHANGE及reference_map；保留原核心D／F／V、effects和event_ids。新消息投影按receipt_schema分派，旧回执保持原样，不扔给旧program_receipt函数硬解。

有真实变化的原生动作在同事务保存USER TEXT操作摘要，作为事件来源，guide_run_id=null；这不是新的待回复问题，不加入pending。精确卡片应用保存USER CARD_RESPONSE且指向原卡。纯无变化请求可没有新用户消息，user_message_id=null，不制造D／F或事件；幂等重放仍返回原回执。完成Closure引用实际操作消息及STEP.before定义快照。

### 5.2 程序私有binding

NewBinding字段固定：schema="formation_card_binding_v3"、requirement_id、document_id、guide_run_id、assistant_message_id、card_key、accepted_discussion_version、formation_version、goal_version、target_revision_id、target_content_version、step_definitions、source_heads、payload_digest、formation_digest。payload_digest来自已解析存储payload的项目规范化序列化，不包含binding自身。

step_definitions记录所有被实际读取、受提案影响的已有步骤定义版本；新步骤只作为本批临时身份。source_heads保留真实Revision来源的当前头。模型不见私有binding，不可提交它。用户确认时核实原消息／运行／实际payload摘要、同文档权限、来源现状与当前用途，不能只信字段相等。

STAGED_WRITE只因新的D／不相关规划F变化不自动失效，本次提交仍用最新D；必须核实目标V／Revision、目标版本及相关步骤定义。FORMATION_PATH_CHANGE核实当前D、V／Goal及v3语义摘要；纯切换不因F变化作废，payload.basis／binding.F保持历史来源身份，不静默改写；实际保存以当前F为基准，见R01。任何源文档头已变需要重新准备精确提案，不以新的acknowledge参数偷偷放行旧内容。

手工编辑AI路线提案时，本地草稿带based_on_proposal；保存原生ADJUST_PATH，在同事务将原提案SUPERSEDED并记录修改后的实际批次。直接采用原卡走responses；两条入口共享同一调整算法／守卫，不能有两套不一致的状态机。

### 5.3 当前读投影与节点追溯

原详情GET增加ReadExtension。概要返回formation_summary及formation_loaded=false，不带完整formation；expand=discussion返回formation_loaded=true、formation（null代表确实尚未建线）、formation_activity、formation_proposals、formation_assessments。保持旧discussion的结构和既有响应字段，新增部分由新投影解码；不能把未读取显示成无路线。

Summary固定所属document_id、exists、formation_version、当前步骤／支线及有效／放弃／待处理提案／未决问题计数。计数来自完整同快照查询，不从首屏或已加载页推算。formation_activity批量返回每节点的创建、开始、最近写入、完成、放弃事件摘要；引用原消息、角色、时间、Revision和原因，不为每节点单独GET。

formation_assessments给is_current及明确stale_reasons，不修改AI原评估。正文改动后已完成节点保留COMPLETED，可显示“成果需复核”；不自动重开。历史入口仍沿formation-events分页返回真实事件及批次。

当前提案页最多20条（上限100），详情可用formation_step_ref选择查看节点，不改变真实工作焦点。补只读GET documents/{id}/formation-proposals，参数step_ref或空、before_sequence_no、limit，返回ProposalPage；游标用原消息sequence_no、每卡真实message_id＋card_key。ProposalView含处置、needs_revision、can_apply和登记reasons；原精确全文仍取不可变消息详情，列表不复制全文。历史节点也能查原提案及为何失效。

加载／失败／占用／无内容按区域呈现；历史或提案页失败不清空路线。晚到回执只更新所属文档缓存，不覆盖当前选中节点或清空另一文档草稿。

### 5.4 Canonical、Wire和模型输出

Canonical采用layout_version="formation_context_v1"，独立formation记录所属文档、冻结完整snapshot、included_step_refs、必要事件和关联提案。旧Discussion原结构保持；ContextBasis／选材来源／所有摘要随真实新Canonical重新计算，旧历史快照不重编译。

Wire的project_position中，旧阶段维度改名stage_overview，新增formation；没有路径时为null。WireFormation含Goal／basis、当前步骤及支线、路径短总览、included_steps、branches、issues、artifacts、recent_events、omitted_step_refs及有界提案摘要。包含的步骤带实际定义／评估／建议；被省略的节点只提供总览，不能让模型更新未读定义。

CanonicalFormation另有message_effects，Wire近期历史有effect_state；程序从真实运行结果／事件标记用户动作、讨论、已应用或结构被拒绝，旧记录无法核实为UNKNOWN，不能依模型文字推断。Wire不复制正文到各成果；成果只提供实际document_refs。源别名从真实MESSAGE／REVISION等材料映射，不把形成事件当新的任意SourceRef类型。current_request增加proposal_context，明确正在调整的原卡、意图及精确内容；canonical保存真实来源，Wire转为本轮别名。

九个输出根字段保持；Progress新增必传formation_delta（无变化为null），ModelCardGroup增加两种新purpose，存储组由程序转换payload并加入NewBinding。完整各任务输出结构在派生L_Output／各操作定义中可校验；程序仍检查operation与response_type、基准、来源和语义权限。普通REVISE／GENERATE的直接保存机制保持。

### 5.5 错误与操作边界

R06已确认恢复体验：超时先核实原动作；已保存但显示失败仅刷新；正文改动后保留旧提案并重新核对；AI失败保留输入和已保存文档，用户明确发起重试。该确认不改变以下程序校验或新增自动Chat。

新预览允许VALIDATION_FAILED、NOT_FOUND、DISCUSSION_VERSION_CONFLICT、CONTENT_VERSION_CONFLICT、STATE_CONFLICT、SOURCE_INVALID、FORMATION_INVALID、FORMATION_LIMIT_EXCEEDED、STORAGE_UNAVAILABLE、CONFIG_INVALID及安全INTERNAL_ERROR；它不取得写占用，可在正在工作时读已提交快照，但保存按钮解释占用原因。

Native／两种卡片应用另核实WORK_STATE_CONFLICT、IDEMPOTENCY_CONFLICT、REQUEST_IN_PROGRESS；卡片入口另有CARD_ALREADY_ANSWERED／CARD_EXPIRED，正文应用还可有PATCH_INVALID／TARGET_STALE／SCOPE_INVALID／DOCUMENT_INVALID／TEMPLATE_INVALID／SOURCE_VERSION_CONFLICT／CAPACITY_EXHAUSTED。只读状态／提案／历史按各入口登记结构、归属、存储和配置错误，不返回虚构写冲突。已有WORK_STATE_INCONSISTENT按真实内部不一致分派。

安全details沿0.6白名单；定义／目标／路线基准失配用STATE_CONFLICT.reason；本次接入Schema增加PATH_CHANGED／SOURCE_CHANGED／UNRESOLVED_DISPOSITION原因，实现时必须同步登记错误投影，不透传内部对象。版本冲突、校验拒绝没有半份业务写入；UNKNOWN先核实原key。Schema结构校验仍不能证明来源、处置覆盖、摘要等于原内容或版本算术正确。

## 6. 存储、来源与资源发布设计

物理状态采用同CURRENT记录的独立可空formation_state_json，F只存在JSON.version。未来目标DDL在requirement_documents完整定义中增加下列字段／约束；不是在旧151运行库执行ALTER：

```sql
formation_state_json TEXT
  CHECK (formation_state_json IS NULL OR
    (json_valid(formation_state_json) AND
     json_type(formation_state_json)='object' AND
     json_type(formation_state_json,'$.schema_version') IS 'integer' AND
     json_extract(formation_state_json,'$.schema_version') IS 1 AND
     json_type(formation_state_json,'$.version') IS 'integer' AND
     json_extract(formation_state_json,'$.version') BETWEEN 1 AND 9007199254740991)),
CHECK (document_type='CURRENT' OR formation_state_json IS NULL)
```

形成事件仍为DISCUSSION_UPDATED及formation_event_v1 payload；新增按document_id／id倒序的部分索引限定该域，节点／支线通过related_refs核实过滤。提案处置为原卡加审计的可重建读投影；若实施物化索引，必须可由原记录核对重建，不能变成另一个事实源。读当前状态不从第一条事件重放全历史。

精确写入新增受信任source_type=CARD_RESPONSE、actor=USER、source_id=本次实际回答ID。必须同时扩展Provenance来源集合／真实来源验证、commit_content占用证明分支、公共区块快照投影和**新资源**BlockMetadata枚举；原GuideRun来源不能冒用，旧冻结Schema不修改。CONTENT_COMMITTED审计及新Revision保留本次回答与原AI卡来源链；用户确认表示采用，不伪称文字最初由用户原创。所有正文提交入口继续统一维护Artifact匹配。

完整目标DDL由实际源版本适配后生成并固定摘要，包含新增列、索引、原触发器／外键及新版本元数据。升级仍采用保留源库、建立独立目标库、显式核验与选择切换；源业务记录／原JSON字节／ID／版本／旧回执不重写。只新增列为null，不从旧正文推断主线。升级失败不切换；新库启用后回退须保全新数据，不能宣称无损双向回滚。

新资源发布契约采用release.key=formation_v1、compiler_version=formation_compiler_v1，Counting.layout=formation_context_v1。保持Release现有字段形状，canonical_schema／wire_schema／六种output_schemas／message_schema指向新发布物；四阶段指引、三个结构及prompt／counting采用新清单真实引用和摘要。具体目录序号／版本号在核对本地基线后分配，不能擅占v17或某数据库号。

设计Schema是输入依据，不是已发布资源。未来实现要提取所需类型、保持确定序列化／字段顺序、核对程序私有材料与Wire、重算原八项计数并完成新发布准入；计数上限沿现有模型配置，新布局不复用旧LIVE。旧运行／消息／回执按真实release恢复，不注入新字段，不补Chat。发布组装与供应方实测属于实施验收工作。

## 7. 首版容量规则与到达上限后的行为

首版采用每文档总计200步骤（含已放弃身份）、1000支线、1000问题、2000成果关联；每步20项成果，状态JSON规范化UTF-8不超过1MiB。单次AI形成增量／路线调整最多20项，规范化UTF-8不超过64KiB。精确正文受原内容／补丁／消息容量及模型输出预算约束，不把全文塞入主线状态。

全部上限是本设计的首版常量，需实施时验证性能；不再留为未选择的方案。超出即明确拒绝，说明是哪一项超限，保留原状态／草稿；不截断后半批、不删除历史、不为了容量自动完成节点。20项限制按实际PathChange计数，拆分过大需用户分批编辑，但每批必须独立满足处置和依赖完整。

总数到限仍允许不会增加实体且满足字节预算的已有操作，原正文阅读／编辑继续沿原规则；新增被拒绝。首版不提供隐藏归档或自动压缩，用户可保留当前文档并另建下一份文档，或等待显式提高容量的新版本；不自动转移成果。模型预算不足先裁可选材料，必需正文／约束仍不足则不Chat，提示缩小工作范围。

## 8. 设计完成清单与实施前置核对（含0.8补充）

| 项目 | 当前设计结论 | 实施／核对要求 |
| --- | --- | --- |
| 主线、状态、文档成果基准 | 已定义 | 按用户确认规则实现；产品验收未执行 |
| 首次建线、首步、写入与完成 | 本版默认已收口 | UI／API联调验证 |
| 拆分／合并／放弃／遗留去向 | 交互、原子操作及预览已定义 | 真实事务／并发及交互验证 |
| AI卡片、binding、读写DTO及模型布局 | 接入Schema和程序守卫责任已定义 | 发布组装、调用链接入及新资源准入 |
| 容量与超限 | 首版数值和操作行为已定义 | 边界／负载验证；不是已证实性能结论 |
| 云端151的存储增量／来源／升级 | 方案及字段／索引／来源变更已定义 | 生成完整目标DDL与升级演练 |
| 未同步本地V2.0 | **外部基线待核对**，不推断其差异 | 实施前取得实际代码提交／DDL／资源清单及活动工作情况 |

本地核对的输入固定为：实际Git提交及未提交改动清单、SQLite版本／完整DDL及迁移摘要、资源release与消息协议版本、文档／运行／旧成功回执结构。若与云端基线兼容，按本方案生成适配与验证清单；若已有同名能力或冲突列／协议，先记录差异并修订接入映射，再编码。身份或原始快照无法无损保留时拒绝升级，不擅自清库。这是实施准入检查，不影响本轮完成业务／交互设计。

在0.6的A01—A30外补充以下未来验收，**全部未执行**：

| 编号 | 场景与预期 |
| --- | --- |
| A31 | 建线直接将首步IN_PROGRESS并设为当前讨论，其余PLANNED；无额外点击或Chat（R01替代） |
| A32 | 路线预览无写入／正式ID分配；版本变化阻止直接保存并保留草稿 |
| A33 | 拆分／合并复用真实正文，原成果和历史保留；正文V不变 |
| A34 | 移动问题及修改支线返回点，origin保持；没有明确去向时禁止取消旧节点 |
| A35 | 暂缓／放弃问题和支线与整批调整同事务，失败全部回滚 |
| A36 | AI路线提案不能与自动形成增量混合应用；用户修改后原卡有明确处置 |
| A37 | CARD_RESPONSE来源在区块、Revision、原卡及审计中一致，旧资源不会错误解码新来源 |
| A38 | 提案分页、节点活动摘要、过期原因及完整计数同快照；查看不切换业务焦点 |
| A39 | 新回执reference_map定位新节点，旧回执按原协议重放；200后GET失败仍为保存成功 |
| A40 | 所有条数／字节边界明确拒绝且不截断；V2.0差异阻止猜测升级 |

本轮设计可作为整体评审输入，未开始产品实施，也未请求正式规格合并。实际结构检查见[0.8核对记录](../../../verification/v2.1/document-formation-design-consistency-2026-11-07.md)；所有实施／发布／迁移与真实调用仍按后续实际任务范围推进。


## 9. 原成果到新成果必须有逐项映射

0.7只有步骤级replaces关系，无法证明某项旧成果被承接还是取消。本次在PathEditCommand、ModelPathProposal、StoredPathProposal和PathPreview增加必传result_routes；没有取消步骤时为[]，不能省略。

| disposition | 字段与含义 |
| --- | --- |
| REPLACED | from_result_ref、至少一个target_result_ref及reason；明确原要求由哪些新／已有有效步骤的成果承接 |
| NOT_REQUIRED | from_result_ref、空target_result_refs及非空reason；用户明确不再要求，不能自动解释为已完成 |

程序核实被取消步骤的全部expected_results恰好各覆盖一次，没有重复／遗漏／不属于本批的来源。目标成果须在提交后的有效步骤中存在；同批临时成果先声明后解析。合并允许多个旧成果指向一个新成果，拆分允许一个指向多个；原要求的语义是否充分由用户检查预览。CONTENT与ANALYSIS不得借REPLACED互换；改变类型要明确把原要求NOT_REQUIRED，再新增不同要求并展示影响。

映射只描述要求去向，不意味着内容已落地。新CONTENT成果还需LINK_CONTENT关联真实已有正文，或后续确认写入。旧Artifact及旧版本不改挂；映射作为RESULT_ROUTE事件差异保存，after中全部使用真实result_ref，不能将new_result_N落入正式历史。相同事务可分多条事件保存，D／F统一一次变化。

独立CANCEL_STEP没有逐项去向参数，而有效节点至少一项成果。因此**当前首版取消入口统一编译为完整ADJUST_PATH**，填写逐项去向；当前NativeRequest移除独立CANCEL_STEP，保留14种原生命令，13种PathChange内仍包含CANCEL_STEP变化。0.6／0.7尚未部署，不为旧设计保留一个永远拒绝的兼容动作。前端不显示第二套简化取消按钮，也不默默将所有成果设为NOT_REQUIRED。

## 10. 完成步骤时收束支线与问题

COMPLETE_STEP增加expected_goal_version与branch_dispositions（无未完支线时[]）；Closure同样保存branch_dispositions。R05已确认：AI整理实际文档成果、遗留去向及下一节点的简短建议，用户点“结束并继续”直接切入推荐节点，不额外发送AI请求；没有下一步时不自动将整份文档定稿。用户结束仍是一键采用已展示的收束建议，程序不再次弹相同确认。建议区显示成果、未决问题、支线去向和下一步；R07：未选择去向时原样保留为待处理，不要求先补齐才能结束，也不暗中处置。

R07由程序快照覆盖所有return_step_ref等于本步骤且status=OPEN的支线，不以origin_step_ref筛选；用户无需逐条选择。未处置的记KEEP_OPEN，保留状态／归属；已明确选择的可为MOVE／DEFERRED／DROPPED：MOVE携带to_step_ref和reason，保持OPEN并改返回点；其余保留用户理由与真实事件。不能提交RESOLVED替代实际讨论结果，也不能只清焦点就让未完支线消失。

MOVE目标须为另一可推进步骤，不能是本次关闭步骤、已完成或已放弃步骤；可等于next_step_ref。所有支线处理、问题处理、Closure、当前完成和可选下一步开始同事务。原origin与触发事件永久不变；父节点已完成后，迁出的支线在新处理节点显示同一引用。

问题的DEFERRED且followup_step_ref非空表示“本步骤暂不解决，交给后续步骤”：保留同一issue_ref、描述及来源，实际Issue.step_ref改为目标、disposition保持OPEN，事件记录转交；Closure保留原步骤的DEFERRED决定及目标。followup为空时才将该问题实际置DEFERRED，保留旧归属。若关联OPEN支线，其新返回点必须与新问题归属一致；已收束支线只作为历史来源，不强制迁移。

Step.issue_refs必须和Issue.step_ref双向一致更新；旧节点移除转交引用，目标节点添加，不能只改一边。R07对结果、问题和支线保守补齐事实快照；缺口分别记OUTSTANDING／KEEP_OPEN，不以未齐拒绝结束。真实身份、版本和明确处置的合法性仍校验。

所有有效节点都COMPLETED时，界面说明“当前路线的步骤已结束”，仍展示待复核成果与暂缓事项；只有CANCELLED／无可推进节点时显示“当前路线没有可推进步骤”。这些是派生显示，不增加路线完成枚举，不自动确认整份文档或改变需求状态。后续新发现可新增步骤或明确重开。

## 11. 发布提案与确认提案的版本依据

### 11.1 发布后不能立即失效

保存提案会产生形成事件并使F增加，不能再用发布前F要求当前F相等。字段责任明确为：

| 位置 | 保存的依据 |
| --- | --- |
| ModelPathProposal／StoredPathProposal.basis | 本轮实际接受并发送给模型的来源快照，保持原始身份，不改成模型未见过的状态 |
| NewBinding.formation_version | 保存卡片及相关形成事件后，本事务真实提交的F；由程序预计算并随状态一起提交 |
| NewBinding.formation_digest | R01的v3摘要移除根version、current_step_ref、active_branch_ref；其余目标、顺序、步骤状态／定义、问题、支线、成果和评估保留 |
| 最新PROPOSAL_BASIS事件（若有） | 用户明确撤回调整后，程序核实并记录的新执行F和相同formation_digest，不修改原卡或原binding |

例如模型实际看到F12，发布路线卡后F13：payload.basis.F仍12，binding.F=13，用户在当前F13确认可以执行。不能把payload改成13伪装模型读过，也不能因13不等于12判卡刚生成就失效。D同样保留来源D与本次请求最新D的不同职责。

阶段性写入仍核实用途／V／Goal／定义及来源，不要求无关F绝对相等。R01路线卡按v3摘要及全部实际用途核实；binding／续期事件的F作为真实来源记录，纯焦点造成的F变化不单独判失效。

### 11.2 调整失败后撤回调整

本节的摘要续期针对FORMATION_PATH_CHANGE。STAGED_WRITE撤回仍按精确V／Goal／步骤定义／来源检查，不增加对无关F或全路线摘要的依赖。

接受“继续调整”产生needs_revision及F变化；若模型失败，原卡保留。用户明确撤回时，重新核实原卡未应用／替代、V／Goal／定义／来源、当前v3去版本／焦点摘要与原formation_digest一致，且当前D／占用正常。只有与提案处置有关的版本递增不会改变该摘要；纯焦点不会改变该摘要，步骤状态／定义／评估等其他实际变化仍导致不一致，不能默默恢复旧方案。

撤回成功同事务清needs_revision并新增PROPOSAL_ADJUSTMENT_WITHDRAWN及PROPOSAL_BASIS差异；before记原有效依据，after记撤回提交后的真实F，digest一致。原卡与binding不改写，读投影从真实事件取得新依据。例如撤回前F15，提交后F16，则新执行依据为16，不能再次绑定15让卡即时失效。

摘要不一致时保持原状态，显示“路线已有其他变化，请重新预览”；允许在路线编辑器打开原内容，基于当前快照重新编辑／预览后明确保存，不隐藏重基，不增加补救Chat。正文提案不允许通过此途径换基准V应用旧补丁。

### 11.3 返回值与计数含义

Summary.pending_proposal_count统计尚未正式处置的PENDING／DEFERRED，界面标签为“未处置提案”，其中可能包含用途已失效的旧提案。它不能直接充当“可确认写入数”，更不能当成果数量；执行可用性由ProposalView.can_apply／reasons及needs_revision说明，列表分页不改变总数。unresolved_issue_count统计OPEN问题，暂缓问题仍在状态／历史中单列，不伪装已解决。

形成版本F变化只表示投影／审计有新事实，不代表路线拓扑变化或正文保存；“内容已写入”只能来自真实DocumentEffect／Revision及关联事件。

## 12. 模型返回失败、原子单元与完整性校验

### 12.1 三类事实分开记录

用户输入被接受、模型调用结束、结构／正文被应用分别处理。新RoundResult扩展formation_result／formation_error和proposal_result／proposal_error，保留原progress_result、application_result、document_effect等事实。GuideRun.status=COMPLETED仅表示该次执行结束，不能显示成步骤完成或文档已写。

DISCUSS的新旧进展、形成增量及新提案卡片构成一个结构单元：先在内存准备并核实所有引用／权限／映射／版本，再写入；任一部分不合法，整个结构单元拒绝，不先更新topic再发现形成失败，也不保存无法执行的半张卡。原用户pending保持，合法可读正文按已有消息机制保留，界面明确“本轮结构变更未应用”。头部／操作／依据／用量不合法时不从不可信子字段恢复业务权限；原返回仅作为阅读／审计材料。

合法DISCUSS结构单元提交时，同一事务保存助手消息、实际进展、形成状态、卡片／binding、事件和运行终态；D／F按真实差异各至多递增一次。卡片发布引起F变化，但formation_result只描述模型形成增量本身：没有增量时NOT_REQUESTED，proposal_result=SAVED，不能据此显示路线已改。全部无变化时不制造形成事件。

用户主动GENERATE／REVISE的已授权正文主结果与讨论增量仍按现有职责分别验证；讨论单元拒绝不应撤销合法正文。正文成功引起的强制Artifact匹配维护仍须随真实内容提交，可能改变F，不能为了宣称“形成增量未应用”而留下错误CURRENT。最终界面按document_effect说明实际保存，按组件结果说明未应用部分；不以一个通用成功／失败覆盖所有事实。

CanonicalFormation.message_effects及Wire.recent_history.effect_state从真实运行终态／事件推导：USER_INPUT／USER_ACTION／DISCUSSION_ONLY／APPLIED／STRUCTURED_REJECTED／UNKNOWN。结构被拒绝的回复以后再次入选上下文时仍带该标记；模型文字里的“已写入／已完成”不改变实际状态。旧记录无法核实标UNKNOWN，不从措辞猜成功。无隐式模型重试、补Chat或修复性写入。

### 12.2 操作的准备／提交规则

| 单元 | 准备阶段 | 提交阶段 |
| --- | --- | --- |
| 路线预览 | 只读冻结D／F／V，解析临时身份，计算全部去向与前后图 | 无持久提交、无正式ID分配 |
| 路线保存／原样采用 | 核实来源／当前版本／完整去向、图、容量及真实用户输入 | 一次保存新身份、全部实体差异、映射、旧卡处置、D／F及成功回执；V不变 |
| 收束步骤 | Goal／定义／V一致，程序核实实际状态并用OUTSTANDING／KEEP_OPEN补齐未处理项 | 逐项处置、Closure、完成和可选下一步同事务；V不变 |
| 确认写入 | 不可变卡、精确范围、V／Revision／定义／Goal、原文及占用证明 | CARD_RESPONSE、正文／Revision、成果／提案／事件与回执同事务 |
| 模型DISCUSS结构单元 | 冻结依据、来源别名、进展／形成／卡片整体准备 | 一次原子保存；业务拒绝保留可读返回及pending，不制造落地事实 |

准备不能调用会提前修改业务状态的仓储方法；实际分配消息身份及保存审计仍服从同一事务。SQLite未知提交结果进入UNKNOWN，保留原body／key查证；不据超时断言回滚。

### 12.3 最终状态必须满足的关系

| 编号 | 程序校验，不由Schema代替 |
| --- | --- |
| I01 | 所有局部身份唯一且计数器高于已分配值；取消后不复用 |
| I02 | 有效顺序覆盖非CANCELLED步骤；current为空或同文档存在的讨论节点，status独立；活动支线OPEN且return为current；详见R01 |
| I03 | Step.issue_refs与Issue.step_ref双向一致；开放问题与开放支线的当前归属一致，历史来源不可改 |
| I04 | 取消步骤全部原成果在result_routes恰好覆盖；替代成果存在、类型符合、实际内容另行核实 |
| I05 | R07允许带遗留结束；程序补齐全部真实快照，保留OUTSTANDING／KEEP_OPEN；不假造完成或强迫转交，用户来源／身份／版本保持真实 |
| I06 | 依赖存在且当前图无环；被放弃前置不能继续作为未完成节点的有效依赖 |
| I07 | 正式事件无临时引用；前后快照和result映射／支线处置可核对；同批版本／序号一致 |
| I08 | 新卡payload来源依据保持不变，执行F等于发布或明确续期后的真实F；摘要来自程序实际状态 |
| I09 | 真实正文提交维护所有受影响Artifact，CURRENT不能只靠旧摘要或模型宣称 |
| I10 | D／F／V、组件结果、幂等回执与实际提交一致；读取和预览不产生写入 |

在A01—A40基础上增加未来验收，均未执行：

| 编号 | 场景与预期 |
| --- | --- |
| A41 | 拆分／合并逐项旧成果映射，遗漏／重复／类型偷换均拒绝；映射不充当写入事实 |
| A42 | 正式RESULT_ROUTE事件全部使用真实新成果身份，旧Artifact及原Revision保持 |
| A43 | COMPLETE按return而非origin收束OPEN支线；遗漏／重复／伪RESOLVED不完成 |
| A44 | 后续问题／支线转交双向引用一致；任何处置失败整个完成事务回滚 |
| A45 | F12来源发布卡后F13，卡在F13可执行；不伪改模型basis为13 |
| A46 | 调整失败后撤回在F16获得真实新依据；摘要不同则保持禁用、重新预览 |
| A47 | DISCUSS任一结构部分非法，进展／形成／新卡一起拒绝，保留pending及可读返回 |
| A48 | 原REVISE正文合法时不因讨论增量失败撤销正文；程序成果匹配仍维护 |
| A49 | 被拒绝结构的历史回复带effect_state，后续不会据文字伪认写入或完成 |
| A50 | 路线所有步骤结束仍不自动确认文档／需求；暂缓事项和复核提示继续可见 |


## 13. R07：完整性提示与用户结束决定

当前[整体评审R07](WALL-E.文档形成主线整体评审记录_V_2.1.md)优先于旧完整性硬门槛。结束表示用户结束本步，不意味着全部成果已满足；请求允许空处置列表，程序补齐OUTSTANDING／KEEP_OPEN的真实Closure。没有明确选择不自动改目标、转交或暂缓，已结束节点仍能回看／讨论；后续适用提案可明确补写，保留原结束快照和新写入事件。

COMPLETE_STEP可处理当前选择的未结束且未放弃步骤，不要求先开始／恢复到IN_PROGRESS。旧单纯RESULT_NOT_WRITTEN／BRANCH_DISPOSITION_INCOMPLETE不作为结束拒绝理由。已结束重复请求按幂等／无变化处理，不造第二次完成；已放弃节点的历史与改变范围规则保留。版本、归属、真实证明、幂等与事务检查继续执行，正文写入仍需用户明确确认。
