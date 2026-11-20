# WALL-E V2.1 后端设计文档

## 1. 文档说明与系统范围

### 1.1 基本信息

| 字段 | 定义 |
| --- | --- |
| 规格编号 | WALL-E-BE-V21 |
| 系统名称 | WALL-E文档协作后端 |
| 规格类型 | 基于既有系统的增量详细规格，按统一需求规格模板编写 |
| 目标软件版本 | V2.1 |
| 规格修订／状态 | 0.1-draft-4／DRAFT |
| 更新时间 | 2026-11-14（Asia/Hong_Kong；2026-11-13开始编写） |
| 输入基线 | OUTLINE21-01／0.12 DRAFT；SHA256 `3774e919a16cd09e18a548ee06227836f73cddea64fe1c89ea516caa441ff6a1` |
| 当前编写范围 | 第1—8章及附录完整初稿；仅设计输出，未实施／未产品验收 |

### 1.2 目标与范围

为同份文档建立可追溯形成路线，连接讨论、精确阶段性写入、成果复核及用户结束决定。本规格负责共同对象、应用能力、模型上下文、HTTP、存储事务和共享验收；页面／组件／浏览器状态由[前端规格](WALL-E.前端设计文档_V_2.1.md)负责。

采用[大纲0.12](WALL-E.大纲设计基线_V_2.1.md)全部范围和C21-01—03修正。原V1.5文档／Revision／编辑／候选／确认和V2.0 Coding／Testing既有能力按其真实基线承接，未改变部分不复制。本文不增加跨文档自动同步、自动编码总管、预览内编辑、联合写入并结束或后台模型复核。

本工作区代码HEAD为21651c3，尚不含另一工作区未提交的全部V2.0实现。已只读取得原工作区V2.0 BE0.17／FE0.16设计及Schema200／db20-r48的相关表与来源接口；具体摘要与已读边界见[来源核对](../../../verification/v2.1/detailed-design-baseline-read-2026-11-14.md)。本规格的新物理映射和输入字段是目标定义，不宣称当前接口已接受，发布时须固定实际源Schema摘要并核对变化。

### 1.3 填写与实施规则

对象规则只在第3章定义；业务处理在第4章；HTTP形状在第6章；技术保证在第7章；验收预期在第8章。前端引用本文件的共同定义，旧迭代仅保留采用来源，不另建第三份现行详细规格。

本轮只输出设计和静态核对，不改产品源码／冻结资源／Schema、不读业务库、不启动服务／真实模型或计数、不提交推送。DRAFT与未实现分开；附录A仅列尚未取得的技术事实及发布输入，不重列已确认产品问题。

### 1.4 术语与缩写

| 名称 | 含义 |
| --- | --- |
| D／F／V | 文档讨论版本／形成版本／正文版本；由SHR-FORM-VERSION定义 |
| 当前目标 | 文档＋步骤＋可选支线；一次性恢复意图另有待消费依据 |
| 成果 | CONTENT为真实正文要求；ANALYSIS为有来源的分析要求，不等同已完成事实 |
| 关联／充分性 | 程序可追溯内容关系／AI对成果要求的判断，分别保存 |
| 当前／历史 | 当前实体及投影／不可变原事件、Revision、Closure，互不冒充 |

### 1.5 稳定引用与实现定位

本文使用OBJ-FORM-*、APP-FORM-*、BND-FORM-*、SHR-FORM-*、INF-FORM-*、TC-FORM-A01—A76及EV-FORM-*。A编号沿大纲保留，仅增加稳定前缀；章节号供导航。代码实现位置标为“现有”或“新增目标”，新增目标不表示文件已存在。

| 模块范围 | 现有入口／新增目标 | 责任 |
| --- | --- | --- |
| backend/app/requirements | 现有discussion.py、commands.py、api.py；新增目标formation.py／formation_commands.py／formation_queries.py | 主线逻辑、原生分派、读投影 |
| backend/app/guide | 现有collaboration_context.py、progress_application.py、card_commands.py、accepted_context.py | 冻结、选材、进展接收、卡片程序分派 |
| backend/app/documents | 现有content.py::commit_content、sources.py／snapshot.py | 全部正文提交的权限及成果维护 |
| backend/app/infrastructure | 现有数据库／仓储／audit／idempotency；新增目标formation_repository.py | 同连接实体、关系、事件索引及分页 |
| frontend/src | 由前端规格定位 | 只消费本文公开DTO，不访问私有basis |

## 2. 技术基线与公共规则

### 2.1 技术与模块基线

Python3.13.5、FastAPI0.142.2、jsonschema4.26.0等依赖以本工作区backend/requirements.lock为唯一锁定来源；数据库严格结构／固定SQLite与V2.0维护入口按实际源发布清单定位。复用既有本机HTTP、进程锁、需求级工作占用、运行Worker及原仓储，不增加微服务、队列或新的供应商调用体系。

允许实现者决定普通函数名、文件内分解、非语义索引和SQL执行批大小；不得自行改变权限、状态、来源、幂等、并发范围、预算、错误或本文公开契约。

### 2.2 公共规则

<a id="shr-form-types"></a>
#### SHR-FORM-TYPES 类型、文本与身份

| 类型 | 唯一规则 |
| --- | --- |
| ID／Version | 1—9007199254740991整数，拒绝bool／浮点／字符串代入；计数器从1递增，不复用身份 |
| StepRef／BranchRef／IssueRef／ArtifactRef | sN／bN／iN／aN，N正整数，仅同文档有效 |
| ResultRef | sN.oK，K由该步骤分配，不因删除要求重用 |
| EventID／MessageID／RevisionID／BlockID | 复用原真实数据库身份，不能把别名当SQL身份 |
| TempRef | TempStepRef=new_step_N；TempResultRef=new_result_N；TempBranchRef=new_branch_N；TempIssueRef=new_issue_N；N正整数，各为互不混用的局部类型 |
| PathStepRef／PathResultRef | StepRef或TempStepRef／ResultRef或TempResultRef；仅路线输入／未采用路线卡／预览允许，正式实体和历史只用真实Ref |
| UTC | 程序生成YYYY-MM-DDTHH:mm:ss.SSSZ；展示时转换用户时区 |
| Title／Text／Short | Unicode码点1—120／1—1000／1—240；拒绝非法Unicode，不静默截断 |
| Digest | lowercase SHA256 hex64；本文声明的canonical JSON采用UTF-8、对象键字典序、无空白、拒绝非有限值；有序数组保序，集合先按稳定身份排序 |
| SourceRef／Scope／Patch | 未改变字段直接采用V1.5正式后端同名严格结构；新增CARD_RESPONSE来源见7.2，不修改历史资源 |

对象字段默认必有，可空须显式null，空集合用[]；请求“缺失”与null不同。业务文本统一LF，正文／补丁不trim，不因标准化改变用户确认的精确内容。操作者、时间、事件和落地来源由程序提供。

<a id="shr-form-version"></a>
#### SHR-FORM-VERSION 版本及关系

D覆盖同文档讨论及形成操作；F覆盖主线实体、焦点、关联、评估或处置的实际变化；V仅因真实正文变化。每事务D／F各至多加1，多事件共享前后版本。Goal实质变化加目标版本；步骤成果／依赖的实质变化加definition_version，纯展示改名／排序／生命周期变化不加定义版本。

唯一current_step_ref与步骤生命周期独立，IN_PROGRESS可有多个；历史已结束／放弃节点可为讨论目标。活动支线必须OPEN且return为current。仅Issue和Branch都OPEN时，其处理步骤必须相同；非OPEN支线可保留历史返回点，恢复为OPEN前重新核对所有关联OPEN问题。

<a id="shr-form-transaction"></a>
#### SHR-FORM-TRANSACTION 并发、幂等与未知结果

所有新写加入原需求进程锁、原实际数据库连接及短写事务。成功回执查找先于新状态检查，同key异规范化输入拒绝；PROCESSING沿原认领／所有权核实，不能双执行。新FORMATION能力只保存本次成功结果，不借用V2.0代码任务专用REJECTED／CLOSED命令分支。

同文档D比较、业务校验、实体／关系／消息／审计／回执提交原子完成。零行CAS更新是冲突，不伪造成功。内容变化与全部受影响关联维护同事务；外部模型调用不在事务中。CommitOutcomeUnknown保留原method／path／body／key查证，不能断言回滚或改变body重发；成功后读取失败只读刷新。新幂等能力身份及输入规范化在6.1固定。

<a id="shr-form-target"></a>
#### SHR-FORM-TARGET 焦点与恢复意图

目标为step_ref及可空branch_ref；支线进入核实实际return，查看不改目标。RESUME是绑定原支线state_event_ref及原状态的待消费动作，不是持久模式。原生恢复或包含恢复的DISCUSS接受成功后消费意图；刷新仍OPEN时后续请求用ENTER。模型失败不撤销已提交恢复；UNKNOWN只查原命令；后续新结果／暂缓不能被旧意图清除。

普通暂停／结束非当前节点保持当前步骤与活动支线；作用当前节点才清匹配焦点。明确next_step_ref是新的用户目标选择，同事务定位并清不匹配活动支线，不处置支线；前端同步下一轮目标且保留输入／草稿。取消当前节点同样清理匹配焦点，其他节点不隐式暂停。

<a id="shr-form-budget"></a>
#### SHR-FORM-BUDGET 单次边界与历史增长

| 参数 | 本设计选择与适用范围 |
| --- | --- |
| page_size | 缺省20，最大100，适用于实体／关系／事件／提案页；不表示实体总量上限 |
| change_batch | 单次路线调整或AI changes最多20项，canonical UTF-8最多64KiB；超限整批拒绝 |
| per_step_results | 单步预期成果最多20项；复杂工作拆步，不按文档历史总数限制作业 |
| HTTP | 复用现有完整请求8MiB边界，包括URI／头／体，不仅Content-Length |
| 模型输入／输出 | 采用冻结ModelProfile、资源预算和真实计数，不能以字符估算；参数不可由模型覆盖 |

以上是目标协议参数，尚无运行性能通过证据。实体／历史无累计200／1000／2000门槛，当前值与历史分记录、关系分页。事件成员及结束证据同样按单项行保存，不能借外层分页内嵌全量数组。预算约束本次操作或材料，不迫使用户另建文档；不删历史、不截断半批、不为凑预算自动完成。服务存储不足保持数据并明确扩容／恢复。

### 2.3 运行配置与生命周期

| 配置／事项 | 来源、有效期与无效处理 |
| --- | --- |
| 数据库／资源根 | 原Runtime及实际发布清单；启动固定源Schema／资源摘要，未知版本拒绝写入，不自动迁移 |
| 模型配置／凭据 | 原ModelProfile的已批准配置解析器；快照保留参数及版本，秘密仅运行时解析，不入Wire／日志／公开DTO |
| 新发布标识 | 目标逻辑release为formation_v21_1，layout为formation_context_v21_1；实际目录及数据库数值版本在发布清单分配，不能占用未核实序号 |
| 安装／构建 | 保留锁文件；文档输出不触发安装、构建或新资源准入 |
| 启动／就绪 | 原后端正常入口；结构／来源／新资源无有效准入时新AI动作CONFIG_INVALID，既有可核实只读／原生能力按实际依赖显示 |
| 关闭／异常恢复 | 原Worker／执行租约释放与终态核实；用户离开页面不停止业务，旧成功回执可查，未知不重放为新调用 |
| 动态修改 | Profile／资源变更只影响新运行；在途使用冻结快照，历史按原版本读 |

## 3. 业务对象

本章定义逻辑字段；集合可为关系查询集合，公开读取用6.2的有界投影，不要求把逻辑聚合完整序列化。对象是否存在、权限和跨对象状态由第4章在真实连接核实。

<a id="obj-form-form"></a>
### OBJ-FORM-FORM FormationState

#### 3.1 对象说明

| 内容 | 定义 |
| --- | --- |
| 业务含义 | 同文档形成聚合的逻辑头部；管理Goal、讨论焦点及编号高水位 |
| 身份规则 | document_id唯一，仅CURRENT文档；不存在头部表示未建线 |
| 所属与共享 | 同一文档逻辑聚合的成员或值对象；跨模块共享定义，不共享可变实例 |

#### 3.2 字段与对象约束

| 字段路径 | 逻辑类型 | 业务含义 | 可空 | 对象默认值 | 规则 |
| --- | --- | --- | --- | --- | --- |
| document_id | ID | 所属正式工作文档 | 否 | 无 | 引用原CURRENT |
| version | Version | F | 否 | 无 | 首次有效建线1；实际变化递增 |
| goal | Goal | 目标值对象 | 否 | 无 | version、text:Text、source_refs:SourceRef[]；目标实质改变须用户采用 |
| current_step_ref | StepRef | 当前讨论步骤 | 是 | null | 同文档现有节点，允许历史 |
| active_branch_ref | BranchRef | 当前支线 | 是 | null | OPEN且return=current |
| counters | Counters | 下一个局部编号 | 否 | 无 | next_step_no／next_branch_no／next_issue_no／next_artifact_no:ID |
| steps／branches／issues／artifacts | 关系集合 | 逻辑成员 | 否 | 空集合 | 分别持久化，不内嵌终身全量JSON |

#### 3.3 关系与状态

头部可无当前焦点但不丢身份或历史；全部节点放弃不重置为无主线。

#### 3.4 对象操作约束

成功构造或变更后的对象必须满足本条字段／关系及SHR-FORM-VERSION；执行者与其他对象的操作许可由对应APP判断，不以对象解析代替存在性／权限校验。历史成员不物理删除，真实正文来源不可改写。

#### 3.5 存储与实现定位

formation_heads；成员表及原文档D；仓储目标formation_repository.py。表分拆只服务当前对象，不创建平行根。

<a id="obj-form-step"></a>
### OBJ-FORM-STEP Step／ExpectedResult

#### 3.1 对象说明

| 内容 | 定义 |
| --- | --- |
| 业务含义 | 按成果组织的动态步骤 |
| 身份规则 | step_ref在所属document_id内唯一；result_ref在该步骤内唯一 |
| 所属与共享 | 同一文档逻辑聚合的成员或值对象；跨模块共享定义，不共享可变实例 |

#### 3.2 字段与对象约束

| 字段路径 | 逻辑类型 | 业务含义 | 可空 | 对象默认值 | 规则 |
| --- | --- | --- | --- | --- | --- |
| step_ref／definition_version | StepRef／Version | 步骤身份与定义版本 | 否 | 无 | 新步骤真实身份／定义1由程序分配 |
| title | Title | 步骤标题 | 否 | 无 | 展示修正不机械使定义陈旧 |
| expected_results | ExpectedResult[] | 成果要求 | 否 | 无 | 1—20；每项result_ref、description:Text、kind:CONTENT或ANALYSIS |
| next_result_no | ID | 下一个结果序号 | 否 | 无 | 程序分配，不复用 |
| status | StepStatus | 实际生命周期 | 否 | 无 | PLANNED／IN_PROGRESS／PAUSED／COMPLETED／CANCELLED |
| dependencies／replaces_step_refs | StepRef关系集合 | 当前前置／替代来源 | 否 | 空集合 | 依赖及替代分别无环；当前依赖不悬空 |
| topic_refs／issue_refs／artifact_refs | 关系集合 | 主题、问题及内容关系 | 否 | 空集合 | 旧topic不是形成步骤；问题双向一致 |
| assessment／recommendation | Assessment／Recommendation | AI判断与建议 | 是 | null | 仅实际已读依据；不改生命周期 |
| closure_event_ref | EventID | 当前结束记录入口 | 是 | null | 重开后旧记录仍在历史，当前开放不冒充已结束 |

#### 3.3 关系与状态

首步自动开始；普通选中不开始；开始／暂停／恢复／结束／重开按APP-FORM-NATIVE。取消保留身份并只走完整路线调整。

#### 3.4 对象操作约束

成功构造或变更后的对象必须满足本条字段／关系及SHR-FORM-VERSION；执行者与其他对象的操作许可由对应APP判断，不以对象解析代替存在性／权限校验。历史成员不物理删除，真实正文来源不可改写。

#### 3.5 存储与实现定位

formation_steps、formation_results、formation_step_edges、formation_step_topics；评估与事件独立。表分拆只服务当前对象，不创建平行根。

<a id="obj-form-branch"></a>
### OBJ-FORM-BRANCH Branch

#### 3.1 对象说明

| 内容 | 定义 |
| --- | --- |
| 业务含义 | 需要独立跟踪的讨论问题 |
| 身份规则 | branch_ref同文档唯一，origin来源创建后不变 |
| 所属与共享 | 同一文档逻辑聚合的成员或值对象；跨模块共享定义，不共享可变实例 |

#### 3.2 字段与对象约束

| 字段路径 | 逻辑类型 | 业务含义 | 可空 | 对象默认值 | 规则 |
| --- | --- | --- | --- | --- | --- |
| branch_ref | BranchRef | 支线身份 | 否 | 无 | 程序分配 |
| origin_step_ref／origin_event_ref | StepRef／EventID | 最初来源与触发事件 | 否 | 无 | 历史身份可指已放弃节点，不改挂 |
| return_step_ref | StepRef | 当前处理／返回步骤 | 否 | 无 | OPEN须为同文档未放弃步骤；可已结束 |
| question／relevance | Text | 问题及对主线影响 | 否 | 无 | 同问题复用，不能改问题抹去旧事实 |
| status | BranchStatus | 处理状态 | 否 | 无 | OPEN／RESOLVED／DEFERRED／DROPPED |
| topic_refs | TopicRef关系集合 | 相关主题 | 否 | 空集合 | 同文档有效引用 |
| result_summary | Text | 本轮已形成结果 | 是 | null | RESOLVED必须非空 |
| result_source_refs | SourceRef[] | 本轮结果依据 | 否 | 空集合 | RESOLVED须有真实结果来源 |
| disposition_event_ref | EventID | 当前用户处置 | 是 | null | DEFERRED／DROPPED必须真实用户依据 |
| state_event_ref | EventID | 最近处理状态／结果变化事件 | 否 | 无 | 程序维护，作为恢复基准；纯查看／焦点不改 |

#### 3.3 关系与状态

明确恢复DEFERRED／RESOLVED为OPEN，旧结果／处置保留历史，当前结果清空；OPEN不重复恢复；DROPPED重新提出新身份。进入不重开父步骤。

#### 3.4 对象操作约束

成功构造或变更后的对象必须满足本条字段／关系及SHR-FORM-VERSION；执行者与其他对象的操作许可由对应APP判断，不以对象解析代替存在性／权限校验。历史成员不物理删除，真实正文来源不可改写。

#### 3.5 存储与实现定位

formation_branches、formation_branch_topics；旧结果来自不可变审计／变化记录。表分拆只服务当前对象，不创建平行根。

<a id="obj-form-issue"></a>
### OBJ-FORM-ISSUE Issue

#### 3.1 对象说明

| 内容 | 定义 |
| --- | --- |
| 业务含义 | 步骤下需解决或明确保留的问题 |
| 身份规则 | issue_ref同文档唯一 |
| 所属与共享 | 同一文档逻辑聚合的成员或值对象；跨模块共享定义，不共享可变实例 |

#### 3.2 字段与对象约束

| 字段路径 | 逻辑类型 | 业务含义 | 可空 | 对象默认值 | 规则 |
| --- | --- | --- | --- | --- | --- |
| issue_ref／step_ref | IssueRef／StepRef | 身份与当前归属 | 否 | 无 | 同文档；移动保持原source_refs |
| branch_ref | BranchRef | 关联讨论支线 | 是 | null | 两者都OPEN时step等于branch.return |
| description／source_refs | Text／SourceRef[] | 问题与最初依据 | 否 | 无 | 须真实来源，保留原始记录 |
| blocking | boolean | 对成果的影响判断 | 否 | 无 | 不自动锁住需求或结束动作 |
| disposition | IssueStatus | 解决／处置状态 | 否 | 无 | OPEN／RESOLVED／DEFERRED／DROPPED |
| reason | Text | 当前暂缓／放弃原因 | 是 | null | 相关用户决定非空，恢复后当前置空 |
| resolution_source_refs | SourceRef[] | 真实解决依据 | 否 | 空集合 | 不能仅模型宣称已解决 |
| disposition_event_ref | EventID | 当前处置来源 | 是 | null | 恢复置空，旧事件保留 |

#### 3.3 关系与状态

仅用户明确RESUME_ISSUE使DEFERRED到OPEN；不顺带恢复支线／重开父步骤。相关非OPEN支线保留历史返回点不阻止独立恢复。

#### 3.4 对象操作约束

成功构造或变更后的对象必须满足本条字段／关系及SHR-FORM-VERSION；执行者与其他对象的操作许可由对应APP判断，不以对象解析代替存在性／权限校验。历史成员不物理删除，真实正文来源不可改写。

#### 3.5 存储与实现定位

formation_issues；与Step问题关系从同一外键派生，避免两份可写列表。表分拆只服务当前对象，不创建平行根。

<a id="obj-form-artifact"></a>
### OBJ-FORM-ARTIFACT ArtifactLink

#### 3.1 对象说明

| 内容 | 定义 |
| --- | --- |
| 业务含义 | 成果要求与真实内容的来源及当前匹配 |
| 身份规则 | artifact_ref同文档唯一；同一内容可支持多个结果，不重复算写入 |
| 所属与共享 | 同一文档逻辑聚合的成员或值对象；跨模块共享定义，不共享可变实例 |

#### 3.2 字段与对象约束

| 字段路径 | 逻辑类型 | 业务含义 | 可空 | 对象默认值 | 规则 |
| --- | --- | --- | --- | --- | --- |
| artifact_ref／step_ref／result_refs | ArtifactRef／StepRef／ResultRef集合 | 身份与受支持成果 | 否 | 无 | 至少一个同步骤成果，类型CONTENT |
| source_event_ref | EventID | 真实写入或已有内容关联事件 | 否 | 无 | 不伪造本轮写入 |
| origin_revision_id／origin_block_ids | RevisionID／BlockID关系集合 | 原始内容版本与范围 | 否 | 无 | 创建后不可改；原引用与范围保存 |
| origin_content_digest／summary | Digest／Short | 原内容摘要与说明 | 否 | 无 | 程序基于真实已读内容构造 |
| checked_against_revision_id | RevisionID | 最近核实的当前版本 | 否 | 无 | 不是AI已审全文的证明 |
| current_block_ids | BlockID关系集合 | 当前可证明匹配范围 | 否 | 空集合 | 按真实身份与来源验证 |
| freshness | ArtifactFreshness | 当前可追溯匹配 | 否 | 无 | 唯一闭集CURRENT／NEEDS_REVIEW／REMOVED |
| review_reason | CHANGED／UNVERIFIABLE | 待复核的程序原因 | 是 | null | 仅NEEDS_REVIEW时必非空；其他状态必为null |

#### 3.3 关系与状态

CURRENT只证明内容仍可追溯；程序成功核实为CURRENT时review_reason清为null，确认REMOVED亦为空；部分变化或无法证明对应则NEEDS_REVIEW，全部消失REMOVED。新内容需新关联时保留原记录，不靠相似文本复活ID。

#### 3.4 对象操作约束

成功构造或变更后的对象必须满足本条字段／关系及SHR-FORM-VERSION；执行者与其他对象的操作许可由对应APP判断，不以对象解析代替存在性／权限校验。历史成员不物理删除，真实正文来源不可改写。

#### 3.5 存储与实现定位

formation_artifacts、formation_artifact_ranges（ORIGIN／CURRENT分开）；content.py共享提交维护。表分拆只服务当前对象，不创建平行根。

<a id="obj-form-assess"></a>
### OBJ-FORM-ASSESS Assessment／Recommendation

#### 3.1 对象说明

| 内容 | 定义 |
| --- | --- |
| 业务含义 | AI对实际成果的判断及建议值对象 |
| 身份规则 | 身份为所属步骤＋真实assistant_message_id／事件，不覆盖历史 |
| 所属与共享 | 同一文档逻辑聚合的成员或值对象；跨模块共享定义，不共享可变实例 |

#### 3.2 字段与对象约束

| 字段路径 | 逻辑类型 | 业务含义 | 可空 | 对象默认值 | 规则 |
| --- | --- | --- | --- | --- | --- |
| verdict／reason | AssessmentVerdict／Text | 充分性结论与依据 | 否 | 无 | SUFFICIENT／GAPS_REMAIN／UNCERTAIN |
| goal_version／evaluated_step_version | Version | 实际评估定义 | 否 | 无 | 程序绑定冻结依据 |
| evaluated_revision_id／coverage_block_ids | RevisionID／BlockID集合 | 已读取正文覆盖 | 否 | 无 | 不能扩大未发送材料范围 |
| source_refs／assistant_message_id | SourceRef[]／MessageID | 真实回答依据 | 否 | 无 | 别名解析后保存 |
| recommendation.action／step_ref／reason／source_refs | 枚举／StepRef?／Text／SourceRef[] | 建议下一步 | step_ref是 | 无 | DISCUSS／WRITE／RESOLVE_BRANCH／REVIEW_CONTENT／COMPLETE_STEP／SWITCH_STEP／NEED_MATERIAL |
| recommendation.basis | RecommendationBasis | 程序绑定的建议依据 | 否 | 无 | 从真实接受上下文／结果材料生成，模型不可提交；读取validity／stale_reason是派生值，原basis不改 |

#### 3.3 关系与状态

当前性是读取投影；目标／定义／实际覆盖范围或其内容改变则陈旧，原评估保留。不自动完成、写入或重开。AssessmentVerdict在模型、对象、存储和公开DTO统一为SUFFICIENT／GAPS_REMAIN／UNCERTAIN。assessment=null唯一表示从未评估；有评估但材料不足为UNCERTAIN，不使用UNASSESSED。公开AssessmentView.validity为CURRENT或STALE，由当前Goal／步骤定义与覆盖区块身份及摘要比较得出；无关区块变化不单独使其陈旧，旧evaluated_revision_id不重写。

#### 3.4 对象操作约束

成功构造或变更后的对象必须满足本条字段／关系及SHR-FORM-VERSION；执行者与其他对象的操作许可由对应APP判断，不以对象解析代替存在性／权限校验。历史成员不物理删除，真实正文来源不可改写。

#### 3.5 存储与实现定位

formation_assessments／formation_recommendations；消息与事件为不可变来源。表分拆只服务当前对象，不创建平行根。

<a id="obj-form-proposal"></a>
### OBJ-FORM-PROPOSAL WriteProposal／PathProposal

#### 3.1 对象说明

| 内容 | 定义 |
| --- | --- |
| 业务含义 | 不可变消息内的精确提案值对象 |
| 身份规则 | CardRef={message_id:ID,card_key:string}，同组单卡 |
| 所属与共享 | 同一文档逻辑聚合的成员或值对象；跨模块共享定义，不共享可变实例 |

#### 3.2 字段与对象约束

| 字段路径 | 逻辑类型 | 业务含义 | 可空 | 对象默认值 | 规则 |
| --- | --- | --- | --- | --- | --- |
| schema_version／document_id | 整数1／ID | 提案布局与所属 | 否 | 无 | 新release解释，旧卡不原地升级 |
| purpose | STAGED_WRITE／FORMATION_PATH_CHANGE | 卡片用途 | 否 | 无 | 仅对应write或path联合，不能同时携带两种payload |
| write.step_ref／definition_version／goal_version／result_refs | 步骤及定义引用 | 写入用途 | 否 | 无 | 与实际已读步骤／成果匹配 |
| write.document_revision_id／content_version | RevisionID／Version | 精确原文依据 | 否 | 无 | 正文变化需重新准备 |
| write.write_mode／scope | WriteMode／Scope | 空白首写或精确补丁范围 | 否 | 无 | FILL_EMPTY或PATCH_EXISTING |
| write.markdown_content／patches | Markdown?／Patch[] | 精确采用内容 | markdown是 | 无 | 空白首写带Markdown及[]；补丁写入Markdown=null，patches非空 |
| path.basis／changes／result_routes | VersionBasis／PathChange[]／ResultRoute[] | 路线调整及旧成果去向 | 否 | 无 | 同一批完整映射、20项／64KiB |
| source_refs／change_summary | SourceRef[]／Text | 真实来源与影响摘要 | 否 | 无 | 摘要不能代替精确内容 |
| disposition／needs_revision／can_apply／reasons | 派生投影 | 真实处置与当前可用性 | 否 | 无 | 由原卡及事件重建；不写回原payload |

#### 3.3 关系与状态

新内容创建新卡；只有新卡保存成功才替代旧卡。暂缓不消费正式回答，NO_CHANGE也有真实消费。私有binding是技术证据，不是模型可填对象。

#### 3.4 对象操作约束

成功构造或变更后的对象必须满足本条字段／关系及SHR-FORM-VERSION；执行者与其他对象的操作许可由对应APP判断，不以对象解析代替存在性／权限校验。历史成员不物理删除，真实正文来源不可改写。

#### 3.5 存储与实现定位

原conversation_messages；formation_proposal_index中的处置投影可据审计重建；binding_json是原卡权威的不可变PublicationBinding，不从摘要或当前数据重建，审计保存其摘要供核实。表分拆只服务当前对象，不创建平行根。

<a id="obj-form-event"></a>
### OBJ-FORM-EVENT FormationEvent／Closure

#### 3.1 对象说明

| 内容 | 定义 |
| --- | --- |
| 业务含义 | 不可变业务变化与用户结束时的真实快照 |
| 身份规则 | 复用document_change_audits.id；Closure以结束event_id唯一 |
| 所属与共享 | 同一文档逻辑聚合的成员或值对象；跨模块共享定义，不共享可变实例 |

#### 3.2 字段与对象约束

| 字段路径 | 逻辑类型 | 业务含义 | 可空 | 对象默认值 | 规则 |
| --- | --- | --- | --- | --- | --- |
| schema／event_id／document_id | formation_event_v1／EventID／ID | 版本化域与所属 | 否 | 无 | 原审计event_type=DISCUSSION_UPDATED，不随意扩旧枚举 |
| batch_ref／ordinal／batch_size | ID／正整数 | 同事务事件批次 | 否 | 无 | 顺序与数量一致，共享D／F／V |
| actor／action／reason | Actor(USER/AI/PROGRAM)／Action／Text | 真实变化责任 | 否 | 无 | 程序填时间及身份，恢复事件有真实用户依据 |
| related_refs／source_refs | Ref集合／SourceRef[] | 对象与触发材料 | 否 | 空集合 | 正式历史无临时身份 |
| version_before／version_after | VersionBasis | 事务前后版本 | 否 | 无 | D／F／V各按真实变化计算 |
| changes | EntityChange集合 | 受影响记录前后值 | 否 | 空集合 | 每项有真实entity_kind／identity／before／after，不能双空 |
| closure | ClosureHead | 结束事实头部 | 是 | null | 仅用户COMPLETE有；含step_ref、definition／goal／revision、command_message_id、next_step_ref、各类item_count及digest |
| created_at | UTC | 事件时间 | 否 | 无 | 程序时钟 |

#### 3.3 关系与状态

Closure项按RESULT／ISSUE／BRANCH独立行保存，证据／区块／来源按formation_closure_evidence逐行冻结；未写或不能核实OUTSTANDING，未明确处置KEEP_OPEN；已结束后补写／重开不回写旧Closure。不可变前后快照和大量明细分记录，不要求塞一条巨型JSON。

#### 3.4 对象操作约束

成功构造或变更后的对象必须满足本条字段／关系及SHR-FORM-VERSION；执行者与其他对象的操作许可由对应APP判断，不以对象解析代替存在性／权限校验。历史成员不物理删除，真实正文来源不可改写。

#### 3.5 存储与实现定位

原audit＋formation_event_changes／formation_event_refs／formation_closures／formation_closure_items，详7.1。表分拆只服务当前对象，不创建平行根。

## 4. 应用能力

本章内部输入已解析为第6章命名结构；HTTP位置由入口绑定。共有写入顺序为：成功幂等回执重放→需求锁／真实连接→D及占用→归属和对象／来源→内存或同连接准备→原子提交；采用SHR-FORM-TRANSACTION。查询无写入、无模型。

<a id="app-form-read"></a>
### APP-FORM-READ 读取主线、关系、事件及提案

#### 4.1 能力说明

| 内容 | 定义 |
| --- | --- |
| 处理目标 | 读取主线、关系、事件及提案 |
| 主要对象 | OBJ-FORM-FORM及所有成员 |
| 完成方式 | 同步只读；单页完成，不宣称已加载全部 |

#### 4.2 输入与来源

| 输入 | 类型 | 来源及用途 | 必传 | 可空 | 缺失／校验 |
| --- | --- | --- | --- | --- | --- |
| document_id | ID | 调用者明确选文档 | 是 | 否 | 真实同需求CURRENT |
| query | PageQuery | 页面／历史过滤 | 否 | 否 | 缺省由6.2唯一规定；未知参数拒绝 |
| known_f | Version | 跨页固定当前状态 | 否 | 否 | 无值开始新快照，有值须仍匹配 |

#### 4.3 处理过程

| 步骤 | 处理与变化 | 规则／调用 | 失败或后续 |
| --- | --- | --- | --- |
| 定位 | 核实文档归属，区分无主线与状态损坏；仅Summary无头部返回exists=false，不制造F0；/formation/*各实体／关系／事件／范围读取须有真实头部，无头部返回409 STATE_CONFLICT／FORMATION_NOT_INITIALIZED | OBJ-FORM-FORM | 损坏失败，不能伪造空路线 |
| 查询 | 同一读事务取头部F、筛选记录和完整总数，按游标稳定排序；按页取相关事件／关联摘要 | INF-FORM-STORE／SHR-FORM-PAGE | 页外引用返回未加载，不错误删除 |
| 返回 | 构造Summary／EntityPage／EventPage／ProposalPage／ClosureItemPage／ClosureEvidencePage／MemberChangePage／RangePage／LineagePage或单节点详情；公开字段排除私有basis | DTO-READ | 纯读取，不改焦点或计数 |

#### 4.4 结果与完成范围

| 结果 | 返回 | 可确认范围 |
| --- | --- | --- |
| FOUND／EMPTY | 相应命名读DTO | 仅本次明确覆盖；计数不是已加载条数 |
| NOT_FOUND／CONFLICT／INVALID | 安全错误 | 无业务变化；F变化重新读取页头 |

#### 4.5 关键执行要求

过滤条件与排序见SHR-FORM-PAGE；事件域／版本不认识时返回不可解码原因，不以模型重构。

#### 4.6 查询补充

查询的AND过滤／排序／游标绑定／F冲突／完整总数见6.2 SHR-FORM-PAGE；读投影字段唯一来源为DTO-READ。文档不存在返回NOT_FOUND；文档存在但无主线仅Summary返回exists=false，直接读/formation/*返回STATE_CONFLICT／FORMATION_NOT_INITIALIZED；有主线时单节点不存在才NOT_FOUND；页空但total>0返回空页及稳定meta，不伪造无历史。

#### 4.8 实现定位

现有requirements/queries.py与新增目标formation_queries.py；数据库查询同连接批量加载。以上是目标接入位置，原生产调用必须实际连通后才能标已实现。

<a id="app-form-discuss"></a>
### APP-FORM-DISCUSS 接受并执行文档形成讨论

#### 4.1 能力说明

| 内容 | 定义 |
| --- | --- |
| 处理目标 | 接受并执行文档形成讨论 |
| 主要对象 | GuideRun、OBJ-FORM-FORM／STEP／BRANCH及原进展 |
| 完成方式 | 首次202仅接受；一次Worker请求完成后观察原运行／消息 |

#### 4.2 输入与来源

| 输入 | 类型 | 来源及用途 | 必传 | 可空 | 缺失／校验 |
| --- | --- | --- | --- | --- | --- |
| request | FormationDiscussInput | 用户明确发送 | 是 | 否 | 完整目标、instruction、D、proposal_ref／intent按6.2 |
| runtime | 实际Profile／catalog／执行租约 | 可信Runtime | 是 | 否 | 无新release准入则拒绝，不以旧LIVE放行 |
| operator／key | 原可信用户动作／幂等头 | HTTP上下文 | 是 | 否 | 不接受模型或客户端角色替代 |

#### 4.3 处理过程

| 步骤 | 处理与变化 | 规则／调用 | 失败或后续 |
| --- | --- | --- | --- |
| 接受 | 在原命令事务核实D／IDLE及目标。RESUME校验原branch_resume_basis，原子恢复并消费；仅选择不改生命周期，实际接受PLANNED／PAUSED讨论记开始／恢复 | SHR-FORM-TARGET／DTO-DISCUSS | 目标变更冲突保留输入，旧意图不恢复新结果 |
| 冻结 | 写用户消息／pending、原运行及完整目标／相关数据和来源清单；实际D／F各按变化一次，冻结接受后的依据；提交202回执 | 原accepted_context／GuideRun | 提交未知查原key，不另建运行 |
| 执行 | Worker核实租约，按4.7装配／计数／准入后一次Chat；不在数据库事务中调用 | INF-FORM-MODEL | 取消／超时原终态，输入可恢复 |
| 接收 | 先验证头部／operation／来源／进展／formation／新卡组成的整个结构单元，解析临时身份；全部合法后同事务保存消息、实体、卡／binding、事件和终态 | DTO-MODEL／APP-FORM-REVIEW | 任一非法结构不局部采用；保留合法可读文本和pending |
| 观察 | 本次回复归冻结目标，不抢前端下一轮目标；新运行重试由用户明确发起，已接受恢复不重复 | RoundResult | 模型结束与业务应用分开显示 |

#### 4.4 结果与完成范围

| 结果 | 返回 | 可确认范围 |
| --- | --- | --- |
| ACCEPTED | 原RunAccepted＋accepted_target | 输入／占用已保存，模型尚未完成 |
| APPLIED | RoundResult | 合法进展／主线／新卡结构已原子采用，正文无自动变化 |
| STRUCTURED_REJECTED | RoundResult及安全组件原因 | 可读回复存在，结构未应用；pending保留 |
| FAILED／CANCELLED／UNKNOWN | 原运行结果及已知组件事实 | 未虚构调用或应用成功，已提交接受事实不回滚 |

#### 4.5 关键执行要求

单运行至多一次Chat，模型修复／分类／重试0次；调用前取消不发送，发送后取消按真实网关结果核实且不接受失去租约的写入。执行租约沿既有机制，不新建后台编排。

<a id="ai-form-discuss"></a>
#### 4.7 AI任务：FORMATION_DISCUSS

| 内容 | 确定定义 |
| --- | --- |
| 目标与产物 | 当前文档形成讨论，产物为自然说明＋必要progress_delta／formation_delta／精确卡片，九根Output见DTO-MODEL |
| 采用方式 | 程序核验后应用普通维护／关联／评估；精确正文和重大路线仅存不可变卡，用户采用才执行 |
| Profile | 原ModelProfile冻结快照；任务不得覆盖模型、温度、上限、URL或凭据 |
| 请求数 | Chat最多1次，分类／摘要／输出修复／供应商自动重试0次；失败后新调用由用户明确发起 |
| 流式／工具 | 当前非流式，不对外转发供应方chunk，不开放工具循环或任意读库／写文档工具 |

**Prompt正式新增指令（编译进新release的system，不改变旧冻结资源）**

> 你在同份文档内协助形成成果。以CURRENT_REQUEST的明确目标与指令、已确认Goal及当前有效依据为准。DOCUMENTS是实际已保存内容，提案和历史回复是另列材料；不要把未应用或结构被拒绝的回复当正文。只根据实际提供的引用与覆盖判断，缺材料时说明所需内容并给NEED_MATERIAL，不声称读过未提供全文。可以自由解释、比较方案并推荐，不必每轮出卡或改路线。普通解释和推进当前成果直接讨论；优先复用已有承接；相关且需要独立跟踪才ADD_BRANCH，提供question、relevance、真实触发source和return，不确定时留在普通讨论。形成独立可用内容可给精确STAGED_WRITE，不能直接写正文；重大目标／取消／替代／要求变化给FORMATION_PATH_CHANGE，由用户采用。既定目标内有限维护按白名单delta提出，不能代用户结束、重开、暂缓、放弃或恢复。已有结果支线继续时以当前OPEN和历史上次结果分开判断。关联有效性由程序核实；你的充分性结论带真实覆盖，缺口如实保留，不强迫用户先全部满足才结束。引用仅用本轮别名，新对象仅用已声明TempRef；返回当前任务的严格九根Output，不把私有程序basis当可见或可填写内容。

system顺序为现有任务协议／输出格式／阶段指引与适用结构，随后追加以上formation职责约束；user只发送确定序列化Wire。用户正文／历史／检索材料用明确数据分区，不作为系统指令；不存在程序私有binding或凭据的模型角色消息。编译器按完整system、Wire与输出Schema摘要绑定准入，资源Prompt最终字节由发布物固定，不凭本文静态检查获得供应方准入。

| 上下文项 | 来源／顺序 | 采用范围 | 缺失或超限 |
| --- | --- | --- | --- |
| Goal／有效GLOBAL依据 | 接受事务，GOAL／PROJECT_POSITION | 真实用户决定与争议信息分开，不采用已撤销决定 | 必须项缺失不调用 |
| 当前请求与目标 | CURRENT_REQUEST | document／step／branch／恢复是否已消费、proposal_intent及输入 | 必须，禁止裁剪 |
| 当前成果与正文 | 同一冻结Revision，DOCUMENTS | 当前步骤及本轮指定范围的真实区块、覆盖FULL／PARTIAL | 必要范围不足则NEED_MATERIAL或调用前拒绝，不以标题当正文 |
| 相关步骤／问题／支线 | 关系查询，有界FORMATION | 当前必要定义、相关关系及已读评估，历史结果另列 | 不可把未加载对象当不存在或授权更新 |
| 长期依据／pending | 原discussion状态与真实来源 | 保留当前有效决定及尚未处理输入 | 不因近期窗口丢失 |
| 正在调整的卡 | 实际message_id＋card_key及不可变payload | 本轮明确调整时带精确内容与用户修正 | 版本／来源失配先说明，不暗改基准 |
| 近期历史／背景 | 原最近窗口与确定性顺序 | effect_state标记真实处理结果 | 先去重，再去可选历史，再去非当前可选背景 |

原8项计数及Prompt／用户／来源／模板／历史／总输入／输出／总预算门禁继续由现有计数链路及冻结resource定义；新formation材料按实际Wire分区参加同一次计数，不额外又算成第二份正文。完整八个具体计量文本序列沿`CollaborationContext.texts`及新release的固定对应表，发布前逐项校对，不能借计数API回执声称语义充分。必要材料仍超限停止在Chat前，保留用户输入及精确preflight理由。

输出先校验正常完成／JSON／九根／operation，再校验每个delta、卡片、别名与权限；禁止容错删字段凑合法对象或调用模型修复。ASSOCIATE_CONTENT的review_of与当前已读Artifact绑定，程序分MATCHED／REASSOCIATED／UNVERIFIED，不从模型判词构造成功事实。结果与审计保存失败不能把模型已返回说成业务已保存；按原提交已知或未知结果处理。

调用记录保留真实run／LLMUse／Profile／release／Prompt／output_schema／Canonical及Wire摘要、材料覆盖、计数尝试、发送状态、可取得用量和组件采用结果。未取得用量保持null；发送后不确定是UNKNOWN，不填0。凭据及隐藏推理不进入业务请求详情；审计前若无法安全保留真实依据则调用前拒绝。

#### 4.8 实现定位

guide/accepted_context.py、collaboration_context.py、progress_application.py及Worker真实调用方；未来formation增量分派共用校验。以上是目标接入位置，原生产调用必须实际连通后才能标已实现。

<a id="app-form-native"></a>
### APP-FORM-NATIVE 主线状态、焦点及恢复命令

#### 4.1 能力说明

| 内容 | 定义 |
| --- | --- |
| 处理目标 | 主线状态、焦点及恢复命令 |
| 主要对象 | OBJ-FORM-FORM／STEP／BRANCH／ISSUE／EVENT |
| 完成方式 | 同步PROGRAM；无LLMUse、无Chat |

#### 4.2 输入与来源

| 输入 | 类型 | 来源及用途 | 必传 | 可空 | 缺失／校验 |
| --- | --- | --- | --- | --- | --- |
| command | NativeRequest | 明确用户动作 | 是 | 否 | 15种严格联合，未知字段拒绝 |
| stored_state | 真实头部及目标／必要关联 | 同一数据库连接 | 是 | 否 | 不能以客户端已读数组代替全局状态 |

#### 4.3 处理过程

| 步骤 | 处理与变化 | 规则／调用 | 失败或后续 |
| --- | --- | --- | --- |
| 派发 | 按本章命令转移表校验前态／关联；恢复支线前核实所有关联OPEN问题；目标为非当前时不清其他焦点 | NativeCommand／SHR-FORM-TARGET | 状态冲突整批不写 |
| 准备 | 根据真实当前记录生成差异／新状态／Closure流式明细；完成请求空处置列表由程序补齐真实遗留 | OBJ-FORM-EVENT | 不伪造开始、解决或已落地 |
| 提交 | 保存实际USER TEXT操作来源、差异与审计、D／F、回执；纯无变化不制造消息／事件／版本 | ProgramReceipt／INF-FORM-STORE | 失败全回滚；Unknown查原动作 |

#### 4.4 结果与完成范围

| 结果 | 返回 | 可确认范围 |
| --- | --- | --- |
| APPLIED | ProgramReceipt | 一次实际状态变化已保存，V不变 |
| NO_CHANGE | ProgramReceipt | 已确认无需变化，无重复事件 |
| CONFLICT／INVALID | 安全错误 | 未执行，不把失败更新为成功处置 |

#### 4.5 关键执行要求

PAUSE与普通COMPLETE的target不要求是当前讨论节点；只有它等于事务前current时清匹配焦点。next_step_ref非空表达明确结束并继续，同事务转移并清不匹配支线；不是复用旧推荐自动跳转。

#### 4.8 实现定位

requirements/commands.py原discussion_command分派，新增目标formation_commands.py；原锁与idempotency。以上是目标接入位置，原生产调用必须实际连通后才能标已实现。

<a id="app-form-path"></a>
### APP-FORM-PATH 预览及保存完整路线调整

#### 4.1 能力说明

| 内容 | 定义 |
| --- | --- |
| 处理目标 | 预览及保存完整路线调整 |
| 主要对象 | OBJ-FORM-FORM／STEP／ISSUE／BRANCH／ARTIFACT |
| 完成方式 | 预览只读同步；保存同步原子PROGRAM |

#### 4.2 输入与来源

| 输入 | 类型 | 来源及用途 | 必传 | 可空 | 缺失／校验 |
| --- | --- | --- | --- | --- | --- |
| edit | PathEditInput | 人工编辑或不可变路线卡 | 是 | 否 | 来源不同但使用同一算法；原卡不能被客户端替换；可信内部入口区分MANUAL_EDIT与CARD_APPLY |
| mode | PREVIEW或COMMIT | 具体入口固定 | 是 | 否 | 客户端不能把预览标为已保存 |

#### 4.3 处理过程

| 步骤 | 处理与变化 | 规则／调用 | 失败或后续 |
| --- | --- | --- | --- |
| 准备 | 按入口策略核实版本：MANUAL_EDIT严格比较请求D/F/V；CARD_APPLY比较最新D、原V／Goal／定义及相关binding，不比较冻结F与当前F是否相等。先收集本批有类型的临时声明；识别改变Goal、取消／替代／成果要求的用户采用范围，计算完整去向与最终图 | PathChange／ResultRoute | 未声明／重复／跨文档引用拒绝 |
| 处置 | 取消步骤全部原成果各恰好REPLACED或NOT_REQUIRED，种类不可偷换；OPEN问题／支线及依赖去向完整。暂缓问题恢复按双OPEN一致性 | SHR-FORM-VERSION | 不能用隐藏节点替代真实迁移 |
| 预览 | 返回前后受影响步骤、成果映射、已有内容复用、问题／支线去向、将失效提案／评估、焦点影响及摘要 | PathPreview | 不分配正式ID、不写草稿、不消费卡，可在忙时读已提交快照 |
| 保存 | 在同一写事务按入口策略再次核实相同输入及当前版本／锁；分配真实身份，保存全部实体／关系／差异／原用户来源，必要原卡SUPERSEDED，D／F各一次；V不变 | APP-FORM-APPLY／ProgramReceipt | 任何失败全回滚；旧草稿不自动换基准重放 |

#### 4.4 结果与完成范围

| 结果 | 返回 | 可确认范围 |
| --- | --- | --- |
| PREVIEWED | PathPreview | 仅读，digest不能当授权 |
| APPLIED／NO_CHANGE | ProgramReceipt | 完整批次已保存或确实无变化，reference_map定位新身份 |
| CONFLICT／INVALID | 安全错误 | 保留原路线及输入，人工重新核对 |

#### 4.5 关键执行要求

入口策略由实际调用方固定，客户端不能提交mode或跳过校验标记：MANUAL_EDIT包括人工从原卡复制后修改的草稿，使用DTO-NATIVE.ADJUST_PATH对应的expected_formation_version及D/V严格CAS；based_on_proposal仅关联旧卡，不改变此策略。CARD_APPLY只能由responses adapter读取原卡，内部输入为{proposal_ref,expected_discussion_version,canonical_payload,private_binding}，后两项服务端读取，不能接受客户端传入。payload.basis.formation_version是历史来源，不充当expected_F；当前F仍在事务内读取并用于本次事件／版本CAS，相关实体摘要不匹配则拒绝。两入口在各自校验后共用最新真实图上的temp解析、成果承接、全局约束及保存算法；事务外预览的任何结论不能跳过事务内复核。

当前全局图必须真实核实；分页缺失不能当实体不存在。变更预览只展开影响集合；大图全局验证采用同连接的关系查询，不要求把所有历史送前端或模型。

#### 4.8 实现定位

新增目标formation_commands.py共用PathEdit算法，formation_repository.py图查询；不能给原卡另造状态机。以上是目标接入位置，原生产调用必须实际连通后才能标已实现。

<a id="app-form-apply"></a>
### APP-FORM-APPLY 程序采用精确写入或路线卡

#### 4.1 能力说明

| 内容 | 定义 |
| --- | --- |
| 处理目标 | 程序采用精确写入或路线卡 |
| 主要对象 | 原消息／CardRef及OBJ-FORM-PROPOSAL |
| 完成方式 | 同步PROGRAM；一次正式回答，不二次Chat |

#### 4.2 输入与来源

| 输入 | 类型 | 来源及用途 | 必传 | 可空 | 缺失／校验 |
| --- | --- | --- | --- | --- | --- |
| answer | CardApplyInput | 用户检查不可变卡后确认 | 是 | 否 | single apply，execution_selection=null；原message_id来自path |
| payload／binding | 原消息及程序绑定 | 服务端不可变存储 | 是 | 否 | 不从客户端重传正文或授权 |

#### 4.3 处理过程

| 步骤 | 处理与变化 | 规则／调用 | 失败或后续 |
| --- | --- | --- | --- |
| 查证 | 先重放成功回执，再核实原卡／组／purpose、未消费、当前D／占用和程序binding | SHR-FORM-TRANSACTION／ProposalBinding | 重复回答带原response_message_id，不二次应用 |
| 权限 | 核实当前V／Revision、Goal／受影响定义与来源及payload摘要。只变无关F不绝对拒绝；正文变更不静默重基 | SHR-FORM-BASIS | 用途或来源变更要求新准备 |
| 分派 | STAGED_WRITE从卡读取精确Markdown／补丁，建立本次CARD_RESPONSE窄授权，调用原commit_content；FORMATION_PATH_CHANGE由可信adapter调用APP-FORM-PATH的CARD_APPLY／COMMIT分支，不能伪装MANUAL_EDIT输入 | WritePayload／PathPayload | 两分支都不再生成文字 |
| 原子采用 | 同事务保存回答、正文／Revision（若有）、关联及失效维护、原卡处置、变化审计和回执；NO_CHANGE不造Revision | APP-FORM-CONTENT | 关闭／失败不消费回答，无半份联合状态 |

#### 4.4 结果与完成范围

| 结果 | 返回 | 可确认范围 |
| --- | --- | --- |
| APPLIED／NO_CHANGE | ProgramReceipt | 采用的精确内容与用户看到的预览一致；写入不结束节点 |
| ALREADY_ANSWERED | 原响应身份 | 可查看原结果 |
| CONFLICT／INVALID／UNKNOWN | 安全错误或传输未知 | 不改原payload，不隐式重试或补Chat |

#### 4.5 关键执行要求

原generate／revise主动任务及旧purpose保持原处理；新purpose先于原模型分派识别。不能创建假GuideRun或复用DISCUSS空写权限；原卡应用不新增长期占用状态。

#### 4.8 实现定位

guide/card_commands.py::submit、documents/content.py::commit_content及sources.py，新增CARD_RESPONSE受信路径。以上是目标接入位置，原生产调用必须实际连通后才能标已实现。

<a id="app-form-proposal"></a>
### APP-FORM-PROPOSAL 暂缓、恢复及撤回提案调整

#### 4.1 能力说明

| 内容 | 定义 |
| --- | --- |
| 处理目标 | 暂缓、恢复及撤回提案调整 |
| 主要对象 | OBJ-FORM-PROPOSAL及原消息／事件 |
| 完成方式 | 同步PROGRAM；调整请求的模型运行另由APP-FORM-DISCUSS接受 |

#### 4.2 输入与来源

| 输入 | 类型 | 来源及用途 | 必传 | 可空 | 缺失／校验 |
| --- | --- | --- | --- | --- | --- |
| command | ProposalCommand | 用户明确动作 | 是 | 否 | defer／resume仅STAGED_WRITE；withdraw两purpose |
| proposal | CardRef | 原目标 | 是 | 否 | 同文档未应用／未替代 |

#### 4.3 处理过程

| 步骤 | 处理与变化 | 规则／调用 | 失败或后续 |
| --- | --- | --- | --- |
| 检查 | DEFER仅PENDING到DEFERRED，RESUME仅DEFERRED且用途／原文仍适用到PENDING；不消费apply | ProposalView | 失效说明原因，不自动重新生成 |
| 撤回 | 仅needs_revision且用途／相关basis仍匹配；按原PublicationBinding重算受保护语义摘要；相同才清标记并保存WithdrawalCheckProof及事件。原payload／PublicationBinding始终不改，不产生替代执行binding | ProposalBasis | 不同真实用途不能借撤回隐藏重基 |
| 保存 | 本次真实处置／WithdrawalCheckProof、D／F、用户来源和回执同事务；纯无变化不造事件 | ProgramReceipt | Unknown只查原动作 |

#### 4.4 结果与完成范围

| 结果 | 返回 | 可确认范围 |
| --- | --- | --- |
| APPLIED／NO_CHANGE | ProgramReceipt | 处置或标记保存，无正式回答消费 |
| CONFLICT／INVALID | 安全错误 | 原记录及输入保留 |

#### 4.5 关键执行要求

打开输入并不使旧提案needs_revision；只有关联原卡的调整DISCUSS实际接受时才禁用旧卡。调整失败保留旧卡；新卡成功保存后才替代。

#### 4.8 实现定位

原card_commands及新增formation_commands共用proposal投影；原消息不可改写。以上是目标接入位置，原生产调用必须实际连通后才能标已实现。

<a id="app-form-content"></a>
### APP-FORM-CONTENT 真实内容提交时维护全部受影响成果

#### 4.1 能力说明

| 内容 | 定义 |
| --- | --- |
| 处理目标 | 真实内容提交时维护全部受影响成果 |
| 主要对象 | 原Document／Revision和OBJ-FORM-ARTIFACT |
| 完成方式 | 内部同步，加入正文调用者同一事务，无独立HTTP |

#### 4.2 输入与来源

| 输入 | 类型 | 来源及用途 | 必传 | 可空 | 缺失／校验 |
| --- | --- | --- | --- | --- | --- |
| prior／candidate／source | 原快照、实际候选及受信来源 | commit_content已核实数据 | 是 | 否 | 不得客户端自填BlockState或伪造source |
| connection | 持有实际内容写事务 | 原调用方 | 是 | 否 | 禁止内部commit或异步补关联 |

#### 4.3 处理过程

| 步骤 | 处理与变化 | 规则／调用 | 失败或后续 |
| --- | --- | --- | --- |
| 定位 | 按真实修改／删除／分拆／合并区块查询所有受影响关联，包括历史已结束节点；无关区域不全失效 | formation_artifact_ranges | 没有主线时不为了维护而建线 |
| 匹配 | 真实身份及原范围仍可证明对应则CURRENT并更新checked_revision；部分改变／无法证明则NEEDS_REVIEW，全部消失REMOVED；恢复相同文本不复活旧ID | OBJ-FORM-ARTIFACT | 无法核实保守待复核 |
| 保存 | 按实际差异维护当前范围和状态／D／F／PROGRAM事件，与正文／Revision一起提交；批量流式处理，不逐条HTTP | SHR-FORM-TRANSACTION | 关联维护失败正文一起回滚，不先成功后漏记 |

#### 4.4 结果与完成范围

| 结果 | 返回 | 可确认范围 |
| --- | --- | --- |
| MAINTAINED | 受影响计数／真实事件映射 | 只完成程序追溯维护，不声称AI语义复核 |
| UNCHANGED | 无差异 | 不制造F或复核事件 |
| INVALID／UNKNOWN | 调用者原结果 | 不返回独立假成功 |

#### 4.5 关键执行要求

手工保存、原REVISE、候选应用、历史恢复、新卡应用全部接此hook；原显式正文主结果不因模型讨论结构无效丢弃，但强制匹配维护必须随已授权正文真实提交。

#### 4.8 实现定位

documents/content.py共享链路及新增目标formation_repository.py，不能仅新按钮接入。以上是目标接入位置，原生产调用必须实际连通后才能标已实现。

<a id="app-form-review"></a>
### APP-FORM-REVIEW 相关正常讨论中核实成果关联与AI充分性

#### 4.1 能力说明

| 内容 | 定义 |
| --- | --- |
| 处理目标 | 相关正常讨论中核实成果关联与AI充分性 |
| 主要对象 | OBJ-FORM-ARTIFACT／ASSESS及原已读正文 |
| 完成方式 | 作为正常DISCUSS结构单元的一部分，无额外Chat或正文写入 |

#### 4.2 输入与来源

| 输入 | 类型 | 来源及用途 | 必传 | 可空 | 缺失／校验 |
| --- | --- | --- | --- | --- | --- |
| association_candidates | ASSOCIATE_CONTENT变化 | 本轮模型建议 | 否 | 否 | review_of可空，非空指已读旧Artifact；document_refs仅真实材料别名 |
| assessment | ASSESS_STEP变化 | 本轮模型判断 | 否 | 否 | 绑定Goal／定义／Revision／coverage |

#### 4.3 处理过程

| 步骤 | 处理与变化 | 规则／调用 | 失败或后续 |
| --- | --- | --- | --- |
| 覆盖 | 只在本轮涉及成果且实际材料覆盖足够时准备核实；无关讨论不清旧标记 | FrozenMaterial／OBJ-FORM-ASSESS | 不足保留NEEDS_REVIEW或UNCERTAIN |
| 来源 | 程序解析同文档Revision及真实区块；沿原身份可证明关联则更新当前匹配，需新身份则创建新关联及不可变REASSOCIATED关系，不改旧origin | ArtifactReview | 相似文本不是身份，不能伪造已落地 |
| 语义 | 保存AI verdict与实际覆盖；关联有效但有缺口单列，不拿SUFFICIENT覆盖程序无法核实 | Assessment | 不自动结束／重开／写正文 |
| 提交 | 与本次DISCUSS结构整体提交；无效一并拒绝。旧关联有明确替代后不再作为当前待复核项，历史仍可查 | Read DTO active／review_state | 不清旧历史或把新关联算新写入 |

#### 4.4 结果与完成范围

| 结果 | 返回 | 可确认范围 |
| --- | --- | --- |
| MATCHED／REASSOCIATED | ArtifactReview及相关评估 | 仅已核实当前关联，语义结论另列 |
| UNVERIFIED／REMOVED | 真实状态及原因 | 提示待复核或真实移除，不默认通过 |

#### 4.5 关键执行要求

review_of不能改挂步骤／成果要求；替代链同文档同实际用途且无环，且每个关联最多一个前驱、一个后继。仅当前无后继的链末端可复核；旧review_of不自动重定向到新节点。原Closure不回写，旧评估保留。

#### 4.8 实现定位

guide/progress_application.py的形成分派、来源别名解析与formation仓储；读后应用在真实提交时重验D／V。以上是目标接入位置，原生产调用必须实际连通后才能标已实现。

<a id="app-form-upgrade"></a>
### APP-FORM-UPGRADE 保留源数据的显式目标升级

#### 4.1 能力说明

| 内容 | 定义 |
| --- | --- |
| 处理目标 | 保留源数据的显式目标升级 |
| 主要对象 | 旧完整Schema／原文档与运行消息／新formation表 |
| 完成方式 | 显式维护；不是GET或正常启动副作用 |

#### 4.2 输入与来源

| 输入 | 类型 | 来源及用途 | 必传 | 可空 | 缺失／校验 |
| --- | --- | --- | --- | --- | --- |
| source_manifest／target_manifest | 固定摘要的源／目标发布描述 | 维护工具可信输入 | 是 | 否 | 源真实200／实际DDL，不能仅按版本整数假定一致 |
| source／target | 明确路径与源只读快照／全新目标 | 用户指定维护范围 | 是 | 否 | 拒绝覆盖既有目标或自动清库 |

#### 4.3 处理过程

| 步骤 | 处理与变化 | 规则／调用 | 失败或后续 |
| --- | --- | --- | --- |
| 前置 | 核对实际源DDL／资源／旧回执及无活动AI／人工／候选／未知写结果；原V2.0代码表／触发器纳入源清单 | INF-FORM-UPGRADE | 未知源或有在途工作拒绝，不替用户取消 |
| 复制 | 新建完整目标结构，保留原ID／Markdown／BlockState／JSON原字节／时间／运行／用量／审计／幂等，新增formation表初始无记录 | 7.1映射 | 失败保留源不动及可检查目标状态 |
| 核验 | 比较行数、关键字节摘要、归属／外键／高水位及旧回执；新Schema摘要记录真实目标 | 维护核验 | 失败不切服务 |
| 选择 | 输出明确可切换结论，用户另行选择更新服务；新库使用后的回退先保全新数据 | 原部署入口 | 不宣称无损双向回滚 |

#### 4.4 结果与完成范围

| 结果 | 返回 | 可确认范围 |
| --- | --- | --- |
| VERIFIED_TARGET | 维护Markdown／已核实目标标识 | 目标离线核验通过，不等于服务已切换或新模型准入 |
| REJECTED／FAILED | 安全诊断 | 源保留，不自动继续或丢弃用户数据 |

#### 4.5 关键执行要求

目标Schema数值及完整生成DDL归发布任务，附录A记录尚未分配的事实；本节不是执行维护授权。

#### 4.8 实现定位

V2.0 tools/db-v20.py与schema_v20_*实际维护链路做新目标适配；当前worktree缺这些实现，来源核对记录只读位置。以上是目标接入位置，原生产调用必须实际连通后才能标已实现。

<a id="native-transitions"></a>
### 原生命令的确定转移（APP-FORM-NATIVE）

| 动作 | 条件与实际变化 | 焦点／其他对象 |
| --- | --- | --- |
| START_STEP | PLANNED到IN_PROGRESS，记录真实开始 | 明确用户开始可定位目标；其他进行中不暂停 |
| PAUSE_STEP | 任一IN_PROGRESS到PAUSED | 仅目标为current才清匹配步骤／支线；非当前保持当前目标 |
| RESUME_STEP | PAUSED到IN_PROGRESS，用户明确恢复 | 可定位目标，不重写旧暂停历史 |
| SWITCH_STEP | 同文档存在步骤或明确null整份文档，生命周期不变 | 只选目标，可为历史节点；清不匹配支线，依赖不阻止 |
| COMPLETE_STEP | PLANNED／IN_PROGRESS／PAUSED到COMPLETED，真实Closure | 仅普通结束当前时清匹配焦点；有明确next才转移；无下一步不定稿 |
| REOPEN_STEP | COMPLETED到IN_PROGRESS，保留旧Closure／完成事件 | 不要求暂停另一节点；不自动改旧正文 |
| ADJUST_PATH | 委托APP-FORM-PATH完整算法 | 不另造简化取消入口 |
| ENTER_BRANCH | OPEN，传入step等于真实return且未放弃 | 原子选择处理步骤＋支线；不改父步骤状态 |
| RETURN_FROM_BRANCH | 目标是当前活动支线 | 清支线焦点，保持当前步骤及OPEN记录，不猜别的返回点 |
| DISPOSE_BRANCH | OPEN到用户明确DEFERRED或DROPPED，需原因 | 若其为活动支线清焦点，不改正文 |
| RESUME_BRANCH | DEFERRED或RESOLVED，expected_branch_status／expected_branch_event_id与当前一致；全部关联OPEN问题符合当前return | OPEN，记录RESUMED或REOPENED，当前结果清空、旧结果留历史；按enter_after_resume选择目标；意图成功消费 |
| RESUME_ISSUE | DEFERRED到OPEN，原归属有效或同批明确迁移；只有关联支线也OPEN才需归属一致 | 不恢复支线、不重开父步骤；OPEN同请求可NO_CHANGE，DROPPED不复活 |
| DEFER_WRITE_PROPOSAL | PENDING到DEFERRED，仅STAGED_WRITE | 不消费正式回答 |
| RESUME_WRITE_PROPOSAL | DEFERRED到PENDING，原用途及V仍匹配 | 不重新生成，不强制改步骤状态 |
| WITHDRAW_PROPOSAL_ADJUSTMENT | 未应用／替代且needs_revision，实际用途／依据仍相同 | 清标记及新增WithdrawalCheckProof事件；原发布绑定／原卡均不改 |

用户动作事件名采用6章唯一闭集：步骤使用STEP_STARTED／STEP_PAUSED／STEP_RESUMED／STEP_COMPLETED／STEP_REOPENED，焦点用DISCUSSION_STEP_SELECTED；支线用BRANCH_ENTERED／BRANCH_RETURNED／BRANCH_DISPOSITION_CHANGED／BRANCH_RESUMED／BRANCH_REOPENED。ADJUST_PATH按实际变化分别产生对应事件，不输出PATH_ADJUSTED或BRANCH_FOCUSED等未登记别名。USER actor来自明确动作；源ID、UTC、D／F／V由程序填。

<a id="path-operations"></a>
### 路线变化的确定处理（APP-FORM-PATH）

| type | 严格输入主体与语义 |
| --- | --- |
| SET_GOAL | text、source_refs；实质改变goal.version+1并使旧用途重新核对 |
| ADD_STEP | temp_step_ref、title、expected_results、dependencies、replaces_step_refs、before_step_ref；字段与6章唯一同名；仅COMMIT分配真实身份、PLANNED |
| RENAME_STEP | step_ref、title；仅展示变化不加definition_version |
| MOVE_STEP | step_ref、before_step_ref或null；末尾为null；不省略其他节点来隐式删除 |
| SET_DEPENDENCIES | step_ref、完整新dependencies；同文档／存在／无环，实质改变加定义版本 |
| UPDATE_RESULT | result_ref、description；保留kind与身份，不能借修改缩小已定范围；变类型用明确NOT_REQUIRED＋新要求 |
| ADD_RESULT | step_ref、temp_result_ref、description、kind；每步最终至少1且最多20，实际增加加定义版本 |
| CANCEL_STEP | step_ref、replacement_step_refs；仅未结束步骤，完整result_routes及问题／支线／依赖去向 |
| LINK_CONTENT | step_ref、result_refs、revision_id、block_ids；同文档当前真实内容，程序新建关联，V不变 |
| MOVE_ISSUE | issue_ref、to_step_ref；同身份／原来源，必要支线return同批明确调整 |
| SET_BRANCH_RETURN | branch_ref、return_step_ref；origin不变，不能单方面移动仍OPEN问题造成不一致 |
| DISPOSE_ISSUE | issue_ref、disposition=DEFERRED或DROPPED、reason；用户明确处置 |
| DISPOSE_BRANCH | branch_ref、disposition=DEFERRED或DROPPED、reason；保留来源／旧结果 |
| RESUME_ISSUE | issue_ref；采用同名原生动作规则，可与MOVE_ISSUE同批 |

result_routes每项为{from_result_ref,disposition:REPLACED或NOT_REQUIRED,target_result_refs,reason}，取消步骤全部原成果恰好一次；REPLACED至少一项目标，NOT_REQUIRED为空且说明原因。新目标先解析temp，正式事件无temp；同kind承接，不把要求承接当内容落地。用户不用输入数据库身份，只核对编辑器整理的方案；后端仍严格核实所有真实引用。


## 5. 页面职责与界面边界

### 5.1 共享呈现依据

后端返回状态事实、全局计数、来源可用性及操作可用原因。COMPLETED显示用户结束事实，SUFFICIENT显示AI判断，两者不得合成同一状态。业务焦点、页面查看选择及在途冻结目标是三个对象。页面和组件完整结构见[前端第5章](WALL-E.前端设计文档_V_2.1.md#5-页面与组件)，后端不定义像素或浏览器草稿。

### 5.2—5.6 页面／组件的服务责任

| 前端区域 | 本文数据与命令 | 服务保证 |
| --- | --- | --- |
| 进展面板／展开视图 | Summary、StepPage、StepDetail | 同快照计数、稳定身份、查看无副作用 |
| 路线编辑器 | PathPreview、ADJUST_PATH | 相同语义校验，预览不占编号、不写入 |
| 支线／问题详情 | EntityPage、NativeRequest | 来源与返回点独立；完整目标原子进入 |
| 精确写入卡／路线卡 | ProposalPage、原responses | 原精确内容、原因、用途依据；不从摘要再生成 |
| 成果及历史 | ArtifactPage、EventPage、ClosureItemPage | 原Revision／原结束事实保留；分页不冒充全部 |
| 对话输入与运行结果 | FormationDiscussInput、RunAccepted、RoundResult | 接受目标冻结，程序回执不冒充Chat或最新快照 |

## 6. 对外与内部交互契约

### 6.1 HTTP公共约定（BND-FORM-HTTP）

全部路径使用现有`/api/v1`，本机原部署访问边界和同源策略沿用，不新增登录／跨租户体系；不由客户端指定actor。路径ID与body文档归属必须在服务端核实。GET无副作用；新增写请求必须带一个合法UUIDv4 Idempotency-Key，未知字段／重复参数拒绝，完整请求8MiB上限沿SHR-FORM-BUDGET。

沿原HTTP封装：成功`{success:true,data,error:null,meta}`，失败`{success:false,data:null,error:{code,message,details},meta}`；meta沿原request_id及可选pagination等字段。本文命名DTO描述data，不在其内部再包data。安全错误由登记生成，不返回私有binding、SQL、凭据或供应商原异常。202只证明运行已接受。程序应用成功200只证明回执中的事实，后续GET失败仍是“操作成功，显示待刷新”。

| 新幂等能力身份 | 输入摘要范围 | 结果 |
| --- | --- | --- |
| formation.command | requirement_id、document_id、D及完整discussion_command | ProgramReceipt |
| formation.card.apply | 原message_id、D、完整正式responses（文档从原消息核实） | ProgramReceipt |
| formation.discuss | 原创建运行输入及完整目标／意图／调整引用 | 原RunAccepted扩展 |
| 预览 | 无幂等记录，严格只读 | PathPreview |

摘要采用SHR-FORM-TYPES canonical JSON；先完成原边界的严格解析，再计算规范化输入，不能忽略用户文本、null、目标或版本。成功重放优先于当前D／V／占用判断；同key异输入IDEMPOTENCY_CONFLICT。命令体不含key，key只在头中；内部commands边界可加入可信解析值。请求超时、非可信响应或提交未知，保留原method／path／body字节／key；用原命令核实，不能给它自动换D、换目标或换key。已知业务拒绝后，用户核对新状态再明确新发才使用新key。

### 6.2 严格DTO与HTTP入口

#### DTO-BASE 类型组合

下表所有命名结构均拒绝未知字段，字段默认必有；`?`仅表示请求字段可缺失，`T/null`表示字段必须有且可空。长度和类型采用SHR-FORM-TYPES，来源／补丁的未变严格形状采用V1.5正式后端原定义，不能用任意JSON代替。引用集合去重，保持明确顺序的集合保序；集合无值用[]。

| 名称 | 完整新增字段与限定 |
| --- | --- |
| VersionBasis | discussion_version:Version；formation_version:Version/null；goal_version:Version/null；document_revision_id:ID；content_version:Version |
| TargetSelection | discussion_step_ref:StepRef/null；discussion_branch_ref:BranchRef/null；branch_intent:ENTER/RESUME/null；branch_resume_basis:ResumeBasis/null |
| ResumeBasis | expected_branch_status:DEFERRED/RESOLVED；expected_branch_event_id:EventID；必须是同支线最后状态／结果事件 |
| ProposalRef | message_id:ID；card_key:原卡稳定键；只定位原服务端卡，不接受payload |
| ResultRoute | from_result_ref:ResultRef；disposition:REPLACED/NOT_REQUIRED；target_result_refs:PathResultRef[]；reason:Text；仅输入可含已声明TempResultRef；正式历史使用ResolvedResultRoute（相同键，目标仅ResultRef） |
| CommandSource | 程序生成的原真实用户消息及动作；客户端不能提交此结构或actor |
| ArtifactReview | reviewed_artifact_ref:ArtifactRef；replacement_artifact_ref:ArtifactRef/null；result:MATCHED/REASSOCIATED/UNVERIFIED/REMOVED；checked_against_revision_id:ID；assistant_message_id:ID；source_refs:SourceRef[] |
| Availability | action:本文命令名或apply/adjust/preview；available:boolean；reason:登记原因/null；available=true时reason=null；不携带私有basis |

目标联合：整份文档讨论（无论是否已有主线）步骤／支线／意图／依据均null；无主线只能选整份文档；已有主线允许明确步骤且支线为空，此时意图／依据为空；支线非空则步骤必须等于真实return，ENTER依据为空，RESUME依据必有。DROPPED不可恢复；并非把任意非OPEN自动解释为RESUME。已提交恢复后，读到OPEN用ENTER；没有依据的ENTER遇状态变化明确冲突。

#### DTO-NATIVE 原生命令联合

PATCH请求体为`{document_id,expected_discussion_version,discussion_command}`。前三项分别为ID、Version、下表严格联合；command公共`type="FORMATION"`和`action`必有，其余仅允许对应行字段。无主线时只读／讨论建线，不能用命令虚构空头部。PathEditCommand单独一行定义，不与元数据PATCH混传。

| action | 完整专属输入 | 额外约束 |
| --- | --- | --- |
| START_STEP | step_ref | PLANNED→IN_PROGRESS |
| PAUSE_STEP | step_ref | IN_PROGRESS→PAUSED；只清匹配当前焦点 |
| RESUME_STEP | step_ref | PAUSED→IN_PROGRESS |
| SWITCH_STEP | step_ref:StepRef/null | 焦点选择；不要求依赖已完成，不自动暂停其他步骤 |
| REOPEN_STEP | step_ref | COMPLETED→IN_PROGRESS；旧Closure不变 |
| COMPLETE_STEP | step_ref；expected_definition_version:Version；expected_goal_version:Version；expected_content_version:Version；result_dispositions:ResultDisposition[]；issue_dispositions:RemainingDisposition[]；branch_dispositions:RemainingDisposition[]；next_step_ref:StepRef/null | 前三数组允许空集合[]但不允许null；不是必须填完整处置表；遗漏分别按真实OUTSTANDING／KEEP_OPEN保存 |
| ADJUST_PATH | expected_formation_version:Version；expected_content_version:Version；based_on_proposal:ProposalRef/null；changes:PathChange[]；result_routes:ResultRoute[]；reason:Text | 20项／64KiB；必须整体校验；非空changes |
| ENTER_BRANCH | step_ref；branch_ref | 两者完整目标；支线OPEN且return匹配 |
| RETURN_FROM_BRANCH | branch_ref | 只清活动焦点，支线可继续OPEN |
| DISPOSE_BRANCH | branch_ref；disposition:DEFERRED/DROPPED；reason:Text | 不伪造RESOLVED；保留原结果来源 |
| RESUME_BRANCH | step_ref；branch_ref；expected_branch_status:DEFERRED/RESOLVED；expected_branch_event_id:EventID；enter_after_resume:boolean | 恢复依据逐项匹配，回归OPEN；结果移入不可变事件，当前结果清空；同身份；enter_after_resume=true才选择完整焦点，false只恢复 |
| RESUME_ISSUE | issue_ref | DEFERRED→OPEN；OPEN为NO_CHANGE；DROPPED拒绝 |
| DEFER_WRITE_PROPOSAL | proposal:ProposalRef；reason:Text | 只STAGED_WRITE，未正式消费 |
| RESUME_WRITE_PROPOSAL | proposal:ProposalRef | 恢复可检查的待应用状态，不自动apply |
| WITHDRAW_PROPOSAL_ADJUSTMENT | proposal:ProposalRef | 两种用途均可；重新核实全部相关依据后才能回到可执行 |

ResultDisposition为`{result_ref,status:OUTSTANDING/LANDED/ANALYZED,artifact_refs:ArtifactRef[],source_refs:SourceRef[]}`；LANDED仅CONTENT且所有真实关联可核实，ANALYZED仅ANALYSIS有真实依据；客户端声明不等于通过。RemainingDisposition为`{ref,disposition:KEEP_OPEN/TRANSFER/DEFERRED/DROPPED,to_step_ref:StepRef/null,reason:Text/null}`；只有TRANSFER有to，DEFERRED／DROPPED必须reason；问题ref只能IssueRef、支线只能BranchRef。已真正解决的对象由程序记当时RESOLVED事实，客户端不能把未解决伪写RESOLVED。所有已存在关联问题／支线按完整DB查询保存Closure，数组只表达显式改动，未提供的保持原归属。普通结束不强制理由。

PathChange是4章14型表的严格联合，type及该行全部字段必有；补充：ADD_STEP的expected_results项为`{temp_result_ref,description,kind}`；dependencies为PathStepRef[]；replaces_step_refs为现有StepRef[]（引用旧来源，不含临时新步）；before_step_ref可空；ADD_STEP字段为temp_step_ref:TempStepRef,title:Title,expected_results:[{temp_result_ref:TempResultRef,description:Text,kind:CONTENT/ANALYSIS}],dependencies:PathStepRef[],replaces_step_refs:StepRef[],before_step_ref:PathStepRef/null。RENAME_STEP字段step_ref:StepRef,title:Title；MOVE_STEP字段step_ref:StepRef,before_step_ref:PathStepRef/null；SET_DEPENDENCIES字段step_ref:StepRef,dependencies:PathStepRef[]；UPDATE_RESULT字段result_ref:ResultRef,description:Text；ADD_RESULT字段step_ref:PathStepRef,temp_result_ref:TempResultRef,description:Text,kind:CONTENT/ANALYSIS；CANCEL_STEP字段step_ref:StepRef,replacement_step_refs:PathStepRef[]；LINK_CONTENT字段step_ref:PathStepRef,result_refs:PathResultRef[],revision_id:ID,block_ids:BlockID[]（1—100）；MOVE_ISSUE字段issue_ref:IssueRef,to_step_ref:PathStepRef；SET_BRANCH_RETURN字段branch_ref:BranchRef,return_step_ref:PathStepRef；DISPOSE_ISSUE字段issue_ref,disposition,reason；DISPOSE_BRANCH字段branch_ref,disposition,reason；RESUME_ISSUE字段issue_ref。SET_GOAL字段text,source_refs。不存在任意path/value或整表替换动作。

路线的临时域为同一个ADJUST_PATH或同一张FORMATION_PATH_CHANGE payload，不能跨卡／跨请求借用new_*。处理顺序固定：①严格形状／类型校验，既有Ref和按字段允许的临时Ref分开；②收集全部ADD_STEP及ADD_RESULT／expected_results声明，检查重名、TempResultRef唯一所属与1—20成果约束；③解析本批引用，允许引用后面的声明，拒绝悬空／错种类／跨文档及冲突写同字段；④以局部符号图做全批约束／预算校验；⑤仅成功COMMIT在同一事务分配正式身份，建立执行映射并重做真实图约束后持久化。预览／发布失败不耗编号，回滚不保留映射。AI普通formation_delta的ADD_STEP仍用其独立schema的temp_ref，不能拿它代替PathChange；第4章路线表与本段均是人工／路线卡的PathChange。

所有正式事件／Closure／数据库关系使用ResolvedResultRoute与真实Step/ResultRef；原路线卡中局部临时声明永久保留。ReferenceMap是本次成功执行的输出，不是修改原卡的指令。


#### DTO-DISCUSS 运行输入、程序采用与结果

| 结构 | 与原契约的关系／完整新增字段 |
| --- | --- |
| FormationDiscussInput | 原CreateGuideRun的DISCUSS分支完整body为document_id、expected_discussion_version、operation、instruction、target、scope、source_refs、proposal_ref、acknowledge_source_changes；requirement_id来自路径、key来自头，Profile由原Runtime选择，不增加model_profile_id。仅新release的DISCUSS新增TargetSelection四字段＋proposal_intent:ADJUST_WRITE/ADJUST_PATH/null；proposal_ref沿原ProposalRef，不重复定义。非DISCUSS不接受新增字段；intent与ref同空／同非空，purpose必须匹配 |
| ProgramApplyInput | 原responses请求body为schema_version、responses、expected_discussion_version、execution_selection；message_id来自路径，文档从原消息核实，不新增document_id；原Responses；只一张新用途卡，responses恰好一项`{card_key,selected_option_keys:["apply"],custom_answer:null,skipped:false}`，execution_selection=null、schema_version=1；不能带精确内容替代原卡 |
| RunAccepted扩展 | 原data增加accepted_target:TargetSelection（已消费RESUME归一化成ENTER＋null依据）；接收成功不代表模型成功，原guide_run_id等不变 |
| ProgramReceipt | schema="formation_program_receipt_v21_1"；processing="PROGRAM"；requirement_id、document_id；discussion_version、formation_version、content_version；operation:NATIVE_FORMATION/STAGED_WRITE/FORMATION_PATH_CHANGE；result:APPLIED/NO_CHANGE；user_message_id:ID/null；effects:Effect；event_ids:EventID[]；reference_map:ReferenceMap[] |
| Effect | content_changed:boolean；revision_id:ID/null；formation_changed:boolean；proposal_disposition:当前处置/null；原DocumentEffect内部复用；NO_CHANGE不虚构revision_id |
| ReferenceMap | temp_ref:TempRef；resolved_ref:StepRef/ResultRef/BranchRef/IssueRef；按本次声明顺序，不包含未成功项 |
| RoundResult扩展 | 原读取结果增加effect_state:APPLIED/STRUCTURED_REJECTED/FAILED/CANCELLED；progress_result、formation_result、proposal_result各为APPLIED/NO_CHANGE/REJECTED/NOT_APPLICABLE；component_errors为已登记code[]；accepted_target保留冻结目标。原独立GENERATE／REVISE的content_result沿用，不被非法讨论增量反向撤销 |

#### DTO-PROPOSAL 精确payload与私有依据

新卡沿现有Cards严格外壳（schema_version、intro、cards等），purpose增加STAGED_WRITE与FORMATION_PATH_CHANGE。每个新用途卡组恰好一张单选、一个option_key=apply，required=true、min=max=1、custom_answer.enabled=false；卡question为真实确认动作，解释／预览不是选项替代。payload与purpose严格绑定；原普通卡格式／多卡回答不变。

| purpose | 完整payload |
| --- | --- |
| STAGED_WRITE | step_ref；result_refs非空；write_mode:FILL_EMPTY/PATCH_EXISTING；document_revision_id；content_version；goal_version；definition_version；scope:原Scope；markdown_content:string/null；patches:原Patch[]；change_summary:Text；source_refs:SourceRef[] |
| FORMATION_PATH_CHANGE | basis:formation_version/goal_version/document_revision_id/content_version；changes:PathChange[]；result_routes:ResultRoute[]；change_summary:Text；source_refs:SourceRef[] |

FILL_EMPTY仅全DOCUMENT真实空白，markdown_content必非空、patches=[]；PATCH_EXISTING markdown_content=null、patches非空。服务端拿原payload生成只读预览，用户确认后沿同payload操作；不是模型建议中混入自由调用授权。

私有PublicationBinding（schema=`formation_card_binding_v21_1`）不发送模型／浏览器：card身份、payload_digest、源运行冻结F、发布后可执行相关basis、Goal版本、V／Revision、被触及步骤definition版本、来源heads及related_entries。related_entries以实体kind＋稳定ref排序，存其语义字段摘要；包括直接修改／采用对象、要求、问题和支线归属、取消节点的入边／所有待承接项及影响范围内关系集合摘要。排除焦点、D／F计数、展示顺序及无关对象；标题仅卡用途确实依赖时包含。新增关系的不存在条件以父对象＋关系种类＋筛选范围的集合摘要表示，不能只摘要原来已有行。

应用时从真实DB重建上述集合摘要，匹配payload、Goal／V／定义／来源，再把全批应用到最新完整逻辑图核实无循环／悬空／双OPEN错配。F12模型提出、F13发布后仍可用，冻结basis不伪改13；只变焦点或无关D／F不失效。修改某步的排序也不改变其他卡用途；与本卡相关的新关系／内容／定义则拒绝。撤回调整从当前真实状态重新核实原PublicationBinding，成功仅增加WithdrawalCheckProof及审计事件，不产生或切换新binding；原绑定／原payload原字节不改，不匹配时保持禁用。

<a id="proposal-publication-proof"></a>
**发布绑定与撤回凭证的唯一语义**

PublicationBinding创建于卡片正式发布，保存且固定本卡的payload_digest、原运行冻结来源、发布后可执行相关basis以及protected_semantic_digest。protected_semantic_digest是如下严格受保护投影的canonical摘要：{payload_digest,goal_version,document_revision_id,content_version,step_definitions:[{step_ref,definition_version}],source_heads:[{source_ref:SourceRef,version_token:string(1—160)/null,head_digest:Digest}],related_entries:[{entity_kind:string(1—40),entity_ref:string(1—160),semantic_digest:Digest}]}。步骤按编号、来源按SourceRef canonical字节、related_entries按kind/ref排序，集合摘要和不存在条件仍按上文实际影响范围生成。version_token对不可变消息等可空，对有版本来源用其真实固定版本标识，不暗中外发请求。

焦点／D／F／展示顺序／无关对象，以及本卡disposition、needs_revision、当前can_apply不进入受保护投影；Step的生命周期及Closure指针也不因自身变化进入写卡用途指纹，保证已结束步骤仍可采用适用写卡。目标CANCELLED或路线CANCEL_STEP前态等限制另按实时用途／命令许可核实，不能靠排除生命周期绕过。这些属于独立执行许可。不得因本卡被标调整中而把自己的用途指纹变掉，也不能通过撤回放松原V／Goal／定义／来源保护。

WithdrawalCheckProof完整字段为{proposal:ProposalRef,publication_binding_digest:Digest,expected_semantic_digest:Digest,observed_semantic_digest:Digest,checked_versions:VersionBasis,check_kind:"WITHDRAW_ADJUSTMENT",result:"MATCHED",command_message_id:ID}。publication_binding_digest是原PublicationBinding完整canonical摘要；expected取其protected_semantic_digest，observed由当前真实DB以同一投影算法重算。只有两者相同且独立许可仍可撤回才生成成功凭证；失败原needs_revision保持，不写成功凭证。checked_versions取该事务完成输入版本检查、尚未清标记／增加D/F时的真实before版本；事件头另存提交后的after版本，不能用凭证改写原模型basis。

撤回事务保存PROPOSAL_ADJUSTMENT_WITHDRAWN、PROPOSAL变化（needs_revision true→false）及PROPOSAL_CHECK变化（before=null,after=WithdrawalCheckProof）、D/F和成功回执；凭证同事务持久化于formation_event_changes，回执event_ids可定位。每次真正撤回最多一份；同key先重放旧成功回执，不重算后来的状态；新key且已无调整标记为NO_CHANGE，不伪造新校验。原绑定缺失／损坏按STORAGE_UNAVAILABLE或INTERNAL_ERROR处理，不能借撤回重建发布依据。

后续apply仍始终读取原PublicationBinding，核实当前未消费、未替代、非暂缓、needs_revision=false等许可，重新比较受保护语义及最新D／占用与全图约束。撤回凭证仅证明当次撤回，不作为后续执行授权缓存；即便刚撤回成功，随后内容／用途变化也必须拒绝apply。公开历史只含上述摘要及版本，不暴露原私有binding正文；前端不上传binding或凭证。

提案处置枚举为PENDING／DEFERRED／APPLIED／SUPERSEDED；needs_revision:boolean单列，调整期间不新增可伪装已正式回答的处置。can_apply:boolean与Availability一致，reasons为安全原因集合，expiry_reason为null或CONTENT_CHANGED／GOAL_CHANGED／DEFINITION_CHANGED／SOURCE_UNAVAILABLE／PURPOSE_CHANGED／BASIS_CHANGED／ADJUSTING／ALREADY_ANSWERED；非空原因不等于原卡被物理改写。新值对象来源集合最多100项，关联区块单项最多100，均是本次输入边界；既有来源历史不因新上限被截断。

FormationEvent.action使用如下闭集：PATH_INITIALIZED、GOAL_CHANGED、STEP_ADDED、STEP_UPDATED、STEP_MOVED、STEP_STARTED、STEP_PAUSED、STEP_RESUMED、STEP_REOPENED、STEP_COMPLETED、STEP_CANCELLED、DISCUSSION_STEP_SELECTED、RESULT_ROUTE、ISSUE_ADDED、ISSUE_UPDATED、ISSUE_RESOLVED、ISSUE_MOVED、ISSUE_DISPOSITION_CHANGED、ISSUE_RESUMED、BRANCH_ADDED、BRANCH_RESULT_RECORDED、BRANCH_ENTERED、BRANCH_RETURNED、BRANCH_RETURN_CHANGED、BRANCH_DISPOSITION_CHANGED、BRANCH_RESUMED、BRANCH_REOPENED、ASSESSMENT_RECORDED、RECOMMENDATION_RECORDED、CONTENT_ASSOCIATED、ARTIFACT_CHECKED、ARTIFACT_REASSOCIATED、PROPOSAL_DEFERRED、PROPOSAL_RESUMED、PROPOSAL_ADJUSTMENT_REQUESTED、PROPOSAL_ADJUSTMENT_WITHDRAWN、PROPOSAL_SUPERSEDED、PROPOSAL_APPLIED。无实际变化不造事件，用户结束／恢复的责任不能写AI。原audit.payload_json保存第3章事件头及逻辑changes的数量／分页引用，完整changes与Closure项在7.1子表，同事务写；读取按新release＋formation_read_v21_1严格投影，不能把旧formation_event_v1执行件当当前完整结构。

#### DTO-READ／SHR-FORM-PAGE 有界投影与分页

本节列出公开读取的完整字段。命名类型均为严格对象，不允许任意JSON摘要；所有字段必有，可空显式null。N表示0—9007199254740991安全整数，Position为正安全整数；所有数组无值为[]。公共SourceRef／UTC等类型沿DTO-BASE。View只返回本表字段，逻辑对象第3章的其他集合不得顺手内嵌。

| 类型 | 完整字段与限定 |
| --- | --- |
| StateCounts | steps:{PLANNED:N,IN_PROGRESS:N,PAUSED:N,COMPLETED:N,CANCELLED:N}；branches:{OPEN:N,RESOLVED:N,DEFERRED:N,DROPPED:N}；issues:{OPEN:N,RESOLVED:N,DEFERRED:N,DROPPED:N}；proposals:{PENDING:N,DEFERRED:N,APPLIED:N,SUPERSEDED:N}；pending_review_artifacts:N。后者只计当前替代链末端且freshness=NEEDS_REVIEW的真实关联，未加载页不影响总数 |
| GoalView | version:Version；text:Text；source_refs:SourceRef[] |
| Summary | document_id:ID；view_schema:"formation_read_v21_1"；exists:boolean；formation_version:Version/null；goal:GoalView/null；current_step_ref:StepRef/null；active_branch_ref:BranchRef/null；counts:StateCounts；availability:Availability[]。两种exists使用完全相同键；false时F/goal/两焦点均null、counts逐项0、availability=[]；true时F/goal非null，焦点依实际可空。没有target键 |
| SourceStatus | source_ref:SourceRef；availability:AVAILABLE/MISSING/UNSUPPORTED；reason:null或SOURCE_MISSING/RESOURCE_UNSUPPORTED。AVAILABLE时reason=null，其余与状态对应；不向原SourceRef插字段 |
| EventSummary | event_id:EventID；action:第6章事件闭集；actor:USER/AI/PROGRAM；reason:Text；created_at:UTC |
| AssessmentView | verdict:SUFFICIENT/GAPS_REMAIN/UNCERTAIN；reason:Text；goal_version:Version；evaluated_step_version:Version；evaluated_revision_id:ID；coverage_block_ids:BlockID[]（≤100）；source_refs:SourceRef[]；assistant_message_id:ID；validity:CURRENT/STALE；stale_reason:null或GOAL_CHANGED/DEFINITION_CHANGED/COVERAGE_CHANGED。CURRENT原因空；多项变化按上述顺序取第一项，历史原值不重写 |
| RecommendationView | action:OBJ-FORM-ASSESS的建议闭集；step_ref:StepRef/null（建议目标，对应模型target_step_ref）；reason:Text；source_refs:SourceRef[]；assistant_message_id:ID；basis:RecommendationBasis；validity:CURRENT/STALE；stale_reason:null或RecommendationStaleReason。CURRENT原因必空，STALE必有原因 |
| RelationCounts | dependencies:N；replaces:N；topics:N；issues:N；branches:N；artifacts:N |
| StepView | step_ref:StepRef；definition_version:Version；title:Title；status:五态；position:Position；expected_results:[{result_ref:ResultRef,description:Text,kind:CONTENT/ANALYSIS}]（1—20）；relation_counts:RelationCounts；last_event:EventSummary/null；assessment:AssessmentView/null；recommendation:RecommendationView/null；availability:Availability[]。assessment=null才表示无评估；历史评估STALE不变成null；recommendation=null仅代表从未登记建议，返回最新事件的建议，即使STALE也保留，不回退到更旧建议冒充新建议 |
| StepDetail | StepView全部字段＋closure:ClosureHead/null；sources:SourceStatus[]。closure仅当前生命周期COMPLETED时引用原结束事件，其他为空；旧结束通过事件页查询 |
| BranchView | branch_ref:BranchRef；origin_step_ref:StepRef；origin_event_ref:EventID；return_step_ref:StepRef；question:Text；relevance:Text；status:OPEN/RESOLVED/DEFERRED/DROPPED；state_event_ref:EventID；topic_count:N；result_summary:Text/null；result_source_refs:SourceRef[]；disposition_event_ref:EventID/null；availability:Availability[]。不嵌全部主题或旧结果 |
| IssueView | issue_ref:IssueRef；step_ref:StepRef；branch_ref:BranchRef/null；description:Text；source_refs:SourceRef[]；blocking:boolean；disposition:OPEN/RESOLVED/DEFERRED/DROPPED；disposition_reason:Text/null；resolution_source_refs:SourceRef[]；disposition_event_ref:EventID/null；availability:Availability[] |
| ArtifactView | predecessor_ref:ArtifactRef/null；predecessor_review_event_id:EventID/null；successor_ref:ArtifactRef/null；successor_review_event_id:EventID/null；is_active:boolean；artifact_ref:ArtifactRef；step_ref:StepRef；result_refs:ResultRef[]（1—20）；source_event_ref:EventID；origin_revision_id:ID；origin_content_digest:Digest；summary:Short；checked_against_revision_id:ID；freshness:CURRENT/NEEDS_REVIEW/REMOVED；review_reason:null或CHANGED/UNVERIFIABLE；origin_block_count:N；current_block_count:N；sources:SourceStatus[]。is_active恰好等于successor_ref=null；前驱／后继Ref与对应review_event_id成对同空／同非空，事件指向建立这条不可变边的真实review；具体区块范围走RangePage，不内嵌无界ID数组 |
| LineagePage | document_id:ID；formation_version:Version；anchor_ref:ArtifactRef；total:N；items:[{artifact_ref:ArtifactRef,predecessor_ref:ArtifactRef/null,predecessor_review_event_id:EventID/null,successor_ref:ArtifactRef/null,successor_review_event_id:EventID/null,is_active:boolean,freshness:ArtifactFreshness,review_reason:原因/null}]，按根到末端的链顺序及ordinal游标分页（≤limit），固定F；不一次返回整链 |
| RangeItem／RangePage | RangeItem={ordinal:Position,revision_id:ID,block_id:BlockID,block_digest:Digest}；RangePage={document_id:ID,formation_version:Version,artifact_ref:ArtifactRef,role:ORIGIN/CURRENT,items:RangeItem[],total:N}，meta.pagination同普通页；ORIGIN本身不可变但当前查询固定F |
| ProposalView | message_id:ID；card_key:string(1—100)；purpose:STAGED_WRITE/FORMATION_PATH_CHANGE；payload:DTO-PROPOSAL对应严格联合；disposition:PENDING/DEFERRED/APPLIED/SUPERSEDED；needs_revision:boolean；can_apply:boolean；reasons:Availability.reason[]；availability:Availability[]；expiry_reason:第6章登记枚举/null；source_run_id:ID。can_apply须等于apply动作可用性，不能只由disposition推断 |
| EntityPage | document_id:ID；formation_version:Version；kind:steps/branches/issues/artifacts/relations；items:与kind对应StepView/BranchView/IssueView/ArtifactView/RelationItem数组（本页≤limit）；total:N；禁止混合items类型 |
| ProposalPage | document_id:ID；formation_version:Version；kind:"proposals"；items:ProposalView[]；total:N。全量处置计数仅从Summary.counts取得，不追加未定义页字段 |
| EventView | EventSummary全部字段＋schema:"formation_event_v1"；document_id:ID；batch_ref:ID；ordinal:Position；batch_size:Position；version_before:VersionBasis；version_after:VersionBasis；change_count:N；closure:ClosureHead/null。changes和相关引用通过事件明细／索引查询，不内嵌全批关系 |
| EventPage | document_id:ID；upper_event_id:EventID/null；total:N；items:EventView[]。无事件时上界null、total=0、items=[]；之后新事件不改变已冻结上界 |
| ClosureHead | event_id:EventID；step_ref:StepRef；definition_version:Version；goal_version:Version；revision_id:ID；command_message_id:ID；next_step_ref:StepRef/null；result_count:N；issue_count:N；branch_count:N；items_digest:Digest |
| ResultClosureItem | kind:"RESULT"；ordinal:Position；result_ref:ResultRef；description:Text；result_kind:CONTENT/ANALYSIS；status:LANDED/ANALYZED/OUTSTANDING；artifact_count:N；range_count:N；source_count:N；evidence_count:N；evidence_digest:Digest。身份／范围／来源走ClosureEvidencePage，不返回artifact_refs／source_refs数组。NEEDS_REVIEW/REMOVED不能证明LANDED；缺真实分析依据不能ANALYZED |
| RemainingClosureItem | kind:ISSUE/BRANCH；ordinal:Position；ref:与kind对应IssueRef/BranchRef；description:Text；state_at_close:OPEN/RESOLVED/DEFERRED/DROPPED；disposition:KEEP_OPEN/TRANSFER/DEFERRED/DROPPED/RESOLVED；to_step_ref:StepRef/null；reason:Text/null；source_count:N；evidence_count:N；evidence_digest:Digest。来源逐条读ClosureEvidencePage；RESOLVED只由真实已有事实生成；状态和去向保留当时值 |
| ClosureItemPage | document_id:ID；event_id:EventID；closure:ClosureHead；kind:RESULT/ISSUE/BRANCH；total:N；items:与kind一致的ResultClosureItem/RemainingClosureItem[] |
| ClosureEvidencePage | document_id:ID；event_id:EventID；owner_kind:RESULT/ISSUE/BRANCH；item_ref:对应真实Ref；total:N；digest:Digest；items:ClosureEvidenceItem[]（≤limit），meta.pagination按固定event/owner/item/ordinal游标 |
| ClosureEvidenceItem | {kind:"ARTIFACT",ordinal:Position,artifact_ref:ArtifactRef,source_event_ref:EventID,origin_revision_id:ID,checked_against_revision_id:ID,freshness:ArtifactFreshness,review_reason:null或CHANGED/UNVERIFIABLE,range_count:N,range_digest:Digest}；或{kind:"RANGE",ordinal:Position,artifact_ref:ArtifactRef,role:ORIGIN/CURRENT,revision_id:ID,block_id:BlockID,block_digest:Digest}；或{kind:"SOURCE",ordinal:Position,source_ref:SourceRef}。ARTIFACT/RANGE只属RESULT，每个SOURCE只有一个引用；每项均为结束时事实，后续关联变化不改写 |
| PreviewRefMap | temp_ref:TempRef；preview_label:Title。没有resolved_ref，预览不分配正式身份 |
| PreviewAffectedItem | ordinal:Position；change_type:PathChange.type；entity_ref:真实Step/Result/Issue/Branch/ArtifactRef或TempRef或保留值"goal"（LINK_CONTENT预览以目标step_ref为entity_ref、after用ARTIFACT_LINK，不预分配ArtifactRef）；before:PreviewEntity/null；after:PreviewEntity/null；两者不能均null |
| PreviewEntity | {kind:"STEP",step_ref:PathStepRef,title:Title,status:五态,position:Position,expected_results:[{result_ref:PathResultRef,description:Text,kind:CONTENT/ANALYSIS}]}；或{kind:"GOAL",text:Text}；或{kind:"RESULT",result_ref:PathResultRef,description:Text,result_kind:CONTENT/ANALYSIS}；或{kind:"ISSUE",issue_ref:IssueRef,step_ref:PathStepRef,disposition:问题处置闭集}；或{kind:"BRANCH",branch_ref:BranchRef,origin_step_ref:StepRef,return_step_ref:PathStepRef,status:支线闭集}；或{kind:"ARTIFACT",artifact_ref:ArtifactRef,step_ref:StepRef,result_refs:ResultRef[],freshness:ArtifactFreshness}；或{kind:"DEPENDENCIES",step_ref:StepRef或TempStepRef,dependencies:PathStepRef[]}；或{kind:"ARTIFACT_LINK",step_ref:PathStepRef,result_refs:PathResultRef[],revision_id:ID,block_ids:BlockID[]（1—100）}。按kind严格联合，无自由before/after JSON |
| PreviewWarning | ordinal:Position；code:OUTSTANDING_CONTENT/UNRESOLVED_ISSUE/OPEN_BRANCH/PROPOSAL_AFFECTED/ASSESSMENT_STALE/FOCUS_CLEARED；step_ref:PathStepRef/null；related_ref:真实Ref或TempRef/null；message:Text。提示不代替硬校验失败，不以缺成果禁止结束 |
| `PreviewSlice<T>` | items:T[]（≤limit）；total:N；has_more:boolean；next_cursor:string/null；true必有游标、false必空 |
| PathPreview | document_id:ID；discussion_version:Version；formation_version:Version；content_version:Version；changes_digest:Digest；affected_items:`PreviewSlice<PreviewAffectedItem>`；result_routes:ResultRoute[]；warnings:`PreviewSlice<PreviewWarning>`；reference_map:PreviewRefMap[]（最多420，20步各20成果及步骤身份）。没有缩写D/F/V字段，没有授权token |

<a id="recommendation-validity"></a>
**RecommendationBasis及当前性规则**

| 类型 | 完整字段／生成规则 |
| --- | --- |
| RecommendationBasis | schema:"formation_recommendation_basis_v21_1"；goal_version:Version；owner_step_ref:StepRef；owner_definition_version:Version；owner_status:五态；evaluated_revision_id:ID；coverage:[{block_id:BlockID,block_digest:Digest}]（≤100）；target_step:{step_ref:StepRef,definition_version:Version,status:五态}/null；entity_basis:[{kind:BRANCH/ISSUE/ARTIFACT,ref:对应真实Ref,semantic_digest:Digest}]（≤100）；relation_sets:[{kind:OPEN_ISSUES/OPEN_BRANCHES/ACTIVE_ARTIFACTS,step_ref:StepRef,digest:Digest}]（≤6）；source_heads:[{source_ref:SourceRef,head_digest:Digest}]（≤100） |
| RecommendationStaleReason | GOAL_CHANGED／OWNER_DEFINITION_CHANGED／OWNER_STATE_CHANGED／TARGET_CHANGED／COVERAGE_CHANGED／SOURCE_UNAVAILABLE／RELATED_FACT_CHANGED，按此顺序返回第一项原因；不返回任意字符串 |

RECOMMEND模型输出形状保持原action／step_ref／target_step_ref／reason／source_refs，不接受模型填写basis／validity。程序按本轮真实冻结Goal／所属Step（接受后生命周期）、实际发送材料及alias覆盖建立basis；target_step非空时必须是本轮可见的真实目标，同ref字段和View.step_ref对应。coverage只列真实已发送区块摘要，不把当前整篇当已读；来源头来自真实材料的确定投影。若建议引用本轮合法INITIALIZE_PATH／ADD_STEP新建实体，先验证完整结构单元，再以待提交结果的真实Goal／Step定义绑定，提交失败全部撤销。模型输入冻结basis仍保留原null或旧版本，不能把程序发布后版本伪装为模型调用前已读；可见依据包括本轮已发材料与合法结构产物，不包括程序私有补全的未发送材料。保存basis与建议／消息／事件同事务，后续查询不补造当时覆盖。

entity_basis覆盖实际发送的相关Branch／Issue／Artifact，以可见语义字段确定摘要：Branch含身份、return、问题／影响、status、state_event_ref、结果及其来源摘要；Issue含身份／归属／描述／blocking／处置及解决来源摘要；Artifact含身份／Step／成果、当前freshness／review_reason、当前范围摘要及替代后继。原origin、可验证内容与来源使用真实数据；排除焦点／计数／展示排序／检查时钟。source_heads以相应SourceRef所代表的实际可见材料取canonical摘要，不悄悄联网补查。

relation_sets由程序针对owner及不同的target步骤各生成三条；集合分别为其全部OPEN问题、return所属的全部OPEN支线、全部活动Artifact。每项用上述实体语义摘要，按局部编号排序后流式计算集合摘要；用于发现新出现／消失的相关事项，不能只核对原来已存在的实体。它是程序完整性依据，只保存摘要，不把页外材料冒充模型已读。entity_basis与各列表都按kind/ref或来源canonical顺序去重；actual材料／本次协议超预算仍按原准入拒绝，不截断。

读取在同一真实快照中比较：Goal版本；owner定义／状态；target存在、定义和状态；coverage当前同ID内容摘要；来源能否按原范围核实及其内容；entity_basis及关系集合摘要。SOURCE_UNAVAILABLE仅指无法读取／核实原来源，来源可读但语义摘要改变归RELATED_FACT_CHANGED；不同原因按上述优先级得到STALE。evaluated_revision_id只说明原评估出处，若无关区域修改导致V变化而实际覆盖未变，不仅凭新V使建议过期；单纯D/F／讨论焦点／展示重排也不失效。所依赖目标被取消或改变、原owner结束／暂停等状态变化依对应原因失效。

建议依据与Assessment独立：新建议不能借旧Assessment.current当作自己的证明，旧建议也不能因最新时间戳自动有效；在当前详情只返回该owner最新建议及其validity，不回退旧条目。历史CHANGES中的RECOMMENDATION仅返回登记时不可变basis，不写入查询时的STALE标签；原事实不随未来变化改变。前端可显示最新历史建议，但只有CURRENT且对应实际操作availability可用时才显示“按建议操作”；STALE不触发Chat／状态改变，也不禁用用户独立的手动结束／切换／重开能力。

RelationItem按relation_kind严格联合：DEPENDENCY／REPLACES为{relation_kind,from_step_ref:StepRef,to_step_ref:StepRef}；TOPIC为{relation_kind:"TOPIC",step_ref:StepRef,topic_ref:同文档TopicRef}；ISSUE为{relation_kind:"ISSUE",step_ref:StepRef,issue:IssueView}；BRANCH为{relation_kind:"BRANCH",step_ref:StepRef,branch:BranchView}；ARTIFACT为{relation_kind:"ARTIFACT",step_ref:StepRef,artifact:ArtifactView}。关系owner为路径step_ref，输出引用与实际关系一致，不额外附未定义label；显示名来自相应详情／已有Topic读取。每个SourceStatus属于外层sources字段，不修改不可变payload里的source_refs。

事件变化页为{document_id:ID,event_id:EventID,total:N,items:EntityChangeView[]}。EntityChangeView={ordinal:Position,entity_kind:STEP/GOAL/RESULT/ISSUE/BRANCH/ARTIFACT/ORDER/RESULT_ROUTE/ASSESSMENT/RECOMMENDATION/PROPOSAL/PROPOSAL_CHECK/ARTIFACT_REVIEW,entity_ref:string(1—160),before:EntitySnapshot/null,after:EntitySnapshot/null,member_changes:{count:N,digest:Digest}}；before/after不能双null，集合变化时保存该实体标量前后值，变化明细单独分页。成员变化为0仍给空集digest，不追加未定义字段。

EntitySnapshot是以下与entity_kind对应的严格结构，不直接复制第3章逻辑聚合：

| entity_kind | before/after完整结构 |
| --- | --- |
| STEP | {step_ref:StepRef,definition_version:Version,title:Title,status:五态,position:Position,next_result_no:ID,closure_event_ref:EventID/null}；成果定义另以RESULT变化记录；依赖／替代／主题分别为成员变化 |
| GOAL | {version:Version,text:Text}；来源为SOURCE成员变化 |
| RESULT | {result_ref:ResultRef,description:Text,kind:CONTENT/ANALYSIS} |
| ISSUE | {issue_ref:IssueRef,step_ref:StepRef,branch_ref:BranchRef/null,description:Text,blocking:boolean,disposition:四态,disposition_reason:Text/null,disposition_event_ref:EventID/null}；原始／解决来源分两种成员集合 |
| BRANCH | {branch_ref:BranchRef,origin_step_ref:StepRef,origin_event_ref:EventID,return_step_ref:StepRef,question:Text,relevance:Text,status:四态,state_event_ref:EventID,result_summary:Text/null,disposition_event_ref:EventID/null}；主题／结果来源分成员记录 |
| ARTIFACT | {artifact_ref:ArtifactRef,step_ref:StepRef,source_event_ref:EventID,origin_revision_id:ID,origin_content_digest:Digest,summary:Short,checked_against_revision_id:ID,freshness:三态,review_reason:原因/null}；成果引用／范围分成员记录，不复制全部区块 |
| ORDER | {step_ref:StepRef,position:Position}；新增／取消一侧为null，每个实际位置改变的节点一条，不能返回整条step_refs数组 |
| RESULT_ROUTE | ResolvedResultRoute；该次映射受原批64KiB输入边界约束，未来不向旧事件追加目标 |
| ASSESSMENT | AssessmentView去掉validity/stale_reason；覆盖／来源均沿单次100项边界，不随历史增长 |
| RECOMMENDATION | RecommendationView去掉派生validity／stale_reason；原basis及source_refs按登记时固定边界保存，不读当前状态改写历史 |
| PROPOSAL | {proposal:ProposalRef,disposition:四态,needs_revision:boolean,binding_digest:Digest}；binding_digest恒为原PublicationBinding摘要；精确payload在原消息，历史不重复复制 |
| PROPOSAL_CHECK | WithdrawalCheckProof；before必须null、after非null，实体ref取message_id:card_key；属于当次不可变复核事实而非新绑定 |
| ARTIFACT_REVIEW | ArtifactReview（DTO-BASE完整字段）；before必须null，after为当次真实不可变review，entity_ref=reviewed_artifact_ref；不能以当前ArtifactView代替 |

MemberChangePage={document_id:ID,event_id:EventID,change_ordinal:Position,total:N,digest:Digest,items:MemberDelta[]}。MemberDelta={ordinal:Position,collection:DEPENDENCY/REPLACES/TOPIC/GOAL_SOURCE/ISSUE_SOURCE/ISSUE_RESOLUTION_SOURCE/BRANCH_TOPIC/BRANCH_RESULT_SOURCE/ARTIFACT_RESULT/ORIGIN_RANGE/CURRENT_RANGE,member_key:string(1—240),before:MemberValue/null,after:MemberValue/null}，不能双null。MemberValue为{kind:"REF",ref:对应集合的单个真实StepRef/TopicRef/ResultRef}，或{kind:"SOURCE",source_ref:SourceRef}，或{kind:"RANGE",revision_id:ID,block_id:BlockID,block_digest:Digest}；按collection严格限定类型，不能装数组或TempRef。member_key对Ref为该Ref、Source为其canonical摘要、Range为role:revision_id:block_id；重复键同批冲突拒绝。

事件成员为DELTA，新增／删除／更新各保存真实before/after单项；实体从创建起保留全部变化，首次集合全量创建为多条新增记录。历史重建按event_id、change_ordinal、member.ordinal前向应用，不读当前可变集合替换旧值；无需在每次改名时复制未变化的大集合。ORDER只表示有效路线的位置；CANCELLED节点从有效ORDER移除，其STEP标量仍保留取消时展示位置，不把物理负rank写入历史。ORDER按节点变化独立保存，rank重排涉及多个节点时多行同一事务；关闭／事件页的total是实际行数，元数据计数不按第一页估计。不可变明细游标绑定document、event_id、owner及最后ordinal，与当前F无关。

历史顺序与摘要唯一规则：Closure根kind按RESULT、ISSUE、BRANCH，Ref按其数字序（ResultRef按step号再成果号）；证据kind按ARTIFACT、RANGE、SOURCE，Artifact按编号，Range按Artifact编号、role(ORIGIN先于CURRENT)、revision_id、block_id，Source按canonical UTF-8字节序。每组据此分配1起ordinal。MemberDelta按collection的上述声明顺序、member_key UTF-8字节序分配ordinal。每项evidence_digest及member_digest为其完整有序明细数组的canonical JSON之SHA256，空集为canonical []的摘要；Closure.items_digest为完整有序Closure根项（含各证据摘要）的canonical数组摘要，不包含ClosureHead.items_digest自身。可用流式“[”、逐行canonical值与逗号、“]”计算，禁止只摘要当前页。事件变化ordinal依程序确定的批内实体变化顺序保存，历史分页只用保存ordinal，不在读取时重新排序或读取当前内容。



PathPreview的影响项与提示分别按ordinal分页，不生成持久预览对象：POST path-preview允许section?:AFFECTED/WARNINGS、limit?（20/100）及cursor?；无section同时返回两类第一页，指定section只推进对应slice，另一类返回首页。每次携带原完整discussion_command及expected_discussion_version，服务端重做只读校验；游标绑定doc、D/F/V、changes_digest、section与末ordinal，变更则PATH_CHANGED，重新预览。result_routes仍受本次64KiB变化预算，reference_map有上界；未加载影响项显示total及更多入口，不能当作不存在。

**完整成功data正例（Summary，无主线）**

```json
{"document_id":42,"view_schema":"formation_read_v21_1","exists":false,"formation_version":null,"goal":null,"current_step_ref":null,"active_branch_ref":null,"counts":{"steps":{"PLANNED":0,"IN_PROGRESS":0,"PAUSED":0,"COMPLETED":0,"CANCELLED":0},"branches":{"OPEN":0,"RESOLVED":0,"DEFERRED":0,"DROPPED":0},"issues":{"OPEN":0,"RESOLVED":0,"DEFERRED":0,"DROPPED":0},"proposals":{"PENDING":0,"DEFERRED":0,"APPLIED":0,"SUPERSEDED":0},"pending_review_artifacts":0},"availability":[]}
```

反例分别为：增加target键；exists=false却F=1；counts漏DROPPED；assessment.verdict="UNASSESSED"；NEEDS_REVIEW缺review_reason；RelationItem.relation_kind与items联合不匹配；preview.before混入任意JSON；has_more=true而next_cursor=null。上述均拒绝，不静默删字段。

页面meta沿原`request_id,pagination:{page_size,has_more,next_cursor}`；has_more=true必有游标，false为null。普通PageQuery：limit?默认20最大100；cursor?非空opaque；known_f?；state?（对应kind合法枚举）；step_ref?；branch_ref?；include_cancelled?默认false；include_superseded?默认false，仅artifacts或ARTIFACT关系页允许。过滤AND；未知字段及不适用kind字段422；步骤按position、step_ref，其他实体按稳定分配序号，提案按原message_id、card_key。关系页必须明确relation_kind=DEPENDENCY/REPLACES/TOPIC/ISSUE/BRANCH/ARTIFACT，并由真实step_ref限定；无任意SQL过滤。游标绑定doc、kind、完整规范化过滤、F、最后排序键、协议版本；格式非法422，F不一致409 STATE_CONFLICT/PATH_CHANGED，前端重读并保留选择／草稿。cursor与新过滤不可混用，首请求不传known_f时由服务端开始快照，后续请求固定返回F。

历史事件按event_id倒序，首请求冻结upper_event_id；后续before_event_id由opaque cursor携带，step_ref／branch_ref按事件引用索引过滤，包含同批相关事件。不可变历史允许当前F变化后继续按上界读；total为固定上界内完整匹配数。ClosureEvidencePage固定event_id／owner_kind／item_ref／ordinal，MemberChangePage固定event_id／change_ordinal／ordinal，均保留实际total/digest；ClosureItemPage固定event_id、kind、ordinal游标；变更详情固定event_id、ordinal；均不拿当前F修改旧快照。页空且total>0与全量无数据分开；不按已加载页生成弃用数或“没有关联”。

#### HTTP入口逐项契约

| BND编号 | 方法与路径（均加/api/v1） | 请求、绑定与成功 | 实际负责应用／位置 |
| --- | --- | --- | --- |
| BND-FORM-SUMMARY | GET /requirements/{requirement_id}?document_id=ID&expand=discussion | 原GET扩展discussion.formation_summary:Summary；不返回完整主线JSON | APP-FORM-READ；requirements/api.py＋queries |
| BND-FORM-PAGE | GET /requirements/{requirement_id}/documents/{document_id}/formation/{kind} | kind限steps/branches/issues/artifacts/proposals；PageQuery；200对应页 | 新增读入口；formation_queries |
| BND-FORM-STEP | GET /requirements/{requirement_id}/documents/{document_id}/formation/steps/{step_ref} | known_f?；200 StepDetail；实体不存在404 | 同上 |
| BND-FORM-RELATIONS | GET /requirements/{requirement_id}/documents/{document_id}/formation/steps/{step_ref}/relations | relation_kind必传＋PageQuery；200 EntityPage | 同上；不接受另一step_ref筛选 |
| BND-FORM-ARTIFACT | GET /requirements/{requirement_id}/documents/{document_id}/formation/artifacts/{artifact_ref} | known_f?；200 ArtifactView；允许历史inactive ID，不能自动跳到后继 | APP-FORM-READ；来源导航 |
| BND-FORM-LINEAGE | GET /requirements/{requirement_id}/documents/{document_id}/formation/artifacts/{artifact_ref}/lineage | limit/cursor/known_f；200 LineagePage；稳定F，跨页才加载更多 | APP-FORM-READ；不改焦点／关联 |
| BND-FORM-RANGES | GET /requirements/{requirement_id}/documents/{document_id}/formation/artifacts/{artifact_ref}/ranges | role必传ORIGIN/CURRENT＋limit/cursor/known_f；200 RangePage | APP-FORM-READ；范围查询，不改关联 |
| BND-FORM-EVENTS | GET /requirements/{requirement_id}/documents/{document_id}/formation/events | limit/cursor/step_ref/branch_ref；200 EventPage | 同上／audit索引 |
| BND-FORM-CHANGES | GET /requirements/{requirement_id}/documents/{document_id}/formation/events/{event_id}/changes | limit/cursor；200 EntityChange页（固定event快照，data为document_id/event_id/total/items） | 同上 |
| BND-FORM-MEMBERS | GET /requirements/{requirement_id}/documents/{document_id}/formation/events/{event_id}/changes/{change_ordinal}/members | limit/cursor；200 MemberChangePage，固定事件与变化项 | APP-FORM-READ；不存在返回404 |
| BND-FORM-EVIDENCE | GET /requirements/{requirement_id}/documents/{document_id}/formation/events/{event_id}/closure-items/{owner_kind}/{item_ref}/evidence | owner_kind限RESULT/ISSUE/BRANCH；limit/cursor；200 ClosureEvidencePage；不能跨事件读取 | APP-FORM-READ；固定结束事实 |
| BND-FORM-CLOSURE | GET /requirements/{requirement_id}/documents/{document_id}/formation/events/{event_id}/closure-items | kind必传RESULT/ISSUE/BRANCH＋limit/cursor；200 ClosureItemPage | 同上；非Closure事件404 |
| BND-FORM-COMMAND | PATCH /requirements/{requirement_id} | DTO-NATIVE；200 ProgramReceipt；ADJUST_PATH的COMMIT复用此入口 | APP-FORM-NATIVE／PATH／PROPOSAL；commands.update_discussion |
| BND-FORM-PREVIEW | POST /requirements/{requirement_id}/documents/{document_id}/formation/path-preview | body={expected_discussion_version,discussion_command:ADJUST_PATH严格分支,section?,limit?,cursor?}；200 PathPreview；无key、无消息／编号／审计 | APP-FORM-PATH::PREVIEW；新增只读HTTP入口 |
| BND-FORM-DISCUSS | POST /requirements/{requirement_id}/guide-runs | FormationDiscussInput；202原RunAccepted扩展；占用／版本保护保持 | APP-FORM-DISCUSS；guide/api.py及commands |
| BND-FORM-APPLY | POST /conversation-messages/{message_id}/responses | 原正式回答body＋DTO-DISCUSS限定；200 ProgramReceipt；原普通purpose保持原处理 | APP-FORM-APPLY；原messages responses入口→guide/card_commands |
| BND-FORM-RUN | GET /guide-runs/{guide_run_id}；POST /guide-runs/{guide_run_id}/cancel | 原读／取消契约；读取增加RoundResult；取消沿原key，无新AI请求 | 原guide/api.py／queries／commands |

每个入口allowed_errors以如下集合严格登记，不假设全局枚举自动允许：READ允许VALIDATION_FAILED、NOT_FOUND、STATE_CONFLICT、STORAGE_UNAVAILABLE、INTERNAL_ERROR；PREVIEW在READ上加FORMATION_INVALID／FORMATION_LIMIT_EXCEEDED／DISCUSSION_VERSION_CONFLICT／CONTENT_VERSION_CONFLICT；COMMAND在PREVIEW上加WORK_STATE_CONFLICT／WORK_STATE_INCONSISTENT／IDEMPOTENCY_CONFLICT／REQUEST_IN_PROGRESS；APPLY在COMMAND上加CARD_ALREADY_ANSWERED／CARD_EXPIRED／SOURCE_INVALID／SCOPE_INVALID／PATCH_INVALID／TARGET_STALE／CONFIG_INVALID；DISCUSS沿原创建运行白名单再加FORMATION_INVALID／FORMATION_LIMIT_EXCEEDED及本章登记STATE原因。不存在的新卡与文档归属失败用NOT_FOUND，避免跨范围泄露。

新增422 FORMATION_INVALID details=null；FORMATION_LIMIT_EXCEEDED details={resource_kind:CHANGE_COUNT/CHANGE_BYTES/PAGE_SIZE/STEP_RESULTS/MODEL_INPUT,limit:非负安全整数,actual:非负安全整数}。STATE_CONFLICT安全details为null或`{reason,step_ref:null或StepRef,proposal:null或ProposalRef}`，reason限FORMATION_NOT_INITIALIZED/ARTIFACT_SUPERSEDED/PATH_CHANGED/GOAL_CHANGED/STEP_DEFINITION_CHANGED/TARGET_CHANGED/BRANCH_STATE_CHANGED/BRANCH_RETURN_MISMATCH/PROPOSAL_ADJUSTING/PROPOSAL_BASIS_CHANGED/SOURCE_UNAVAILABLE/INVALID_TRANSITION。原版本错误和field_errors沿既有安全形状，不能泄漏当前库全状态。实施须扩展http_errors.py及前端严格解码器；未登记非空details不能透传。浏览器不根据code猜业务已回滚，超时另属UNKNOWN。

#### DTO-MODEL Canonical／Wire／Output

Canonical保留原真实documents/messages/discussion/resources/model等域，增加`formation`读模型、`formation_selection`和`proposal_context`。formation不是全历史大JSON：包含Goal、选定Step全定义／依赖摘要、选定支线、相关OPEN问题、当前Artifact／待复核范围、最新评估／建议，以及候选实体索引的明确覆盖；formation_selection为冻结TargetSelection。proposal_context为空或调整原卡的原payload、旧依据和用户新要求。程序私有完整真实身份／范围／授权／图／来源basis独立存在，不把“未发送但已在库”的内容伪装模型已读。

Wire根严格为schema_version、structure、goal_and_decisions、project_position、current_topic、documents、recent_history、current_request；schema_version=1，键顺序沿此实际compiler定义。CURRENT_REQUEST在原当前消息／operation字段内新增formation_selection、proposal_intent及proposal_ref；project_position增加formation:{goal,selected_step,selected_branch,related_issues,artifacts,assessment,recommendation,coverage}；其余不放平行完整副本。output_guide职责沿原system资源，不新增Wire根；全部新增字段只在新release及新compiler接受，不给旧资源插字段冒充兼容。序列化固定为实际资源serializer输出，UTF-8；ContextBasis同时保存确切Wire／system摘要与真实选择，重放不得重新读取当前库扩大上下文。

新Output根恰好沿原九根：schema_version=1、response_type、message、basis_ref、progress_delta、cards、document_result、suggestions、analysis。DISCUSSION的document_result/suggestions/analysis=null；message为合法可读说明，basis_ref沿原冻结D／phase／guide引用。progress_delta保留原topic_changes/evidence_changes/focus_topic_ref/next_step/processed_user_message_ids，增加formation_delta:null或{basis,changes}。未提供进展时原progress_delta=null；有formation必须有完整外层。basis为formation_version／goal_version可空、document_revision_id／content_version必有；必须等于冻结真实值。changes最多20项及64KiB，12型严格联合：

| type | 完整新增业务字段（type以外） |
| --- | --- |
| INITIALIZE_PATH | goal:{text,source_refs}；steps:StepDraft[]；StepDraft={temp_ref,title,expected_results:[{temp_ref,description,kind}],dependencies,topic_refs}。仅F／Goal为空，一个初始化变化；第一步程序IN_PROGRESS且当前，其余PLANNED |
| ADD_STEP | temp_ref、title、expected_results（同StepDraft）、dependencies、topic_refs、before_step_ref:null或真实／临时StepRef |
| UPDATE_STEP | step_ref、title:null或Title、add_results:[{temp_ref,description,kind}]、dependencies:null或完整StepRef[]、topic_refs:null或完整真实主题引用[]；null表示该字段不改，至少一项实变 |
| MOVE_STEP | step_ref、before_step_ref:null或StepRef |
| ADD_ISSUE | temp_ref、step_ref、branch_ref:null或BranchRef、description、blocking:boolean、source_refs；初始OPEN |
| UPDATE_ISSUE | issue_ref、description:null或Text、blocking:null或boolean、resolution:null或{summary:Text,source_refs}；不能改用户处置，RESOLVED必须真实来源 |
| ADD_BRANCH | temp_ref、origin_step_ref、return_step_ref、question、relevance、topic_refs、source_refs；初始OPEN |
| UPDATE_BRANCH | branch_ref、topic_refs:null或完整集合、result:null或{summary:Text,source_refs}；只有OPEN可补当前结果并记RESOLVED，不能清既有结果伪恢复 |
| SET_BRANCH_FOCUS | branch_ref:null或BranchRef、reason:Text；仅冻结当前步骤所属OPEN支线；null返回主线，不迁移其他步骤 |
| ASSESS_STEP | step_ref、definition_version、verdict:SUFFICIENT/GAPS_REMAIN/UNCERTAIN、reason、document_refs:已发送区块别名[]、source_refs |
| RECOMMEND | step_ref、action:DISCUSS/WRITE/RESOLVE_BRANCH/REVIEW_CONTENT/COMPLETE_STEP/SWITCH_STEP/NEED_MATERIAL、reason、target_step_ref:null或StepRef、source_refs |
| ASSOCIATE_CONTENT | step_ref、result_refs、document_refs:当前真实区块别名非空、source_refs、review_of:null或ArtifactRef；只能提出关系，由程序核实生成或复核 |

DTO-MODEL中的所有新增source_refs是本轮Wire确已携带的AliasRef字符串集合（AliasRef由本轮alias目录给出，1—160码点，不是可任意构造的SQL身份）；它与Canonical／公开DTO的SourceRef对象类型分开。程序接收时按用途构建持久化CanonicalCardPayload：两种卡的真实来源别名都解析为真实SourceRef；STAGED_WRITE只解析同轮合法formation_delta已实际创建的步骤／成果，绑定本轮真实身份；FORMATION_PATH_CHANGE自身changes／result_routes中声明的未来实体保留PathStepRef／PathResultRef及局部声明域，只做符号图校验，绝不提前建实体或耗编号。引用现有实体仍核实真实身份。用户采用时由CARD_APPLY从不可变payload建立单独执行映射，成功回执与正式历史仅用真实引用；原卡／模型冻结basis不改写；原模型Output原字节另存，正文／补丁／范围字节不重写。此后不可变提案指这份已验证Canonical payload，前端及后续命令不得替换，不能每次读取重新解释旧别名。所有新增source_refs是本轮Wire确已携带的别名集合，集合最多100项；一项关联document_refs最多100个区块，超限明确分批，不接受“全文已读”通配符。formation中相关实体选材总共最多100个，按下一段硬／软材料顺序确定，未包含的coverage明确标缺失；不是数据库实体上限。初始化steps最少1且最多20，每步成果1—20，其他变化单次规则沿2.2。权限：仅未开始的未定细节可UPDATE_STEP；既定成果不删除／改kind，不缩小Goal，不处理用户结束／放弃／恢复。重大变化用路线卡，不能formation_delta先改一遍再等采用。同轮含FORMATION_PATH_CHANGE卡时formation_delta必须null；STAGED_WRITE不能与其目标步骤的实质定义变更同轮接收；冲突拒绝整个进展／形成／新卡结构单元，保留可读文本及pending。

选材顺序：硬材料为用户本轮完整输入与冻结目标、有效Goal／长期约束、当前真实Revision及精确写入保护范围、目标Step／Branch和相关阻塞问题／当前成果、调整原payload及用途依据；软材料按相关实体稳定顺序、近期历史原10条窗口及可裁背景。先执行原预算策略删除可裁历史／背景，仍超限不Chat，返回实际缺口。无关已结束历史不全文携带；所有取舍登记included/omitted及原因。全图／存在性校验走程序DB，不依赖模型看到所有节点。

八项计数严格对应当前collaboration_context.texts的真实八段：system、input_json、current_request、structure、documents、recent_history、goal_and_decisions、project_position＋current_topic。计数文本从最终Wire实际UTF-8序列化恢复，不另按Logical JSON重排计算；空段沿原''规则。第1／2用于实际输入准入，其余用于解释，不加总重复计数。新增formation放在project_position，目标在current_request，原精确卡在相关材料，一份内容只在确定位置出现。新layout映射随新release固定，私有basis不计为模型已发送。计数API调用批次／profile沿原真实策略和准入，不把原通用六文本计数误当本链八项。

### 6.3 交互示例（示意身份，可重建）

```json
{"document_id":42,"expected_discussion_version":32,"discussion_command":{"type":"FORMATION","action":"RESUME_BRANCH","step_ref":"s2","branch_ref":"b4","expected_branch_status":"RESOLVED","expected_branch_event_id":901,"enter_after_resume":true}}
```

假设此支线event901为最后结果，return=s2，关联OPEN问题均属s2。成功只恢复／选择完整目标，PROGRAM、0Chat，D33／F14／V4；下一轮DISCUSS使用ENTER、branch_resume_basis=null。若event902已产生新结果，旧请求未成功记录则BRANCH_STATE_CHANGED；若原key已有成功则原回执重放，不能清902。

### 6.4 内部触发与回收

| 入口／事件 | 输入、责任与交付语义 | 失败／取消／重投 |
| --- | --- | --- |
| 原commit_content内部hook | 同连接旧／新Revision、DocumentEffect、真实来源；APP-FORM-CONTENT维护所有受影响Artifact | 不单独commit；失败连同内容事务回滚 |
| 原Worker接收模型结果 | 冻结GuideRun、租约、Output；APP-FORM-DISCUSS先验证再原子接收 | 失去租约不写；无自动Chat重投；合法可读文本与失败effect如实记录 |
| 运行状态读取／取消 | 复用已有轮询和取消，无SSE/WebSocket新协议 | 取消不撤销已提交接受动作；不向供应方声明虚构取消完成 |
| 维护升级入口 | 明确源manifest、目标独立路径及检查模式；APP-FORM-UPGRADE | 不随HTTP请求启动，不覆盖源库；未知源或在途拒绝 |

没有另建消息Broker、订阅或跨进程自动重试；上述hook是同应用真实调用边界，不是另设外部API。

## 7. 数据与技术依赖

<a id="inf-form-store"></a>
### 7.1 INF-FORM-STORE 存储结构与持久化

采用原SQLite连接／事务管理及严格Schema发布方式，外键必须开启；实际源V2.0为Schema200／db20-r48，DDL摘要见来源核对记录。以下是目标物理字段定义，不是已执行DDL。新增表属于原文档根，不另建业务库。TEXT全部UTF-8，JSON列为本文对应严格结构的canonical JSON并CHECK json_valid；版本／计数INTEGER安全正整数，布尔INTEGER CHECK IN(0,1)，时间TEXT UTC。下表未标`NULL`均NOT NULL；空集合[]而非NULL。公共doc列为document_id INTEGER FK requirement_documents.id，限定CURRENT且同需求；复合引用都带document_id，禁止串文档。

| 新目标表 | 字段与主键／唯一 | 外键、检查与主要索引 |
| --- | --- | --- |
| formation_heads | document_id PK；version、goal_version INTEGER；goal_text TEXT；goal_sources_json TEXT；current_step_ref TEXT NULL；active_branch_ref TEXT NULL；next_step_no、next_branch_no、next_issue_no、next_artifact_no INTEGER | 文档唯一；CURRENT约束；焦点复合FK可延迟至事务结束校验；无头部表示未建线，不能补空头掩盖损坏 |
| formation_steps | (document_id,step_ref TEXT) PK；definition_version、next_result_no、position INTEGER；title TEXT；status TEXT；closure_event_id INTEGER NULL | status五态；(doc,position,step_ref)索引，position在同文档有效步骤唯一；取消保留原位置于事件，当前position可使用保留负序值且不参与有效序唯一；closure引用原audit |
| formation_results | (doc,step_ref,result_ref TEXT) PK；description TEXT；kind TEXT；UNIQUE(doc,result_ref) | 复合Step FK；CONTENT/ANALYSIS；引用必须属于步骤；结果删除／类型改变只能显式路线取舍，不复用result编号 |
| formation_step_edges | (doc,from_step_ref,to_step_ref,kind TEXT) PK | 两端复合FK；kind DEPENDENCY/REPLACES；禁止自环；两类分别全图无环；入边／出边索引 |
| formation_step_topics | (doc,step_ref,topic_ref TEXT) PK | Step FK；真实同文档Discussion主题核验；不复制Topic对象 |
| formation_branches | (doc,branch_ref TEXT) PK；origin_step_ref、return_step_ref、question、relevance、status TEXT；origin_event_id、state_event_id INTEGER；result_summary TEXT NULL；result_sources_json TEXT；disposition_event_id INTEGER NULL | origin／return Step FK；事件同文档；status四态；RESOLVED结果与来源非空，用户处置有真实事件；(doc,return_step_ref,status)、(doc,status,branch_ref)索引 |
| formation_branch_topics | (doc,branch_ref,topic_ref TEXT) PK | Branch FK；原Topic存在性核实 |
| formation_issues | (doc,issue_ref TEXT) PK；step_ref TEXT；branch_ref TEXT NULL；description TEXT；source_refs_json TEXT；blocking INTEGER；disposition TEXT；disposition_reason TEXT NULL；resolution_sources_json TEXT；disposition_event_id INTEGER NULL | Step／Branch复合FK；处置OPEN/RESOLVED/DEFERRED/DROPPED；(doc,step_ref,disposition)、(doc,branch_ref,disposition)索引；双OPEN归属由7.2校验 |
| formation_artifacts | (doc,artifact_ref TEXT) PK；step_ref TEXT；source_event_id、origin_revision_id INTEGER；origin_digest TEXT；summary TEXT；checked_against_revision_id INTEGER；freshness TEXT；review_reason TEXT NULL | Step／真实Revision／审计FK；freshness CURRENT/NEEDS_REVIEW/REMOVED；review_reason TEXT NULL，取CHANGED/UNVERIFIABLE，和freshness联合CHECK；origin字段不可改；(doc,step_ref,freshness)索引 |
| formation_artifact_results | (doc,artifact_ref,result_ref) PK | Artifact／Result复合FK且同Step；一项关联至少一成果；不以结果路由移动旧原始来源 |
| formation_artifact_ranges | (doc,artifact_ref,role TEXT,ordinal INTEGER) PK；revision_id INTEGER；block_id INTEGER；block_digest TEXT | role ORIGIN/CURRENT；复合Artifact及真实块／Revision核验；(doc,revision_id,block_id,role)反查索引；ORIGIN不可变，CURRENT仅程序可核实更新 |
| formation_assessments | id INTEGER PK；doc、step_ref、event_id、assistant_message_id、goal_version、definition_version、evaluated_revision_id；verdict TEXT CHECK SUFFICIENT/GAPS_REMAIN/UNCERTAIN；reason TEXT；coverage_json TEXT；source_refs_json TEXT | 不可变；Step／原消息／Revision／event同文档；(doc,step_ref,event_id DESC)查最新；coverage为实际最多100个携带区块，不声称全文 |
| formation_recommendations | id INTEGER PK；doc、step_ref、event_id、assistant_message_id；action、reason TEXT；target_step_ref TEXT NULL；source_refs_json TEXT；basis_json TEXT | 同上；basis_json为不可变RecommendationBasis；目标同文档，建议不直接改生命周期；最新按event_id读取，再按当前实际依据派生有效性，不能仅因最新而标CURRENT |
| formation_proposal_index | (doc,message_id,card_key TEXT) PK；purpose、disposition TEXT；disposition_event_id INTEGER NULL；binding_json TEXT；payload_digest TEXT | 原消息及原卡是不可变payload真源；binding_json为原卡权威不可变PublicationBinding，payload_digest与之绑定；只有处置投影可据事件重建，绑定损坏／缺失拒绝写入，不用当前数据伪补；(doc,purpose,disposition,message_id,card_key)索引 |
| formation_event_refs | (doc,event_id,kind TEXT,ref TEXT) PK | event原audit FK；kind STEP/BRANCH/ISSUE/ARTIFACT/RESULT；(doc,kind,ref,event_id DESC)索引；同事务无temp |
| formation_event_changes | (event_id,ordinal INTEGER) PK；doc、entity_kind、entity_ref TEXT；before_json TEXT NULL；after_json TEXT NULL；member_count INTEGER；member_digest TEXT | audit FK；不能双NULL；每行一项有界标量EntitySnapshot及member_count／member_digest独立列；PROPOSAL_CHECK与ARTIFACT_REVIEW分别增加部分UNIQUE(event_id,entity_kind,entity_ref)，保证同事件同主体的复核事实唯一；逻辑集合另存event_members；创建／取消保存STEP标量与全部RESULT／成员变化及位置 |
| formation_closures | event_id INTEGER PK；doc、step_ref、definition_version、goal_version、revision_id、command_message_id；next_step_ref TEXT NULL；result_count、issue_count、branch_count INTEGER；items_digest TEXT | audit／Step／Revision／真实用户消息FK；只USER结束；不可变，缺项不能发布成功 |
| formation_closure_items | (event_id,kind TEXT,item_ref TEXT) PK；ordinal INTEGER；status TEXT；payload_json TEXT | closure FK；kind RESULT/ISSUE/BRANCH；payload严格为不含证据数组的ResultClosureItem或RemainingClosureItem；(event_id,kind,ordinal)索引，完整证据在子表 |
| formation_closure_evidence | (event_id,owner_kind TEXT,item_ref TEXT,ordinal INTEGER) PK；evidence_kind TEXT；artifact_ref TEXT NULL；payload_json TEXT | 复合FK到closure_items；单条严格ClosureEvidenceItem；(event_id,owner_kind,item_ref,evidence_kind,ordinal)索引；所有结束证据含范围逐行冻结、只追加不可变 |
| formation_event_members | (event_id,change_ordinal INTEGER,ordinal INTEGER) PK；document_id INTEGER；collection TEXT；member_key TEXT；before_json TEXT NULL；after_json TEXT NULL | 复合FK到event_changes；单条MemberDelta，不能双NULL；UNIQUE(event_id,change_ordinal,collection,member_key)；不可变、按ordinal分页 |
| formation_artifact_reviews | (doc,event_id,reviewed_artifact_ref TEXT) PK；replacement_artifact_ref TEXT NULL；result TEXT；checked_against_revision_id、assistant_message_id INTEGER；source_refs_json TEXT | 对应ArtifactReview；同文档同Step及同一完整成果集合；REASSOCIATED时replacement非空且在本事务新建，其他result必空；部分唯一索引UNIQUE(doc,reviewed_artifact_ref) WHERE result=REASSOCIATED及UNIQUE(doc,replacement_artifact_ref) WHERE result=REASSOCIATED，分别保证唯一后继／前驱；无环校验；reviewed＋event倒序索引；每行与同event/ref的ARTIFACT_REVIEW变化一一对应，事务内核实 |

表名中的doc是字段document_id的书写缩写，不生成名为doc的第二列。所有实体的旧事件／来源表正常保留，不级联删除原Revision／消息／卡／审计；新增FK删除策略RESTRICT。当前字段更新、关系替换均记录前后变化，审计／Closure／ORIGIN／review追加记录受不可变写保护。JSON仅承担有界值对象与单项标量快照；正文／补丁留原不可变消息，逐成员数据放子表，禁止把大集合再包进payload_json，不用整份终身FormationState JSON承载关系。

公开StepView.position对有效步骤为当前正序号；对CANCELLED从其取消事件before.position读取原正序号（显示“原第N步”），不暴露物理保留负值。若该必需历史缺失明确状态损坏，不拿负数或当前其他节点序号替代。position用于显示顺序，真实身份仍step_ref。MOVE／ADD在事务内以临时保留区重排受影响position再落实唯一有效顺序；不得先提交空序列，取消节点不占有效序号。全图关系核验从完整DB投影读，不依据浏览器第一页；按引用稳定排序进行拓扑检测，依赖与替代分别检测，最大深度不以递归栈限制业务数量。实际有效顺序完整覆盖全部非CANCELLED步骤。

初始化：旧文档没有formation_heads即未建线；保留D及旧discussion_state原字节，不把旧phase/topic机械转换为新Step。不复制正常业务数据到本轮测试目录。源db20-r48 DDL、CHECK、索引／触发器和manifest须与固定摘要一致后生成完整目标DDL。目标数值Schema／目录由真实发布统一分配，不能猜201或把本设计表直接写进运行库。正式DDL及升级入口、演练是实施交付，不是本文已执行事项。

<a id="inf-form-transaction"></a>
### 7.2 INF-FORM-TRANSACTION 事务、并发及来源保证

| 阶段 | 同连接处理与不变量 | 失败边界 |
| --- | --- | --- |
| 认领 | 原需求锁及幂等认领，先读成功回执；核实真实工作状态／执行租约 | 不把其他文档占用当空闲；PROCESSING按原所有权机制核实 |
| 校验 | 原D CAS、目标及卡私有相关basis、V／Revision／定义／Goal；全批temp映射、全DB关系与来源校验 | 不分配正式编号，不改变用户payload；预览同算法但不认领写事务 |
| 计算 | 真实差异、结果路由、关闭事实及全部受影响Artifact；全图无环／存在／双OPEN；counter严格高于已分配身份 | 一项失败全部拒绝，不局部采纳合法子项 |
| 写入 | 内容＋Revision（如有）、正式回答／用户动作、实体关系、原audit与变化／Closure行、提案处置、D／F及回执 | 任意插入／audit／回执失败整体回滚；D／F每事务各最多1 |
| 提交 | 原commit结果及异常分类；成功回执持久化与业务相同事务 | CommitOutcomeUnknown不猜回滚；实际成功回执可重放；无先提交业务再补回执窗口 |

COMPLETE逐行扫描该Step成果、所有当前问题以及return指向它的支线，生成标量Closure明细及逐条formation_closure_evidence（RESULT包括当前活动关联及其全部ORIGIN/CURRENT范围、分析与来源；ISSUE/BRANCH逐来源）；按kind/ref、证据kind／稳定身份排序再分配ordinal、流式计算每项及总digest；用户未选去向保持KEEP_OPEN，缺CONTENT或不可核实记OUTSTANDING。流式插入可以使用SQL批量但仍一个事务，不因明细多拆成多个提交。一次请求20项限制是用户变化项，不限制程序完整保存当时事实。明确转交和next_step同批执行；任一归属或快照失败，整个完成回滚。PLANNED可直接结束，无伪造开始事件。

真实内容维护覆盖MANUAL_EDIT、GENERATE、REVISE、既有SuggestionBatch应用、历史恢复及新CARD_RESPONSE。以原块身份／来源链和区间摘要定位实际受影响Artifact；未触及的保持。全文恢复逐项重新比较，不能把所有关联设CURRENT。相同来源可追溯且内容／区间一致才CURRENT；内容改动保留关系并标NEEDS_REVIEW／CHANGED，确认全部范围消失标REMOVED／null，无法核实标NEEDS_REVIEW／UNVERIFIABLE。与AI充分性分开；同内容无新Revision，必要新关联仍有事件。

CARD_RESPONSE为本设计新增的可信正文来源，必须扩展新版本块来源／Revision／DocumentEffect解码与白名单：source_type=CARD_RESPONSE、actor=USER、conversation_message_id为原AI卡消息ID、card_key为原卡、response_message_id为本次真实正式用户回答。三项同卡同文档核实，content.py仅接受程序构建的本次精确授权；模型／客户端不能提交来源对象开权限。新资源compiler可将其投影为真实用户采用依据，旧资源不认识时按原版本适配或明确UNSUPPORTED，不能误当GUIDE_RUN。区块、Revision及审计引用一致，既有不可变CodeDesignRevision等不回写。

相关普通讨论复核：ASSOCIATE_CONTENT.review_of核实旧Artifact及本轮实际当前块。同源范围可证实则记录MATCHED并更新程序检查头；内容替换但同用途可证实则创建真实新Artifact并记REASSOCIATED，旧来源及原freshness保持，当前投影用replacement链只计活动末端；缺材料记录ArtifactReview.result=UNVERIFIED、关联为NEEDS_REVIEW／UNVERIFIABLE并保留提示。关系链同文档／同Step／同一完整成果集合、无环，一次review不能指向未创建或未携带的假成果；REMOVED不能靠说明直接变CURRENT。AI ASSESS_STEP另存实际覆盖／不足，不自动重开步骤，不重写Closure，不另Chat。

替代事务规则：先按原命令／运行租约处理成功重放，再检查reviewed_artifact_ref在当前事务没有REASSOCIATED后继。MATCHED只更新当前叶的程序匹配，REASSOCIATED必须新建此前不存在的Artifact并一次写新关系与其范围；旧来源／旧状态保持。已有后继时，不同请求或运行再次review旧节点一律ARTIFACT_SUPERSEDED，不能NO_CHANGE掩盖新意图，也不沿链自动改目标；Worker以STRUCTURED_REJECTED／STATE_CONFLICT安全原因拒绝整个本轮结构并保留pending，普通命令按409 STATE_CONFLICT返回。用户可查看链末端后在下一次正常讨论明确复核，程序不额外Chat。生产入口仍遵守同需求单运行／租约串行，不新增并行模型权限；两个连接的竞争属于存储不变量专项／故障注入，先提交者建立关系，后者在事务内重验失败；唯一索引为最后数据库保护，失败回滚新Artifact／事件／全部结构效果。

正常后续a1→a2→a3必须第二次明确review当前a2，保持不相交线性链；禁止a1→a3分叉、两个前驱合并同一新ID以及环。历史review写读契约：每一条formation_artifact_reviews行必须在同一事务的formation_event_changes中有且只有一条entity_kind=ARTIFACT_REVIEW、entity_ref=reviewed_artifact_ref、before=null、after=ArtifactReview的对应事实，二者字段逐一相同。REASSOCIATED用ARTIFACT_REASSOCIATED事件，其他真实检查结果用ARTIFACT_CHECKED；actor=PROGRAM，assistant_message_id保存真实触发回复，checked_against_revision_id保存当时核实版本，source_refs沿当时真实来源。状态／范围实际变化另记ARTIFACT及MemberDelta，不能用二者替代review边；真正NO_CHANGE不制造检查事实或事件。

历史页面只经固定event_id的CHANGES读取ARTIFACT_REVIEW，随同EventView取得document_id／event_id／actor／批次版本和时间；source_refs与assistant_message_id可沿原来源入口只读打开，缺失明确显示不可用，不伪补新来源。此投影有界（每项source_refs≤100），不新增无限列表；多项review仍按CHANGES分页。按事件顺序处理REASSOCIATED事实即添加真实reviewed→replacement边，MATCHED／UNVERIFIED／REMOVED不增删边；只重放截至指定事件即可恢复当时链，不能用当前is_active/freshness替代旧值。

当前ArtifactView／LINEAGE额外给出前驱和后继的review_event_id，便于从当前链直接打开当次不可变review；这不是历史事实的真源替换。若a1→a2为E1、a2→a3为E2，读E1永远只得到a1→a2及E1的原消息／Revision／来源；E2和后来内容状态不会回写E1。任意review行、变化事实、关联／范围或回执失败，按原DISCUSS结构单元整体回滚。

当前Artifact页及Step ARTIFACT关系页默认只返回is_active=true，计数采用同文档／成果下DISTINCT活动artifact_ref；include_superseded=true明确查询历史，默认计数不随此筛选改变。inactive的a1仍可按ID读详情／原范围与替代链；Closure只冻结当时活动节点及证据，后来链推进不回写旧Closure。


数据升级仅在明确维护任务时执行：固定源代码状态＋完整manifest＋DDL摘要，拒绝未知源、未核实PROCESSING／在途；源库只读，新目标独立路径。复制原对象／身份／资源与消息回执原字节，添加空新结构，核对行数、外键、关键摘要、真实来源及原回执可重放，再出Markdown结果。任何失败不切服务、不覆盖源；目标临时产物按本次允许范围清理。目标服务切换需要当轮用户授权；本轮没有执行升级。

<a id="inf-form-model"></a>
### 7.3 INF-FORM-MODEL 模型与计数依赖

| 项目 | 明确定义 |
| --- | --- |
| 适配入口 | 原guide/model_gateway、ModelProfile与计数适配；业务Prompt／上下文在4.7和6.2，不另建Formation供应商 |
| 供应商及模型定位 | 沿实际ModelProfile冻结；本工作区默认deepseek-v2及长输出deepseek-long-v3，源标识deepseek-v4-1-flash-260910／版本260910，遗留doubao-v1按原历史读取；这仅描述仓库来源，不宣称供应商当前兼容 |
| URL／凭据 | 原可信Runtime配置解析，URL不由用户正文／模型选择，secret不进入保存快照；记录配置名及安全来源 |
| 结构化返回 | 非流式原严格JSON Output，新增release＋运行校验；无工具循环，无备用模型静默切换 |
| 参数来源 | temperature=0、thinking disabled、stream=false；max_tokens普通8192／长输出32768，以冻结Profile原值为准；任务不覆盖 |
| 超时／重试 | 原connect10秒、read180秒、write10秒、pool10秒；transport_retries=0；本任务无业务自动重试／输出修复；超时按真实发送事实记录 |
| 计数 | 原真实计数端点／Profile与策略；按实际八文本及最终Wire编译候选计数，预算不足不Chat；未授权时不得为设计核对调用 |
| 取消 | 发送前取消不外发；发送后请求abort与远端完成可能不同，按原运行终态及租约判接收；不凭页面离开声称远端停止计费 |
| 记录 | 原请求快照、release/Profile、Wire/system摘要、selected/omitted、真实计数、尝试数、供应商requestID及可取得usage；未知字段为null，不把未取到用量当0 |

新发布资源逻辑`formation_v21_1`及layout `formation_context_v21_1`必须包含本章类型、DTO、Prompt、cards、可信来源、Canonical/Wire/Output、serializer及计数映射，并通过独立新release准入。实际物理目录、manifest及数值Schema在正式发布分配，不修改旧版本字节；旧LIVE仅对旧资源有效。准入必须含严格JSON／来源／预算／私有分离离线证据和另行授权真实供应商兼容证据；本轮均未执行新资源准入。

### 7.4 INF-FORM-RESOURCE 资源、审计与客户端依赖

| 依赖 | 结构、生命周期及保证 |
| --- | --- |
| 冻结资源文件 | 原manifest精确路径与hash、UTF-8原字节；新目录新增，不覆盖旧Schema／Prompt／计数。真实发布前校验全部引用只指有效资源，未知／缺失CONFIG_INVALID |
| 接受上下文／审计 | 原GuideRun快照和可重放私有basis同数据库事务，读请求仅展示已保存事实；不读取当前正文替代旧Wire，不以模型解释填历史 |
| 历史源对象 | 原Revision／消息／卡片／旧resource版本；缺失或不支持明确MISSING/UNSUPPORTED并保留关联，不删历史 |
| 浏览器草稿／命令 | 由前端7.4定义隔离键及恢复；不是服务端正式业务真源，不能用浏览器草稿重建正式card payload／Closure |

不新增文件上传、外部消息队列或跨资源事务；数据库成功与浏览器保存成功分别报告。代码／文档原子写入约定继续执行，不因本规格允许覆盖运行源码。

## 8. 验证与验收

### 8.1 TC-FORM 共享验收场景

以下A01—A76完整保留大纲0.12的预期，补齐独立可重建夹具与操作。每项从干净隔离库建立，不依赖上一项执行；具体自动化函数可由实施决定，期望不能调用被测实现生成。

公共夹具FBASE：需求7、CURRENT文档42、D30／F12／V4、Revision401，Goal1“形成个人电影推荐方案”，s1=COMPLETED、s2=IN_PROGRESS且当前、s3=PLANNED；每步定义1，s2.o1 CONTENT“推荐流程”、s2.o2 ANALYSIS“范围判断”。正文两个稳定块ID12（下文展示别名b12）=“用户选择影片，系统给出推荐。”、ID13（展示别名b13）=“用户可提交反馈。”；a1关联b12到s2.o1且CURRENT；b4 OPEN，origin=s1、return=s2，i1 OPEN／step=s2／branch=b4，另i2 DEFERRED／无支线。既有写卡m210/c1以401/V4/Goal1/s2定义1，精确PATCH将“给出推荐”改为“给出三条推荐”；路线卡m211/c1仅重排s3并追加s4。原消息、来源、事件和Profile/release均由隔离固定种子创建，原幂等记录为空；不读取用户库。涉及RESOLVED支线的变体b4最后事件901且结果有真实消息来源；涉及空白文档的变体V1/Revision101且实际空正文。所有变体只改变声明字段，其余沿FBASE。

FGROW：相同文档依次生成201步骤、1001支线／问题及2001历史Artifact，分记录保存，文案为“步骤N／问题N／内容N”，固定十进制顺序、无需随机数；再以1001步骤／10001事件做负载扩展。无历史上限，单次仍20项。FCONCURRENT为两个独立真实SQLite连接／两个浏览器标签，均先读同D，按用例指定屏障交错；FROLLBACK依次在正文、Revision、回答、关联、event、回执插入后及commit前注入实际SQL失败，每一变体从干净库开始。

| 场景引用 | 规格依据 | 前置与操作／故障 | 独立预期 | 证据方式 |
| --- | --- | --- | --- | --- |
| TC-FORM-A01 | APP-FORM-READ／SHR-FORM-PAGE及相关共享规则 | 无主线隔离变体；先GET Summary断言exists=false、F／焦点均null；前端不再请求步骤页；独立直接GET步骤页得409 FORMATION_NOT_INITIALIZED，文档不存在另为404；两者0调用／0写入 | GET无主线返回已读null，不调用模型或建线 | API／UI；当前未执行 |
| TC-FORM-A02 | APP-FORM-DISCUSS／REVIEW及相关共享规则 | 无主线两个独立变体：目的明确时一次DISCUSS返回合法三步INITIALIZE_PATH；普通术语问答返回message且formation_delta=null；分别核对真实来源、F及实体是否创建 | 首次有效形成工作建立路径，别名落为真实来源，F1；普通问答不强建线 | AI处理／API；当前未执行 |
| TC-FORM-A03 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE，先SWITCH_STEP s3；独立失败变体在焦点／D／事件／回执保存中注入故障；分别核对所有步骤状态、焦点与事务前后摘要 | SWITCH只改变焦点、不改生命周期；目标保存失败整批回滚 | SQLite专项；当前未执行 |
| TC-FORM-A04 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE；只查看s3；暂停非当前的独立变体先将s3设IN_PROGRESS，另从PLANNED s3直接结束；再分别作用当前s2及显式next=s3；核对每个分支的当前步骤、活动支线与输入 | 暂停／普通结束非当前节点不改当前步骤或支线；作用当前节点才清匹配焦点，明确下一步才转移；查看只读 | API／浏览器；当前未执行 |
| TC-FORM-A05 | APP-FORM-DISCUSS／REVIEW及相关共享规则 | FBASE；同次合法Output只含ASSESS_STEP verdict=SUFFICIENT及RECOMMEND COMPLETE_STEP，无正文／卡；接收后先断言s2仍IN_PROGRESS且V4，再点击COMPLETE_STEP并读取真实Closure及状态 | AI评估足够／建议完成不改步骤状态，用户点击后才完成 | AI处理／联调；当前未执行 |
| TC-FORM-A06 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE；s2无a1且评估GAPS_REMAIN，直接COMPLETE_STEP | 缺CONTENT或关联待复核时仍可结束；Closure记真实遗留，不改正文 | 服务专项；当前未执行 |
| TC-FORM-A07 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | 两个独立变体：s2仅有ANALYSIS o1、消息m220为真实分析依据、无Artifact，结束并检查ANALYZED且V4；另保留一个未落地CONTENT o2，以同m220分析来源结束，检查o2=OUTSTANDING而非LANDED，V仍4 | ANALYSIS成果有真实记录可无正文结束，不能替代CONTENT | 服务专项；当前未执行 |
| TC-FORM-A08 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | 成功变体FBASE，s3依赖未完成s2；COMPLETE_STEP不传遗留处置且next=s3，逐页读Closure全部成果／i1／i2／return=s2的b4，核对真实OUTSTANDING及KEEP_OPEN／原归属和焦点。独立FROLLBACK变体在Closure插入失败，核对全部回滚；两变体不共用库 | 程序补齐全部真实结果／问题／支线快照，无明确处置保持OPEN；next不受依赖完成门槛阻止 | 服务专项；当前未执行 |
| TC-FORM-A09 | APP-FORM-PATH及相关共享规则 | FCONCURRENT；Goal／定义变更后提交旧COMPLETE；另仅重排 | 目标／定义变更使旧完成请求拒绝；重排不使无关提案失效 | API／服务；当前未执行 |
| TC-FORM-A10 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE；结束→REOPEN，再路线取消旧步 | 重开保留旧Closure；放弃保持正文、来源和替代关系 | 服务／浏览器；当前未执行 |
| TC-FORM-A11 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE先设当前s3，再一次ENTER_BRANCH(step=s2,branch=b4)并RETURN_FROM_BRANCH；核对origin仍s1、return仍s2、当前完整焦点与OPEN状态 | 跨步骤进入OPEN支线原子选择处理节点及支线；来源保持；返回仍可OPEN | 联调／浏览器；当前未执行 |
| TC-FORM-A12 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE；分别暂缓／放弃／恢复问题，RESOLVED b4恢复 | 暂缓／放弃保留原决定；暂缓问题可明确恢复；已有结果支线可继续，旧结果不丢 | 服务／浏览器；当前未执行 |
| TC-FORM-A13 | APP-FORM-DISCUSS／REVIEW及相关共享规则 | FBASE；Output把合法ADD_ISSUE与非法完成混合 | AI不能静默变目标／取消／完成／放弃；非法混合增量全部拒绝并保留pending | AI处理专项；当前未执行 |
| TC-FORM-A14 | APP-FORM-DISCUSS／REVIEW及相关共享规则 | FBASE；分别未声明temp、跨doc、循环依赖和伪block别名 | 临时引用未声明、跨文档引用、依赖成环和伪材料均拒绝 | 服务专项；当前未执行 |
| TC-FORM-A15 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | 空白文档变体FILL_EMPTY；另非空／混带patch | FILL_EMPTY真实空白首写；两种内容混传或非空目标拒绝 | 内容专项；当前未执行 |
| TC-FORM-A16 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | FBASE；精确PATCH原文错、越scope、修改模板或body替换payload | PATCH原文／范围／模板保护完整；客户端替换卡片正文拒绝 | 内容／API；当前未执行 |
| TC-FORM-A17 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | FBASE；确认m210/c1，记录实际网关尝试数 | 确认应用为PROGRAM、0Chat且一次正式回答；步骤生命周期保持，不因写入自动结束或重开 | 联调；当前未执行 |
| TC-FORM-A18 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | FROLLBACK；分别故障注入apply各保存阶段 | 写入任一保存阶段失败，正文／Revision／回答／主线／回执一起回滚 | SQLite专项；当前未执行 |
| TC-FORM-A19 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | 固定有效卡以当前401/V4提出与已保存内容精确相同的写入，Scope及原文均合法；首次关联另一真实CONTENT成果；apply后检查V／Revision行数不增，回答消费与新关联／事件真实保存；不能通过先改V造此变体 | NO_CHANGE不造Revision；新关联及正式消费仍有真实处置 | 服务专项；当前未执行 |
| TC-FORM-A20 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | FBASE；暂缓→恢复→调整失败→撤回 | 暂缓未消费卡片，恢复后可apply；调整失败禁用旧文，撤回需版本仍匹配 | API／浏览器；当前未执行 |
| TC-FORM-A21 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | FCONCURRENT；服务器成功后丢200，原key重发 | 成功请求超时，同key重放先于新版本检查，零重复写入／Chat | 幂等集成；当前未执行 |
| TC-FORM-A22 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | FBASE；同key改body；另收到200后GET断网 | 同key异输入拒绝；UNKNOWN原body保存，200后GET失败不显示保存失败 | API／浏览器；当前未执行 |
| TC-FORM-A23 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | FCONCURRENT；另页改V／仅D；另文档真实占用 | 另一页改V后旧提案拒绝；只变D且用途仍同可带最新D应用；同需求其他文档占用仍拦截 | 并发集成；当前未执行 |
| TC-FORM-A24 | APP-FORM-CONTENT／REVIEW及相关共享规则 | 人工编辑、GENERATE、REVISE、候选应用、历史恢复、新CARD_RESPONSE各独立变体：分别只改无关b13、改b12、删除其全部范围、保留区块但来源暂不可核实；逐值核对freshness/review_reason、公开页与计数及Closure | 所有正文提交入口更新成果匹配；变更、删除、历史恢复均不伪造CURRENT | 内容集成；当前未执行 |
| TC-FORM-A25 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | FBASE；一次多项变化，读取batch与缺失来源变体 | 事件同批版本／顺序一致；来源／Revision可追溯；缺来源显示不可用 | 审计／浏览器；当前未执行 |
| TC-FORM-A26 | APP-FORM-READ／SHR-FORM-PAGE及相关共享规则 | FGROW；分页过滤已放弃／事件并查看真实ID | 历史分页／过滤保持真实ID；已放弃计数不依赖已加载页 | API／浏览器；当前未执行 |
| TC-FORM-A27 | APP-FORM-READ／PATH／SHR-FORM-BUDGET | FBASE损坏引用变体；21项变化／大body；FGROW新增 | 坏状态明确报错；单次超预算拒绝不截断，历史累计不迫使换文档 | API／服务；当前未执行 |
| TC-FORM-A28 | APP-FORM-UPGRADE／INF-FORM-MODEL及相关共享规则 | 固定源隔离副本执行升级；另未知DDL摘要 | 源库保留，新目标复制字节／身份／旧回执校验；未知V2.0阻止猜测升级 | 离线升级演练；当前未执行 |
| TC-FORM-A29 | APP-FORM-UPGRADE／INF-FORM-MODEL及相关共享规则 | 原资源历史运行／卡片和新release缺准入变体 | 旧资源／运行快照／卡片按原版本读取；新资源无准入不得用旧LIVE放行 | 资源／准入；当前未执行 |
| TC-FORM-A30 | 前端5／8章及SHR-FORM-TARGET | 前端规定窄宽布局与键盘，处理中／UNKNOWN晚到回执 | 窄宽布局、键盘／读屏、空／错／加载／忙／UNKNOWN及晚到回执不抢焦点 | 产品浏览器；当前未执行 |
| TC-FORM-A31 | APP-FORM-DISCUSS／REVIEW及相关共享规则 | 无主线变体建立三步，记录Chat数与生命周期 | 建线直接将首步IN_PROGRESS并设为当前讨论，其余PLANNED；无额外点击或Chat（R01替代） | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A32 | APP-FORM-PATH及相关共享规则 | FBASE预览新增／取消，预览后另一页改F再保存 | 路线预览无写入／正式ID分配；版本变化阻止直接保存并保留草稿 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A33 | APP-FORM-PATH及相关共享规则 | FBASE拆s2为两步／合并另一组，复用真实b12关联 | 拆分／合并复用真实正文，原成果和历史保留；正文V不变 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A34 | APP-FORM-PATH及相关共享规则 | FBASE取消s2，分别缺i1去向／同时转交i1及b4 | 移动问题及修改支线返回点，origin保持；没有明确去向时禁止取消旧节点 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A35 | APP-FORM-PATH及相关共享规则 | FROLLBACK；带用户暂缓／放弃的ADJUST_PATH失败 | 暂缓／放弃问题和支线与整批调整同事务，失败全部回滚 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A36 | APP-FORM-DISCUSS／REVIEW及相关共享规则 | FBASE；同Output含路线卡与冲突自动变化；另用户编辑卡路线 | AI路线提案不能与自动形成增量混合应用；用户修改后原卡有明确处置 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A37 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | FBASE采用m210，沿block→Revision→card→answer→audit查来源 | CARD_RESPONSE来源在区块、Revision、原卡及审计中一致，旧资源不会错误解码新来源 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A38 | APP-FORM-READ／SHR-FORM-PAGE及相关共享规则 | FGROW另种60张固定提案消息及处置，分页20；同快照对照完整SQL计数／节点last_event／可用原因，随后另一页改F；验证冲突重读与查看前后焦点相同 | 提案分页、节点活动摘要、过期原因及完整计数同快照；查看不切换业务焦点 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A39 | APP-FORM-READ／SHR-FORM-PAGE及相关共享规则 | FBASE；新增temp步回执定位；旧版本回执重放；GET失败 | 新回执reference_map定位新节点，旧回执按原协议重放；200后GET失败仍为保存成功 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A40 | APP-FORM-READ／SHR-FORM-PAGE及相关共享规则 | FGROW单次超预算与未知V2.0结构变体 | 单次请求／页／模型预算明确拒绝且不截断，终身累计不作门槛；V2.0差异阻止猜测升级 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A41 | APP-FORM-PATH及相关共享规则 | FBASE取消有两个成果的s2，分别遗漏／重复／换kind路由 | 拆分／合并逐项旧成果映射，遗漏／重复／类型偷换均拒绝；映射不充当写入事实 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A42 | APP-FORM-PATH及相关共享规则 | FBASE temp新步承接旧成果，检查RESULT_ROUTE真实身份 | 正式RESULT_ROUTE事件全部使用真实新成果身份，旧Artifact及原Revision保持 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A43 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE结束s2，未选b4处置；另伪RESOLVED | COMPLETE按return快照OPEN支线；未选择记KEEP_OPEN，伪RESOLVED／重复冲突仍拒绝 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A44 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE先成功结束并将i1／b4转s3，核对issue.step_ref与branch.return双向一致；独立FROLLBACK变体在任一转交保存失败时读取全部前态证明整体回滚 | 后续问题／支线转交双向引用一致；任何处置失败整个完成事务回滚 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A45 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | 冻结F12的路线卡m211，接收发布F13，经真实responses→CARD_APPLY→共享COMMIT采用；断言payload.basis仍12、事件版本为实际提交前后F；独立人工草稿expected_F=12在F13经MANUAL_EDIT→同COMMIT必须PATH_CHANGED | F12来源发布卡后F13，卡在F13可执行；不伪改模型basis为13 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A46 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | FBASE调整失败后F16撤回，分别相关basis相同／不同 | 调整失败后撤回在F16获得真实新依据；摘要不同则保持禁用、重新预览 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A47 | APP-FORM-DISCUSS／REVIEW及相关共享规则 | FBASE DISCUSS合法topic＋非法formation／非法card各变体 | DISCUSS任一结构部分非法，进展／形成／新卡一起拒绝，保留pending及可读返回 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A48 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | FBASE REVISE正文合法、进展非法 | 原REVISE正文合法时不因讨论增量失败撤销正文；程序成果匹配仍维护 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A49 | APP-FORM-DISCUSS／REVIEW及相关共享规则 | FBASE上轮结构拒绝，下一轮选历史消息 | 被拒绝结构的历史回复带effect_state，后续不会据文字伪认写入或完成 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A50 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE全部步骤结束且i2暂缓，读取文档／需求确认状态 | 路线所有步骤结束仍不自动确认文档／需求；暂缓事项和复核提示继续可见 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A51 | APP-FORM-DISCUSS／REVIEW及相关共享规则 | 无主线变体；首次合法建线并读事件 | 建线同事务进入第一步，其他待开始，无额外点击或Chat | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A52 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE s3依赖未完成，SWITCH_STEP s3 | 依赖未完成也可切换；不填理由、不暂停旧节点、不完成新节点、不改正文 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A53 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE查看并明确讨论COMPLETED s1／CANCELLED历史步 | 已完成／已放弃节点可作为讨论上下文，原状态和历史保持，无自动重开 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A54 | APP-FORM-DISCUSS／REVIEW及相关共享规则 | FBASE运行冻结s2，用户改下一轮s3，回复晚到 | 在途回复继续按原节点保存且不抢UI焦点；下一轮按最后有效选择冻结材料 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A55 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | m210写卡／m211路线卡分别独立发布后仅切焦点，再经各自真实responses采用；另独立变体修改原文／相关定义／用途摘要，核对明确拒绝；路线卡全过程进入CARD_APPLY共享COMMIT，不能测试专用旁路 | 纯焦点切换后待写及路线提案仍可核实采用；真实内容变化继续拦截 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A56 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE查看PLANNED s3／PAUSED变体，再实际发送 | 用户实际向未开始／暂停节点发送讨论才记开始／恢复；仅查看不改状态 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A57 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE无成果且GAPS_REMAIN，直接结束 | 无已写成果、AI评估有缺口时用户仍可结束；V不变，Closure记录OUTSTANDING，页面保留待处理提示 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A58 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE结束不传遗留项处置，读取Closure与当前归属 | 未选择遗留去向时KEEP_OPEN及原归属保持；没有自动暂缓／放弃／转交，没有强制理由表单 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A59 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | FBASE先结束s2，仍适用m210后再明确apply | 结束后适用提案可继续明确写入，实际版本／来源保护保持，原Closure不回写 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A60 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | FBASE跨文档Ref／伪LANDED／版本冲突及重放 | 真实跨文档身份、伪造已写证明、版本冲突或重复提交仍按程序保护处理，不增加force_success旁路 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A61 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE RESUME_ISSUE i2 | 用户恢复暂缓问题：同身份OPEN、旧暂缓原因可查，无正文／模型变化 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A62 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE恢复i2同key重放／OPEN／DROPPED变体 | 重放恢复只产生一次真实变化；OPEN无变化；DROPPED不能原地恢复 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A63 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE将b4暂缓、i1设DEFERRED并明确移到s3，再RESUME_ISSUE i1；检查OPEN且历史return=s2。独立非法恢复b4时拒绝；独立合法调整return=s3后再恢复b4，核对双OPEN归属 | 暂缓支线保留历史返回点不阻止问题独立恢复；两者都OPEN或支线再恢复时核对归属，非法调整整批回滚 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A64 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE RESOLVED b4，RESUME_BRANCH同身份 | 已有结果支线继续讨论：原结果历史保持，当前OPEN且不冒充新结果；无重复支线 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A65 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE原生恢复／DISCUSS接受恢复，刷新再发送ENTER | 原生或DISCUSS接受的支线恢复成功只消费一次意图；刷新仍OPEN后用ENTER，不重开父步骤或自动Chat | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A66 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE当前s3，完整选择s2/b4一次进入 | 另一节点支线一次选择完整目标，无先切步骤后失败的半状态 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A67 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE在途下一轮RESUME，接受成功后模型失败／响应未知 | 在途未生效恢复保留RESUME；首次提交消费，模型失败不倒退；UNKNOWN只查原动作，晚到不抢焦点 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A68 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FCONCURRENT；ENTER前状态变；旧RESUME后产生新event | ENTER状态变化不自动恢复；已消费RESUME不清后续新结果，失效返回点／跨文档／恢复依据变化拒绝并保留输入 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A69 | APP-FORM-CONTENT／REVIEW及相关共享规则 | FBASE只改无关b13，再改a1范围b12，各正文入口 | 所有正文提交入口仅核对受影响成果，无关修改不使全主线失效 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A70 | APP-FORM-DISCUSS／REVIEW及相关共享规则 | a1=NEEDS_REVIEW／CHANGED，相关DISCUSS分别携带完整可核实区块与缺材料；核实前者CURRENT／null并清提示、后者NEEDS_REVIEW／UNVERIFIABLE且提示保留；两者各只有本轮一次Chat | 相关正常讨论消除可核实的复核提示；材料不足保持待复核，不额外调用模型 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A71 | APP-FORM-DISCUSS／REVIEW及相关共享规则 | 三个独立变体：assessment=null；真实ASSESS_STEP UNCERTAIN且覆盖不足；已有SUFFICIENT后覆盖区块变化造成validity=STALE。另在s2已结束且关联CURRENT但GAPS_REMAIN时读取，分开显示且旧Closure摘要不变 | 关联有效但语义有缺口分开显示；已结束步骤不自动重开，旧Closure不回写 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A72 | APP-FORM-READ／SHR-FORM-PAGE及相关共享规则 | FGROW；继续新增／讨论／精确写入并查全局count | 历史量超过旧累计阈值仍可继续同文档；页内计数不能冒充全局计数 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A73 | APP-FORM-PATH及相关共享规则 | FBASE 21项／65KiB／模型硬材料超限，保留草稿 | 单次超预算保留完整草稿／状态，分批也保持引用与事务完整，无静默截断 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A74 | APP-FORM-READ／SHR-FORM-PAGE及相关共享规则 | FGROW跨页引用最后节点／成环入边，完整DB校验 | 当前图／历史引用跨页核实，未加载对象不误判缺失或允许悬空关系 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A75 | APP-FORM-NATIVE／SHR-FORM-TARGET及相关共享规则 | FBASE直接结束PLANNED s3，与已开始变体对照 | 直接结束PLANNED节点无伪造开始事件；有实际开始事件时才显示开始记录 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |
| TC-FORM-A76 | APP-FORM-APPLY／PROPOSAL／SHR-FORM-TRANSACTION及相关共享规则 | FBASE结束s2后采用m210且版本仍匹配 | 已结束步骤仍可明确采用适用写入提案，不要求为写入先重开，原结束历史保持 | 按真实入口专项／集成，涉及界面补浏览器；当前未执行 |

### 六项审查修正的专项设计场景（均未执行）

| 场景 | 固定输入／真实触发 | 独立预期 |
| --- | --- | --- |
| TC-FORM-R01 | A24的六个提交入口，四种范围／来源变化；对照查询完整count与Closure | 只允许CURRENT/null、NEEDS_REVIEW/CHANGED、NEEDS_REVIEW/UNVERIFIABLE、REMOVED/null；CURRENT及REMOVED携带非空reason拒绝；替代链旧关联不计当前待复核 |
| TC-FORM-R02 | A71的无评估／不确定／陈旧及充分／缺口五变体；模型输出UNASSESSED反例 | null、不确定、陈旧分别呈现；UNCERTAIN从模型到对象／存储／UI同义；无效枚举整结构拒绝，不把缺材料变充分 |
| TC-FORM-R03 | A45及A55真实共用COMMIT；冻结F12→发布F13→纯焦点F14；相关摘要相同／不同 | 卡按CARD_APPLY可接受无关F变化，相关变更拒绝；人工草稿严格F冲突；原basis／payload不改，事务内全图约束仍生效 |
| TC-FORM-R05 | 本章完整Summary正例及逐项反例、每种RelationItem／PreviewEntity联合、预览101条影响与Artifact101条范围 | 严格键／空值／枚举一致；超过首100项可分页读取且total准确；错误联合拒绝，未加载不算不存在 |

<a id="r22-closure"></a>
### R22-01—05协议闭环与新增验收（均未执行）

下例为完整人工ADJUST_PATH body；沿FBASE，另明确i2也属于s2、next_step_no=4，新步成果编号从1开始；s3无指向s2的入边。头部仍须真实Idempotency-Key。合法结果应保留s2为CANCELLED、新建s4及s4.o1／s4.o2、i1/i2和b4.return转s4、b4.origin仍s1、V4不变；所有身份只在成功提交后出现，原卡／原Artifact不重写。

```json
{"document_id":42,"expected_discussion_version":30,"discussion_command":{"type":"FORMATION","action":"ADJUST_PATH","expected_formation_version":12,"expected_content_version":4,"based_on_proposal":null,"changes":[{"type":"ADD_STEP","temp_step_ref":"new_step_1","title":"完善推荐流程与范围","expected_results":[{"temp_result_ref":"new_result_1","description":"推荐流程","kind":"CONTENT"},{"temp_result_ref":"new_result_2","description":"范围判断","kind":"ANALYSIS"}],"dependencies":[],"replaces_step_refs":["s2"],"before_step_ref":"s3"},{"type":"MOVE_ISSUE","issue_ref":"i1","to_step_ref":"new_step_1"},{"type":"MOVE_ISSUE","issue_ref":"i2","to_step_ref":"new_step_1"},{"type":"SET_BRANCH_RETURN","branch_ref":"b4","return_step_ref":"new_step_1"},{"type":"CANCEL_STEP","step_ref":"s2","replacement_step_refs":["new_step_1"]}],"result_routes":[{"from_result_ref":"s2.o1","disposition":"REPLACED","target_result_refs":["new_result_1"],"reason":"保留原推荐流程成果"},{"from_result_ref":"s2.o2","disposition":"REPLACED","target_result_refs":["new_result_2"],"reason":"保留原范围判断成果"}],"reason":"改组步骤并保留全部成果及遗留事项"}}
```

此正例逐字段反例：把temp_step_ref改成temp_ref、把replaces_step_refs改成replaces、把new_result_1放入dependencies、同批重复声明new_result_1、路由指向未声明new_result_9、跨卡借用临时域、把源from_result_ref写成临时身份，分别拒绝。两种TempRef不是字符串同义别名；正式回执示意映射new_step_1→s4、new_result_1→s4.o1、new_result_2→s4.o2，不能在发布／预览伪造此结果。

| 场景 | 独立前置、操作及故障 | 必须证明的结果 |
| --- | --- | --- |
| TC-FORM-R22-01 | 上述完整请求及七种单字段反例，原事务各阶段回滚变体；另包含前向声明引用及成环变体 | 形状／声明／全图校验闭合；正例一次真实分配并返回映射，非法／预览不耗号；正式事件全真实引用，未采用原卡允许局部临时引用 |
| TC-FORM-R22-02 | 普通DISCUSS产出带同样ADD_STEP／路由的FORMATION_PATH_CHANGE卡，先只读预览／保存卡、不采用；然后真实responses→CARD_APPLY→COMMIT；另STAGED_WRITE绑定同轮合法已建步骤 | 发布卡保存本身可以变D/F，但无新Step/Result及编号消耗；卡未来TempRef字节／payload摘要不变；采用才分配并同事务写回答／事件／回执；写卡的同轮已生效身份在发布时真实解析 |
| TC-FORM-R22-03 | 文档42无主线；先读Summary；独立直接请求/formation/steps；另请求不存在文档；首次建线后再按F读页 | Summary=false时前端零实体页请求；直接实体页409 FORMATION_NOT_INITIALIZED，真缺文档404；建线后正常Version页，不能出现F0或把空态当失败 |
| TC-FORM-R22-04 | 一个CONTENT结果有1001个活动Artifact，每个各1段ORIGIN和CURRENT（共2段范围）；结束后按20/100读取全部证据；1001节点路线移动首节点到末尾，读取ORDER变化／成员页；随后改正文／重开／再排序 | Closure根项无证据数组，证据各行完整、计数及digest可独立重算；ORDER逐节点有界，无step_refs巨型数组；分页覆盖全部、旧快照不受后改动影响；故障注入最后证据行／digest／回执失败均全回滚 |
| TC-FORM-R22-05 | a1→a2成功；不同请求再次review a1；两个连接竞争替代a2；胜者a2→a3后读取当前页、include_superseded历史页和LINEAGE；另不同成果／环／两个前驱反例 | 旧review_of拒绝且不自动改目标；同key先重放；最多一条真实后继，失败者无新Artifact或半结构；活动页仅a3、历史a1/a2可读，计数一致；旧Closure继续指当时证据 |

<a id="r23-closure"></a>
### R23-01—03补齐场景（设计预期，均未执行）

| 场景 | 独立前置／动作与观察 | 明确预期 |
| --- | --- | --- |
| TC-FORM-R23-01 | 固定原PublicationBinding、protected摘要、payload及模型来源F12；调整实际接受后needs_revision=true；仅无关焦点／讨论使当前F16，再WITHDRAW。另独立变体改V／Goal／相关定义／来源，及先撤回成功后再改正文／apply | 匹配时原绑定／payload摘要不变，清标记；PROPOSAL_CHECK保存before版本F16的成功凭证，事件after按真实差异递增。相关变化拒绝且标记保持。后续apply不借旧凭证绕过当前校验；缺失绑定报错不重建。凭证／标记／事件／回执任一失败全回滚 |
| TC-FORM-R23-01-REPLAY | 上一匹配变体提交后丢响应，同key核实；另撤回成功收到200但GET失败；原卡再次调整后用户使用新key撤回 | 原key只回原回执／原凭证，不重算新状态、不清后来的新调整；已成功GET失败只刷新；新的真实调整周期可形成新凭证，仍引用同一原绑定；新key且无调整为NO_CHANGE |
| TC-FORM-R23-02 | E1有a1→a2及消息m220／核实Revision401；E2有a2→a3；随后a2/a3的当前freshness变化；只GET E1的CHANGES及原消息／Revision，独立重放公开review事实 | E1的ARTIFACT_REVIEW仍为a1→a2及原来源，不出现a3或后改状态；固定事实一一对应原review行；重放E1只生成一条边，至E2才两条。当前LINEAGE可用各边review_event_id定位历史；不从当前节点猜旧事实 |
| TC-FORM-R23-02-ROLLBACK | 在review行、ARTIFACT_REVIEW变化、范围／实体、消息／终态或回执保存处独立注入失败；另MATCHED/UNVERIFIED/REMOVED实际检查 | 任何失败无孤立边或半个结构；非REASSOCIATED事实可追溯但不增删替代边；同key成功重放不造重复review／变化事实 |
| TC-FORM-R23-03 | 定义1下建议COMPLETE_STEP；分别只切焦点／改无关正文、增加CONTENT成为定义2、暂停owner、取消目标、改变覆盖／相关问题／支线／关联；另无建议及新合法建议变体 | 只变焦点／无关F/V仍CURRENT；各相关改变按固定原因STALE；无建议才null，新建议按新basis替代显示，不回退旧条目。历史Snapshot不含派生当前性；STALE不额外Chat，不禁独立手动结束／重开 |
| TC-FORM-R23-03-NEW | 同轮合法INITIALIZE_PATH及RECOMMEND，首步实际IN_PROGRESS、Goal1；另非法进展与建议混合 | 合法结果原子保存新实体与程序RecommendationBasis，原模型输入basis仍null/F未建线；非法整体拒绝，无伪造发布依据或建议。模型自填basis/validity因未知字段拒绝 |

以上成功／失败变体各自从独立隔离数据开始，不依赖其他用例先执行。PublicationBinding为唯一执行绑定；WithdrawalCheckProof是成功复核事实；ArtifactReview为独立不可变历史事实；RecommendationBasis是建议登记依据，均不得彼此替代授权。

### 8.2 关键技术保证取证

| 引用 | 环境／方法与明确通过条件 | 未覆盖边界 |
| --- | --- | --- |
| EV-FORM-TXN | 原实际SQLite及发布Schema，FROLLBACK全部阶段、双连接CAS／回执交错；最终正文／Revision／回答／F／事件／receipt全有或全无，同key一次效果 | 内存Mock不能代替真实事务；提交未知必须故障演练 |
| EV-FORM-GRAPH | 固定循环、自环、跨页入边、双OPEN迁移和取消承接参数化；逐项独立预期；未加载节点仍完整校验 | 只验证JSON结构不能证明程序权限 |
| EV-FORM-PAGE | FGROW跨页过滤和F变化、历史高水位；独立SQL总数与公开total一致，零重复／遗漏，页大小最大100 | 正确性与性能分别记录 |
| EV-FORM-UPGRADE | 固定源Schema200/db20-r48摘要的只读隔离副本，目标外键检查、旧数据字节／ID／回执摘要一致；未知源／PROCESSING拒绝，无服务切换 | 不能把该源演练外推到其他V2.0未提交状态 |
| EV-FORM-CONTEXT | 新release离线严格结构、八文本与实际Wire字节一致、私有basis不在请求、来源别名及预算正反例；旧快照按旧版本重放 | 不证明供应商接受／语义效果 |
| EV-FORM-SOURCE | 实际CARD_RESPONSE从正式回答到块／Revision／audit一致；伪来源及旧资源未知新来源拒绝或明确不可用 | 不回写历史资源 |

### 8.3 EV-FORM-AI 模型效果评测计划

设计评测集按确定规则建立，不能从当前生成结果选“看起来通过”的样本。用两份基准正文：空白文档；FBASE两个中文块。每份组合以下六类用户输入：①“只解释推荐为何需要反馈，不改路线”；②“好友可帮忙推荐，先讨论是否纳入”且无相关旧支线；③同②但有同问题OPEN b4；④“先给出可写入的推荐流程”且成果CONTENT；⑤“将s2拆成流程与异常两步，保留全部要求”；⑥人工将b12改为“系统列出候选影片，用户选择后获得三条推荐”，随后“核对流程是否充分”。共12个输入基元，固定ID与文字，不使用用户数据；无主线变体先提供明确Goal／三步种子。

每个输入基元派生五项任务：普通说明及支线判断、STAGED_WRITE精确内容、FORMATION_PATH_CHANGE完整路线、人工修改后ASSOCIATE_CONTENT关联复核、ASSESS_STEP充分性及下一步。任务指令明确所求、对应材料及缺失反例；共60样本，完整输入在未来评测manifest冻结，hash登记后不得挑样。每样本每个固定Profile／release运行1次，无自动重试；失败／预算拒绝亦计入该样本结果，不移除分母；更换资源后完整重评。执行前必须另获60次Chat及实际必要计数的明确预算与重试边界，本轮没有该授权，也未执行。

| 指标 | 判定来源／目标 |
| --- | --- |
| 权限与真实性 | 60/60不越权写正文／结束／重开／用户处置、不伪造来源或已读、不漏关键要求；任一为发布阻断 |
| 严格协议与预算 | 60/60可按固定Output及实际别名校验，无隐藏调用／修复；无效结构不得局部落地；供应商不兼容单独记录失败 |
| 分支判断 | 12个该类样本至少10个由两名独立人工按“普通讨论／复用／新独立跟踪”标注一致；同问题不重复、origin/return正确为关键项必须全部通过 |
| 精确写入与路径 | 对应各12样本至少10个内容／路线可用；所有PATCH原文命中、scope/成果全承接／临时引用正确必须全通过，程序接受率与人工可用率分别报告 |
| 关联与充分性 | 对应各12样本至少10个正确区分程序匹配和语义缺口；材料不足不声称完整、已结束不重开为关键项全部通过 |

人工分歧按未通过记录，附简短理由及来源；阈值为本设计的发布目标，尚无通过证据。真实一次成功不代表稳定效果；离线Mock不能替代真实Profile结果。评测输入／实际尝试／失败／usage／人工结论只留批准范围内的Markdown摘要，不保存临时原始JSON／日志。

### 8.4 性能、界面与容量目标

隔离环境记录Windows版本、CPU／内存、Python／SQLite、数据规模及冷／热缓存；FGROW扩展到1001步骤、1001支线／问题、2001Artifact／10001事件。目标普通页20项／Summary热读p95≤500ms，单命令（不含模型及用户交互）p95≤1秒；每类先1次预热再20次测量，报告实际p50/p95与峰值内存。COMPLETE全事实流式保存及大图调整另报规模／耗时，不以删除历史满足目标。上述为待测工程目标，未通过时优化索引／查询，不私自恢复累计业务门槛；不把本轮设计静态核对称为性能验收。

UI尺寸／真实键盘、状态／空态及UNKNOWN流程由前端第8章定义；源目标、来源打开、按钮禁用原因与浏览器草稿恢复需真实页面证据，不以API专项替代。新模型性能含计数／Chat实际时延，程序测量不包含供应商推断保证。

### 8.5 本次设计交付状态

本文第1—8章及前端对应章节构成模板化详细设计初稿；稳定引用、DTO、命令、存储映射和76项预期均为设计依据。当前产品代码／目标DDL／可执行Schema／新资源发布／迁移／产品测试／浏览器／真实模型均未执行。静态结果见[本修订静态核对](../../../verification/v2.1/detailed-design-r23-fixes-2026-11-14.md)。不升EFFECTIVE、不合并正式设计、不提交推送。

## 附录A 技术接续与发布输入

| 条目 | 已确定／仍需取得 | 对应大纲技术待办 |
| --- | --- | --- |
| 源V2.0现场 | 已只读定位BE0.17／FE0.16及db20-r48与相关代码；完整源未提交清单、全部生产调用／资源及实际在途状态在启动实施时固定；不能用当前旧工作区宣称全量兼容 | T21-01 |
| 可执行协议 | 本文完整新输入／联合／预算／输出／读投影／错误已定义；实现时生成同义严格Schema、allowed_errors及decoder并做离线反例，旧v1—v4及未采用v5均不是本设计执行件 | T21-02 |
| 物理发布 | 实体／关系／历史字段／键／索引／事务算法已定义；仍须完整目标DDL、触发器、manifest、数值Schema／目录分配及显式升级演练，不抢占未知编号 | T21-03 |
| 容量 | 单次20项／64KiB、单步20成果、分页20/100及材料100已确定；真实负载／容量／回滚耗时待测，不代表终身上限 | T21-04 |
| 模型资源 | 新逻辑release／layout、Prompt／Canonical／Wire／Output及八计数／来源已定义；真实物理发布、compiler实现及新准入证据待取得 | T21-05 |
| 文档／验收 | 本轮输出两份完整模板初稿；正式审定与产品实施／验收分开，A01—A76及60样本模型效果未执行 | T21-06／T21-07 |

上述是实施／发布事实缺口，没有重新打开Q01—Q04或B01—B03产品决定。初稿后续评审只调整实际发现的契约问题；新需求先独立迭代，正式合并仍依项目规则。
