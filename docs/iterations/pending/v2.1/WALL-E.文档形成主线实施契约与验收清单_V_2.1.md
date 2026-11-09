# WALL-E V2.1 文档形成主线实施契约与验收清单

日期：2026-11-07（Asia/Hong_Kong）。任务M21-FORMATION-01；文档修订0.6／DRAFT。本文是[主设计](WALL-E.文档形成主线与阶段性写入_V_2.1.md)的待评审附件，供未来实施核对，不是第三份正式规格。没有实施业务代码或迁移数据。

当前接续：[0.8交互与接入收口](WALL-E.文档形成主线交互与接入收口_V_2.1.md)。本文保留0.6核心依据；ADJUST_PATH、支线活动归属、新卡片／回执及读投影以0.8附件和接入Schema v2为准。

## 1. 本次收口与规则优先级

完成权限沿用户已确认规则：AI判断并建议，用户一键结束步骤；确认写入另行执行。步骤只有PLANNED／IN_PROGRESS／PAUSED／COMPLETED／CANCELLED；SUFFICIENT等属于评估，COMPLETE_STEP等属于建议／命令，“可进入下一步”不增加状态。

本附件收束核心DTO、原生命令、事件、错误和验收输入。字段形状以[设计Schema](schemas/formation-contract.v1.schema.json)为本次0.6建议；业务权限仍受主设计约束。与早期简写有差异时采用第2—6节的明确映射；历史修订及证据保留，不倒写为当时已具备。Schema通过不代表动作获准、真实资源已发布或业务已实现。

## 2. 可校验的边界

Schema为Draft 2020-12，$id为urn:walle:v2.1:formation-contract:v1，只含本地$ref。共66个定义、10个根DTO；校验已知DTO时应按$defs名称选择，不靠猜测消息类型。字符串长度按Unicode码点，UTF-8字节预算另核实；运行校验器必须显式启用日期时间校验，format不能仅当注释。

| 根DTO | 使用位置与职责 |
| --- | --- |
| FormationState | 独立formation_state_json及展开详情中的formation；尚未建线由外层null表达 |
| FormationCommandRequest | 原requirements PATCH的新增请求联合分支；15种FORMATION动作，不扩大其他分支 |
| StagedWriteResponse | 原responses入口，单组单卡、仅apply选项；不接受客户端传入替换正文 |
| WriteProposal | 新purpose中不可变提案内容；外层真实消息／card_key确定身份 |
| FormationDelta | 新资源progress_delta的子对象；12种AI变化；没有变化时由外层null表达 |
| ProgramReceipt | 成功data中的事实回执，processing=PROGRAM，不是HTTP完整壳 |
| FormationError | 失败error对象，完整HTTP仍沿success／data／error／meta壳；本附件第5节约束来源 |
| FormationEvent | 审计的形成事件公共投影及版本化payload |
| HistoryData／HistoryMeta | 历史接口data及meta；游标为真实before_event_id，默认20、最多100 |

所有业务对象拒绝未知字段；明确可空字段必须传null，集合无值传[]。外层purpose、程序私有binding、完整新Canonical／Wire／九根模型输出、展开GET概要及完整目标数据库DDL尚未全部定义为可执行Schema；本附件不宣称已具备完整发布包。

公共Scope沿现有接口：DOCUMENT的scope_ref=null；BLOCK／SECTION为{block_id}；SELECTION为{block_id,selected_text,prefix_text,suffix_text}，选中文本1—2000码点、前后文各0—100码点。不得把内部解析的heading_id或偏移直接当公共范围。既有补丁四个定义逐项复用且保留来源摘要；仍需真实原文／目标／模板和补丁组合校验，结构合法不是可执行权限。

## 3. 原生命令逐项流转

下表是未来程序转移表，尚未接入。共同前提：真实归属及用户身份、需求级IDLE和原互斥、最新D、已存在且有效的形成状态。成功幂等回执优先于当前状态检查；同key异输入拒绝。同一原子事务最多D+1／F+1，表内纯主线命令V不变；无实际变化不制造事件和版本。用户命令的actor为USER，时间及事件ID由程序填。

| 动作 | 前态及额外核实 | 同一事务的后态／主要事件 |
| --- | --- | --- |
| START_STEP | 没有当前步骤；目标PLANNED | 目标IN_PROGRESS且为当前；STEP_STARTED |
| PAUSE_STEP | 目标就是当前IN_PROGRESS | 目标PAUSED；当前及支线焦点清空；STEP_PAUSED |
| RESUME_STEP | 没有当前步骤；目标PAUSED | 目标IN_PROGRESS且为当前；STEP_RESUMED |
| SWITCH_STEP | from为当前；to为不同PLANNED／PAUSED步骤 | 暂停from，开始／恢复to，清支线焦点；两事件同批 |
| REOPEN_STEP | 没有当前步骤；目标COMPLETED | 原完成记录保留；目标IN_PROGRESS；STEP_REOPENED |
| CANCEL_STEP | 目标PLANNED／IN_PROGRESS／PAUSED；替代引用有效 | 目标CANCELLED，必要时清焦点；保留正文／成果／支线原归属；STEP_CANCELLED |
| COMPLETE_STEP | 当前IN_PROGRESS；定义／V匹配；成果／问题全覆盖且可核实 | 目标COMPLETED及Closure；清支线焦点；可开始选定下一步；STEP_COMPLETED及可选开始事件 |
| ADJUST_PATH | 1—20项严格PathChange；先解析本批临时引用并检查最终图 | 整批接受或整批拒绝；目标／定义按实际变化递增；PATH_ADJUSTED及实体差异 |
| ENTER_BRANCH | 目标OPEN；来源步骤就是当前步骤 | 只设置active_branch_ref；BRANCH_FOCUSED；不是查看动作 |
| RETURN_FROM_BRANCH | 目标就是当前支线；返回点仍为有效当前主线步骤 | 清支线焦点，保留OPEN／已有结果；BRANCH_RETURNED |
| DISPOSE_BRANCH | OPEN且所属步骤有效；明确DEFERRED／DROPPED及原因 | 保存真实处置事件；仅在它是焦点时清焦点；BRANCH_DEFERRED／BRANCH_DROPPED |
| RESUME_BRANCH | 仅DEFERRED；来源／返回点有效，父步骤尚未放弃 | 回到OPEN，不自动进入；BRANCH_RESUMED；DROPPED不原地复活 |
| DEFER_WRITE_PROPOSAL | 原卡未正式消费，处置PENDING | DEFERRED；PROPOSAL_DEFERRED；不产生正式回答 |
| RESUME_WRITE_PROPOSAL | DEFERRED，目标／来源／定义／V仍匹配且无待调整 | PENDING；PROPOSAL_RESUMED；不重新生成内容 |
| WITHDRAW_PROPOSAL_ADJUSTMENT | 原卡未应用／替代；needs_revision=true；用途及V仍匹配 | needs_revision=false；PROPOSAL_ADJUSTMENT_WITHDRAWN；不撤销新卡或已写内容 |

START／RESUME／SWITCH可在展示未完成依赖后由用户明确先处理，并保存reason；依赖不是全局审批锁。COMPLETE_STEP携带next_step_ref时，其依赖应在本事务结束后已完成；否则先next=null收束，再由用户带原因SWITCH／START。REOPEN另一已完成步骤前，先暂停当前步骤；本版不增加隐式暂停组合命令。

RETURN_FROM_BRANCH不偷偷跨步骤。如果原返回点与当前步骤不再一致，显示可选返回位置，由用户明确切换，不能猜第一节点。父步骤切换或支线变RESOLVED时清支线焦点，OPEN记录继续保留；已放弃节点的支线仍在历史中可查。新增分支需要真实origin_event_ref，不把当前查看节点当来源。

ADJUST_PATH允许SET_GOAL／ADD_STEP／RENAME_STEP／MOVE_STEP／SET_DEPENDENCIES／UPDATE_RESULT／ADD_RESULT／CANCEL_STEP。依赖变化是定义变化；排序及纯展示改名不改变definition_version。**MVP建议暂不提供删除成果按钮**：减少既定成果范围时，明确放弃原步骤并建立replaces关系的新步骤，保留旧成果与提案；不得通过全数组替换删掉某项。此限制是0.6技术建议，未来若提供成果转移，需要独立定义完整去向和旧引用处理。

AI十二种变化为INITIALIZE_PATH、ADD_STEP、UPDATE_STEP、MOVE_STEP、ADD_BRANCH、UPDATE_BRANCH、SET_BRANCH_FOCUS、ADD_ISSUE、UPDATE_ISSUE、ASSESS_STEP、RECOMMEND、ASSOCIATE_CONTENT。UPDATE_STEP明确使用add_results追加成果，而非旧章笼统的expected_results替换；既定目标／成果kind／取消／重开仍由用户动作处理。F为null时只允许一个INITIALIZE_PATH；有F时禁止再次初始化。模型临时引用只能在同批声明并经程序映射后使用。

## 4. 写入、收束和事件的精确关系

### 4.1 不可变提案与原生应用

FILL_EMPTY带完整markdown_content、空patches、DOCUMENT范围，要求基准真实为空；PATCH_EXISTING带至少一项严格补丁，markdown_content=null。用户预览来自不可变精确内容，不从change_summary再生成。

应用沿原responses入口，校验原卡、最新D、原V／Revision、目标版本、步骤定义／成果、范围和来源；0.6建议允许IN_PROGRESS或PAUSED步骤的有效提案写入，不因只切焦点自动失效；COMPLETED先明确重开、CANCELLED重新准备。成功不切换工作焦点、不结束步骤。原生精确授权只由本次用户正式回答和程序核实生成，不能从DISCUSS或保存提案推导写权限。

原正式回答、正文／Revision、真实DocumentEffect、ArtifactLink、提案处置、状态／审计及幂等回执同事务。NO_CHANGE不产生新Revision；若首次建立合法成果关联或消费卡片，则D／F可变。暂缓、继续调整及撤回调整都不提前消耗正式apply机会；新卡成功落库后旧卡才SUPERSEDED。

### 4.2 用户实际看到的操作

例如当前步骤“明确推荐与反馈流程”：AI已提出正文，但未保存。节点显示“有待写入内容”，结束按钮说明尚缺文档成果。用户点“确认写入”，保存后成果出现可定位的当前Revision；节点仍在进行中。AI根据文档提出结束建议，展示成果和遗留事项；用户点“结束并继续”，才完成该节点并开始下一节点。无需再弹相同确认，也不把保存和完成合成一个含糊动作。

如果用户中途讨论冷启动：在来源步骤下登记支线和触发消息。点标题只是查看；点“进入支线讨论”才改焦点。先返回主线时该支线仍OPEN；暂缓则显示真实处置原因。放弃旧步骤后默认路线隐藏其卡片，但“已放弃节点”入口仍可查看来源、原位置、成果及替代节点。

### 4.3 回执与历史

ProgramReceipt采用最小事实：requirement_id、document_id、D／F／V、effects、event_ids、processing=PROGRAM；不要求每次复制完整状态。相应最新状态通过原GET取得，替代12.5节“回执附全状态”的笼统建议。后续GET失败显示“操作成功，显示待刷新”；成功回执不是保存失败，更不是当前最新快照。

FormationEvent物理版本标记统一为schema="formation_event_v1"、actor=USER／AI／PROGRAM，替代17.5节早期schema_version／actor_kind命名；不同时保留同义可写字段。增加batch_ref／ordinal／batch_size和可空closure，其余按Schema。完成事件必须USER且有Closure；STEP的before快照保存当时完整定义，Closure引用其定义版本及实际Revision。创建／放弃的STEP及ORDER差异共同保存标题、原位置和替代关系，程序必须保证这些必需快照齐备，不能只靠Schema接受了空changes。

当前状态与每批事件同事务；同批D／F／V前后值一致，事件有独立真实ID。before／after都空的差异无效；ordinal不得大于batch_size。读历史返回data={document_id,items}，meta={request_id,page_size,has_more,next_cursor}；has_more=true必有下一游标，false为null。过滤step_ref／branch_ref后仍用真实事件ID，不能将分页已加载条数当历史总数。

## 5. 错误、回执与前端恢复

本节是错误映射设计，现有http_errors.py尚未更改。Schema列出当前27种wire错误及拟新增2种，不代表每个路由均可返回全部错误；实施时每个入口还要登记实际可达的allowed_errors。message由程序按登记代码生成，不透传数据库、供应方异常或用户正文。

| 情况 | HTTP／wire代码与安全details | 前端恢复 |
| --- | --- | --- |
| 请求结构／未知字段 | 422 VALIDATION_FAILED；内部INVALID_INPUT映射；field_errors为field／登记reason／安全message | 保留输入，就地改正 |
| 来源／范围／补丁不合法 | 422 SOURCE_INVALID／SCOPE_INVALID／PATCH_INVALID | 保留预览并说明；补丁详情不虚构suggestion_id，本版新卡可为null |
| 主线图／临时引用语义非法 | 拟新增422 FORMATION_INVALID，details=null | 拒绝整批，保留上一有效状态；不是保存后清空主线 |
| 超出形成容量 | 拟新增422 FORMATION_LIMIT_EXCEEDED；resource_kind／limit／actual | 明确额度和缩减入口，不静默截断 |
| D已变 | 409 DISCUSSION_VERSION_CONFLICT；现有安全VersionConflictDetail或null | 刷新并核实原动作，不能自动改body重放 |
| V已变 | 409 CONTENT_VERSION_CONFLICT，沿现有白名单details=null | 展示已读取的新版本，重新准备提案；本版不扩出未登记详情 |
| 状态／定义／目标／焦点不匹配 | 409 STATE_CONFLICT；拟登记reason、step_ref或null、proposal或null | 显示具体原因，刷新有效操作；不自动把步骤完成／提案失效写入 |
| 已被占用／已有正式回答／卡已过期 | 409 WORK_STATE_CONFLICT／CARD_ALREADY_ANSWERED／CARD_EXPIRED | 已回答详情只为response_message_id；进入原结果或解释占用 |
| 幂等冲突／尚在处理 | 409 IDEMPOTENCY_CONFLICT／REQUEST_IN_PROGRESS | 同key异内容停止；原动作保留并核实 |
| 资源／存储不可用 | 503 CONFIG_INVALID／STORAGE_UNAVAILABLE | 保留输入和已知事实，允许原动作核实；不自行再Chat |
| 保存状态损坏／内部不一致 | 沿500 INTERNAL_ERROR或已有409 WORK_STATE_INCONSISTENT，按真实原因 | 显示错误并限制依赖损坏状态的写入；不能当作未建线自动覆盖 |

版本详情resource_kind仅沿Requirement／RequirementDocument／Discussion／Revision；Step和Goal不是已有数字实体，定义变化用STATE_CONFLICT的登记reason表达。字段reason沿现有REQUIRED／INVALID_TYPE／INVALID_FORMAT／INVALID_ENUM／TOO_SHORT／TOO_LONG／OUT_OF_RANGE／UNKNOWN_FIELD／DUPLICATE_PARAMETER。PATCH_INVALID／TARGET_STALE的原suggestion_errors仅用于真实既有建议对象。

STATE_CONFLICT新增详情以及两个新错误必须在实现时显式扩展安全投影和入口白名单；当前程序会拒绝未知非空details，不能只新增文档枚举。未登记的错误仍归安全INTERNAL_ERROR，不把私有栈带给用户。

明确业务拒绝不提交半份正文／状态／回答。传输超时和CommitOutcomeUnknown不属于“已知未提交”：客户端进入UNKNOWN，保留同method／path／body／key，先核实原动作。已成功则原样重放旧回执；不得改V后再发相同补丁或重新生成。

## 6. 结构校验后必须执行的程序不变量

| 校验范围 | 程序必须核实的事实 |
| --- | --- |
| 身份／归属 | 文档属于路径需求；所有步骤／成果／支线／事件／卡片／Revision／来源属于真实允许范围 |
| 当前投影 | 局部ID无重复，计数器严格高于已分配身份；有效步骤顺序完整、已放弃项不在有效路线；恰好零或一个IN_PROGRESS且与current对应 |
| 支线焦点 | OPEN、真实来源和当前父步骤一致；返回点可执行；RESOLVED结果与来源真实；用户处置不可由模型伪造 |
| 定义与依赖 | 结果引用属于指定步骤；依赖存在、无自环／循环；所有本批临时身份先声明后解析；变更权限不因结构合法扩大 |
| 材料／权限 | 别名确实随本轮材料携带且覆盖足够；评估不能越过未读正文；卡片、授权和真实用户回答对应同一精确内容 |
| 完成／成果 | 全部预期成果及未决问题恰好覆盖；CONTENT有当前可核实Artifact；ANALYSIS有真实结果来源；定义和目标版本不变 |
| 版本／事务 | 按真实差异计算D／F／V及DocumentEffect；NO_CHANGE不造Revision；事件快照／批次齐备；任何失败整体回滚 |
| 文本／容量 | 序列化后UTF-8字节预算、集合总量、模型输入预算与输出上限；Schema码点上限不代替资源计数 |

## 7. 未来产品验收清单（全部未执行）

以下是后续实施必须满足的场景，**不是本轮通过记录**。服务／SQLite专项、前后端联调和浏览器分别取证；涉及真实模型的新资源检查单独取得当前授权，离线模拟不能替代供应方证据。

| 编号 | 触发与预期事实 | 层级 |
| --- | --- | --- |
| A01 | GET无主线返回已读null，不调用模型或建线 | API／UI |
| A02 | 首次有效形成工作建立路径，别名落为真实来源，F1；普通问答不强建线 | AI处理／API |
| A03 | SWITCH两个状态及焦点同事务；第二步保存失败全部回滚 | SQLite专项 |
| A04 | PAUSE清焦点；RESUME只有明确动作；查看历史节点完全只读 | API／浏览器 |
| A05 | AI评估足够／建议完成不改步骤状态，用户点击后才完成 | AI处理／联调 |
| A06 | 缺CONTENT成果／关联需复核时结束被拒绝，旧状态不变 | 服务专项 |
| A07 | ANALYSIS成果有真实记录可无正文结束，不能替代CONTENT | 服务专项 |
| A08 | COMPLETE逐项覆盖且无重复遗漏；下一步不可开始时整次拒绝 | 服务专项 |
| A09 | 目标／定义变更使旧完成请求拒绝；重排不使无关提案失效 | API／服务 |
| A10 | 重开保留旧Closure；放弃保持正文、来源和替代关系 | 服务／浏览器 |
| A11 | 支线明确来源；查看不进焦点；ENTER需当前父步骤；返回仍OPEN | 联调／浏览器 |
| A12 | 暂缓／放弃留下用户依据；恢复仅DEFERRED；无效返回点不乱跳 | 服务／浏览器 |
| A13 | AI不能静默变目标／取消／完成／放弃；非法混合增量全部拒绝并保留pending | AI处理专项 |
| A14 | 临时引用未声明、跨文档引用、依赖成环和伪材料均拒绝 | 服务专项 |
| A15 | FILL_EMPTY真实空白首写；两种内容混传或非空目标拒绝 | 内容专项 |
| A16 | PATCH原文／范围／模板保护完整；客户端替换卡片正文拒绝 | 内容／API |
| A17 | 确认应用为PROGRAM、0Chat且一次正式回答；步骤仍进行／暂停 | 联调 |
| A18 | 写入任一保存阶段失败，正文／Revision／回答／主线／回执一起回滚 | SQLite专项 |
| A19 | NO_CHANGE不造Revision；新关联及正式消费仍有真实处置 | 服务专项 |
| A20 | 暂缓未消费卡片，恢复后可apply；调整失败禁用旧文，撤回需版本仍匹配 | API／浏览器 |
| A21 | 成功请求超时，同key重放先于新版本检查，零重复写入／Chat | 幂等集成 |
| A22 | 同key异输入拒绝；UNKNOWN原body保存，200后GET失败不显示保存失败 | API／浏览器 |
| A23 | 另一页改V后旧提案拒绝；只变D且用途仍同可带最新D应用；同需求其他文档占用仍拦截 | 并发集成 |
| A24 | 所有正文提交入口更新成果匹配；变更、删除、历史恢复均不伪造CURRENT | 内容集成 |
| A25 | 事件同批版本／顺序一致；来源／Revision可追溯；缺来源显示不可用 | 审计／浏览器 |
| A26 | 历史分页／过滤保持真实ID；已放弃计数不依赖已加载页 | API／浏览器 |
| A27 | 坏状态明确报错而非null；超容量明确拒绝而非截断 | API／服务 |
| A28 | 源库保留，新目标复制字节／身份／旧回执校验；未知V2.0阻止猜测升级 | 离线升级演练 |
| A29 | 旧资源／运行快照／卡片按原版本读取；新资源无准入不得用旧LIVE放行 | 资源／准入 |
| A30 | 窄宽布局、键盘／读屏、空／错／加载／忙／UNKNOWN及晚到回执不抢焦点 | 产品浏览器 |

## 8. 实施顺序与剩余取舍

| 批次 | 输入与交付 | 完成条件 |
| --- | --- | --- |
| B1 契约与升级准备 | 核实真实本地基线；完整读写DTO、purpose／私有binding／新资源Schema、错误注册、目标DDL及升级计划 | 消除字段分歧，契约夹具和升级设计可检查；不切真实服务 |
| B2 主线原生闭环 | 文档独立列、状态机／命令／审计／历史及幂等 | 只靠程序完成建模、操作、重放与只读追溯；关键事务专项通过 |
| B3 阶段性写入 | 原cards程序分派、可信授权、补丁／空白首写、统一内容提交关联 | 精确预览＝应用内容，成功原子保存；失败及UNKNOWN可恢复 |
| B4 AI材料与增量 | 新Canonical／Wire／Output、引用映射、来源／覆盖及统一增量接收 | 离线校验权限完整；资源计数及新release证据独立，不复用旧准入 |
| B5 产品接入与验收 | 已认可节点交互接入真实投影／命令，升级演练与全闭环 | A01—A30逐项取证，遗留明确；发布／数据切换另按实际授权 |

本轮建议MVP保持两个明确按钮：“确认写入”和“结束步骤”；首步默认先显示计划，由用户点“开始这一步”，Schema允许初始化current_step_ref=null。首步自动开始、联合写入并结束仍未获用户逐项确认；后续可评审，不把建议追记为已定案。

集合／字节容量仍是设计上限建议，需负载验证；真实V2.0结构、数据库目标版本号和完整新资源绑定尚待核实。下一步应完成B1的余项及这些取舍，而不是继续扩展平行功能。本轮只交付设计附件和结构核对，没有启动上述实施批次。
