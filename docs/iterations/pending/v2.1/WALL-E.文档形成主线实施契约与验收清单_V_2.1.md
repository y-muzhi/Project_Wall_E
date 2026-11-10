# WALL-E V2.1 文档形成主线实施契约与验收清单

日期：2026-11-07；更新：2026-11-10（Asia/Hong_Kong）。任务M21-FORMATION-01；文档修订0.9／DRAFT。本文与[主设计](WALL-E.文档形成主线与阶段性写入_V_2.1.md)、[交互与接入说明](WALL-E.文档形成主线交互与接入收口_V_2.1.md)共同描述当前待合并设计，供未来实施核对；未实施业务代码、迁移或产品验收。

## 1. 当前契约与权限边界

业务结论以[整体评审R01—R08](WALL-E.文档形成主线整体评审记录_V_2.1.md)为依据，严格结构统一采用[接入Schema v4](schemas/formation-integration.v4.schema.json)。讨论焦点与生命周期独立；首次建线自动进入第一步，自由切换不要求暂停或完成其他步骤。AI判断并建议，用户一键结束，允许保留未写／未决事项；确认写入独立执行。

步骤状态为PLANNED／IN_PROGRESS／PAUSED／COMPLETED／CANCELLED；SUFFICIENT等属于评估，COMPLETE_STEP等属于建议／命令。“已结束”不等于成果全部满足或文档定稿。结构校验不代替真实来源、版本、权限和事务核实。

## 2. 可校验的边界

当前Schema为Draft 2020-12，$id为urn:walle:v2.1:formation-integration:v4，只含本地$ref，192个定义、13个根DTO。校验已知DTO时按$defs名称选择，不靠猜测消息类型。字符串长度按Unicode码点，UTF-8字节预算另核实；运行校验器显式启用日期时间校验。设计Schema尚未成为产品发布包。

| 根DTO | 使用位置与职责 |
| --- | --- |
| L_Canonical | 程序内部完整上下文，含CanonicalFormation及冻结依据 |
| L_Wire | 实际模型输入投影，含WireFormation及已选近期事件 |
| L_Output | 九根模型输出；形成增量及提案由程序验证后应用 |
| L_ModelCardGroup | 模型提交的两种新purpose卡片与既有组联合 |
| L_StoredCardGroup | 解析真实来源并加入私有binding后的存储卡片组 |
| F_StagedWriteResponse | 单组单卡、仅apply选项的正式回答，不接受替换正文 |
| NativeRequest | 原requirements PATCH的14种FORMATION命令分支 |
| PathPreview | 完整路线调整的只读影响预览 |
| ReadExtension | 文档主线概要或展开详情，区分未读取与已读null |
| GuideRequest | 仅定义operation=DISCUSS的discussion_step_ref和可空proposal_intent；同一HTTP入口的非DISCUSS请求仍由既有契约处理 |
| ProgramReceipt | 程序动作的事实回执，processing=PROGRAM，不是HTTP完整壳 |
| ProposalPage | 提案摘要、可用性原因及游标分页 |
| RoundResult | 模型结束、正文保存、进展／形成／提案结果分别表达 |

内部F_FormationState用于formation_state_json；F_FormationEvent及F_HistoryData／F_HistoryMeta用于审计与历史，F_FormationError定义安全错误。根DTO和内部定义均来自同一v4文件，不从旧核心Schema拼装请求。历史Schema保持原字节。

所有业务对象拒绝未知字段；明确可空字段必须传null，集合无值传[]。binding标识仍是formation_card_binding_v3，协议标识与设计文件v4不是同一版本维度。

公共Scope沿现有接口：DOCUMENT的scope_ref=null；BLOCK／SECTION为{block_id}；SELECTION为{block_id,selected_text,prefix_text,suffix_text}，选中文本1—2000码点、前后文各0—100码点。不得把内部解析的heading_id或偏移直接当公共范围。既有补丁形状保留，仍需真实原文／目标／模板和补丁组合校验。

## 3. 原生命令逐项流转

下表是未来程序转移表，尚未接入。共同前提：真实归属及用户身份、需求级IDLE和原互斥、最新D、已存在且有效的形成状态。成功幂等回执优先于当前状态检查；同key异输入拒绝。同一原子事务最多D+1／F+1，表内纯主线命令V不变；无实际变化不制造事件和版本。用户命令的actor为USER，时间及事件ID由程序填。

| 动作 | 前态及额外核实 | 同一事务的后态／主要事件 |
| --- | --- | --- |
| START_STEP | 目标PLANNED；不要求其他步骤先暂停 | 明确开始目标并设置当前讨论；STEP_STARTED |
| PAUSE_STEP | 目标IN_PROGRESS | 目标PAUSED；仅在它是当前节点时清当前及支线焦点；STEP_PAUSED |
| RESUME_STEP | 目标PAUSED；不要求当前焦点为空 | 目标IN_PROGRESS并设置当前讨论；STEP_RESUMED |
| SWITCH_STEP | step_ref为同文档真实节点，含已完成／已放弃节点 | 只改讨论指针并清不匹配支线焦点；DISCUSSION_STEP_SELECTED；生命周期不变 |
| REOPEN_STEP | 目标COMPLETED；不要求先暂停其他节点 | 保留旧Closure，目标IN_PROGRESS；STEP_REOPENED |
| COMPLETE_STEP | 当前选择的未结束且未放弃步骤；Goal／定义／V匹配 | 程序补齐真实Closure及遗留，目标COMPLETED；可定位next_step_ref；STEP_COMPLETED |
| ADJUST_PATH | 1—20项PathChange及完整result_routes；解析临时引用并核对最终图 | 整批接受或拒绝；目标／定义按实际变化递增；PATH_ADJUSTED及实体差异 |
| ENTER_BRANCH | 目标OPEN，return_step_ref等于当前讨论节点 | 只设置active_branch_ref；BRANCH_FOCUSED；查看本身不改焦点 |
| RETURN_FROM_BRANCH | 目标为当前支线，返回点与当前讨论节点一致 | 清支线焦点，保留OPEN／已有结果；BRANCH_RETURNED |
| DISPOSE_BRANCH | OPEN；明确DEFERRED／DROPPED及原因 | 保存真实处置；仅在它是焦点时清焦点；BRANCH_DEFERRED／BRANCH_DROPPED |
| RESUME_BRANCH | 仅DEFERRED；返回点真实且可用 | 回到OPEN，不自动进入；BRANCH_RESUMED；DROPPED不原地复活 |
| DEFER_WRITE_PROPOSAL | 原卡未正式消费，处置PENDING | DEFERRED；PROPOSAL_DEFERRED；不产生正式回答 |
| RESUME_WRITE_PROPOSAL | DEFERRED，目标／来源／定义／V仍匹配且无待调整 | PENDING；PROPOSAL_RESUMED；不重新生成内容 |
| WITHDRAW_PROPOSAL_ADJUSTMENT | 原卡未应用／替代；needs_revision=true；用途及真实依据仍匹配 | 清needs_revision，记录撤回及必要依据事件；不撤销新卡或已写内容 |

日常开始／恢复由用户实际发送DISCUSS的接受事务完成，不要求额外开始按钮；表内保留独立明确动作的契约。依赖只提示，不阻止讨论切换或next_step_ref选择。结束并继续对未结束目标可开始／恢复；目标已完成／放弃时只定位，保留原状态。所有开始／恢复／重开操作都不隐式暂停其他步骤。

AI运行期间可在本地选择下一轮节点，不改在途运行的冻结依据；空闲时只保存最后有效选择，或下次接受DISCUSS时一并处理。在途回复继续归属原节点，不抢回UI焦点。未生效本地选择不生成服务端事件。

支线origin_step_ref及origin_event_ref不可变，return_step_ref是当前处理／返回点。返回点失效时展示可选位置，由用户明确选择，不猜第一节点。焦点切换只清不匹配活动支线，OPEN记录和原来源继续保留。

取消节点统一使用ADJUST_PATH中的CANCEL_STEP，不存在独立原生CANCEL_STEP请求。13种PathChange为SET_GOAL／ADD_STEP／RENAME_STEP／MOVE_STEP／SET_DEPENDENCIES／UPDATE_RESULT／ADD_RESULT／CANCEL_STEP／LINK_CONTENT／MOVE_ISSUE／SET_BRANCH_RETURN／DISPOSE_ISSUE／DISPOSE_BRANCH。取消的每项旧成果必须在result_routes说明REPLACED或NOT_REQUIRED，问题／支线及依赖也须有合法去向。排序及纯展示改名不改变definition_version，实质定义变化递增。完整规则见[接入说明第3、9节](WALL-E.文档形成主线交互与接入收口_V_2.1.md)。

AI十二种变化为INITIALIZE_PATH、ADD_STEP、UPDATE_STEP、MOVE_STEP、ADD_BRANCH、UPDATE_BRANCH、SET_BRANCH_FOCUS、ADD_ISSUE、UPDATE_ISSUE、ASSESS_STEP、RECOMMEND、ASSOCIATE_CONTENT。UPDATE_STEP明确使用add_results追加成果，而非旧章笼统的expected_results替换；既定目标／成果kind／取消／重开仍由用户动作处理。F为null时只允许一个INITIALIZE_PATH；有F时禁止再次初始化。模型临时引用只能在同批声明并经程序映射后使用。

## 4. 写入、收束和事件的精确关系

### 4.1 不可变提案与原生应用

FILL_EMPTY带完整markdown_content、空patches、DOCUMENT范围，要求基准真实为空；PATCH_EXISTING带至少一项严格补丁，markdown_content=null。用户预览来自不可变精确内容，不从change_summary再生成。

应用沿原responses入口，校验原卡、最新D、原V／Revision、Goal、步骤定义／成果、范围、来源及真实用途。纯切焦点和COMPLETED状态本身均不使仍适用提案失效；已结束节点无需仅为确认写入先重开，原Closure不回写。CANCELLED或用途已变则按真实原因重新准备。成功不切换工作焦点、不结束步骤。原生精确授权只由本次用户正式回答和程序核实生成，不能从DISCUSS或保存提案推导写权限。

原正式回答、正文／Revision、真实DocumentEffect、ArtifactLink、提案处置、状态／审计及幂等回执同事务。NO_CHANGE不产生新Revision；若首次建立合法成果关联或消费卡片，则D／F可变。暂缓、继续调整及撤回调整都不提前消耗正式apply机会；新卡成功落库后旧卡才SUPERSEDED。

### 4.2 用户实际看到的操作

例如当前步骤“明确推荐与反馈流程”：AI已提出正文但尚未保存，节点显示“有待写入内容”。用户可确认写入，也可带遗留结束；前者保存真实Revision／成果关联但不结束步骤，后者V不变并在Closure记录OUTSTANDING。AI整理成果、遗留和推荐下一节点，用户点“结束并继续”后保存真实结束事实并定位下一节点，不额外Chat或重复确认。

如果用户中途讨论冷启动：在来源步骤下登记支线和触发消息。点标题只是查看；点“进入支线讨论”才改焦点。先返回主线时该支线仍OPEN；暂缓则显示真实处置原因。放弃旧步骤后默认路线隐藏其卡片，但“已放弃节点”入口仍可查看来源、原位置、成果及替代节点。

### 4.3 回执与历史

ProgramReceipt包含receipt_schema、requirement_id、document_id、user_message_id、operation、result、reference_map、D／F／V、effects、event_ids、processing=PROGRAM；完整字段以v4为准。相应最新状态通过原GET取得，不在回执复制全状态。后续GET失败显示“操作成功，显示待刷新”；成功回执不是保存失败，更不是当前最新快照。

F_FormationEvent物理版本标记为schema="formation_event_v1"、actor=USER／AI／PROGRAM，不设置同义可写字段。增加batch_ref／ordinal／batch_size和可空closure，其余按Schema。完成事件必须USER且有Closure；STEP的before快照保存当时完整定义，Closure引用其定义版本及实际Revision。创建／放弃的STEP及ORDER差异共同保存标题、原位置和替代关系，程序必须保证这些必需快照齐备，不能只靠Schema接受了空changes。

当前状态与每批事件同事务；同批D／F／V前后值一致，事件有独立真实ID。before／after都空的差异无效；ordinal不得大于batch_size。读历史返回data={document_id,items}，meta={request_id,page_size,has_more,next_cursor}；has_more=true必有下一游标，false为null。过滤step_ref／branch_ref后仍用真实事件ID，不能将分页已加载条数当历史总数。

## 5. 错误、回执与前端恢复

本节是错误映射设计，现有http_errors.py尚未更改。Schema列出既有wire错误及拟新增FORMATION_INVALID／FORMATION_LIMIT_EXCEEDED，不代表每个路由均可返回全部错误；实施时每个入口还要登记实际可达的allowed_errors。message由程序按登记代码生成，不透传数据库、供应方异常或用户正文。

| 情况 | HTTP／wire代码与安全details | 前端恢复 |
| --- | --- | --- |
| 请求结构／未知字段 | 422 VALIDATION_FAILED；内部INVALID_INPUT映射；field_errors为field／登记reason／安全message | 保留输入，就地改正 |
| 来源／范围／补丁不合法 | 422 SOURCE_INVALID／SCOPE_INVALID／PATCH_INVALID | 保留预览并说明；补丁详情不虚构suggestion_id，本版新卡可为null |
| 主线图／临时引用语义非法 | 拟新增422 FORMATION_INVALID，details=null | 拒绝整批，保留上一有效状态；不是保存后清空主线 |
| 超出形成容量 | 拟新增422 FORMATION_LIMIT_EXCEEDED；resource_kind／limit／actual | 明确超限项目并保留原状态／草稿，不静默截断；容量达限体验仍待Q04评审 |
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
| 当前投影 | 局部ID无重复，计数器严格高于已分配身份；有效顺序覆盖非CANCELLED步骤；current为空或同文档已存在节点（含历史），与status独立，可有多个IN_PROGRESS |
| 支线焦点 | OPEN且return等于当前讨论节点；origin及触发事件不可变；RESOLVED结果与来源真实；用户处置不可由模型伪造 |
| 定义与依赖 | 结果引用属于指定步骤；依赖存在、无自环／循环；所有本批临时身份先声明后解析；变更权限不因结构合法扩大 |
| 材料／权限 | 别名确实随本轮材料携带且覆盖足够；评估不能越过未读正文；卡片、授权和真实用户回答对应同一精确内容 |
| 完成／成果 | 程序补齐完整真实Closure；已写／已分析须有可核实依据，不足记OUTSTANDING，未处置问题／支线KEEP_OPEN；不得伪造完成或强迫转交；定义和目标版本不变 |
| 版本／事务 | 按真实差异计算D／F／V及DocumentEffect；NO_CHANGE不造Revision；事件快照／批次齐备；任何失败整体回滚 |
| 文本／容量 | 序列化后UTF-8字节预算、集合总量、模型输入预算与输出上限；Schema码点上限不代替资源计数 |

## 7. 未来产品验收清单（全部未执行）

以下是后续实施必须满足的场景，**不是本轮通过记录**。服务／SQLite专项、前后端联调和浏览器分别取证；涉及真实模型的新资源检查单独取得当前授权，离线模拟不能替代供应方证据。

| 编号 | 触发与预期事实 | 层级 |
| --- | --- | --- |
| A01 | GET无主线返回已读null，不调用模型或建线 | API／UI |
| A02 | 首次有效形成工作建立路径，别名落为真实来源，F1；普通问答不强建线 | AI处理／API |
| A03 | SWITCH只改变讨论焦点及不匹配支线指针；生命周期不变；持久保存失败整体回滚 | SQLite专项 |
| A04 | 暂停当前节点时清焦点；恢复来自明确动作或实际发送讨论；只查看历史不改状态 | API／浏览器 |
| A05 | AI评估足够／建议完成不改步骤状态，用户点击后才完成 | AI处理／联调 |
| A06 | 缺CONTENT成果／关联需复核时可结束；V不变，Closure如实记OUTSTANDING | 服务专项 |
| A07 | 有真实分析依据记ANALYZED，无依据记OUTSTANDING；不能将分析伪装CONTENT落地 | 服务专项 |
| A08 | COMPLETE可提交空处置列表，程序补齐真实快照；next可定位历史节点且不受前置依赖拦截；非法身份／版本／显式处置整次拒绝 | 服务专项 |
| A09 | 目标／定义变更使旧完成请求拒绝；重排不使无关提案失效 | API／服务 |
| A10 | 重开保留旧Closure；放弃保持正文、来源和替代关系 | 服务／浏览器 |
| A11 | 支线明确来源；查看不进焦点；ENTER的return需等于当前讨论节点；返回仍OPEN | 联调／浏览器 |
| A12 | 暂缓／放弃留下用户依据；恢复仅DEFERRED；无效返回点不乱跳 | 服务／浏览器 |
| A13 | AI不能静默变目标／取消／完成／放弃；非法混合增量全部拒绝并保留pending | AI处理专项 |
| A14 | 临时引用未声明、跨文档引用、依赖成环和伪材料均拒绝 | 服务专项 |
| A15 | FILL_EMPTY真实空白首写；两种内容混传或非空目标拒绝 | 内容专项 |
| A16 | PATCH原文／范围／模板保护完整；客户端替换卡片正文拒绝 | 内容／API |
| A17 | 确认应用为PROGRAM、0Chat且一次正式回答；步骤状态及原结束快照保持 | 联调 |
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
| B5 产品接入与验收 | 已认可节点交互接入真实投影／命令，升级演练与全闭环 | A01—A60按当前规则逐项取证，遗留明确；发布／数据切换另按实际授权 |

当前提供独立“确认写入”和“结束步骤”，不提供联合“写入并结束”；首次建线直接进入第一步。Q03成果复核提示如何消除、Q04容量达限体验仍待产品评审；现有设计常量不是用户已批准的限制后果。真实V2.0结构、目标数据库版本号和新资源发布绑定须在B1核对。

A01—A30见本表，A31—A50见[接入说明](WALL-E.文档形成主线交互与接入收口_V_2.1.md)，A51—A60见[评审记录](WALL-E.文档形成主线整体评审记录_V_2.1.md)，均未执行。此处只定义实施输入，不启动这些实施批次。
