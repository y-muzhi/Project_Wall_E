# WALL-E.V1_0.6 后端设计文档

修订依据：[原始设计文档修改清单](../原始设计文档修改清单.md)及其中 D-001—D-015 的有效确认。沿用原章节、字段表、处理表、结果表和稳定编号；本次文档合并不表示测试通过。原始版本见 [归档](originals/WALL-E.V1_0.6.后端设计文档.md)。2026-10-09根据迭代UX-008同步创建后初始化模式只读；字段、能力、HTTP及验证去向见[本次合并记录](合并记录-2026-10-09.md)。

## 1. 文档说明与系统范围

### 1.1 基本信息

|字段|确定定义|
|---|---|
|规格编号|WALL-E-BACKEND-V1_0.6|
|系统名称|WALL-E|
|规格类型|0→1初始规格|
|目标软件版本|V1_0.6|
|规格版本|1.0-draft-sync2|
|原始规格版本|1.0-draft；原字节归档在 originals/ 同名文件|
|文档状态|DRAFT；已确认结论已合入，剩余待定及运行验收状态不因此改变|
|最后更新时间|2026-10-09；合入UX-008创建后初始化模式只读；同步属性更新字段、处理、接口和验证定义，其他前端交互不新增后端契约|

### 1.2 目标与范围

|内容|确定定义|
|---|---|
|系统目标|将用户的需求想法逐步形成可维护的 Markdown 需求正文，通过初始化、人工编辑、AI 问答与检查、经用户决策的修改建议、评论和历史版本维护同一需求的已确认内容。|
|使用者与使用场景|单用户通过工作台和需求详情页维护需求；前端通过 HTTP 接口提交动作、读取资源和观察后台 AI 运行。|
|运行与使用范围|HTTP 接口不设置身份认证；运行恢复以当前单进程实际运行集合为依据。单进程、本机文件数据库及启动配置见 [Q-BASELINE](#q-baseline)、[Q-08](#q-08)。|
|本版本包含|需求生命周期；CURRENT 与独立 MANUAL_DRAFT；不可变 Revision；连续对话及整组卡片回答；GuideRun 与逐次 LLMUse；SuggestionBatch 及逐项决策；评论维护、定位与正文更新后的锚点重校验；37 个 HTTP 入口（原 I01—I36 加新增 I37）；后台推进及中断、超时恢复。|
|本版本明确排除|业务删除需求；评论回复与评论线程；恢复历史版本；人工重新挂载评论；流式模型展示；Tool Calling；多用户实时协作。ASK 和 REVIEW 不直接修改正文，MODIFY 必须经建议批次确认。|
|已确认的输入依据|《Wall-E _V1_0.6_后端设计(2).md》第4、5章；《WALL-E_V1_0.6_API接口模块(1).md》第6.4、6.5节；《WALL-E_V1_0.6_前端模块(1).md》第6章中的调用与交互要求。三份文件共同约束 V1_0.6；文中“V1”指本版范围。|

前端视觉、页面本地状态和用户操作反馈由《WALL-E.V1_0.6.前端设计文档.md》第5章正式定义。本文件定义业务事实和服务端保证，前端的提前禁用不能代替服务端校验。

### 1.3 填写与实施规则

业务对象的有效性由第3章定义，动作条件与完成范围由第4章定义，HTTP 传输和错误映射由第6章定义，持久化和模型适配保证由第7章定义。相同事实使用稳定条目引用；应用输入、HTTP 输入和数据库记录不得混为同一种对象。

所有写入必须满足所引用的对象约束、事务边界、占用和版本条件。接口成功接受 AI 任务只确认接受事务，不证明模型结果已生成或正文已更新。缺失的模板、Prompt、Schema 或技术保证不能用未确定的默认行为代替；其已知边界及影响记入附录A。

### 1.4 术语与缩写

|正式术语|别名|含义|
|---|---|---|
|需求|Requirement|OBJ-REQ；维护生命周期、固定模板引用和正文流程占用。|
|当前正式正文|CURRENT|OBJ-DOC 中 document_type=CURRENT 的唯一实例。初始化阶段的“Working Draft”也指该实例。|
|人工草稿|MANUAL_DRAFT|OBJ-DOC 中人工编辑期间单独存在的实例，不是正式正文的新状态。|
|内容版本|content_version|每个文档实例独立递增的并发版本，不是历史版本序号。|
|历史版本|Revision|OBJ-REV；不可变正文与区块快照，version_no 在需求内编号。|
|AI运行|GuideRun|OBJ-GUIDE 聚合根；承载动作、冻结协议、工作进度及最终业务结果。|
|真实模型请求记录|LLMUse|OBJ-GUIDE 内部实体；每次实际发送给供应方的请求单独记录。|
|逻辑调用／真实尝试|call_no／attempt_no|同一运行中，用户继续会产生新的逻辑调用；自动重试属于该逻辑调用的不同真实请求。|
|处理范围|Scope|请求处理的文档、章节、区块或选区，不等于写入权限。|
|允许修改目标|Allowed Targets|后端依据动作、来源和 Scope 冻结的写入授权；ASK、REVIEW 为空。|
|读取清单|Read Manifest|模型实际读取上下文的记录，不授予修改权限。|
|修改建议批次|SuggestionBatch|OBJ-BATCH；保存固定目标与补丁，以及用户对各项建议的决定。|
|业务结果／HTTP结果|result／响应包装|前者是 code、data、details；后者由接口映射为 success、data、error、meta。|

### 1.5 稳定引用与实现定位

沿用 OBJ、APP、BND、INF、SHR、TC 稳定编号。第3、4章按实际对象、能力重复相应模板小节，实例标题使用稳定编号；局部字段以“编号＋字段路径”定位。源码路径均为仓库相对路径，按实际责任位置登记，不表示已经通过测试。

本文件是对象、应用输入输出、共享业务规则和 HTTP 契约的正式来源。前端跨文档引用使用本文件名和稳定编号。普通内部辅助函数及 SQL 组织可由实现者确定，不能借此改变业务语义、事务范围、重试次数、数据结构或对外行为。

## 2. 技术基线与公共规则

### 2.1 技术与模块基线

|技术项|已确认选择与要求|用途|
|---|---|---|
|后端模块组织|backend/app 下 requirements、documents、revisions、comments、suggestions、guide、messages；各条目定位到 commands.py、queries.py、contracts.py、api.py、http_models.py 及快照/来源验证、Repository/DDL 中的适用位置|按业务职责组织，不要求拆成独立服务。|
|接口|/api/v1 下 JSON HTTP 请求和一次性响应；snake_case 字段|前后端入口。|
|应用与数据访问|Command 通过聚合 Repository 写入，Query 返回读取模型；多对象写入使用同一短事务|不得将 HTTP 或 ORM 对象作为应用契约。|
|模型调用|后台非流式调用；一次请求取得一个 assistant.content，再解析 JSON；不启用 Tool Calling|AI 运行推进。|
|Schema|JSON Schema Draft 2020-12；正式输出中对象 additionalProperties=false|模型结果的结构验证；固定资源及版本关系见[正式AI资源](#sync-be-15)。|
|运行恢复|启动恢复先于接受新业务请求；使用本进程 live_run_ids 判断活动执行|中断与超时处置，详见 APP-GUIDE-CMD-C09。|

语言、运行时、Web框架和依赖版本采用本节确认基线；数据库使用SQLite，完整安装依据为backend/requirements.lock，运行/迁移见第2.3及7.1节。

|模块范围|主要责任|依赖与访问限制|
|---|---|---|
|requirements|需求身份、生命周期、属性、工作占用及查询|跨聚合动作由 APP 明确事务，不能由页面连续调用凑成原子过程。|
|documents|CURRENT、MANUAL_DRAFT 及完整快照提交|正文和区块状态必须共同保存；不能交换文档类型替代提交。|
|revisions|不可变版本快照与查询|不提供恢复、覆盖或修改历史快照。|
|comments|评论维护、锚点重校验、读取定位|重校验加入正文写事务；查询定位不修改持久化锚点。|
|suggestions|建议批次、决定和组合补丁应用|Suggestion 通过批次聚合写入，没有独立写 Repository。|
|guide|运行命令、上下文读取、模型编排、可信结果提交及恢复|模型结果只经 APP-GUIDE-CMD-C07 采用；LLMUse 经 GuideRun 聚合保存。|
|messages|消息读取与 HTTP 卡片入口|卡片提交绑定 APP-GUIDE-CMD-C06，不在入口中重复业务编排。|


<a id="sync-be-01"></a>

**后端技术、安装和启动基线**

采用 Python 3.13.5、FastAPI 0.142.2、uvicorn 0.54.0、httpx 0.28.1、jsonschema 4.26.0、markdown-it-py 4.2.0、mdit-py-plugins 0.6.1，开发测试依赖含 pytest 9.1.1；完整环境按 `backend/requirements.lock` 固定。SQLite 为本机文件数据库，单进程、一个 uvicorn worker、无 reload。服务绑定 `127.0.0.1:8000`，默认库为项目 `data/wall-e.sqlite`，`WALLE_DATABASE_PATH` 可指定绝对路径。

初始化使用 `python -m backend.app.infrastructure.database init`，已有库检查使用同模块 `check`；基础启动 `python -m backend.app`。正式 AI 的显式启动工具为 `python tools/ai-service.py --start`，其密钥导入边界见 [BE-18](#sync-be-18)。初始化/迁移是独立明确操作，正式启动不自动重建数据库。支持平台基线和资源锁文件不等于当前所有机器环境已验证一致。

**确认依据**：D-001、D-003；启动辅助器另依 D-014/015。**代码对应**：`backend/requirements.lock`、`backend/app/{__main__,service}.py`、`infrastructure/database.py`、`tools/ai-service.py`。

### 2.2 公共规则

**逻辑类型**

|类型|含义与约束来源|
|---|---|
|ID / BlockId / PositiveInt|ID是实体种类内正整数身份；BlockId是需求文档内区块身份；PositiveInt是正整数。对外范围及身份关系采用SHR-ID，具体字段的上限和用途以字段契约为准|
|Int / Bool / Text|整数、布尔值、Unicode文本；整数不接受布尔值；文本的标准化与长度采用SHR-TEXT|
|UtcTime / JSON对象|UTC时间值采用SHR-TIME；JSON对象表示逻辑结构，不等同数据库TEXT，须满足所属对象/共享Schema|
|Title / Idea / CommentText / Markdown|分别采用title、initial_idea、Comment.content约束；Markdown为完整支持方言文本，方言由[Q-06](#q-06)闭合|
|ConfiguredType / RequestKey / ScopeRef / ValidatedOutput|需求类型NEW/CHANGE；RequestKey为客户端UUID v4；ScopeRef见APP-GUIDE-CMD-C01，ValidatedOutput是冻结Schema及业务校验通过产物，完整资源与验证分别见第4.7节及SHR-BLOCK|

<a id="shr-id"></a>
**SHR-ID 身份与编号**

ID 表示某一实体种类内的正整数身份；实体相等要求实体类型和 id 均相同。对外 ID、BlockId、内容版本及消息序号范围为 1～9007199254740991。Requirement 的可见业务编号为 REQ 加六位数字，不能替代 requirement_id；Revision 使用需求内 version_no 展示；其他内部 ID 不作展示编号。ID 生成、业务编号分配及容量边界见 [Q-ID](#q-id)，不得自行改为 UUID 主键或另造编号规则。RequestKey 是客户端 UUID v4，与实体身份分开。


<a id="sync-be-03"></a>

**ID/序号分配和耗尽结果**

每实体种类使用独立持久序列；REQ 使用独立 1—999999 序列，格式从 REQ000001 开始。消息和 Revision 在需求内按最大序号加一，内容版本按当前值加一，分配都加入业务事务。已成功分配不重复使用；回滚分配未成为成功事实可重试。正安全整数上限保持 9007199254740991；`next_block_id` 还须保留可表示的下一号，不能消耗上限后回绕。耗尽返回明确 `CAPACITY_EXHAUSTED`，HTTP 503，安全说明“编号或版本容量已用尽”，整体事务不部分提交。CAPACITY_EXHAUSTED 仅适用于实际可达的分配路径，不适用于纯查询。

**确认依据**：D-003。**代码对应**：`infrastructure/identifiers.py::{_allocate,requirement_number,increment}`、`shared/http_errors.py`、各命令/HTTP 模型。

<a id="shr-time"></a>
**SHR-TIME 时间**

业务时间点使用 UTC；HTTP 按 YYYY-MM-DDTHH:mm:ss.SSSZ 输出到毫秒，可空时间使用 null。created_at 不修改；updated_at 仅在所属能力规定的真实变化时更新，查询、无变化属性请求及重复解决、重开、删除等不能伪造新的事件时间。前端本地时区展示由前端第5章定义。数据库物理精度、时钟入口及受控测试方式见 [Q-BASELINE](#q-baseline)。

<a id="shr-text"></a>
**SHR-TEXT 文本与长度**

普通文本先将 CRLF/CR 统一为 LF，再去首尾 Unicode 空白；不做 NFC/NFKC 或全半角转换。长度按 Unicode 码点计，不按 UTF-8 字节或 UTF-16 单元计。Markdown、原文快照及定位片段不 trim、不做 Unicode 归一化。不可暗中裁剪大文本，不能把 Idea 的上限套用到完整文档。

|文本|标准化后的范围|换行与空值|
|---|---|---|
|title|1～20 个码点|不允许内部换行；不可为空。|
|initial_idea、instruction|1～10000 个码点|允许换行；不可为空。|
|Comment.content|1～2000 个码点|纯文本，允许换行；不可为空。|
|keyword|0～100 个码点|不允许内部换行；空白标准化为空后表示无关键词筛选。|
|Revision.description|0～1000 个码点|允许换行；未提供、null 或标准化后空字符串均为 null。|
|selected_text|1～2000 个码点|保留原文，不截断。|
|prefix_text、suffix_text|0～100 个码点|保留紧邻选区的原文，允许空字符串。|

枚举英文编码区分大小写，不自动去除空白。需求类型为 NEW、CHANGE；初始化模式为 IDEATION、DESIGN。正文、区块状态、建议编辑内容及全请求字节容量见 [Q-10](#q-10)。


<a id="sync-be-21"></a>

**大文本和批次容量**

Markdown 最多 1000000 码点、BlockState 序列化最多 4MiB、顶层块最多 10000；单建议编辑内容/模型 proposed 最多 100000 码点、批次最多 100 项；完整 HTTP 请求（路径、查询、头与 Body 的应用可见字节合计）最多 8MiB、单原始审计项最多 4MiB、模型 assistant.content 最多 1MiB UTF-8。原 title/idea/instruction/comment/description/keyword 等更小字段约束不变。按入口和执行阶段返回对应 TOO_LONG/OUTPUT_INVALID 等安全失败，不截断、不同步套 Idea 上限；这些是合法性边界，不是已验证性能指标。

**确认依据**：D-005。**代码对应**：`documents/{markdown,snapshot}.py`、`suggestions/contracts.py`、`backend/resources/v2/schemas/`、`shared/http_boundary.py`、`infrastructure/audit_data.py`、`guide/trusted_output.py`。

<a id="shr-concurrency"></a>
**SHR-CONCURRENCY 版本与占用**

动作以所属能力指定的 CURRENT 或 MANUAL_DRAFT.content_version 为比较对象。请求版本、事务内重读版本和写入必须形成原子判断；不得仅依赖先前 GET。版本冲突不覆盖现有正文或草稿。工作占用由 Requirement 的 document_work_state、active_operation_type、active_operation_id、state_started_at 与活动对象共同约束，关系不一致时返回 WORK_STATE_INCONSISTENT，不能猜测一个对象继续执行。具体事务技术保证见 INF-TX。

<a id="shr-idempotency"></a>
**SHR-IDEMPOTENCY 重复执行**

适用于能力输入含 idempotency_key 的写动作。能力统一编排幂等识别和成功记录；成功记录与业务写入原子提交。相同键和业务输入重放原成功结果；相同键不同输入返回 IDEMPOTENCY_CONFLICT；同一请求进行中返回 REQUEST_IN_PROGRESS，不启动第二次执行。键范围、输入比较与 HTTP 重放正式定义于第6.1节 API-COM-IDEMPOTENCY；物理记录、保留期和崩溃恢复采用本规则已确认的持久幂等方案。无此键的保存草稿等动作只能遵循各自版本、状态条件，不能假定网络失败意味着未写入。


<a id="sync-be-04"></a>

**持久幂等的所有权、保留和恢复**

持久键为 `(capability_id,target_identity,idempotency_key)`，UUID 按同一规范值比较；输入保存解析/默认后的规范 JSON，保留 PATCH 省略与 null 差别及数组顺序。PROCESSING 以短事务领取，记录 `owner_epoch`，同键同输入进行中返回 REQUEST_IN_PROGRESS，异输入返回 IDEMPOTENCY_CONFLICT。业务写入和 SUCCEEDED 原成功载荷/HTTP 状态同事务提交；成功记录永久保留，重放使用原载荷但新建 request_id。已知拒绝/回滚可释放 PROCESSING，未知提交不据网络错误释放；启动取得独占进程锁后清除前进程未成功记录，不自动重执行业务，不按任意 TTL 抢占当前执行。

**确认依据**：D-003。**代码对应**：`infrastructure/idempotency.py::{Idempotency,canonical_input,request_key}`、迁移 001/002、`shared/command_execution.py`、`shared/http_commands.py`。

<a id="shr-result"></a>
**SHR-RESULT 应用结果与失败**

应用结果为 {code,data,details}；成功 details=null，失败 data=null。data 采用能力的完整结果定义，分页结果包含 items 与相应分页字段，由接口移入 meta.pagination。拒绝默认不修改业务数据；APP-GUIDE-CMD-C05 明确允许提交 ORPHANED 锚点校正后返回 COMMENT_ORPHANED。多对象写入失败回滚其共同事务，已完成的真实模型请求记录不得因业务提交失败被抹除。未预期异常或未登记结果编码由 HTTP 边界映射为 INTERNAL_ERROR；安全错误不得包含密钥、堆栈、Provider 原始内容或内部推理。


<a id="sync-be-22"></a>

**内部成功data和失败details**



| 能力 | 正式内部成功 data |
| --- | --- |
| COMMENT-C06 | `{requirement_id,document_id,content_version,attached_comment_ids,orphaned_comment_ids}` |
| GUIDE-C07 | `{guide_run_id,status,assistant_message_id,current_document:null或{id,content_version},suggestion_batch_id:null或ID}` |
| GUIDE-C08 | `{guide_run_id,status,ended_at,occupancy_released}`，同时适用于两个成功结果码 |
| GUIDE-C09 | `{recovery_reason,operation_time,recovered_run_ids,repaired_requirement_ids,unchanged_requirement_ids}` |
| GUIDE-ORCH-C01 | `{guide_run_id,status,current_step,last_call_no}`；AI_FAILED 的 data=null、details=`{guide_run_id,error_code}` |
| GUIDE-QUERY-C03 | `{run,requirement,current_document,template,scope,allowed_targets,user_input,history,source,read_manifest}`，各成员为固定完整结构，非任意 JSON |

内部失败仍只允许登记的安全 details 或 null，不能穿透 Provider 异常。GuideRun 私有 final_result_json 保存 C07 实际提交效果，REVIEW 可另保留正式 review_result 供 REVIEW_RESULT 来源读取；公开 I16 的 final_result 仍只投影 `summary/assistant_message_id/current_document_version/suggestion_batch_id`，不暴露完整 review_result、Prompt 或 LLMUse。内部 INITIALIZE 结果可保留未变化的 CURRENT 身份/版本供卡片过期绑定；公开 current_document_version 仍遵守原条款：只返回本次运行实际写入的版本，没有写入则为 null，不使用后续最新 CURRENT 版本代替。公开字段语义不因内部契约补全而改变，不新增检查对象。

**确认依据**：D-005 公共决策稿 C 及决策记录中的既有内部表示说明。**代码对应**：`comments/contracts.py::revalidate_anchors_result`、`guide/{contracts,commands,orchestrator,model_context,result_persistence}.py`。

<a id="shr-page"></a>
**SHR-PAGE 分页**

页码默认1，允许1～100000，每页固定20；total_pages=ceil(total/20)，total=0 时 total_pages=0。超出实际页数但处于合法页码范围时成功返回空 items，保留请求 page。列表与总数必须来自同一读取快照。具体匹配、排序和读取字段由各 Query 定义。消息采用 APP-MSG-QUERY-C01 的排他游标，不套用页码分页或总数。

<a id="shr-serialize"></a>
**SHR-SERIALIZE 结构序列化**

逻辑 JSON对象不是数据库 TEXT 字符串。入口拒绝重复 JSON 键、未知字段及错误类型；输出按白名单投影，*_json 解码为对象，不穿透 ORM 或原始模型响应。模型输出只接受一份完整 JSON，使用冻结 Schema 和业务验证后才可成为可信结果。HTTP 专属策略见第6.1节；历史消息损坏的唯一降级规则见 APP-MSG-QUERY-C01。

|复杂共享规则|正式归属与使用范围|
|---|---|
|SHR-BLOCK|OBJ-DOC 的 BlockState 字段与快照约束；解析、身份继承细则见[共同Block规则](#sync-be-07)和[分配证明](#sync-be-09)。适用于编辑、正文提交、版本、补丁和评论定位。|
|SHR-ANCHOR|OBJ-COMMENT 的锚点结构与 APP-COMMENT-CMD-C06 的重校验；定位算法见[共同锚点规则](#sync-be-11)。|
|SHR-CARDS|OBJ-MSG 的卡片／回答结构及 APP-GUIDE-CMD-C06 的整组提交；前端只维护未提交选择。|
|SHR-PATCH|OBJ-BATCH 的固定补丁结构与 APP-BATCH-CMD-C02 的原子应用；组合及权限算法见[补丁规则](#sync-be-12)。|
|SHR-SCOPE|APP-GUIDE-CMD-C01 的范围输入及 APP-GUIDE-QUERY-C03 的业务上下文；授权清单见[Scope规则](#sync-be-10)。|

### 2.3 运行配置与生命周期

|配置或固定资源|来源与生效规则|无效处理与暴露限制|
|---|---|---|
|需求模板 template_key＋template_version|创建需求时由用户选择，后端验证类型适用性并固定；已有需求不随目录变化替换模板|无效返回 TEMPLATE_INVALID；实际目录、内容及锁定结构见 INF-TEMPLATE／[Q-01](#q-01)。|
|FunctionType 及 Prompt、输入／输出 Schema、ContextPolicy 版本|后端在创建运行时选择并冻结；同运行继续保留冻结版本；失败任务重新运行创建新运行并重新冻结|资源缺失或无效返回 CONFIG_INVALID；不能静默回退其他版本。详见 INF-FUNCTION、[Q-02](#q-02)。|
|供应方、模型、采样与请求参数|由 INF-MODEL、INF-PROFILE 承载，调用记录保存实际配置快照|不得把真实密钥写入请求快照、日志或对外响应；具体来源、默认值及完整配置见 [Q-07](#q-07)、[Q-09](#q-09)。|

|运行事项|确定要求|
|---|---|
|启动|先执行 APP-GUIDE-CMD-C09 恢复中断占用，再接受新业务请求；不得把其他进程运行误判为本进程中断。|
|AI任务接受|只有接受事务成功提交的运行才允许交给 APP-GUIDE-ORCH-C01；事务内不访问 Provider。|
|异常退出后|原 RUNNING 运行由恢复能力标记失败并按占用关系处理，不自动重发模型请求。WAITING_USER、PENDING 批次和人工草稿不因等待时长自动清除。|
|超时监测|运行连续15分钟无进展按 EXECUTION_TIMEOUT 处理；等待用户的时间不计入该执行超时。扫描周期、最大检测延迟与工作领取机制见 [Q-08](#q-08)。|

安装和启动采用本节基线及backend/requirements.lock；资源/结构校验失败拒绝启动。正常关闭与在途任务处置按下述单进程协调规则，初始化/迁移须独立显式执行。



<a id="sync-be-05"></a>

**后台进程协调、监测和关闭**

本机操作系统文件锁保证一个执行进程，Windows 使用 OS 文件锁，不靠 PID 文件存在性；第二进程拒绝启动，进程退出由 OS 释放。启动校验资源和数据库，取得锁并恢复，再接受 HTTP。后台按 run_id 去重，业务接受提交后才调度，调度异常不改写已提交接受事实。每 30 秒进行不重叠的无进展扫描，错过时不并发补跑；15 分钟无进展阈值不变，正常调度下一扫描检测，进程卡顿不承诺墙钟硬上限。关闭停止接入、新调度和监测，为在途任务提供 10 秒宽限，随后退役执行权并尝试取消连接、记录中断；失败留待下次恢复，不自动重发。WAITING_USER、草稿和批次不因关闭被清除，外部计费不能回滚。

**确认依据**：D-003。**代码对应**：`infrastructure/process_lock.py::ProcessLock`、`infrastructure/execution_lease.py`、`guide/worker.py::{GuideWorker,check_no_progress,close}`、`service.py`。

## 3. 业务对象

实体的共同身份、时间和逻辑文本规则采用 SHR-ID、SHR-TIME、SHR-TEXT。JSON字段是逻辑结构，不能把数据库编码作为业务类型。对象默认值与创建场景的初始值分开；标为“无”的字段由创建能力确定，不允许缺失。


<a id="obj-req"></a>
### OBJ-REQ Requirement

#### 3.1 对象说明

|内容|确定定义|
|---|---|
|对象引用与名称|OBJ-REQ Requirement|
|业务含义|保存需求身份、固定模板引用、生命周期和正文流程占用|
|身份或相等规则|各实体以 id 为身份；生成依 SHR-ID／INF-DB；实体种类与 id 同时相等才相等。|
|所属与组成|唯一聚合根为 Requirement；内部成员见下表。外部写入通过本聚合根或根ID；跨聚合一致性由APP事务定义。|
|是否共享定义|是；以下逻辑结构供应用、持久化和公开投影引用，不共享可变运行实例。|


|成员引用|名称与类型|可单独引用|变更边界|
|---|---|---|---|
|OBJ-REQ-M1|Requirement／聚合根|是；修改仍经根|外部写入经本根或根ID，跨聚合一致性由所属 APP 事务保证。|


#### 3.2 字段与对象约束

**Requirement**

|字段路径|逻辑类型或定义引用|业务含义|可为null|对象默认值|字段规则或派生依据|
|---|---|---|---|---|---|
|id|ID|Requirement 纯数字主键|否|无|不可修改|
|requirement_no|Text|面向用户展示和查询Requirement的稳定业务编号|否|无|不可修改|
|requirement_type|NEW / CHANGE|创建时选择的需求业务类型|否|无|不可修改|
|initialization_mode|IDEATION / DESIGN|创建时选定的灵感模式或设计模式|否|无|创建时必须提供；创建后只读，属性更新不可修改，既有数据及运行快照保持|
|title|Text|当前需求标题|否|无|由所属APP能力修改|
|template_key|Text|创建时选择的稳定模板键|否|无|不可修改|
|template_version|Text|固定模板版本|否|无|不可修改|
|status|Text|当前生命周期阶段|否|无|由所属APP能力修改|
|document_work_state|Text|当前 Requirement 的正文互斥操作状态|否|无|由所属APP能力修改|
|active_operation_type|Text|当前占用文档的对象类型|是|null|由所属APP能力修改|
|active_operation_id|ID|当前草稿、GuideRun 或 SuggestionBatch 的数字 ID|是|null|由所属APP能力修改|
|created_at|UtcTime|Requirement 创建成功的时间|否|无|不可修改|
|updated_at|UtcTime|需求属性、生命周期或已定义占用变化的事件时间；查询和无变化请求不更新|否|无|由所属APP能力修改|
|completed_at|UtcTime|当前一次进入 COMPLETED 的时间|是|null|由所属APP能力修改|
|state_started_at|UtcTime|当前非 IDLE 工作状态的开始时间|是|null|由所属APP能力修改|


|约束引用|必须成立的条件|违反结果|
|---|---|---|
|OBJ-REQ-V01|id与requirement_no不可变且不同；编号满足SHR-ID|拒绝构造或变更；OBJECT_INVALID|
|OBJ-REQ-V02|title 经SHR-TEXT标准化后1～20个字符且无换行|拒绝构造或变更；OBJECT_INVALID|
|OBJ-REQ-V03|需求类型为NEW/CHANGE；template_key+template_version共同定位固定模板，创建后不替换|拒绝构造或变更；OBJECT_INVALID|
|OBJ-REQ-V04|status为INITIALIZING/ACTIVE/COMPLETED；COMPLETED必须有completed_at，其余为null|拒绝构造或变更；OBJECT_INVALID|
|OBJ-REQ-V05|IDLE的active_operation_type/id/state_started_at全部null；MANUAL_EDITING对应MANUAL_DRAFT；GUIDE_ACTIVE对应GUIDE_RUN；SUGGESTION_REVIEWING对应SUGGESTION_BATCH；非IDLE引用与开始时间非空|拒绝构造或变更；OBJECT_INVALID|
|OBJ-REQ-V06|initialization_mode为IDEATION或DESIGN|拒绝构造或变更；OBJECT_INVALID|


#### 3.3 关系与状态

一对多Document/Revision/Message/GuideRun/Batch/Comment；全部以requirement_id关联；禁止业务删除需求。

|状态值|准确含义|可观察数据|是否终态|
|---|---|---|---|
|INITIALIZING|尚未用户完成初始化|尚无BASELINE|否|
|ACTIVE|可维护阶段|已有BASELINE，completed_at为空|否|
|COMPLETED|用户声明完成|completed_at非空，正文维护只读|否，可重新激活|
|IDLE|无正文流程占用|active_operation_type/id均空|否|
|MANUAL_EDITING|人工草稿流程占用|活动指向唯一草稿|否|
|GUIDE_ACTIVE|AI运行或等用户占用|活动指向RUNNING/WAITING_USER运行|否|
|SUGGESTION_REVIEWING|等待整批建议处理|活动指向PENDING批次|否|



#### 3.5 存储与实现定位

由第7章 INF-REQ-REP 经聚合根保存，物理映射见 INF-DB，读取投影见所属 Query／INF-READ。持久化不改变本节字段及有效性。

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/requirements/contracts.py|Requirement字段/读取模型验证|OBJ-REQ对象约束；Repository/DDL共同承载|


<a id="obj-doc"></a>
### OBJ-DOC RequirementDocument

#### 3.1 对象说明

|内容|确定定义|
|---|---|
|对象引用与名称|OBJ-DOC RequirementDocument|
|业务含义|保存一份 Markdown 及同一快照的区块状态；正文和草稿是独立实例|
|身份或相等规则|各实体以 id 为身份；生成依 SHR-ID／INF-DB；实体种类与 id 同时相等才相等。|
|所属与组成|唯一聚合根为 RequirementDocument；内部成员见下表。外部写入通过本聚合根或根ID；跨聚合一致性由APP事务定义。|
|是否共享定义|是；以下逻辑结构供应用、持久化和公开投影引用，不共享可变运行实例。|


|成员引用|名称与类型|可单独引用|变更边界|
|---|---|---|---|
|OBJ-DOC-M1|RequirementDocument／聚合根|是；修改仍经根|外部写入经本根或根ID，跨聚合一致性由所属 APP 事务保证。|


#### 3.2 字段与对象约束

**RequirementDocument**

|字段路径|逻辑类型或定义引用|业务含义|可为null|对象默认值|字段规则或派生依据|
|---|---|---|---|---|---|
|id|ID|RequirementDocument 纯数字主键|否|无|不可修改；OBJ-DOC-V01～V05|
|requirement_id|ID|所属 Requirement|否|无|不可修改；OBJ-DOC-V01～V05|
|document_type|Text|区分正式正文和人工草稿|否|无|不可修改；OBJ-DOC-V01～V05|
|markdown_content|Text|当前记录保存的完整 Markdown|否|无|由所属APP能力修改；敏感内容；OBJ-DOC-V01～V05|
|block_state_json|BlockState（OBJ-DOC／SHR-BLOCK）|当前记录Markdown对应的BlockState，见SHR-BLOCK|否|无|由所属APP能力修改；OBJ-DOC-V01～V05|
|content_version|PositiveInt|控制自动保存和并发覆盖|否|1|由所属APP能力修改；OBJ-DOC-V01～V05|
|created_at|UtcTime|当前记录创建时间|否|无|不可修改；OBJ-DOC-V01～V05|
|updated_at|UtcTime|当前记录最近成功保存时间|否|无|由所属APP能力修改；OBJ-DOC-V01～V05|


|约束编号|作用对象|确定条件|违反结果|
|---|---|---|---|
|OBJ-DOC-V01|身份与类型|document_type为CURRENT或MANUAL_DRAFT；同需求同类型唯一|对象不能形成；OBJECT_INVALID|
|OBJ-DOC-V02|内容快照|markdown_content与block_state_json描述同一时点、同顺序的顶层区块|对象不能形成；OBJECT_INVALID|
|OBJ-DOC-V03|内容版本|content_version为正整数；CURRENT和MANUAL_DRAFT分别计数|对象不能形成；OBJECT_INVALID|
|OBJ-DOC-V04|区块结构|BlockState符合SHR-BLOCK；每区块身份唯一，next_block_id大于全部当前ID|对象不能形成；OBJECT_INVALID|
|OBJ-DOC-V05|区块元数据|创建时间不晚于最近修改时间；作者及来源合法；已有创建来源不可改|对象不能形成；OBJECT_INVALID|

CURRENT为正式正文；INITIALIZING页面曾使用“Working Draft”称呼，它仍是CURRENT，统一称“初始化中的正文”。MANUAL_DRAFT为另一条文档记录，只有人工编辑器读取。DocumentType是实例类别，不是生命周期状态；身份不得靠交换document_type晋升。

<a id="shr-block"></a>
**SHR-BLOCK／BlockState**

此结构供 CURRENT、MANUAL_DRAFT 和 Revision 快照复用。对象字段必须存在，未明确可空时不接受 null；未知字段拒绝。API 的同名字段只是本结构投影。

|字段路径|类型|含义|出现条件|可为null|约束|
|---|---|---|---|---|---|
|schema_version|integer|结构版本|始终存在|否|固定为 1|
|next_block_id|integer|下一个区块 ID|始终存在|否|大于全部现存 block_id，最大 9007199254740991|
|blocks|array[object]|区块列表|始终存在|否|按 Markdown 顶层区块顺序排列；空文档可为 []|
|blocks[].block_id|integer|区块 ID|每个元素必有|否|正整数|
|blocks[].block_type|string|区块类型|每个元素必有|否|解析器生成的顶层区块类型；完整枚举依本节[共同Block规则](#sync-be-07)|
|blocks[].section_path|array[string]|章节路径|每个元素必有|否|从外到内的标题文本；标题区块包含自身，首标题前为 []|
|blocks[].created_by_type|string|创建者类型|每个元素必有|否|USER / AI / SYSTEM|
|blocks[].created_source_type|string|创建来源类型|每个元素必有|否|TEMPLATE / GUIDE_RUN / SUGGESTION_BATCH / MANUAL_EDIT|
|blocks[].created_source_id|integer|创建来源 ID|每个元素必有|是|来源为 TEMPLATE 时 null；其余按来源对象关系验证|
|blocks[].created_at|string|创建时间|每个元素必有|否|UTC，YYYY-MM-DDTHH:mm:ss.SSSZ|
|blocks[].last_modified_by_type|string|最近修改者类型|每个元素必有|否|USER / AI / SYSTEM|
|blocks[].last_modified_source_type|string|最近修改来源类型|每个元素必有|否|TEMPLATE / GUIDE_RUN / SUGGESTION_BATCH / MANUAL_EDIT|
|blocks[].last_modified_source_id|integer|最近修改来源 ID|每个元素必有|是|来源引用规则同创建来源|
|blocks[].last_modified_at|string|最近修改时间|每个元素必有|否|UTC，YYYY-MM-DDTHH:mm:ss.SSSZ|


完整 Markdown 方言、解析器版本、全部 block_type 枚举、拆分／合并／移动／复制的身份继承与 next_block_id 分配、派生元数据及来源校验算法见 [Q-06](#q-06)。已有创建来源不可改；来源对象和署名组合按[人工来源规则](#sync-be-08)，人工分配事件、创建时间和撤销证明按[身份证明规则](#sync-be-09)；前端节点属性不能泄漏进Markdown。


<a id="sync-be-07"></a>

**Markdown方言、Block类型和身份继承**

CommonMark 0.31.2 加 GFM 表格、删除线、自动链接、任务列表；后端解析器 markdown-it-py 4.2.0 及已锁定插件。顶层类型完整集合为 heading、paragraph、blockquote、bullet_list、ordered_list、task_list、code_block、thematic_break、table、html_block、link_definition；图片为段落内联内容。HTML 保留为惰性可见原文，不执行；未注册数学/图表语法不新增 Block 类型。Markdown 源不 trim，顶层源片段与 BlockState 按顺序配对，空文档 blocks=[]，不能只凭数量相同判有效。

编辑/显式移动保留原节点 ID；新插入/复制分配新 ID；拆分前部保留、后部新建；合并保留文档顺序首个 ID。无明确映射的粘贴分配新身份，不按内容相似度猜。创建事实不可变；正文或 section_path 真正变化更新最近修改来源，纯顺序移动且章节路径不变不刷新修改事实。高水位不回退，撤销恢复只使用同草稿已证明身份，新增证明机制见 [BE-09](#sync-be-09)。

标题 section_path 使用由外到内的标题纯文本并包含自身，前标题区域为 []；重复标题允许，SECTION 按 heading 的 block_id 定位。完整 Markdown/类型/章节路径/身份/来源仍须共同校验，元数据不写进 Markdown。

**确认依据**：D-004，D-009 补身份证明。**代码对应**：`documents/{markdown,snapshot,raw_source,autolinks,strikethrough}.py`；前端 `documents/{editor-source,source-nodes,identity,edited-snapshot}.ts`；`shared/fixtures/` 的共同方言输入仅为辅助对应。

#### 3.3 关系与状态

多对一Requirement；一条CURRENT必须伴随需求创建，MANUAL_DRAFT只在编辑流程中存在。

#### 3.5 存储与实现定位

由第7章 INF-DOC-REP 经聚合根保存，物理映射见 INF-DB，读取投影见所属 Query／INF-READ。持久化不改变本节字段及有效性。

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/documents/contracts.py|文档字段/读取模型验证|OBJ-DOC；另见snapshot.py、sources.py、guards.py|


<a id="obj-rev"></a>
### OBJ-REV Revision

#### 3.1 对象说明

|内容|确定定义|
|---|---|
|对象引用与名称|OBJ-REV Revision|
|业务含义|保存一次不可变的正式正文与区块状态快照|
|身份或相等规则|各实体以 id 为身份；生成依 SHR-ID／INF-DB；实体种类与 id 同时相等才相等。|
|所属与组成|唯一聚合根为 Revision；内部成员见下表。外部写入通过本聚合根或根ID；跨聚合一致性由APP事务定义。|
|是否共享定义|是；以下逻辑结构供应用、持久化和公开投影引用，不共享可变运行实例。|


|成员引用|名称与类型|可单独引用|变更边界|
|---|---|---|---|
|OBJ-REV-M1|Revision／聚合根|是；修改仍经根|外部写入经本根或根ID，跨聚合一致性由所属 APP 事务保证。|


#### 3.2 字段与对象约束

**Revision**

|字段路径|逻辑类型或定义引用|业务含义|可为null|对象默认值|字段规则或派生依据|
|---|---|---|---|---|---|
|id|ID|纯数字主键|否|无|不可修改；OBJ-REV-V01～V03|
|requirement_id|ID|所属 Requirement|否|无|不可修改；OBJ-REV-V01～V03|
|version_no|PositiveInt|Requirement 内递增的版本序号|否|无|不可修改；OBJ-REV-V01～V03|
|revision_type|Text|初始化基线或手动版本|否|无|不可修改；OBJ-REV-V01～V03|
|markdown_snapshot|Text|创建版本时的完整正文|否|无|不可修改；敏感内容；OBJ-REV-V01～V03|
|block_state_snapshot_json|BlockState（OBJ-DOC／SHR-BLOCK）|与 Markdown 同一时点的区块状态|否|无|不可修改；OBJ-REV-V01～V03|
|description|Text|用户可填写的版本说明|是|null|不可修改；OBJ-REV-V01～V03|
|source_content_version|PositiveInt|创建快照时CURRENT的content_version|否|无|不可修改；OBJ-REV-V01～V03|
|created_at|UtcTime|版本创建时间|否|无|不可修改；OBJ-REV-V01～V03|


|约束编号|作用对象|确定条件|违反结果|
|---|---|---|---|
|OBJ-REV-V01|版本身份|requirement_id+version_no唯一；version_no正整数|对象不能形成；OBJECT_INVALID|
|OBJ-REV-V02|基线|BASELINE为version_no=1；每需求最多一条；其他类型MANUAL|对象不能形成；OBJECT_INVALID|
|OBJ-REV-V03|不可变快照|Markdown快照与区块快照同一时点；source_content_version为正整数；创建后所有字段不可变|对象不能形成；OBJECT_INVALID|

Revision 的 block_state_snapshot_json 完整采用 OBJ-DOC／BlockState；description 采用 SHR-TEXT，不重复定义快照字段。

#### 3.3 关系与状态

多对一Requirement；历史快照不包含Comment，不提供恢复。

#### 3.5 存储与实现定位

由第7章 INF-REV-REP 经聚合根保存，物理映射见 INF-DB，读取投影见所属 Query／INF-READ。持久化不改变本节字段及有效性。

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/revisions/contracts.py|版本字段/读取模型验证|OBJ-REV不可变快照约束|


<a id="obj-msg"></a>
### OBJ-MSG ConversationMessage

#### 3.1 对象说明

|内容|确定定义|
|---|---|
|对象引用与名称|OBJ-MSG ConversationMessage|
|业务含义|保存一条实际可见且不可变的用户或助手消息|
|身份或相等规则|各实体以 id 为身份；生成依 SHR-ID／INF-DB；实体种类与 id 同时相等才相等。|
|所属与组成|唯一聚合根为 ConversationMessage；内部成员见下表。外部写入通过本聚合根或根ID；跨聚合一致性由APP事务定义。|
|是否共享定义|是；以下逻辑结构供应用、持久化和公开投影引用，不共享可变运行实例。|


|成员引用|名称与类型|可单独引用|变更边界|
|---|---|---|---|
|OBJ-MSG-M1|ConversationMessage／聚合根|是；修改仍经根|外部写入经本根或根ID，跨聚合一致性由所属 APP 事务保证。|


#### 3.2 字段与对象约束

**ConversationMessage**

|字段路径|逻辑类型或定义引用|业务含义|可为null|对象默认值|字段规则或派生依据|
|---|---|---|---|---|---|
|id|ID|纯数字主键|否|无|不可修改；OBJ-MSG-V01～V05|
|requirement_id|ID|所属 Requirement|否|无|不可修改；OBJ-MSG-V01～V05|
|guide_run_id|ID|消息所属或触发的 GuideRun|是|null|不可修改；OBJ-MSG-V01～V05|
|sequence_no|PositiveInt|Requirement 连续对话中的顺序|否|无|不可修改；OBJ-MSG-V01～V05|
|role|Text|用户或 AI|否|无|不可修改；OBJ-MSG-V01～V05|
|content|Text|用户或 AI 实际看到的可读文字，也是结构化内容异常时的降级展示|否|无|不可修改；敏感内容；OBJ-MSG-V01～V05|
|message_type|Text|区分普通文本、卡片组和卡片响应|否|无|不可修改；OBJ-MSG-V01～V05|
|structured_content_json|卡片组或整组回答（本节 SHR-CARDS）|保存完整卡片组或整组用户响应|是|null|不可修改；OBJ-MSG-V01～V05|
|reply_to_message_id|ID|CARD_RESPONSE 对应的原卡片消息|是|null|不可修改；OBJ-MSG-V01～V05|
|idempotency_key|Text|防止同一次用户提交重复创建消息|是|null|不可修改；OBJ-MSG-V01～V05|
|created_at|UtcTime|消息产生时间|否|无|不可修改；OBJ-MSG-V01～V05|


|约束编号|作用对象|确定条件|违反结果|
|---|---|---|---|
|OBJ-MSG-V01|序列身份|requirement_id+sequence_no唯一且正整数；创建后消息不可变|对象不能形成；OBJECT_INVALID|
|OBJ-MSG-V02|角色与类型|USER或ASSISTANT；TEXT/INTERACTION_CARDS/CARD_RESPONSE；卡片组只属ASSISTANT、响应只属USER|对象不能形成；OBJECT_INVALID|
|OBJ-MSG-V03|结构条件|TEXT的structured_content_json与reply_to_message_id为null；卡片组结构完整；CARD_RESPONSE必须指同需求助手卡片组|对象不能形成；OBJECT_INVALID|
|OBJ-MSG-V04|响应唯一|每条卡片组至多一条CARD_RESPONSE；答案满足SHR-CARDS|对象不能形成；OBJECT_INVALID|
|OBJ-MSG-V05|幂等字段|用户提交的消息有idempotency_key；助手消息为null|对象不能形成；OBJECT_INVALID|



<a id="shr-cards"></a>
**SHR-CARDS／结构化消息**

INTERACTION_CARDS 根只含 schema_version、intro、cards；CARD_RESPONSE 根只含 schema_version、responses；两者不能混合字段。表中按 message_type 指定的条件选择一个结构，未知字段拒绝。

|字段路径|类型|含义|出现条件|可为null|约束|
|---|---|---|---|---|---|
|schema_version|integer|结构版本|父对象非 null 时必有|否|固定 1|
|intro|string|卡片引导文字|message_type=INTERACTION_CARDS 且结构有效时必有|否|—|
|cards|array[object]|卡片组|message_type=INTERACTION_CARDS 且结构有效时必有|否|1～5 张|
|cards[].card_key|string|卡片键|每个元素必有|否|—|
|cards[].card_type|string|卡片类型|每个元素必有|否|本契约传输编码：SINGLE_SELECT / MULTI_SELECT / CONFIRM|
|cards[].question|string|问题|每个元素必有|否|—|
|cards[].context|string|问题背景|每个元素必有|否|—|
|cards[].required|boolean|是否必答|每个元素必有|否|—|
|cards[].options|array[object]|选项|每个元素必有|否|单选 2～6 项，多选 2～8 项，确认固定 2 项|
|cards[].options[].option_key|string|选项键|每个元素必有|否|同一卡片内唯一|
|cards[].options[].label|string|选项名称|每个元素必有|否|—|
|cards[].options[].description|string|选项说明|每个元素必有|否|—|
|cards[].options[].impact|string|影响说明|每个元素必有|否|—|
|cards[].options[].risks|string|风险说明|每个元素必有|否|—|
|cards[].selection_rule|object|选项数量约束|每个元素必有|否|—|
|cards[].selection_rule.min|integer|最少选择数|每个元素必有|否|非负整数|
|cards[].selection_rule.max|integer|最多选择数|每个元素必有|否|不小于 min；单选/确认固定 1|
|cards[].custom_answer|object|自定义回答配置|每个元素必有|否|—|
|cards[].custom_answer.enabled|boolean|是否允许自定义|每个元素必有|否|—|
|cards[].custom_answer.max_length|integer|最大码点数|每个元素必有|否|enabled=true 时 1～2000；false 时 0|
|cards[].recommendation|object|AI 推荐|每个元素必有|是|—|
|cards[].recommendation.option_keys|array[string]|推荐选项键|父对象非 null 时必有|否|仅展示，不算正式选择|
|cards[].recommendation.reason|string|推荐理由|父对象非 null 时必有|否|—|
|cards[].related_spec_context|array[object]|关联规格片段|每个元素必有|否|只作展示，不授予修改范围|
|cards[].related_spec_context[].block_id|integer|区块 ID|每个元素必有|否|正整数|
|cards[].related_spec_context[].content_snapshot|string|原文快照|每个元素必有|否|—|
|responses|array[object]|整组回答|message_type=CARD_RESPONSE 且结构有效时必有|否|—|
|responses[].card_key|string|卡片键|每个元素必有|否|必须来自原卡片组，整组内唯一|
|responses[].selected_option_keys|array[string]|选项键列表|每个元素必有|否|来自当前卡片 options；数组内不可重复|
|responses[].custom_answer|string|自定义回答|每个元素必有|是|未使用时 null；可用性和长度由原卡片约束|
|responses[].skipped|boolean|是否跳过|每个元素必有|否|仅非必答卡片允许 true|


card_key 在同组唯一；option_key 在同卡片唯一。卡片组1～5张，交互优先1～3张独立问题，不把必需后继问题藏在同组选择后才生成。推荐只是展示，related_spec_context 只是关联展示，均不构成用户选择或扩大写入授权。CONFIRM 固定两个选项且不允许自定义；单选预设与自定义互斥，多选允许组合，自定义非空计作一次选择。完整回答必须覆盖全部 card_key，选项键来自原卡片且不重复；必答不能跳过，非必答未答必须显式 skipped=true、selected_option_keys=[]、custom_answer=null。提交、可用性与正式回答唯一性由 APP-GUIDE-CMD-C06 判断。

原组 card_state 是读取模型计算值，不增加持久化消息字段。TEXT 的 structured_content_json 和 reply_to_message_id 为 null；损坏历史结构只能按 APP-MSG-QUERY-C01 降级展示，不成为合法新消息。


<a id="sync-be-14"></a>

**唯一可回答卡片组和过期规则**

正式 CARD_RESPONSE 存在优先为 ANSWERED；否则仅最新助手卡片组可候选。后续新正式用户意图/新运行、初始化完成、正文版本或生命周期不再匹配使旧组失效。初始化组要求来自相应已完成 INITIALIZE 运行，当前仍 INITIALIZING/IDLE 且 CURRENT 身份版本等于该轮结果；其他组要求属于当前唯一 WAITING_USER 运行及实际占用，且正文身份版本匹配。暂时 MANUAL_EDITING 时不可答，取消且无正文变化后可重新由后端推导为 AVAILABLE；不设置等待自动过期时间，不将 card_state 写回消息。前端只服从服务端状态，不自行选择旧组恢复。

**确认依据**：D-004。**代码对应**：`messages/queries.py::card_state`、`infrastructure/message_repository.py`、`guide/commands.py`、前端 `guide/card-groups.ts`。

#### 3.3 关系与状态

多对一Requirement；可引用GuideRun；CARD_RESPONSE引用原Message。

#### 3.5 存储与实现定位

由第7章 INF-MSG-REP 经聚合根保存，物理映射见 INF-DB，读取投影见所属 Query／INF-READ。持久化不改变本节字段及有效性。

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/messages/contracts.py|消息字段/读取模型验证|OBJ-MSG；结构验证另见cards.py|


<a id="obj-guide"></a>
### OBJ-GUIDE GuideRun

#### 3.1 对象说明

|内容|确定定义|
|---|---|
|对象引用与名称|OBJ-GUIDE GuideRun|
|业务含义|保存一次用户触发的AI任务及其中每次真实模型请求|
|身份或相等规则|各实体以 id 为身份；生成依 SHR-ID／INF-DB；实体种类与 id 同时相等才相等。|
|所属与组成|唯一聚合根为 GuideRun；内部成员见下表。实体数量不等于聚合数量；表只承担存储。LLMUse归GuideRun、Suggestion归SuggestionBatch，均不设独立写Repository。|
|是否共享定义|是；以下逻辑结构供应用、持久化和公开投影引用，不共享可变运行实例。|


|成员引用|名称与类型|可单独引用|变更边界|
|---|---|---|---|
|OBJ-GUIDE-M1|GuideRun／聚合根|是；修改仍经根|外部写入经本根或根ID，跨聚合一致性由所属 APP 事务保证。|
|OBJ-GUIDE-M2|LLMUse／聚合内实体|是；修改仍经根|通过 GuideRun 聚合根；内部实体不设独立写 Repository。|


#### 3.2 字段与对象约束

**GuideRun**

|字段路径|逻辑类型或定义引用|业务含义|可为null|对象默认值|字段规则或派生依据|
|---|---|---|---|---|---|
|id|ID|纯数字主键|否|无|不可修改；OBJ-GUIDE-V01～V07|
|requirement_id|ID|所属 Requirement|否|无|不可修改；OBJ-GUIDE-V01～V07|
|idempotency_key|Text|防止同一用户动作重复创建|否|无|不可修改；OBJ-GUIDE-V01～V07|
|trigger_message_id|ID|本轮启动或最近一次继续输入的用户消息ID；初次创建与消息归属在同事务形成|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|trigger_type|Text|发起本轮或本次继续运行的业务动作|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|source_type|Text|本轮主要修改或处理依据|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|source_id|ID|REVIEW GuideRun 或 Comment 的来源对象 ID|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|function_type|Text|本轮采用的 AI 处理协议|否|无|不可修改；OBJ-GUIDE-V01～V07|
|context_template_key|Text|本轮 ContextAssembler 使用的固定模板|否|无|不可修改；OBJ-GUIDE-V01～V07|
|context_template_version|Text|本轮实际使用的 ContextTemplate 版本|否|无|不可修改；OBJ-GUIDE-V01～V07|
|prompt_version|Text|本轮 Function Prompt 的实际版本|否|无|不可修改；OBJ-GUIDE-V01～V07|
|action_type|Text|本轮最大权限|否|无|不可修改；OBJ-GUIDE-V01～V07|
|mode_snapshot|Text|INITIALIZE 时使用|是|null|不可修改；OBJ-GUIDE-V01～V07|
|instruction_summary|Text|用户任务摘要，仅作索引和展示；不能替代真实指令消息|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|scope_type|Text|用户希望处理的范围|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|scope_ref_json|ScopeRef（APP-GUIDE-CMD-C01 输入）|标题 Block、BlockRef 或 Selection 数据|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|read_scope_manifest_json|JSON对象|ContextAssembler 实际读取的内容|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07；结构与版本按第4.7节，审计按第7.3节|
|allowed_targets_json|JSON对象|程序根据 ActionType 和 Scope 生成|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07；结构与版本按第4.7节，审计按第7.3节|
|status|Text|当前 GuideRun 状态|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|current_step|Text|当前或最后执行到的程序步骤|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|final_result_json|JSON对象|经过解析和业务校验的结果|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07；结构与版本按第4.7节，审计按第7.3节|
|created_at|UtcTime|GuideRun 创建时间|否|无|不可修改；OBJ-GUIDE-V01～V07|
|started_at|UtcTime|实际开始执行时间|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|waiting_user_at|UtcTime|最近进入 WAITING_USER 的时间|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|ended_at|UtcTime|完成、失败或取消时间|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|updated_at|UtcTime|状态最近更新时间|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|error_code|Text|GuideRun 最终失败分类|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|error_message|Text|供诊断和前端映射的失败摘要|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|cancel_reason|Text|GuideRun 被取消的原因|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|retry_of_guide_run_id|ID|本运行由哪个 FAILED GuideRun 重新创建|是|null|不可修改；OBJ-GUIDE-V01～V07|


**LLMUse**

|字段路径|逻辑类型或定义引用|业务含义|可为null|对象默认值|字段规则或派生依据|
|---|---|---|---|---|---|
|id|ID|纯数字主键|否|无|不可修改；OBJ-GUIDE-V01～V07|
|guide_run_id|ID|所属 GuideRun|否|无|不可修改；OBJ-GUIDE-V01～V07|
|call_no|PositiveInt|GuideRun 内第几次业务调用|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|attempt_no|PositiveInt|同一逻辑调用的第几次重试|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|provider|Text|实际 Provider|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|model_name|Text|实际模型|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|model_version|Text|可获得时记录|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|function_type|Text|本次真实调用采用的 FunctionType|否|无|不可修改；OBJ-GUIDE-V01～V07|
|prompt_config|Text|本次实际使用的 Prompt Key 和版本|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|request_snapshot_json|JSON对象|实际发送给模型的请求及协议引用|否|无|由所属APP能力修改；敏感内容；OBJ-GUIDE-V01～V07；结构与版本按第4.7节，审计按第7.3节|
|parsed_output_json|JSON对象|成功解析为单一 JSON 对象但尚未完成业务校验的输出|是|null|由所属APP能力修改；敏感内容；OBJ-GUIDE-V01～V07；结构与版本按第4.7节，审计按第7.3节|
|trusted_output_json|JSON对象|通过输出 Schema、业务规则、状态、Scope 和 Allowed Targets 校验后的结果|是|null|由所属APP能力修改；敏感内容；OBJ-GUIDE-V01～V07；结构与版本按第4.7节，审计按第7.3节|
|input_summary|Text|便于排查的输入概述|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|context_manifest_json|JSON对象|本次实际读取的事实来源|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07；结构与版本按第4.7节，审计按第7.3节|
|raw_response_json|JSON对象|Provider 返回的原始结果|是|null|由所属APP能力修改；敏感内容；OBJ-GUIDE-V01～V07；结构与版本按第4.7节，审计按第7.3节|
|finish_reason|Text|Provider 返回的结束原因|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|parse_status|Text|原始响应是否成功解析|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|parse_error|Text|解析失败信息|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|validation_status|Text|解析结果是否通过业务校验|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|validation_error|Text|结构、权限或目标校验错误|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|call_status|Text|Provider 调用结果|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|input_tokens|Int|Provider 用量|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|output_tokens|Int|Provider 用量|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|cache_info_json|JSON对象|Provider 返回的缓存命中信息|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|provider_request_id|Text|供应方外部调用追踪ID原值，最多1024码点|是|null|不转内部ID、不截断；审计脱敏按INF-MODEL|
|cost|Text|供应方明确费用的定点十进制字符串|是|null|与cost_currency成对或均null；当前无费用取得映射，不推算或自拟小数位|
|cost_currency|Text|供应方明确费用币种|是|null|与cost成对或均null，不自拟币种|
|started_at|UtcTime|调用开始时间|否|无|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|ended_at|UtcTime|调用结束时间|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|duration_ms|Int|本次尝试耗时|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|error_code|Text|Provider 或网关错误分类|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|
|error_message|Text|调用失败原因|是|null|由所属APP能力修改；OBJ-GUIDE-V01～V07|


|约束编号|作用对象|确定条件|违反结果|
|---|---|---|---|
|OBJ-GUIDE-V01|运行类型|Action/Source/Function组合符合INF-FUNCTION；INITIALIZE有mode_snapshot；非初始化模式为空|对象不能形成；OBJECT_INVALID|
|OBJ-GUIDE-V02|冻结配置|context_template_key/version及prompt_version创建后不变；function_type不得被模型改变|对象不能形成；OBJECT_INVALID|
|OBJ-GUIDE-V03|终态字段|COMPLETED/FAILED/CANCELLED有ended_at；FAILED有安全error_code/message；CANCELLED有cancel_reason；取消不产生final_result_json|对象不能形成；OBJECT_INVALID|
|OBJ-GUIDE-V04|调用归属|LLMUse只属于一个GuideRun；guide_run_id+call_no+attempt_no唯一；序号为正整数|对象不能形成；OBJECT_INVALID|
|OBJ-GUIDE-V05|调用结果分离|call_status与parse_status、validation_status分别表示传输、解析和校验；trusted_output_json仅在validation_status=SUCCEEDED时非空|对象不能形成；OBJECT_INVALID|
|OBJ-GUIDE-V06|重试来源|retry_of_guide_run_id不能指自身，须同需求更早的FAILED运行|对象不能形成；OBJECT_INVALID|
|OBJ-GUIDE-V07|计量|Token与duration_ms为非负整数或null；未知不填0；cost/cost_currency成对或均null，仅使用供应方明确费用，不从token推算|对象不能形成；OBJECT_INVALID|

GuideRun中LLMUse的call_no表示逻辑调用位置；attempt_no表示该位置第几次真实请求，首次为1。Provider成功只结束传输维度，parse/validation仍可继续变化；“调用终态不得改写”不能解释为禁止首次解析或校验落库。取消后的迟到响应不得反向改写传输终态或补写可信输出。

GuideRun 的 current_step 对外编码为 PREPARING、CALLING_MODEL、VALIDATING、PERSISTING、WAITING_USER、FINISHED；status 由下节约束。final_result_json 是可信业务结果，其公开安全摘要由 APP-GUIDE-QUERY-C01 定义，不能直接返回存储 JSON。

LLMUse.attempt_no 包含初次真实请求，初次为1，同一 call_no 最多3次真实请求；名称中的“重试”不表示从第二次才开始计数。供应方未提供的 token、耗时或请求标识按各字段可空性处理，未知用量不能填0。cost为供应方明确费用的定点十进制字符串，与cost_currency成对或均null；当前没有费用取得映射，两者均null，不推算金额或自拟精度。

#### 3.3 关系与状态

多对一Requirement；包含多条LLMUse；MODIFY与Batch零或一；多态来源指Comment或REVIEW Run。

|状态值|准确含义|可观察数据|是否终态|
|---|---|---|---|
|RUNNING|正在准备或处理|current_step非FINISHED|否|
|WAITING_USER|等用户补充|waiting_user_at有值且占用保留|否|
|COMPLETED|可信业务结果已持久化|ended_at存在|是|
|FAILED|任务无法完成|error_code及ended_at存在|是|
|CANCELLED|取消获胜，后续输出不用|cancel_reason及ended_at存在|是|
|LLMUse.call_status=SUCCEEDED|Provider传输成功|收到响应；不意味着解析成功|传输维度终态|
|LLMUse.call_status=FAILED/CANCELLED|传输失败或业务取消|安全错误或取消结束时间|是|
|LLMUse.parse_status|NOT_STARTED/SUCCEEDED/FAILED|是否形成单一JSON解析结果|依处理阶段|
|LLMUse.validation_status|NOT_STARTED/SUCCEEDED/FAILED|是否通过全部校验|依处理阶段|



#### 3.5 存储与实现定位

由第7章 INF-GUIDE-REP 经聚合根保存，物理映射见 INF-DB，读取投影见所属 Query／INF-READ。持久化不改变本节字段及有效性。

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/guide/contracts.py|运行字段/读取模型验证|OBJ-GUIDE；LLMUse审计另见infrastructure/audit_repository.py、audit_data.py|


<a id="obj-batch"></a>
### OBJ-BATCH SuggestionBatch

#### 3.1 对象说明

|内容|确定定义|
|---|---|
|对象引用与名称|OBJ-BATCH SuggestionBatch|
|业务含义|保存一批建议、单项决定和整批应用结果|
|身份或相等规则|各实体以 id 为身份；生成依 SHR-ID／INF-DB；实体种类与 id 同时相等才相等。|
|所属与组成|唯一聚合根为 SuggestionBatch；内部成员见下表。实体数量不等于聚合数量；表只承担存储。LLMUse归GuideRun、Suggestion归SuggestionBatch，均不设独立写Repository。|
|是否共享定义|是；以下逻辑结构供应用、持久化和公开投影引用，不共享可变运行实例。|


|成员引用|名称与类型|可单独引用|变更边界|
|---|---|---|---|
|OBJ-BATCH-M1|SuggestionBatch／聚合根|是；修改仍经根|外部写入经本根或根ID，跨聚合一致性由所属 APP 事务保证。|
|OBJ-BATCH-M2|Suggestion／聚合内实体|是；修改仍经根|通过 SuggestionBatch 聚合根；内部实体不设独立写 Repository。|


#### 3.2 字段与对象约束

**SuggestionBatch**

|字段路径|逻辑类型或定义引用|业务含义|可为null|对象默认值|字段规则或派生依据|
|---|---|---|---|---|---|
|id|ID|纯数字主键|否|无|不可修改；OBJ-BATCH-V01～V06|
|requirement_id|ID|所属 Requirement|否|无|不可修改；OBJ-BATCH-V01～V06|
|guide_run_id|ID|生成本批建议的 MODIFY GuideRun|否|无|不可修改；OBJ-BATCH-V01～V06|
|source_type|Text|本批修改意图来源|否|无|由所属APP能力修改；OBJ-BATCH-V01～V06|
|source_id|ID|来源 REVIEW GuideRun 或 Comment ID|是|null|由所属APP能力修改；OBJ-BATCH-V01～V06|
|title|Text|修改任务名称|否|无|由所属APP能力修改；OBJ-BATCH-V01～V06|
|summary|Text|修改目的和范围|否|无|由所属APP能力修改；OBJ-BATCH-V01～V06|
|status|Text|当前生命周期|否|无|由所属APP能力修改；OBJ-BATCH-V01～V06|
|completion_result|Text|是否产生实际正文变化|是|null|由所属APP能力修改；OBJ-BATCH-V01～V06|
|error_message|Text|提交或应用失败信息|是|null|由所属APP能力修改；OBJ-BATCH-V01～V06|
|base_content_version|Int|生成建议时使用的 Current Document 版本|否|无|由所属APP能力修改；OBJ-BATCH-V01～V06|
|applied_content_version|Int|实际修改正文后的 Current Document 版本|是|null|由所属APP能力修改；OBJ-BATCH-V01～V06|
|created_at|UtcTime|批次生成时间|否|无|不可修改；OBJ-BATCH-V01～V06|
|completed_at|UtcTime|完成或放弃时间|是|null|由所属APP能力修改；OBJ-BATCH-V01～V06|
|updated_at|UtcTime|批次状态或所属 Suggestion 决策最近变化时间|否|无|由所属APP能力修改；OBJ-BATCH-V01～V06|


**Suggestion**

|字段路径|逻辑类型或定义引用|业务含义|可为null|对象默认值|字段规则或派生依据|
|---|---|---|---|---|---|
|id|ID|纯数字主键|否|无|不可修改；OBJ-BATCH-V01～V06|
|batch_id|ID|所属 SuggestionBatch|否|无|不可修改；OBJ-BATCH-V01～V06|
|order_no|PositiveInt|展示和确定性应用顺序|否|无|不可修改；OBJ-BATCH-V01～V06|
|title|Text|单项建议名称|否|无|由所属APP能力修改；OBJ-BATCH-V01～V06|
|explanation|Text|为什么这样修改|否|无|由所属APP能力修改；OBJ-BATCH-V01～V06|
|impact|Text|可能影响的章节或规则|是|null|由所属APP能力修改；OBJ-BATCH-V01～V06|
|patch_operation|Text|确定性修改方式|否|无|不可修改；OBJ-BATCH-V01～V06|
|target_ref_json|TargetRef（本节 SHR-PATCH）|目标区块定位信息|否|无|不可修改；OBJ-BATCH-V01～V06|
|selector_json|TableRowSelector（本节 SHR-PATCH）|TABLE_ROW 定位信息|是|null|不可修改；OBJ-BATCH-V01～V06|
|original_content|Text|生成建议时读取的目标原始内容|否|无|不可修改；OBJ-BATCH-V01～V06|
|proposed_markdown|Text|Block 级建议内容|是|null|不可修改；OBJ-BATCH-V01～V06|
|proposed_data_json|TableRowData（本节 SHR-PATCH）|TABLE_ROW 等结构化修改内容|是|null|不可修改；OBJ-BATCH-V01～V06|
|user_edited_content|Text|EDITED 状态下最终内容|是|null|由所属APP能力修改；OBJ-BATCH-V01～V06|
|status|Text|用户当前决策|否|无|由所属APP能力修改；OBJ-BATCH-V01～V06|
|validation_status|Text|最近一次建议校验状态；生成时保存；应用失败仅返回本次安全详情，不更新已存状态，见[Patch规则](#sync-be-12)|否|无|由所属APP能力修改；OBJ-BATCH-V01～V06|
|validation_error|Text|校验失败原因|是|null|由所属APP能力修改；OBJ-BATCH-V01～V06|
|created_at|UtcTime|建议生成时间|否|无|不可修改；OBJ-BATCH-V01～V06|
|decided_at|UtcTime|用户处理时间|是|null|由所属APP能力修改；OBJ-BATCH-V01～V06|
|updated_at|UtcTime|内容或状态最近更新时间|否|无|由所属APP能力修改；OBJ-BATCH-V01～V06|


|约束编号|作用对象|确定条件|违反结果|
|---|---|---|---|
|OBJ-BATCH-V01|组成|至少一条Suggestion；同GuideRun最多一批且来源必须为MODIFY；Suggestion只能随根访问修改|对象不能形成；OBJECT_INVALID|
|OBJ-BATCH-V02|决策|Suggestion状态为PENDING/ACCEPTED/REJECTED/EDITED；EDITED有合法user_edited_content；其他不用它作为应用内容|对象不能形成；OBJECT_INVALID|
|OBJ-BATCH-V03|批次终态|PENDING/COMPLETED/DISCARDED；COMPLETED有CHANGES_APPLIED或NO_CHANGE；只有CHANGES_APPLIED有applied_content_version|对象不能形成；OBJECT_INVALID|
|OBJ-BATCH-V04|目标版本|base_content_version正整数；order_no在批次内唯一且正整数|对象不能形成；OBJECT_INVALID|
|OBJ-BATCH-V05|Patch结构|patch_operation属于SHR-PATCH支持集合；目标和内容结构必须匹配操作|对象不能形成；OBJECT_INVALID|
|OBJ-BATCH-V06|计数|counts是读取结果，不是持久化对象字段；total等于四类单项状态数量之和|对象不能形成；OBJECT_INVALID|

<a id="shr-patch"></a>
**SHR-PATCH／固定补丁结构**

|结构|字段|类型／可空|确定约束|
|---|---|---|---|
|TargetRef|block_id|ID／否|原目标或插入锚点的区块ID；只有此字段。|
|TableRowSelector|key_column_index|非负整数／否|从0开始的键列索引。|
|TableRowSelector|key_value|Text／否|在目标表中唯一匹配，不做类型推断。|
|TableRowData|cells|array[string]／否|按表头顺序的替换行单元格，不含表头，数量与列数一致。|


|patch_operation|selector_json|proposed_markdown|proposed_data_json|决定限制|
|---|---|---|---|---|
|REPLACE_BLOCK|null|非空Markdown|null|ACCEPTED、REJECTED、EDITED|
|INSERT_BEFORE|null|非空Markdown|null|ACCEPTED、REJECTED、EDITED|
|INSERT_AFTER|null|非空Markdown|null|ACCEPTED、REJECTED、EDITED|
|DELETE_BLOCK|null|null|null|只允许ACCEPTED、REJECTED，不能EDITED|
|REPLACE_TABLE_ROW|TableRowSelector|null|TableRowData|EDITED时user_edited_content使用仅含cells的JSON文本|


original_content 保存基线目标原文，用于直接比较。用户不得改变 target_ref、patch_operation、selector、order_no；非 EDITED 决策清空 user_edited_content。对外 validation_status 为 VALID／INVALID，INVALID 时 validation_error 为安全提示，VALID 时 null。生成批次保存校验状态；决定或完成失败只返回安全suggestion_errors，不反写validation_status/validation_error或批次error_message。EDITED按USER/SUGGESTION_BATCH署名，组合算法及原子性见[Patch规则](#sync-be-12)。


<a id="sync-be-12"></a>

**五种Patch、组合冲突和失败详情**

基线一次校验，original_content 逐字等于实际原块/原行，接受或编辑的补丁按 order_no 应用。REPLACE_BLOCK/插入结果必须恰为一个顶层块；DELETE_BLOCK 不可 EDITED。表格行只提交等列数的字符串 cells JSON，按纯文本转义，`key_column_index` 从 0 起，在指定列纯文本中精确唯一匹配，不扩成整表操作。

同块多个替换/删除、块替换与行替换、同一行重复替换、目标删除与锚定插入冲突时 PATCH_INVALID；不同行替换可组合，同锚点插入按既定顺序。目标/原文/授权失效为 TARGET_STALE，不部分应用。替换保留 ID，插入新分配，删除不复用；ACCEPTED 改动来源 AI/SUGGESTION_BATCH，EDITED 来源 USER/SUGGESTION_BATCH，既有创建事实不变。

生成批次须全项合法；失败完成不改正文、决定或已存校验状态。I21/I22 的适用失败可返回安全 `{suggestion_errors:[{suggestion_id,code,message}]}`，前端用本次详情定位，不以失败动作偷偷写 validation_status/error。

**确认依据**：D-004，公共决策稿 B。**代码对应**：`documents/{patch_validation,patch_application,tables}.py`、`suggestions/commands.py`、`suggestions/contracts.py`、`shared/http_errors.py`。

#### 3.3 关系与状态

多对一Requirement；来源一个MODIFY Run；至少包含一条Suggestion。

|状态值|准确含义|可观察数据|是否终态|
|---|---|---|---|
|PENDING|等待整批完成|completed_at为空|否|
|COMPLETED|整批已提交|completion_result存在|是|
|DISCARDED|用户放弃整批|completed_at有值，单项保留|是|
|Suggestion.PENDING|尚未决定|decided_at为空|否|
|Suggestion.ACCEPTED|采用模型原建议|decided_at有值|随批次终结|
|Suggestion.REJECTED|不采用本项|不产生对应Patch|随批次终结|
|Suggestion.EDITED|采用用户编辑内容|user_edited_content有值|随批次终结|



#### 3.5 存储与实现定位

由第7章 INF-BATCH-REP 经聚合根保存，物理映射见 INF-DB，读取投影见所属 Query／INF-READ。持久化不改变本节字段及有效性。

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/suggestions/contracts.py|批次及建议字段验证|OBJ-BATCH；另见文档Patch规则|


<a id="obj-comment"></a>
### OBJ-COMMENT Comment

#### 3.1 对象说明

|内容|确定定义|
|---|---|
|对象引用与名称|OBJ-COMMENT Comment|
|业务含义|保存独立评论、原引用、处理状态及锚点状态|
|身份或相等规则|各实体以 id 为身份；生成依 SHR-ID／INF-DB；实体种类与 id 同时相等才相等。|
|所属与组成|唯一聚合根为 Comment；内部成员见下表。外部写入通过本聚合根或根ID；跨聚合一致性由APP事务定义。|
|是否共享定义|是；以下逻辑结构供应用、持久化和公开投影引用，不共享可变运行实例。|


|成员引用|名称与类型|可单独引用|变更边界|
|---|---|---|---|
|OBJ-COMMENT-M1|Comment／聚合根|是；修改仍经根|外部写入经本根或根ID，跨聚合一致性由所属 APP 事务保证。|


#### 3.2 字段与对象约束

**Comment**

|字段路径|逻辑类型或定义引用|业务含义|可为null|对象默认值|字段规则或派生依据|
|---|---|---|---|---|---|
|id|ID|Comment 纯数字主键|否|无|不可修改；OBJ-COMMENT-V01～V05|
|requirement_id|ID|所属 Requirement|否|无|不可修改；OBJ-COMMENT-V01～V05|
|content|Text|用户填写的纯文本评论|否|无|由所属APP能力修改；OBJ-COMMENT-V01～V05|
|anchor_type|Text|评论关联完整区块或区块内选区|否|无|不可修改；OBJ-COMMENT-V01～V05|
|block_id|BlockId|Current Document 中的原区块身份|否|无|不可修改；OBJ-COMMENT-V01～V05|
|anchor_ref_json|AnchorRef（本节 SHR-ANCHOR）|创建时的引用快照和 Selection 定位上下文|否|无|不可修改；OBJ-COMMENT-V01～V05|
|anchor_status|Text|当前能否可靠定位|否|无|由所属APP能力修改；OBJ-COMMENT-V01～V05|
|status|Text|评论是否已经解决|否|无|由所属APP能力修改；OBJ-COMMENT-V01～V05|
|resolved_at|UtcTime|当前一次解决评论的时间|是|null|由所属APP能力修改；OBJ-COMMENT-V01～V05|
|deleted_at|UtcTime|评论软删除时间|是|null|由所属APP能力修改；OBJ-COMMENT-V01～V05|
|created_at|UtcTime|评论创建时间|否|无|不可修改；OBJ-COMMENT-V01～V05|
|updated_at|UtcTime|评论正文或生命周期最近更新时间|否|无|由所属APP能力修改；OBJ-COMMENT-V01～V05|


|约束编号|作用对象|确定条件|违反结果|
|---|---|---|---|
|OBJ-COMMENT-V01|正文|SHR-TEXT标准化后1～2000字符，纯文本可换行|对象不能形成；OBJECT_INVALID|
|OBJ-COMMENT-V02|锚点|anchor_type为BLOCK或SELECTION；block_id正整数；anchor_ref符合SHR-ANCHOR；不得含指纹|对象不能形成；OBJECT_INVALID|
|OBJ-COMMENT-V03|双状态|status为OPEN/RESOLVED；anchor_status为ATTACHED/ORPHANED；两维独立|对象不能形成；OBJECT_INVALID|
|OBJ-COMMENT-V04|事件时间|RESOLVED有resolved_at；OPEN为null；deleted_at非空表示软删除|对象不能形成；OBJECT_INVALID|
|OBJ-COMMENT-V05|引用|requirement_id固定；同一锚点允许多条不同身份评论|对象不能形成；OBJECT_INVALID|

<a id="shr-anchor"></a>
**SHR-ANCHOR／AnchorRef**

|anchor_type|anchor_ref_json完整字段|约束|
|---|---|---|
|BLOCK|block_markdown_snapshot: string|创建时完整区块Markdown；后端从CURRENT构造。|
|SELECTION|selected_text: string；prefix_text: string；suffix_text: string|分别采用SHR-TEXT的原文范围；必须在原block_id内唯一定位，不能跨区块。|


AnchorRef 按 anchor_type 二选一，未知字段拒绝，不含指纹，不因后续编辑替换创建时原引用。锚点重校验只修改 anchor_status，不修改评论 content、业务 status 或 updated_at；能够在原 block_id 再次唯一定位时允许自动恢复 ATTACHED，但不提供人工重新挂载。当前读取的 location 是独立计算投影，不覆盖持久化 anchor_status；偏移单位与文本提取采用本节[唯一定位算法](#sync-be-11)。


<a id="sync-be-11"></a>

**锚点投影和唯一定位算法**

定位使用共同纯文本投影：文字、代码、链接标签及图片 alt 保留，显示标记去除；软/硬换行为 LF，列表项/表格行之间 LF，表格列之间 TAB，HTML 使用原源文本。偏移为 Unicode 码点半开区间。仅在原 block_id 内逐位置匹配 selected_text 和紧邻 prefix/suffix，包含重叠候选；不 trim、不 Unicode 归一化、不跨块，恰好一个候选才可定位。BLOCK 原 ID 存在即可定位；原 Block 恢复且选区重新唯一可恢复 ATTACHED。创建引用快照不可变，查询只计算 location，不改 anchor_status/updated_at；只有既定写路径重校验持久锚点状态。

**确认依据**：D-004。**代码对应**：`documents/markdown.py`、`documents/anchors.py::{locate,validate_anchor}`、`comments/commands.py::revalidate_anchors`、前端 `documents/selection.ts`。

#### 3.3 关系与状态

多对一Requirement；block_id为快照内部身份，不能建数据库外键；可被Run和Batch历史引用。

|状态值|准确含义|可观察数据|是否终态|
|---|---|---|---|
|OPEN|尚未解决|resolved_at为空|否|
|RESOLVED|用户已解决|resolved_at有值|否|
|ATTACHED|原锚点可定位|算法能确定位置|否|
|ORPHANED|原锚点不可唯一定位|只保留创建时原引用|否|
|deleted_at非空|用户软删除|默认查询排除|是，无恢复|



#### 3.5 存储与实现定位

由第7章 INF-COMMENT-REP 经聚合根保存，物理映射见 INF-DB，读取投影见所属 Query／INF-READ。持久化不改变本节字段及有效性。

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/comments/contracts.py|评论字段/读取模型验证|OBJ-COMMENT；另见锚点规则|


## 4. 应用能力

<a id="app-exec-common"></a>


**APP-EXEC-COMMON 写入共同要求**

所有声明共同写入的步骤使用 INF-TX 同一短事务；成功记录与业务结果同时提交，相同成功幂等请求直接返回原结果。拒绝默认不写入，APP-GUIDE-CMD-C05 的锚点校正为明确例外。任一步映射、存储或提交失败均回滚共同写入，不保留部分对象结果。事务内重新读取状态并原子检查占用、关系与指定版本，不能依赖先前 GET。只有已提交的 AI 运行可交给后台；Provider 调用始终在 Command 事务之外。带 idempotency_key 的能力采用 SHR-IDEMPOTENCY，其他写入按自身状态与版本重试。物理实现见 INF-TX、INF-DB，持久幂等采用[所有权、保留与恢复规则](#sync-be-04)。

应用结果统一采用 SHR-RESULT。每项 4.4 的 data 是成功业务载荷；失败为 data=null、details 采用 API-COM-ERROR 中已定义的安全结构，HTTP 状态只由第6章映射。公共失败只在对应条件实际触发时返回；未预期异常不能冒充业务拒绝。所有 Query 无业务副作用，不修复占用、不写锚点、不改时间、不建版本、不触发模型。


<a id="app-req-cmd-c01"></a>
### APP-REQ-CMD-C01 创建需求

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-REQ-CMD-C01 创建需求|
|处理目标|创建需求的完整应用结果|
|主要对象或过程|OBJ-REQ|
|完成方式|接受后继续执行；本次只确认接受事务，最终状态由APP-GUIDE-QUERY-C01观察。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|title|Title|调用参数；需求标题|是|否|标准化后 1～20 个 Unicode 码点，不含换行；缺失：拒绝；必填值|
|requirement_type|NEW / CHANGE|调用参数；固定业务类型|是|否|NEW：需求新增；CHANGE：需求改造；区分大小写；缺失：拒绝；必填值|
|template_key|Text|调用参数；模板键|是|否|非空字符串，最多 128 个码点；必须命中所选类型的模板目录；缺失：拒绝；必填值|
|template_version|Text|调用参数；固定模板版本|是|否|非空字符串，最多 64 个码点；与模板键共同确定固定资源；缺失：拒绝；必填值|
|initial_idea|Idea|调用参数；首条用户输入|是|否|标准化后 1～10000 个 Unicode 码点，可换行；缺失：拒绝；必填值|
|initialization_mode|IDEATION / DESIGN|调用参数；用户主动选择的模式|是|否|IDEATION：灵感模式；DESIGN：设计模式；创建时必须主动提供；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始<br>|标准化标题和Idea，校验有效值及固定模板适用性；数据变化：无|OBJ-REQ；SHR-TEXT；INF-TEMPLATE|合法→P02；否则INVALID_INPUT或TEMPLATE_INVALID|
|P02；输入有效|读取幂等记录；相同已成功请求返回原资源；数据变化：无|SHR-IDEMPOTENCY|未执行→P03；其他→幂等结果|
|P03；首次执行|在同一短事务创建Requirement、CURRENT、首条用户TEXT和INITIALIZE GuideRun；初始化区块身份；绑定GUIDE_ACTIVE占用；数据变化：四个聚合新增；Requirement工作状态直接指向新运行|INF-TX；INF-REQ-REP；INF-DOC-REP；INF-MSG-REP；INF-GUIDE-REP|提交成功→CREATED；存储失败→STORAGE_UNAVAILABLE|


**入口绑定的业务约束**

- 创建同一事务包含 Requirement、CURRENT、首条用户消息及 INITIALIZE GuideRun。CREATED 仅表示资源创建和任务已接受，最终结果通过 I16 读取。

- 模板键与版本必须来自已配置目录；初始模式没有默认值。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|CREATED|成功|返回Requirement、CURRENT id、GuideRun id；仅表示创建及接受AI任务；完整成功载荷见本节。|接受后继续执行；本次只确认接受事务，最终状态由APP-GUIDE-QUERY-C01观察。|
|TEMPLATE_INVALID|拒绝|模板不存在或不适用于所选需求类型|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|


**成功载荷 data**

|字段路径|类型或定义引用|含义|出现条件及可空性|确定限制|
|---|---|---|---|---|
|requirement|[RequirementReadModel](#requirementreadmodel)（APP-REQ-QUERY-C02）|新需求|始终存在；不可为null|—|
|current_document_id|Int|当前正文 ID|始终存在；不可为null|正整数|
|guide_run_id|Int|初始化运行 ID|始终存在；不可为null|正整数|


**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`TEMPLATE_INVALID`|模板键/版本不存在，或不适用于需求类型；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONFIG_INVALID`|初始化所需冻结协议资源缺失；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CAPACITY_EXHAUSTED`|编号/版本/序号分配耗尽；拒绝整个事务，不部分提交。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

创建事务内不访问Provider。已提交的需求不会因后续模型失败而回滚；提交后由后台入口推进APP-GUIDE-ORCH-C01。初始Idea仅作为用户消息保存，不增加Requirement.initial_idea列。模板采用[已确认固定资源](#sync-be-06)，资产缺失按TEMPLATE_INVALID拒绝，不生成替代模板。

采用 APP-EXEC-COMMON；参与Repository为 INF-DOC-REP、INF-GUIDE-REP、INF-MSG-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/requirements/commands.py|create_requirement|APP-REQ-CMD-C01|
|backend/app/requirements/contracts.py|create_requirement_input / create_requirement_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-req-cmd-c02"></a>
### APP-REQ-CMD-C02 修改需求

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-REQ-CMD-C02 修改需求|
|处理目标|仅修改需求标题；初始化模式创建后只读，不提供模式更新能力|
|主要对象或过程|OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|title|Title|调用参数；只修改标题|是|否|标准化后1～20个Unicode码点、不含换行；缺失、显式null、未知字段（含initialization_mode）均拒绝|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|只接受requirement_id及必填title；空输入、null或未知字段整体拒绝，模式同值或与标题混合也拒绝；数据变化：无|OBJ-REQ；SHR-TEXT|合法→P02；否则INVALID_INPUT|
|P02；字段合法|读取需求并在同一写事务复核标题仅INITIALIZING或ACTIVE可修改；不额外要求IDLE；数据变化：无|INF-REQ-REP；INF-TX|允许→P03；否则NOT_FOUND或STATE_CONFLICT|
|P03；允许|仅更新发生变化的title；同值成功且不写updated_at；模式、正文、运行mode_snapshot、历史和审计不变|INF-REQ-REP|UPDATED|


**入口绑定的业务约束**

- title必填；所有模式字段（含同值及与合法标题混合）先按未知字段整体拒绝，不部分修改标题或updated_at。

- 标题可在INITIALIZING／ACTIVE修改，保持原并发事务复核；COMPLETED拒绝。模式只在创建选择，此后只读；无需数据库迁移或历史数据重写。相同标题成功且不刷新updated_at。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|UPDATED|成功|返回更新后的Requirement；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[RequirementReadModel](#requirementreadmodel)（APP-REQ-QUERY-C02）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|标题修改时需求不是INITIALIZING／ACTIVE；无业务写入，按SHR-RESULT返回。|
|`WORK_STATE_CONFLICT`|HTTP响应错误集合仍保留该编码；当前仅标题修改没有占用限制，不再存在模式非IDLE分支，不以该编码拒绝合法标题更新。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

采用 APP-EXEC-COMMON；参与Repository为 INF-REQ-REP。Repository.update_attributes仅允许title；非法模式在进入写入前拒绝。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/requirements/commands.py|update_requirement|APP-REQ-CMD-C02|
|backend/app/requirements/contracts.py|update_requirement_input / update_requirement_result|应用输入输出；不含HTTP或ORM对象|



<a id="app-req-cmd-c03"></a>
### APP-REQ-CMD-C03 完成初始化

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-REQ-CMD-C03 完成初始化|
|处理目标|完成初始化的完整应用结果|
|主要对象或过程|OBJ-DOC|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|expected_content_version|PositiveInt|调用参数；读取时的CURRENT内容版本|是|否|读取时的 CURRENT.content_version；正整数，不接受布尔值；不等于 Revision.version_no；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验幂等并读取Requirement与CURRENT；数据变化：无|SHR-IDEMPOTENCY；INF-REQ-REP；INF-DOC-REP|首次执行→P02；已有成功→原结果|
|P02；首次执行|在同一写事务检查INITIALIZING、IDLE、无草稿/活动Run/待处理批次且无BASELINE；校验正文版本和快照、模板锁定结构；数据变化：无|INF-TX；OBJ-DOC；INF-TEMPLATE|合法→P03；否则状态/版本/快照错误|
|P03；校验成功|复制CURRENT快照创建BASELINE V1，说明为“初始化基线”；Requirement改为ACTIVE；数据变化：仅新增Revision并改变Requirement.status/updated_at|INF-REV-REP；INF-REQ-REP|INITIALIZATION_COMPLETED|


**入口绑定的业务约束**

- 要求 INITIALIZING、IDLE、无草稿/活动运行/待处理批次，且没有 BASELINE。成功创建 BASELINE V1，说明固定“初始化基线”，需求转 ACTIVE；CURRENT ID 和 content_version 保持原值。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|INITIALIZATION_COMPLETED|成功|返回Requirement、baseline_revision和current_document身份/版本；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

|字段路径|类型或定义引用|含义|出现条件及可空性|确定限制|
|---|---|---|---|---|
|requirement|[RequirementReadModel](#requirementreadmodel)（APP-REQ-QUERY-C02）|需求|始终存在；不可为null|—|
|baseline_revision|[RevisionSummary](#revisionsummary)（APP-REV-QUERY-C01）|初始化基线|始终存在；不可为null|—|
|current_document|object|当前正文身份及版本|始终存在；不可为null|—|
|current_document.id|Int|文档 ID|始终存在；不可为null|正整数|
|current_document.content_version|Int|内容版本|始终存在；不可为null|CURRENT 与 MANUAL_DRAFT 各自独立递增|


**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|非 INITIALIZING 或已有 BASELINE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|不是 IDLE 或仍存在草稿、活动运行、待处理批次；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|CURRENT 或活动关系不一致；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONTENT_VERSION_CONFLICT`|CURRENT 版本与预期不符；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`DOCUMENT_INVALID`|CURRENT 快照不合法；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`TEMPLATE_INVALID`|初始化正文不符合锁定模板结构；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CAPACITY_EXHAUSTED`|编号/版本/序号分配耗尽；拒绝整个事务，不部分提交。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

采用 APP-EXEC-COMMON；参与Repository为 INF-DOC-REP、INF-REQ-REP、INF-REV-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/requirements/commands.py|complete_initialization|APP-REQ-CMD-C03|
|backend/app/requirements/contracts.py|complete_initialization_input / complete_initialization_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-req-cmd-c04"></a>
### APP-REQ-CMD-C04 完成需求

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-REQ-CMD-C04 完成需求|
|处理目标|完成需求的完整应用结果|
|主要对象或过程|OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|expected_content_version|PositiveInt|调用参数；读取时的CURRENT内容版本|是|否|读取时的 CURRENT.content_version；正整数，不接受布尔值；不等于 Revision.version_no；缺失：拒绝；指CURRENT内容版本，接口改名映射见第6章|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验幂等并在事务读取需求、CURRENT和活动关系；数据变化：无|INF-TX；INF-REQ-REP；INF-DOC-REP；SHR-IDEMPOTENCY|首次执行→P02；重放→原结果|
|P02；首次执行|要求ACTIVE、IDLE、无草稿/活动Run/待处理批次且CURRENT版本相等；数据变化：无|OBJ-REQ；SHR-CONCURRENCY|满足→P03；否则状态/占用/版本冲突|
|P03；满足|将status写为COMPLETED，写completed_at和updated_at；数据变化：仅Requirement|INF-REQ-REP|REQUIREMENT_COMPLETED|


**入口绑定的业务约束**

- expected_version 对应 CURRENT.content_version；要求 ACTIVE、IDLE 且没有活动对象；成功写 COMPLETED、completed_at。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|REQUIREMENT_COMPLETED|成功|返回Requirement；正文、版本记录不变；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[RequirementReadModel](#requirementreadmodel)（APP-REQ-QUERY-C02）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|非 ACTIVE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|不是 IDLE 或仍有活动对象；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|CURRENT 或活动关系不一致；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONTENT_VERSION_CONFLICT`|CURRENT 版本与预期不符；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

采用 APP-EXEC-COMMON；参与Repository为 INF-DOC-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/requirements/commands.py|complete_requirement|APP-REQ-CMD-C04|
|backend/app/requirements/contracts.py|complete_requirement_input / complete_requirement_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-req-cmd-c05"></a>
### APP-REQ-CMD-C05 重新激活需求

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-REQ-CMD-C05 重新激活需求|
|处理目标|重新激活需求的完整应用结果|
|主要对象或过程|涉及对象由下列处理步骤及Repository确定；不建立额外业务对象。|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|读取幂等与需求，要求COMPLETED、IDLE且占用关系一致；数据变化：无|INF-TX；INF-REQ-REP；SHR-IDEMPOTENCY|满足→P02；否则状态或占用冲突|
|P02；满足|status写ACTIVE，清空completed_at，更新updated_at；数据变化：仅Requirement|INF-REQ-REP|REACTIVATED|


**入口绑定的业务约束**

- 要求 COMPLETED、IDLE；成功改为 ACTIVE，completed_at 清空。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|REACTIVATED|成功|返回Requirement；CURRENT及其版本不变；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[RequirementReadModel](#requirementreadmodel)（APP-REQ-QUERY-C02）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|非 COMPLETED；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|不是 IDLE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|占用关系不一致；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

采用 APP-EXEC-COMMON；参与Repository为 INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/requirements/commands.py|reactivate_requirement|APP-REQ-CMD-C05|
|backend/app/requirements/contracts.py|reactivate_requirement_input / reactivate_requirement_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-doc-cmd-c01"></a>
### APP-DOC-CMD-C01 开始人工编辑

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-DOC-CMD-C01 开始人工编辑|
|处理目标|开始人工编辑的完整应用结果|
|主要对象或过程|OBJ-DOC、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|expected_content_version|PositiveInt|调用参数；读取时的CURRENT内容版本|是|否|读取时的 CURRENT.content_version；正整数，不接受布尔值；不等于 Revision.version_no；缺失：拒绝；指CURRENT内容版本，接口改名映射见第6章|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|在事务检查需求为INITIALIZING或ACTIVE、IDLE；CURRENT存在且版本相等，无草稿或其他占用；数据变化：无|INF-TX；INF-REQ-REP；INF-DOC-REP；SHR-IDEMPOTENCY|满足→P02；否则状态/占用/版本错误|
|P02；满足|复制CURRENT的Markdown和完整区块状态为独立MANUAL_DRAFT；草稿版本为1，保留继承区块来源；数据变化：新草稿；CURRENT不变|OBJ-DOC；INF-DOC-REP|P03|
|P03；草稿已创建|与草稿创建同事务保存manual_draft_context基线及EDITING人工会话，绑定MANUAL_EDITING与草稿ID，设置state_started_at；数据变化：Requirement占用和技术来源记录|INF-REQ-REP；INF-DOC-REP；[草稿基线与来源](#sync-be-08)|DRAFT_STARTED|


**入口绑定的业务约束**

- expected_version 对应 CURRENT.content_version。复制完整快照创建独立 MANUAL_DRAFT，初始版本 1，并将需求占用设为 MANUAL_EDITING。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|DRAFT_STARTED|成功|返回草稿和需求占用；编辑器改为读取草稿；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

|字段路径|类型或定义引用|含义|出现条件及可空性|确定限制|
|---|---|---|---|---|
|manual_draft|[DocumentReadModel](#documentreadmodel)（APP-DOC-QUERY-C01）|人工草稿|始终存在；不可为null|—|
|requirement|[RequirementReadModel](#requirementreadmodel)（APP-REQ-QUERY-C02）|占用后的需求|始终存在；不可为null|—|


**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|不是 INITIALIZING/ACTIVE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|非 IDLE 或已有草稿/其他占用；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|CURRENT 或活动关系不一致；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONTENT_VERSION_CONFLICT`|CURRENT 版本与预期不符；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CAPACITY_EXHAUSTED`|编号/版本/序号分配耗尽；拒绝整个事务，不部分提交。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|



<a id="sync-be-08"></a>

**草稿基线、人工来源对象和修改原因**

内部 `manual_draft_context` 关联独立 draft_id、原 CURRENT id、base_content_version 和初始 BlockState；完成时同事务复查原 CURRENT 身份及基线版本，写回原 CURRENT，不交换文档类型。中间草稿可保留未完成 Markdown，但快照结构、身份、来源和初始化标题锁仍须合法。

`MANUAL_EDIT.source_id` 引用内部持久 `manual_edit_sessions` 的 draft_id，表示那次人工编辑会话，不指向 CURRENT 或提交审计。开始时与草稿/占用共同创建 EDITING 会话，完成/取消与草稿删除、占用释放共同关闭为 COMPLETED/CANCELLED，永久保留最小来源关系，不保留会话正文，不新增公开字段、接口或分配序列。缺失或跨需求关系拒绝，旧数据无法证明来源则拒绝迁移。

署名组合为 TEMPLATE=SYSTEM/null；GUIDE_RUN=AI/同需求 INITIALIZE Run；SUGGESTION_BATCH=AI（接受）或 USER（编辑）/同需求批次；MANUAL_EDIT=USER/同需求编辑会话。来源关系合法不额外授予新写入权限。

ACTIVE 人工完成导致 Markdown 正文实际变化时写内部 `document_change_audits`，`reason_code=USER_MANUAL_EDIT`，source_id 为编辑会话 draft_id；前端不增加原因输入，I12 不增加字段。无实际正文变化不伪造该原因审计。

**确认依据**：D-004、D-008；[人工来源补充稿](../proposals/manual-edit-source-v1.md)。**代码对应**：`documents/{commands,sources}.py`、`infrastructure/document_repository.py`、迁移 001/003。

#### 4.5 关键执行要求

相同幂等请求返回原结果；不同请求不能创建第二份草稿。草稿不保存CURRENT的副本版本作为自己的版本。基线由manual_draft_context独立保存，见[人工来源及基线](#sync-be-08)。

采用 APP-EXEC-COMMON；参与Repository为 INF-DOC-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/documents/commands.py|start_manual_draft|APP-DOC-CMD-C01|
|backend/app/documents/contracts.py|start_manual_draft_input / start_manual_draft_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-doc-cmd-c02"></a>
### APP-DOC-CMD-C02 保存人工草稿

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-DOC-CMD-C02 保存人工草稿|
|处理目标|保存人工草稿的完整应用结果|
|主要对象或过程|OBJ-DOC、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|expected_version|PositiveInt|调用参数；读取时的MANUAL_DRAFT内容版本|是|否|读取时的 MANUAL_DRAFT.content_version；正整数，不接受布尔值；不等于 Revision.version_no；缺失：拒绝；必填值|
|markdown_content|Markdown|调用参数；完整草稿正文|是|否|完整 Markdown，可为空；不单独裁剪或截断；快照一致性按 SHR-BLOCK；缺失：拒绝；必填值|
|block_state_json|BlockState（OBJ-DOC）|调用参数；同一时点的区块身份状态|是|否|JSON 对象，与 markdown_content 同一快照；不是转义 JSON 字符串；缺失：拒绝；必填值|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验MANUAL_EDITING、活动类型/ID与唯一草稿一致；数据变化：无|INF-REQ-REP；INF-DOC-REP|一致→P02；否则WORK_STATE_CONFLICT或WORK_STATE_INCONSISTENT|
|P02；编辑有效|校验预期草稿版本，解析Markdown和区块身份；保护创建来源并生成权威派生值及时间；数据变化：无|OBJ-DOC；SHR-BLOCK；SHR-CONCURRENCY|有效→P03；否则CONTENT_VERSION_CONFLICT或DOCUMENT_INVALID|
|P03；有效|按[分配证明规则](#sync-be-09)登记高水位区间及首次实际出现新块的创建事实，与草稿Markdown、区块状态、content_version+1、updated_at一起提交；数据变化：草稿及临时身份证明，CURRENT不变|INF-TX；INF-DOC-REP；manual_block_allocation_ranges/manual_block_origins|DRAFT_SAVED|


**入口绑定的业务约束**

- expected_version 对应草稿版本。正文和区块状态必须同一快照；后端验证继承身份并重算派生元数据，成功保存后草稿版本加 1。

- 本能力没有idempotency_key；成功响应丢失后，以相同旧版本再次提交会冲突，应先读取草稿确认结果。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|DRAFT_SAVED|成功|返回后端确认的草稿和版本；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[DocumentReadModel](#documentreadmodel)（APP-DOC-QUERY-C01）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|不处于本草稿的 MANUAL_EDITING；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|活动草稿缺失、数量或归属不一致；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONTENT_VERSION_CONFLICT`|草稿版本与预期不符；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`DOCUMENT_INVALID`|Markdown 与区块身份不能形成有效快照；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CAPACITY_EXHAUSTED`|编号/版本/序号分配耗尽；拒绝整个事务，不部分提交。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|



<a id="sync-be-09"></a>

**草稿分配事件、创建时间和撤销证明**

成功保存提高 next_block_id 时，内部 `manual_block_allocation_ranges` 原子保存 `[旧 next,新 next)` 和服务器操作时间；`manual_block_origins` 保存实际出现的新块不可变创建事实。新 ID 的创建时间取服务器首次接受其分配区间的时间，不采用客户端自报时间。区间已分配但此前未出现在保存快照的 ID，后续可在同草稿撤销恢复时首次登记；不展开大区间，也不允许范围外或其他会话身份。已有创建事实不变，恢复后的最近修改事实按本次真实保存推导。

区间、出生证明、正文、BlockState 和版本同事务提交；失败全回滚，未知结果先读取事实。完成/取消同事务清临时证明并关闭持久会话；CURRENT/Revision 继续通过保留的会话证明来源。旧草稿无法证明既有分配历史时拒绝升级，不按 ID、时间或相似正文猜历史。前端权威回执接续遵循 [FE-07](WALL-E.V1_0.6.前端设计文档.md#sync-fe-07)。

**确认依据**：D-009；[身份回执补充稿](../proposals/manual-identity-receipts-v1.md)。**代码对应**：`documents/manual_identity.py::ManualIdentityProofs`、`documents/commands.py`、迁移 004；前端 `documents/edited-snapshot.ts`。

#### 4.5 关键执行要求

不新增last_autosaved_at，保存时间使用草稿updated_at。不改CURRENT、Comment或Revision。允许保存内容未完成的中间稿，结构校验与初始化模板锁定边界按[草稿基线及来源](#sync-be-08)。自动保存重试只发送最新快照；响应未知时先读取草稿，不盲目对旧expected_version重试。

采用 APP-EXEC-COMMON；参与Repository为 INF-DOC-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/documents/commands.py|save_manual_draft|APP-DOC-CMD-C02|
|backend/app/documents/contracts.py|save_manual_draft_input / save_manual_draft_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-doc-cmd-c03"></a>
### APP-DOC-CMD-C03 完成人工编辑

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-DOC-CMD-C03 完成人工编辑|
|处理目标|完成人工编辑的完整应用结果|
|主要对象或过程|OBJ-DOC、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|expected_version|PositiveInt|调用参数；读取时的MANUAL_DRAFT内容版本|是|否|读取时的 MANUAL_DRAFT.content_version；正整数，不接受布尔值；不等于 Revision.version_no；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|确认活动草稿、需求可编辑及客户端已结束最新一次保存；校验草稿预期版本；数据变化：无|INF-REQ-REP；INF-DOC-REP；SHR-IDEMPOTENCY|满足→P02；否则状态/版本错误|
|P02；草稿有效|完整校验Markdown、区块状态；INITIALIZING还检查模板锁定；准备同一CURRENT身份的替换内容；数据变化：无|OBJ-DOC；SHR-BLOCK；INF-TEMPLATE|合法→P03；否则DOCUMENT_INVALID或TEMPLATE_INVALID|
|P03；校验完成|同一事务更新原CURRENT及其content_version+1，重校验评论锚点；ACTIVE正文实际变化才写USER_MANUAL_EDIT原因审计；删除临时身份证明和草稿，关闭编辑会话为COMPLETED，清空占用回IDLE；数据变化：CURRENT、Comment.anchor_status、技术记录、草稿删除、占用释放|INF-TX；INF-DOC-REP；APP-COMMENT-CMD-C06；INF-REQ-REP；[人工来源](#sync-be-08)/[身份证明](#sync-be-09)|DRAFT_COMPLETED|


**入口绑定的业务约束**

- 先等待最近一次草稿保存完成，再提交该草稿版本；后端用版本和占用检查，不能相信客户端“已保存”声明。

- 同一事务更新原 CURRENT（版本加 1）、重校验评论锚点、删除草稿并释放占用；返回 CURRENT，不创建 Revision。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|DRAFT_COMPLETED|成功|返回完整CURRENT；不自动创建Revision；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[DocumentReadModel](#documentreadmodel)（APP-DOC-QUERY-C01）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|需求不再允许编辑；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|不是本草稿的有效编辑占用；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|草稿或 CURRENT 关系异常；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONTENT_VERSION_CONFLICT`|草稿版本与预期不符；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`DOCUMENT_INVALID`|草稿快照不合法；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`TEMPLATE_INVALID`|初始化阶段的主章节结构不合法；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CAPACITY_EXHAUSTED`|编号/版本/序号分配耗尽；拒绝整个事务，不部分提交。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

任一步失败整体回滚并保留草稿与MANUAL_EDITING。ACTIVE完成且正文实际变化时，同事务写document_change_audits，reason_code=USER_MANUAL_EDIT，source_id=编辑会话draft_id；无变化不写原因审计；不增加I12字段。

采用 APP-EXEC-COMMON；参与Repository为 INF-DOC-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/documents/commands.py|complete_manual_draft|APP-DOC-CMD-C03|
|backend/app/documents/contracts.py|complete_manual_draft_input / complete_manual_draft_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-doc-cmd-c04"></a>
### APP-DOC-CMD-C04 取消人工编辑

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-DOC-CMD-C04 取消人工编辑|
|处理目标|取消人工编辑的完整应用结果|
|主要对象或过程|OBJ-DOC、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|expected_version|PositiveInt|调用参数；读取时的MANUAL_DRAFT内容版本|是|否|读取时的 MANUAL_DRAFT.content_version；正整数，不接受布尔值；不等于 Revision.version_no；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|幂等重放优先；要求活动草稿存在、归属一致且版本相等；数据变化：无|INF-REQ-REP；INF-DOC-REP；SHR-IDEMPOTENCY|满足→P02；否则状态/版本错误|
|P02；满足|同一事务清除临时身份证明及草稿、关闭编辑会话为CANCELLED、清空占用回IDLE；数据变化：草稿和临时记录删除，永久最小来源保留；CURRENT不变|INF-TX；INF-DOC-REP；INF-REQ-REP；[人工来源](#sync-be-08)/[身份证明](#sync-be-09)|DRAFT_CANCELLED|


**入口绑定的业务约束**

- 取消必须提供草稿expected_version。成功后返回被取消草稿的身份；同键重放可返回原成功结果。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|DRAFT_CANCELLED|成功|返回requirement_id、manual_draft_id及cancelled=true；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

|字段路径|类型或定义引用|含义|出现条件及可空性|确定限制|
|---|---|---|---|---|
|requirement_id|Int|需求 ID|始终存在；不可为null|正整数|
|manual_draft_id|Int|已取消草稿 ID|始终存在；不可为null|正整数|
|cancelled|Bool|是否已取消|始终存在；不可为null|成功固定 true|


**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|没有当前可取消的草稿占用；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|活动草稿关系异常；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONTENT_VERSION_CONFLICT`|草稿版本与预期不符；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

采用 APP-EXEC-COMMON；参与Repository为 INF-DOC-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/documents/commands.py|cancel_manual_draft|APP-DOC-CMD-C04|
|backend/app/documents/contracts.py|cancel_manual_draft_input / cancel_manual_draft_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-rev-cmd-c01"></a>
### APP-REV-CMD-C01 保存手动版本

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-REV-CMD-C01 保存手动版本|
|处理目标|保存手动版本的完整应用结果|
|主要对象或过程|OBJ-DOC、OBJ-REQ、OBJ-REV|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|expected_content_version|PositiveInt|调用参数；读取时的CURRENT内容版本|是|否|读取时的 CURRENT.content_version；正整数，不接受布尔值；不等于 Revision.version_no；缺失：拒绝；指CURRENT内容版本，接口改名映射见第6章|
|description|Text|调用参数；用户填写的版本说明|否|是|标准化后最多 1000 个码点，可换行；空字符串归一为 null；缺失：null；null（未传时）|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|幂等查询；在事务检查ACTIVE、IDLE、无草稿且CURRENT版本匹配；数据变化：无|SHR-IDEMPOTENCY；INF-TX；INF-REQ-REP；INF-DOC-REP|满足→P02；否则状态/版本错误|
|P02；满足|完整校验CURRENT快照；在同一事务分配本需求max(version_no)+1并插入MANUAL Revision；数据变化：新增不可变Revision，记录source_content_version|OBJ-DOC；INF-REV-REP|REVISION_CREATED|


**入口绑定的业务约束**

- 只保存当前正式正文快照；要求 ACTIVE、IDLE、CURRENT 版本匹配。返回 MANUAL 版本摘要；description 省略、null 或标准化后为空均存 null。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|REVISION_CREATED|成功|返回Revision摘要；CURRENT和评论不变；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[RevisionSummary](#revisionsummary)（APP-REV-QUERY-C01）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|需求非 ACTIVE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|非 IDLE 或仍有草稿；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|CURRENT 或活动关系异常；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONTENT_VERSION_CONFLICT`|CURRENT 版本与预期不符；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`DOCUMENT_INVALID`|CURRENT 快照不合法；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CAPACITY_EXHAUSTED`|编号/版本/序号分配耗尽；拒绝整个事务，不部分提交。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

无前端BASELINE创建入口；版本号不复用。description采用SHR-TEXT，最多1000个Unicode码点，可换行，空白归一为null。

采用 APP-EXEC-COMMON；参与Repository为 INF-DOC-REP、INF-REQ-REP、INF-REV-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/revisions/commands.py|create_manual_revision|APP-REV-CMD-C01|
|backend/app/revisions/contracts.py|create_manual_revision_input / create_manual_revision_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-comment-cmd-c01"></a>
### APP-COMMENT-CMD-C01 创建评论

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-COMMENT-CMD-C01 创建评论|
|处理目标|创建评论的完整应用结果|
|主要对象或过程|OBJ-COMMENT、OBJ-DOC、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|expected_content_version|PositiveInt|调用参数；读取时的CURRENT内容版本|是|否|读取时的 CURRENT.content_version；正整数，不接受布尔值；不等于 Revision.version_no；缺失：拒绝；必填值|
|content|CommentText|调用参数；纯文本评论|是|否|标准化后 1～2000 个码点，纯文本，可换行；缺失：拒绝；必填值|
|anchor_type|AnchorType|调用参数；BLOCK或SELECTION|是|否|BLOCK / SELECTION；缺失：拒绝；必填值|
|block_id|BlockId|调用参数；原区块身份|是|否|1～9007199254740991 的整数；整数，不接受布尔值；缺失：拒绝；必填值|
|selection|SelectionRef|调用参数；SELECTION时必填|条件|是|SELECTION 时必填对象；BLOCK 时必须省略或 null；缺失：BLOCK 时 null；BLOCK 时 null（未传时）|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|

|字段路径|类型|含义|必须存在或出现条件|可为null|限制|
|---|---|---|---|---|---|
|selection.selected_text|Text|选区原文|父对象提供时必有|否|1～2000 个 Unicode 码点；缺失：拒绝|
|selection.prefix_text|Text|前文|父对象提供时必有|否|紧邻选区的前文，0～100 个码点；缺失：拒绝|
|selection.suffix_text|Text|后文|父对象提供时必有|否|紧邻选区的后文，0～100 个码点；缺失：拒绝|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|检查ACTIVE、IDLE、CURRENT版本匹配和评论文本合法；数据变化：无|INF-TX；INF-REQ-REP；INF-DOC-REP；OBJ-COMMENT；SHR-IDEMPOTENCY|满足→P02；否则状态/版本/输入错误|
|P02；可写|按原Block验证锚点；从CURRENT生成权威引用快照，不信任客户端上下文；数据变化：无|SHR-ANCHOR|唯一定位→P03；否则ANCHOR_INVALID|
|P03；有效锚点|新增OPEN、ATTACHED评论和同一操作时间；数据变化：新增Comment|INF-COMMENT-REP|COMMENT_CREATED|


**入口绑定的业务约束**

- 要求 ACTIVE、IDLE 和 CURRENT 版本一致；BLOCK 时不传 selection，SELECTION 时必须传完整选区对象。

- 后端在原区块验证并生成权威 anchor_ref，不直接信任客户端上下文；新评论为 OPEN、ATTACHED。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|COMMENT_CREATED|成功|返回Comment；CURRENT、区块状态、Revision不变；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|
|ANCHOR_INVALID|拒绝|区块不存在、跨区块或选区不能唯一定位|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|


**成功载荷 data**

[CommentReadModel](#commentreadmodel)（APP-COMMENT-QUERY-C02）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|需求非 ACTIVE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|非 IDLE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|CURRENT 或活动关系异常；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONTENT_VERSION_CONFLICT`|CURRENT 版本与预期不符；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`ANCHOR_INVALID`|区块不存在、跨区块或选区不能唯一定位；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CAPACITY_EXHAUSTED`|编号/版本/序号分配耗尽；拒绝整个事务，不部分提交。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

采用 APP-EXEC-COMMON；参与Repository为 INF-COMMENT-REP、INF-DOC-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/comments/commands.py|create_comment|APP-COMMENT-CMD-C01|
|backend/app/comments/contracts.py|create_comment_input / create_comment_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-comment-cmd-c02"></a>
### APP-COMMENT-CMD-C02 编辑评论

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-COMMENT-CMD-C02 编辑评论|
|处理目标|编辑评论的完整应用结果|
|主要对象或过程|OBJ-COMMENT、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|comment_id|ID|调用参数；评论身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|content|CommentText|调用参数；替换评论正文|是|否|标准化后 1～2000 个码点，纯文本，可换行；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|读取评论及所属需求，重放已成功幂等结果；不存在返回NOT_FOUND；数据变化：无|INF-COMMENT-REP；INF-REQ-REP；SHR-IDEMPOTENCY|存在→P02|
|P02；存在|新变更要求ACTIVE、IDLE；编辑/解决/重开拒绝已删除评论；ORPHANED不阻止此类人工操作；数据变化：无|INF-TX；OBJ-COMMENT|允许→P03；否则STATE_CONFLICT或WORK_STATE_CONFLICT|
|P03；允许|要求OPEN；更新content与updated_at；数据变化：仅Comment|INF-COMMENT-REP|COMMENT_UPDATED|


**入口绑定的业务约束**

- 要求评论未删除且 OPEN、需求 ACTIVE/IDLE；ORPHANED 不阻止编辑评论文字。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|COMMENT_UPDATED|成功|返回当前Comment；不改正文或Revision；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[CommentReadModel](#commentreadmodel)（APP-COMMENT-QUERY-C02）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|评论或所属需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|评论已删除、非 OPEN，或需求非 ACTIVE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|需求非 IDLE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|



<a id="sync-be-13"></a>

**评论无版本字段时的竞争策略**

不新增 expected_version。动作在写事务内重读最新评论，原生命周期、工作占用和状态限制仍先满足；在允许编辑的情况下，同内容字段并发以较后成功提交者覆盖。解决/重开按事务内最新状态判断，重复状态动作不刷新时间。软删除终态获胜，已删拒绝编辑/解决/重开，重复删除保持原时间。前端同评论串行动作，结果未知先复查，不把此策略理解为任何状态都可覆盖。

**确认依据**：D-004，公共决策稿 B。**代码对应**：`comments/commands.py::_comment_action`、`infrastructure/comment_repository.py`、`frontend/src/comments/commands.ts`。

#### 4.5 关键执行要求

重复状态请求不重写事件时间；软删除不抹除历史来源。并发编辑覆盖策略见[Q-04](#q-04)。

采用 APP-EXEC-COMMON；参与Repository为 INF-COMMENT-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/comments/commands.py|edit_comment|APP-COMMENT-CMD-C02|
|backend/app/comments/contracts.py|edit_comment_input / edit_comment_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-comment-cmd-c03"></a>
### APP-COMMENT-CMD-C03 解决评论

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-COMMENT-CMD-C03 解决评论|
|处理目标|解决评论的完整应用结果|
|主要对象或过程|OBJ-COMMENT、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|comment_id|ID|调用参数；评论身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|读取评论及所属需求，重放已成功幂等结果；不存在返回NOT_FOUND；数据变化：无|INF-COMMENT-REP；INF-REQ-REP；SHR-IDEMPOTENCY|存在→P02|
|P02；存在|新变更要求ACTIVE、IDLE；编辑/解决/重开拒绝已删除评论；ORPHANED不阻止此类人工操作；数据变化：无|INF-TX；OBJ-COMMENT|允许→P03；否则STATE_CONFLICT或WORK_STATE_CONFLICT|
|P03；允许|OPEN改RESOLVED，写resolved_at与updated_at；已RESOLVED返回原值；数据变化：仅Comment|INF-COMMENT-REP|COMMENT_UPDATED|


**入口绑定的业务约束**

- 要求评论未删除、需求 ACTIVE/IDLE；OPEN 改为 RESOLVED；已 RESOLVED 返回原结果，不重写 resolved_at。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|COMMENT_UPDATED|成功|返回当前Comment；不改正文或Revision；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[CommentReadModel](#commentreadmodel)（APP-COMMENT-QUERY-C02）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|评论或所属需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|评论已删除或需求非 ACTIVE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|需求非 IDLE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

重复状态请求不重写事件时间；软删除不抹除历史来源。并发编辑覆盖策略见[Q-04](#q-04)。

采用 APP-EXEC-COMMON；参与Repository为 INF-COMMENT-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/comments/commands.py|resolve_comment|APP-COMMENT-CMD-C03|
|backend/app/comments/contracts.py|resolve_comment_input / resolve_comment_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-comment-cmd-c04"></a>
### APP-COMMENT-CMD-C04 重新打开评论

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-COMMENT-CMD-C04 重新打开评论|
|处理目标|重新打开评论的完整应用结果|
|主要对象或过程|OBJ-COMMENT、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|comment_id|ID|调用参数；评论身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|读取评论及所属需求，重放已成功幂等结果；不存在返回NOT_FOUND；数据变化：无|INF-COMMENT-REP；INF-REQ-REP；SHR-IDEMPOTENCY|存在→P02|
|P02；存在|新变更要求ACTIVE、IDLE；编辑/解决/重开拒绝已删除评论；ORPHANED不阻止此类人工操作；数据变化：无|INF-TX；OBJ-COMMENT|允许→P03；否则STATE_CONFLICT或WORK_STATE_CONFLICT|
|P03；允许|RESOLVED改OPEN，清空resolved_at并更新updated_at；已OPEN返回原值；数据变化：仅Comment|INF-COMMENT-REP|COMMENT_UPDATED|


**入口绑定的业务约束**

- 要求评论未删除、需求 ACTIVE/IDLE；RESOLVED 改为 OPEN，清空 resolved_at；已 OPEN 返回原结果。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|COMMENT_UPDATED|成功|返回当前Comment；不改正文或Revision；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[CommentReadModel](#commentreadmodel)（APP-COMMENT-QUERY-C02）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|评论或所属需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|评论已删除或需求非 ACTIVE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|需求非 IDLE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

重复状态请求不重写事件时间；软删除不抹除历史来源。并发编辑覆盖策略见[Q-04](#q-04)。

采用 APP-EXEC-COMMON；参与Repository为 INF-COMMENT-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/comments/commands.py|reopen_comment|APP-COMMENT-CMD-C04|
|backend/app/comments/contracts.py|reopen_comment_input / reopen_comment_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-comment-cmd-c05"></a>
### APP-COMMENT-CMD-C05 删除评论

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-COMMENT-CMD-C05 删除评论|
|处理目标|删除评论的完整应用结果|
|主要对象或过程|OBJ-COMMENT、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|comment_id|ID|调用参数；评论身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|读取评论及所属需求，重放已成功幂等结果；不存在返回NOT_FOUND；数据变化：无|INF-COMMENT-REP；INF-REQ-REP；SHR-IDEMPOTENCY|存在→P02|
|P02；存在|新变更要求ACTIVE、IDLE；编辑/解决/重开拒绝已删除评论；ORPHANED不阻止此类人工操作；数据变化：无|INF-TX；OBJ-COMMENT|允许→P03；否则STATE_CONFLICT或WORK_STATE_CONFLICT|
|P03；允许|首次写deleted_at和updated_at；已删除返回原结果且不改时间；数据变化：仅Comment|INF-COMMENT-REP|COMMENT_UPDATED|


**入口绑定的业务约束**

- 软删除：写 deleted_at；已删除时返回原删除结果，不重复改时间。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|COMMENT_UPDATED|成功|返回当前Comment；不改正文或Revision；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[CommentReadModel](#commentreadmodel)（APP-COMMENT-QUERY-C02）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|评论或所属需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|首次删除时需求非 ACTIVE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|首次删除时需求非 IDLE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

重复状态请求不重写事件时间；软删除不抹除历史来源。并发编辑覆盖策略见[Q-04](#q-04)。

采用 APP-EXEC-COMMON；参与Repository为 INF-COMMENT-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/comments/commands.py|delete_comment|APP-COMMENT-CMD-C05|
|backend/app/comments/contracts.py|delete_comment_input / delete_comment_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-comment-cmd-c06"></a>
### APP-COMMENT-CMD-C06 重校验评论锚点

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-COMMENT-CMD-C06 重校验评论锚点|
|处理目标|重校验评论锚点的完整应用结果|
|主要对象或过程|OBJ-COMMENT|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|可信内部调用；被修改正文的需求|是|否|必填，无默认；被修改正文的需求|
|new_document|完整DocumentSnapshot（OBJ-DOC的markdown_content与BlockState）|可信内部调用；本事务内的新CURRENT|是|否|必填，无默认；本事务内的新CURRENT|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；正文提交事务已开启|加载本需求所有未软删除评论，包含OPEN和RESOLVED；数据变化：无|INF-COMMENT-REP|加载完成→P02|
|P02；逐条评论|调用锚点算法，只判断原Block；更新为ATTACHED或ORPHANED，允许原Block恢复唯一匹配后重新附着；数据变化：仅anchor_status；不改updated_at或处理状态|SHR-ANCHOR；INF-COMMENT-REP|全部完成→ANCHORS_UPDATED；异常→回滚外层事务|


#### 4.4 结果与完成范围

本能力完整内部data/details按本节结果表及[内部结果契约](#sync-be-22)；成功details=null，失败data=null，不以空对象代替正式载荷。

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|ANCHORS_UPDATED|成功|全部未删除评论与新正文对应|同步完成；结果中的提交、无变化或失败范围以4.4为准。|



**成功载荷 data**

|字段或结构|类型与出现条件|来源及约束|
|---|---|---|
|`{requirement_id,document_id,content_version,attached_comment_ids,orphaned_comment_ids}`|成功时完整返回的对象；details=null|两个ID数组覆盖全部未删除评论且互斥；不可空，空集合用[]。|

#### 4.5 关键执行要求

这是正文提交的内部能力，不单建外部行为链；参与调用方事务，绝不自行提交。无法定位是正常数据结果，JSON损坏或程序异常不是正常孤立。

采用 APP-EXEC-COMMON；参与Repository为 INF-COMMENT-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/comments/commands.py|revalidate_anchors|APP-COMMENT-CMD-C06|
|backend/app/comments/contracts.py|revalidate_anchors_input / revalidate_anchors_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-batch-cmd-c01"></a>
### APP-BATCH-CMD-C01 处理建议决策

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-BATCH-CMD-C01 处理建议决策|
|处理目标|处理建议决策的完整应用结果|
|主要对象或过程|OBJ-BATCH、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|suggestion_id|ID|调用参数；单项建议身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|decision|SuggestionDecision|调用参数；ACCEPTED、REJECTED或EDITED|是|否|ACCEPTED / REJECTED / EDITED，不接受 PENDING；缺失：拒绝；必填值|
|edited_content|Text|调用参数；EDITED时必填|条件|是|EDITED 时必填且非空；其他决策必须省略或 null；Block 操作传 Markdown，行替换传仅含 cells 的 JSON 文本；DELETE_BLOCK 不允许 EDITED；缺失：非 EDITED 时 null；非 EDITED 时 null（未传时）|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|经Suggestion id定位所属聚合根；要求ACTIVE、SUGGESTION_REVIEWING、活动批次匹配且PENDING；数据变化：无|INF-BATCH-REP；INF-REQ-REP；SHR-IDEMPOTENCY|满足→P02；否则状态/占用错误|
|P02；合法批次|仅允许改决策和编辑内容；EDITED按Patch类型校验；禁止改target/selector/operation/order；数据变化：无|OBJ-BATCH|合法→P03；否则INVALID_INPUT或PATCH_INVALID|
|P03；合法决策|写Suggestion决策/编辑内容/decided_at/updated_at并更新批次updated_at，同事务从明细算counts；数据变化：仅建议聚合|INF-TX；INF-BATCH-REP|SUGGESTION_DECIDED|


**入口绑定的业务约束**

- 只能改变决策和 EDITED 内容，不能改变原目标、操作、行选择条件或 order_no。非 EDITED 决策清空 user_edited_content。

- REPLACE_TABLE_ROW 的 edited_content 是 JSON 文本，仅含 cells 数组；传输仍保持原接口 string 类型。DELETE_BLOCK 只接受 ACCEPTED/REJECTED。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|SUGGESTION_DECIDED|成功|返回Suggestion和counts；CURRENT不变；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|
|PATCH_INVALID|拒绝|编辑后内容不符合本建议操作的结构|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|


**成功载荷 data**

|字段路径|类型或定义引用|含义|出现条件及可空性|确定限制|
|---|---|---|---|---|
|suggestion|[SuggestionReadModel](#suggestionreadmodel)（APP-BATCH-QUERY-C01）|更新后的建议|始终存在；不可为null|—|
|counts|[SuggestionCounts](#suggestioncounts)|决策数量|始终存在；不可为null|—|


**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|建议或所属批次不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|需求非 ACTIVE 或批次非 PENDING；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|当前占用不是该批次；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|建议、批次和需求关系异常；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`PATCH_INVALID`|EDITED 内容不符合固定补丁结构；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

批次结束前允许ACCEPTED、REJECTED、EDITED互相改选；ACCEPTED使用原建议，REJECTED清除旧编辑内容；DELETE_BLOCK禁止EDITED；EDITED来源署名规则见[Q-06](#q-06)。

采用 APP-EXEC-COMMON；参与Repository为 INF-BATCH-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/suggestions/commands.py|decide_suggestion|APP-BATCH-CMD-C01|
|backend/app/suggestions/contracts.py|decide_suggestion_input / decide_suggestion_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-batch-cmd-c02"></a>
### APP-BATCH-CMD-C02 完成建议批次

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-BATCH-CMD-C02 完成建议批次|
|处理目标|完成建议批次的完整应用结果|
|主要对象或过程|OBJ-BATCH、OBJ-DOC、OBJ-GUIDE、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|batch_id|ID|调用参数；活动建议批次|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|expected_content_version|PositiveInt|调用参数；读取时的CURRENT内容版本|是|否|读取时的 CURRENT.content_version；正整数，不接受布尔值；不等于 Revision.version_no；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|幂等查询后在事务读取需求、CURRENT、批次、全部Suggestion和来源运行的Allowed Targets；数据变化：无|INF-TX；INF-BATCH-REP；INF-REQ-REP；INF-DOC-REP；INF-GUIDE-REP；SHR-IDEMPOTENCY|读取完成→P02|
|P02；读取完成|要求ACTIVE、活动批次匹配且PENDING；后端逐项确认无PENDING；三方正文版本相等；数据变化：无|OBJ-BATCH；SHR-CONCURRENCY|成立→P03；否则BATCH_PENDING或状态/版本错误|
|P03；可提交|在基线快照校验目标、Selector、original_content、EDITED结构、权限和Patch冲突，按order_no在内存应用有效建议；数据变化：无|SHR-PATCH；OBJ-DOC|合法且有变化→P04；合法且无变化→P05；否则PATCH_INVALID或TARGET_STALE|
|P04；有变化|写CURRENT及版本+1，重校验评论锚点；批次COMPLETED/CHANGES_APPLIED，记录applied_content_version，清占用；数据变化：同一事务提交正文、锚点和批次终态|INF-DOC-REP；APP-COMMENT-CMD-C06；INF-BATCH-REP；INF-REQ-REP|BATCH_APPLIED|
|P05；无变化|批次COMPLETED/NO_CHANGE，applied_content_version=null；清占用；数据变化：仅批次与占用|INF-BATCH-REP；INF-REQ-REP|BATCH_NO_CHANGE|


**入口绑定的业务约束**

- 请求版本、CURRENT.content_version、batch.base_content_version 三者必须相等；全部建议均非 PENDING 才可提交。

- 有变化返回 BATCH_APPLIED：一次 CURRENT 更新、版本加 1、批次 COMPLETED/CHANGES_APPLIED；无变化返回 BATCH_NO_CHANGE：版本不变、批次 COMPLETED/NO_CHANGE、applied_content_version=null。

- 成功响应均包含 batch、counts 和完整 current_document。补丁失败不保留部分正文写入；不在提交时将行替换升级为整表替换。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|BATCH_APPLIED|成功|整批产生一次CURRENT更新；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|
|BATCH_NO_CHANGE|成功|所有建议拒绝或最终无实际变化；CURRENT版本不变；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|
|BATCH_PENDING|拒绝|仍存在未决Suggestion|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|
|TARGET_STALE|冲突|目标不存在或原内容/权限不再匹配|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|
|PATCH_INVALID|拒绝|Patch结构或组合不能合法应用|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|


**成功载荷 data**

|字段路径|类型或定义引用|含义|出现条件及可空性|确定限制|
|---|---|---|---|---|
|batch|[SuggestionBatchMetadata](#suggestionbatchmetadata)（APP-BATCH-QUERY-C01）|完成后的批次|始终存在；不可为null|—|
|counts|[SuggestionCounts](#suggestioncounts)|决策数量|始终存在；不可为null|—|
|current_document|[DocumentReadModel](#documentreadmodel)（APP-DOC-QUERY-C01）|提交后的当前正文|始终存在；不可为null|—|


**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|批次或需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|需求非 ACTIVE 或批次非 PENDING；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|当前占用不是该批次；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|CURRENT/批次/活动关系异常；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONTENT_VERSION_CONFLICT`|请求版本、CURRENT 版本和 base_content_version 不一致；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`BATCH_PENDING`|仍有 PENDING 建议；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`TARGET_STALE`|目标、原内容或授权已不匹配；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`PATCH_INVALID`|补丁结构或组合冲突；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`DOCUMENT_INVALID`|应用后的文档快照不合法；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CAPACITY_EXHAUSTED`|编号/版本/序号分配耗尽；拒绝整个事务，不部分提交。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

任何失败不提交部分正文，批次保持PENDING、原单项决定保留，不自动Merge。目标失效只能放弃后重发MODIFY；未处理项或可编辑内容错误可修正。失败只返回本次安全suggestion_errors，不修改已存validation_status/validation_error或批次error_message；正文、决定和批次状态按原事务全回滚，见[Patch规则](#sync-be-12)。

采用 APP-EXEC-COMMON；参与Repository为 INF-BATCH-REP、INF-DOC-REP、INF-GUIDE-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/suggestions/commands.py|complete_batch|APP-BATCH-CMD-C02|
|backend/app/suggestions/contracts.py|complete_batch_input / complete_batch_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-batch-cmd-c03"></a>
### APP-BATCH-CMD-C03 放弃建议批次

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-BATCH-CMD-C03 放弃建议批次|
|处理目标|放弃建议批次的完整应用结果|
|主要对象或过程|OBJ-BATCH、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|batch_id|ID|调用参数；活动批次|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|检查活动批次匹配、PENDING及需求占用关系；数据变化：无|INF-BATCH-REP；INF-REQ-REP；SHR-IDEMPOTENCY|满足→P02；否则状态/占用错误|
|P02；满足|同事务写DISCARDED及completed_at并清占用；保留全部单项决定；数据变化：批次终态及Requirement回IDLE|INF-TX；INF-BATCH-REP；INF-REQ-REP|BATCH_DISCARDED|


**入口绑定的业务约束**

- 要求活动批次 PENDING；写 DISCARDED 与 completed_at，保留各条建议决定并释放占用。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|BATCH_DISCARDED|成功|返回批次和counts；CURRENT及来源Comment不变；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

|字段路径|类型或定义引用|含义|出现条件及可空性|确定限制|
|---|---|---|---|---|
|batch|[SuggestionBatchMetadata](#suggestionbatchmetadata)（APP-BATCH-QUERY-C01）|已放弃批次|始终存在；不可为null|—|
|counts|[SuggestionCounts](#suggestioncounts)|决策数量|始终存在；不可为null|—|


**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|批次不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|批次非 PENDING 或需求非 ACTIVE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|当前占用不是该批次；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|活动关系异常；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

采用 APP-EXEC-COMMON；参与Repository为 INF-BATCH-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/suggestions/commands.py|discard_batch|APP-BATCH-CMD-C03|
|backend/app/suggestions/contracts.py|discard_batch_input / discard_batch_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-guide-cmd-c01"></a>
### APP-GUIDE-CMD-C01 创建AI运行

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-GUIDE-CMD-C01 创建AI运行|
|处理目标|创建AI运行的完整应用结果|
|主要对象或过程|OBJ-DOC、OBJ-GUIDE、OBJ-MSG、OBJ-REQ|
|完成方式|接受后继续执行；本次只确认接受事务，最终状态由APP-GUIDE-QUERY-C01观察。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|expected_content_version|PositiveInt|调用参数；读取时的CURRENT内容版本|是|否|读取时的 CURRENT.content_version；正整数，不接受布尔值；不等于 Revision.version_no；缺失：拒绝；指CURRENT内容版本，接口改名映射见第6章|
|action_type|Action|调用参数；用户选择的最大动作权限|是|否|INITIALIZE / ASK / REVIEW / MODIFY；动作许可依需求状态；缺失：拒绝；必填值|
|instruction|Text|调用参数；用户明确指令|是|否|标准化后 1～10000 个码点，可换行；缺失：拒绝；必填值|
|scope_type|ScopeType|调用参数；关注范围|是|否|DOCUMENT / SECTION / BLOCK / SELECTION；范围不等于写入权限；缺失：拒绝；必填值|
|scope_ref|ScopeRef（下表）|调用参数；非DOCUMENT必填|条件|是|DOCUMENT 时省略或 null；其他类型必填；字段见本表子项；缺失：DOCUMENT 时 null；DOCUMENT 时 null（未传时）|
|source_type|SourceType|调用参数；仅USER_INSTRUCTION或REVIEW_RESULT|是|否|USER_INSTRUCTION / REVIEW_RESULT；REVIEW_RESULT 仅允许 action_type=MODIFY；缺失：拒绝；必填值|
|source_id|ID|调用参数；REVIEW_RESULT必填|条件|是|REVIEW_RESULT 时必填，引用本需求已完成的 REVIEW Run；USER_INSTRUCTION 时省略或 null；缺失：USER_INSTRUCTION 时 null；USER_INSTRUCTION 时 null（未传时）|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|

|字段路径|类型|含义|必须存在或出现条件|可为null|限制|
|---|---|---|---|---|---|
|scope_ref.block_id|Int|区块 ID|父对象提供时必有|否|SECTION 时必须是标题区块；BLOCK/SELECTION 为目标区块；缺失：拒绝|
|scope_ref.selected_text|Text|选区原文|scope_type=SELECTION 时必有|否|1～2000 个 Unicode 码点；缺失：拒绝|
|scope_ref.prefix_text|Text|前文|scope_type=SELECTION 时必有|否|紧邻选区的前文，0～100 个码点；缺失：拒绝|
|scope_ref.suffix_text|Text|后文|scope_type=SELECTION 时必有|否|紧邻选区的后文，0～100 个码点；缺失：拒绝|



<a id="sync-be-10"></a>

**Scope和Allowed Targets**

DOCUMENT 为当前全文；SECTION 从指定 heading 至下一个同/更高级 heading 前；BLOCK 仅指定块；SELECTION 仅指定单块纯文本码点半开区间。局部读取包含目标、祖先标题和左右各 2 块，SECTION 包含节内全部及对应邻域；读邻域不增加写权。ASK/REVIEW 无写权限。

AllowedTarget 为 `{block_id,operations,selection_range,row_selectors}`，空可选范围用 null；持久结构为 `{schema_version:1,targets:[...]}`，模型输入取 targets 数组。权限由服务端真实状态/来源/Scope 冻结并恢复校验，不由模型声明。SELECTION 仅允许可证明选区外文本及标记未变的 REPLACE_BLOCK，不允许插删块或扩大为行/整块改写；来源评论不得扩大授权。

**确认依据**：D-004/005，公共决策稿 B/C。**代码对应**：`documents/scopes.py::{AllowedTarget,ResolvedScope,resolve_scope,restore_authority}`、`patch_validation.py::prove_selection`、`guide/model_context.py`。

#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验输入并幂等查重，读取需求/CURRENT/来源；数据变化：无|SHR-IDEMPOTENCY；INF-REQ-REP；INF-DOC-REP；INF-GUIDE-REP|首次执行→P02；重放→原结果|
|P02；首次执行|校验INITIALIZING仅INITIALIZE；ACTIVE仅ASK/REVIEW/MODIFY；COMPLETED仅ASK；要求IDLE、CURRENT版本匹配且来源属于同一需求；数据变化：无|OBJ-REQ；SHR-CONCURRENCY|合法→P03；否则状态/占用/版本/来源错误|
|P03；允许动作|后端确定FunctionType与冻结协议版本，解析Scope并产生Allowed Targets；ASK/REVIEW为空；不允许前端指定函数、权限和上下文；数据变化：无|INF-FUNCTION；SHR-SCOPE|合法→P04；否则SCOPE_INVALID或CONFIG_INVALID|
|P04；输入及授权完成|短事务保存用户TEXT、新GuideRun并绑定GUIDE_ACTIVE；提交后通知后台推进；数据变化：消息、运行、占用|INF-TX；INF-MSG-REP；INF-GUIDE-REP；INF-REQ-REP|GUIDE_ACCEPTED|


**入口绑定的业务约束**

- INITIALIZING 仅允许 INITIALIZE；ACTIVE 允许 ASK/REVIEW/MODIFY；COMPLETED 仅允许 ASK；均要求 IDLE 和 CURRENT 版本匹配。

- REVIEW_RESULT 仅用于 MODIFY；source_id 是同需求已完成 REVIEW 运行。COMMENT 来源必须使用 I34，不能从本接口传入。

- DOCUMENT 的 scope_ref 为 null；SECTION/BLOCK 只传 block_id；SELECTION 传 block_id 和选区上下文。范围不是写入权限，ASK/REVIEW 的 Allowed Targets 为空。

- 接受结果只表示任务已接受，通过 I16 读取状态、I35 读取消息。INITIALIZE 首轮由 I02 创建，本接口只用于后续轮次。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|GUIDE_ACCEPTED|成功|返回新GuideRun id/status/current_step及用户消息；完整成功载荷见本节。|接受后继续执行；本次只确认接受事务，最终状态由APP-GUIDE-QUERY-C01观察。|
|SCOPE_INVALID|拒绝|范围无效或引用不能确定|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|
|SOURCE_INVALID|拒绝|来源不属于本需求或不是已完成REVIEW结果|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|
|CONFIG_INVALID|已知失败|冻结协议资源缺失或无效|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|


**成功载荷 data**

|字段路径|类型或定义引用|含义|出现条件及可空性|确定限制|
|---|---|---|---|---|
|guide_run|[GuideRunAccepted](#guiderunaccepted)（APP-GUIDE-QUERY-C01）|新运行|始终存在；不可为null|—|
|user_message|[MessageReadModel](#messagereadmodel)（APP-MSG-QUERY-C01）|已保存用户消息|始终存在；不可为null|—|


**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|需求状态不允许所选动作；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|正文不是 IDLE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|CURRENT 或占用关系异常；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONTENT_VERSION_CONFLICT`|CURRENT 版本与预期不符；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`SOURCE_INVALID`|来源不是同需求已完成 REVIEW，或来源与动作不匹配；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`SCOPE_INVALID`|范围无法确定；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONFIG_INVALID`|冻结协议资源缺失或无效；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CAPACITY_EXHAUSTED`|编号/版本/序号分配耗尽；拒绝整个事务，不部分提交。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

REVIEW_RESULT只能用于MODIFY；历史检查结果只作来源，重新读取最新正文。INITIALIZE首轮复用创建需求中的同一事务，不再额外创建Run。

采用 APP-EXEC-COMMON；参与Repository为 INF-DOC-REP、INF-GUIDE-REP、INF-MSG-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/guide/commands.py|create_guide_run|APP-GUIDE-CMD-C01|
|backend/app/guide/contracts.py|create_guide_run_input / create_guide_run_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-guide-cmd-c02"></a>
### APP-GUIDE-CMD-C02 继续等待中的运行

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-GUIDE-CMD-C02 继续等待中的运行|
|处理目标|继续等待中的运行的完整应用结果|
|主要对象或过程|OBJ-GUIDE、OBJ-MSG、OBJ-REQ|
|完成方式|接受后继续执行；本次只确认接受事务，最终状态由APP-GUIDE-QUERY-C01观察。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|guide_run_id|ID|调用参数；原等待运行|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|instruction|Text|调用参数；本次补充说明|是|否|标准化后 1～10000 个码点，可换行；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|读取原运行与需求，校验ASK/REVIEW/MODIFY且WAITING_USER、GUIDE_ACTIVE归属一致；数据变化：无|INF-GUIDE-REP；INF-REQ-REP；SHR-IDEMPOTENCY|满足→P02；否则状态/占用错误|
|P02；允许继续|在短事务新增用户TEXT；原运行回RUNNING并更新触发消息、步骤和进展时间，call_no在下一次调用增加；数据变化：新增消息、原Run状态；已有卡片由消息关系推导失效|INF-TX；INF-GUIDE-REP；INF-MSG-REP|GUIDE_CONTINUED|


**入口绑定的业务约束**

- 只继续 ASK/REVIEW/MODIFY 的 WAITING_USER 运行；保留同一运行 ID 与冻结协议。普通补充文本不自动作为卡片答案。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|GUIDE_CONTINUED|成功|返回同一GuideRun id；继续使用冻结协议；完整成功载荷见本节。|接受后继续执行；本次只确认接受事务，最终状态由APP-GUIDE-QUERY-C01观察。|


**成功载荷 data**

[GuideRunAccepted](#guiderunaccepted)（APP-GUIDE-QUERY-C01）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|运行不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|动作不是 ASK/REVIEW/MODIFY 或状态不是 WAITING_USER；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|不属于需求当前 GUIDE_ACTIVE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|运行与占用关系异常；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONFIG_INVALID`|原冻结协议资源不可用；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CAPACITY_EXHAUSTED`|编号/版本/序号分配耗尽；拒绝整个事务，不部分提交。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

不把普通文字自动映射为卡片选项；INITIALIZE没有WAITING_USER，下一条用户输入走创建新运行。

采用 APP-EXEC-COMMON；参与Repository为 INF-GUIDE-REP、INF-MSG-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/guide/commands.py|continue_guide_run|APP-GUIDE-CMD-C02|
|backend/app/guide/contracts.py|continue_guide_run_input / continue_guide_run_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-guide-cmd-c03"></a>
### APP-GUIDE-CMD-C03 取消AI运行

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-GUIDE-CMD-C03 取消AI运行|
|处理目标|取消AI运行的完整应用结果|
|主要对象或过程|OBJ-GUIDE、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|guide_run_id|ID|调用参数；活动运行|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|幂等查询；读取运行并在同一事务争用持久化状态门禁；数据变化：无|INF-TX；INF-GUIDE-REP；INF-REQ-REP；SHR-IDEMPOTENCY|已CANCELLED→GUIDE_CANCELLED；其他→P02|
|P02；尚未取消|仅RUNNING或WAITING_USER且current_step非PERSISTING允许取消；数据变化：无|OBJ-GUIDE|允许→P03；否则STATE_CONFLICT|
|P03；取消获胜|写CANCELLED/FINISHED、USER_REQUESTED、ended_at；清占用；结束未完成尝试，停止等待及后续重试并尝试关闭连接；数据变化：Run终态及占用释放|INF-GUIDE-REP；INF-REQ-REP；INF-MODEL|GUIDE_CANCELLED|


**入口绑定的业务约束**

- 仅 RUNNING/WAITING_USER 且尚未进入 PERSISTING 可取消；已经 CANCELLED 返回原结果，不修改原结束时间。

- 逻辑取消不保证供应商停止推理或计费；取消获胜后的迟到结果不能再次写入业务。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|GUIDE_CANCELLED|成功|业务层不再采用输出；已保存消息和历史调用保留；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[GuideRunAccepted](#guiderunaccepted)（APP-GUIDE-QUERY-C01）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|运行不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|既非已 CANCELLED，也非可取消的 RUNNING/WAITING_USER，或步骤已为 PERSISTING；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|活动运行与需求占用关系异常；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

逻辑取消不保证Provider停止推理或计费。迟到结果必须再过状态门禁，不得补写正文、消息、建议或trusted_output。

采用 APP-EXEC-COMMON；参与Repository为 INF-GUIDE-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/guide/commands.py|cancel_guide_run|APP-GUIDE-CMD-C03|
|backend/app/guide/contracts.py|cancel_guide_run_input / cancel_guide_run_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-guide-cmd-c04"></a>
### APP-GUIDE-CMD-C04 重新运行失败任务

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-GUIDE-CMD-C04 重新运行失败任务|
|处理目标|重新运行失败任务的完整应用结果|
|主要对象或过程|OBJ-DOC、OBJ-GUIDE、OBJ-MSG、OBJ-REQ|
|完成方式|接受后继续执行；本次只确认接受事务，最终状态由APP-GUIDE-QUERY-C01观察。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|guide_run_id|ID|调用参数；原FAILED运行|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|要求原运行FAILED且归属有效；读取已正式提交的指令/回答及来源；数据变化：无|INF-GUIDE-REP；INF-MSG-REP；SHR-IDEMPOTENCY|满足→P02；否则STATE_CONFLICT|
|P02；原失败运行合法|重新读取最新CURRENT，检查当前需求允许原Action、IDLE、来源仍有效，并重新解析Scope与权限；数据变化：无|INF-DOC-REP；INF-REQ-REP；SHR-SCOPE|合法→P03；否则状态/范围/来源冲突|
|P03；可重新执行|新建GuideRun，retry_of_guide_run_id指原运行，trigger_type=RETRY，冻结新协议并绑定占用；不复制原用户消息；数据变化：仅新Run与占用|INF-TX；INF-GUIDE-REP；INF-REQ-REP；INF-FUNCTION|GUIDE_RETRY_ACCEPTED|


**入口绑定的业务约束**

- 创建新的运行并设置 retry_of_guide_run_id；原 FAILED 运行保持不变。重新读取当前正文、验证来源与范围，不复制原用户消息。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|GUIDE_RETRY_ACCEPTED|成功|返回新运行；原FAILED运行不可改回RUNNING；完整成功载荷见本节。|接受后继续执行；本次只确认接受事务，最终状态由APP-GUIDE-QUERY-C01观察。|
|SCOPE_INVALID|拒绝|原范围不能映射到当前正文|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|
|SOURCE_INVALID|拒绝|评论或REVIEW来源已失效|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|


**成功载荷 data**

[GuideRunReadModel](#guiderunreadmodel)（APP-GUIDE-QUERY-C01）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|原运行不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|原运行非 FAILED 或当前需求不允许原动作；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|需求非 IDLE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|正文/占用关系异常；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`SOURCE_INVALID`|原评论或 REVIEW 来源已失效；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`SCOPE_INVALID`|原范围无法在最新正文中确定；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONFIG_INVALID`|新冻结协议资源无效；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CAPACITY_EXHAUSTED`|编号/版本/序号分配耗尽；拒绝整个事务，不部分提交。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

采用 APP-EXEC-COMMON；参与Repository为 INF-DOC-REP、INF-GUIDE-REP、INF-MSG-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/guide/commands.py|retry_guide_run|APP-GUIDE-CMD-C04|
|backend/app/guide/contracts.py|retry_guide_run_input / retry_guide_run_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-guide-cmd-c05"></a>
### APP-GUIDE-CMD-C05 从评论发起修改

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-GUIDE-CMD-C05 从评论发起修改|
|处理目标|从评论发起修改的完整应用结果|
|主要对象或过程|OBJ-COMMENT、OBJ-DOC、OBJ-GUIDE、OBJ-MSG、OBJ-REQ|
|完成方式|接受后继续执行；本次只确认接受事务，最终状态由APP-GUIDE-QUERY-C01观察。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|comment_id|ID|调用参数；来源评论|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|expected_content_version|PositiveInt|调用参数；读取时的CURRENT内容版本|是|否|读取时的 CURRENT.content_version；正整数，不接受布尔值；不等于 Revision.version_no；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|读取Comment和所属需求/CURRENT；要求ACTIVE、IDLE、OPEN且未删除，CURRENT版本相等；数据变化：无|INF-COMMENT-REP；INF-REQ-REP；INF-DOC-REP；SHR-IDEMPOTENCY|成立→P02；否则状态/占用/版本错误|
|P02；允许发起|在原Block重新定位锚点；已ORPHANED不能发起，重新定位失败时只更新anchor_status=ORPHANED后返回COMMENT_ORPHANED；数据变化：重新定位失败时仅提交anchor_status=ORPHANED|SHR-ANCHOR；INF-COMMENT-REP|可定位→P03；不可定位→COMMENT_ORPHANED|
|P03；定位合法|后端从评论生成Scope和指令快照，固定MODIFY_FROM_COMMENT；同事务保存真实用户TEXT、Run并占用；数据变化：消息、Run、占用；Comment保持OPEN|INF-TX；SHR-SCOPE；INF-FUNCTION；INF-GUIDE-REP；INF-MSG-REP；INF-REQ-REP|GUIDE_ACCEPTED|


**入口绑定的业务约束**

- 后端从评论生成指令与范围，固定 MODIFY_FROM_COMMENT；不接受客户端覆盖 content、source_type、source_id、scope。

- 重新定位失败时允许只提交 anchor_status=ORPHANED 校正，然后返回 COMMENT_ORPHANED；不创建用户消息或运行。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|GUIDE_ACCEPTED|成功|返回Run；前端不可覆盖评论正文、来源或可写范围；完整成功载荷见本节。|接受后继续执行；本次只确认接受事务，最终状态由APP-GUIDE-QUERY-C01观察。|
|COMMENT_ORPHANED|冲突|锚点失效，不创建消息和运行|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|


**成功载荷 data**

[GuideRunReadModel](#guiderunreadmodel)（APP-GUIDE-QUERY-C01）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|评论或所属需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STATE_CONFLICT`|评论非 OPEN、已删除或需求非 ACTIVE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_CONFLICT`|需求非 IDLE；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|CURRENT 或活动关系异常；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONTENT_VERSION_CONFLICT`|CURRENT 版本与预期不符；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`COMMENT_ORPHANED`|已失效或重新定位失败；后者可提交 anchor_status=ORPHANED 校正；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONFIG_INVALID`|MODIFY_FROM_COMMENT 协议缺失；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CAPACITY_EXHAUSTED`|编号/版本/序号分配耗尽；拒绝整个事务，不部分提交。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

此能力存在一个明确的“拒绝结果但更新锚点”分支，P02只提交Comment.anchor_status，不与后续新建Run事务混淆。

采用 APP-EXEC-COMMON；参与Repository为 INF-COMMENT-REP、INF-DOC-REP、INF-GUIDE-REP、INF-MSG-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/guide/commands.py|modify_from_comment|APP-GUIDE-CMD-C05|
|backend/app/guide/contracts.py|modify_from_comment_input / modify_from_comment_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-guide-cmd-c06"></a>
### APP-GUIDE-CMD-C06 提交整组卡片

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-GUIDE-CMD-C06 提交整组卡片|
|处理目标|提交整组卡片的完整应用结果|
|主要对象或过程|OBJ-GUIDE、OBJ-MSG、OBJ-REQ|
|完成方式|接受后继续执行；本次只确认接受事务，最终状态由APP-GUIDE-QUERY-C01观察。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|message_id|ID|调用参数；助手卡片消息|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|schema_version|PositiveInt|调用参数；固定结构版本|是|否|JSON 整数，固定 1；缺失：拒绝；必填值|
|responses|SHR-CARDS.responses|调用参数；全部卡片答案|是|否|1～5 项，准确覆盖原消息的全部 card_key；不允许遗漏、多余或重复；缺失：拒绝；必填值|
|idempotency_key|UUID v4|调用参数；同一用户动作重试时保持原值；机制见[持久幂等](#sync-be-04)|是|否|客户端生成的 UUID v4 字符串；同一动作重试保持原值，新的动作使用新值；见 API-COM-IDEMPOTENCY；缺失：拒绝；调用方提供幂等键|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|幂等查重，加载来源消息/所属运行/需求；要求ASSISTANT且INTERACTION_CARDS；数据变化：无|INF-MSG-REP；INF-GUIDE-REP；INF-REQ-REP；SHR-IDEMPOTENCY|来源合法→P02；否则SOURCE_INVALID|
|P02；来源合法|推导AVAILABLE；验证完整组、必答/跳过、选项唯一性、自定义回答与数量；任一错误整组拒绝；数据变化：无|SHR-CARDS；OBJ-MSG|全部合法→P03；已回答→CARD_ALREADY_ANSWERED；失效→CARD_EXPIRED；错误→INVALID_INPUT|
|P03；答案合法|同事务新增唯一CARD_RESPONSE和后端可读摘要；INITIALIZE新建Run，其他动作继续原WAITING_USER运行；占用同步写入；数据变化：一条正式响应；只推进一个Run|INF-TX；INF-MSG-REP；INF-GUIDE-REP；INF-REQ-REP|CARDS_ACCEPTED|


**入口绑定的业务约束**

- responses 必须覆盖原消息全部卡片；required=true 不能跳过，非必答未回答须显式 skipped=true 且选项为空、自定义为 null。

- 单选的预设与自定义互斥；多选可组合，自定义非空时计作一次选择；确认卡片不允许自定义，选项键以原消息为准。

- 仅一条 CARD_RESPONSE 能正式关联原卡片组。INITIALIZE 回答创建新运行，其他动作继续原 WAITING_USER 运行；成功 card_state=ANSWERED。

- 同幂等键重放原成功结果；不同键再次提交已答卡片返回 CARD_ALREADY_ANSWERED，error.details.response_message_id 指向已有正式回答。


**卡片可用性与前端绑定**

已有正式CARD_RESPONSE时为ANSWERED。尚未回答的INITIALIZE卡片只在初始化空闲状态提交并新建Run；其他动作卡片必须属于当前WAITING_USER运行，提交继续该运行。普通文本替代卡片交互成功后，原组由服务端推导为EXPIRED；不把普通文本猜成选项。AVAILABLE按[唯一可回答卡片组](#sync-be-14)推导；前端只展示读取结果，不能自行创造过期时间。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|CARDS_ACCEPTED|成功|返回正式响应、运行id/status和ANSWERED状态；完整成功载荷见本节。|接受后继续执行；本次只确认接受事务，最终状态由APP-GUIDE-QUERY-C01观察。|
|CARD_ALREADY_ANSWERED|冲突|已存在正式响应，不覆盖已有答案；返回已有响应的安全引用|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|
|CARD_EXPIRED|冲突|该组卡片已不再属于当前待回复流程|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|
|SOURCE_INVALID|拒绝|来源不是有效助手卡片组|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|


**成功载荷 data**

|字段路径|类型或定义引用|含义|出现条件及可空性|确定限制|
|---|---|---|---|---|
|response_message|[MessageReadModel](#messagereadmodel)（APP-MSG-QUERY-C01）|正式回答消息|始终存在；不可为null|—|
|guide_run|[GuideRunAccepted](#guiderunaccepted)（APP-GUIDE-QUERY-C01）|推进的运行|始终存在；不可为null|—|
|card_state|Text|原卡片组状态|始终存在；不可为null|成功固定 ANSWERED|


**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|来源消息或所属运行不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`SOURCE_INVALID`|来源不是同需求 ASSISTANT 的有效 INTERACTION_CARDS；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CARD_ALREADY_ANSWERED`|已存在唯一正式回答；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CARD_EXPIRED`|原消息不再属于当前待回复流程；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|消息、运行和占用关系异常；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CONFIG_INVALID`|新建或继续所需协议资源缺失；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`IDEMPOTENCY_CONFLICT`|同键但业务输入不同；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`REQUEST_IN_PROGRESS`|同键动作尚在执行；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`CAPACITY_EXHAUSTED`|编号/版本/序号分配耗尽；拒绝整个事务，不部分提交。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.5 关键执行要求

schema_version必须为1。两个不同幂等键竞争同一消息由唯一回复约束兜底；响应已保存后模型失败，卡片仍ANSWERED，不准重提原组。

采用 APP-EXEC-COMMON；参与Repository为 INF-GUIDE-REP、INF-MSG-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/guide/commands.py|submit_card_responses|APP-GUIDE-CMD-C06|
|backend/app/guide/contracts.py|submit_card_responses_input / submit_card_responses_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-guide-cmd-c07"></a>
### APP-GUIDE-CMD-C07 提交可信AI结果

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-GUIDE-CMD-C07 提交可信AI结果|
|处理目标|提交可信AI结果的完整应用结果|
|主要对象或过程|OBJ-BATCH、OBJ-DOC、OBJ-GUIDE、OBJ-MSG、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|guide_run_id|ID|可信内部调用；当前运行|是|否|必填，无默认；当前运行|
|llm_use_id|ID|可信内部调用；已通过校验的真实调用|是|否|必填，无默认；已通过校验的真实调用|
|trusted_output|冻结输出Schema校验产物（4.7，[Q-02](#q-02)）|可信内部调用；完整校验后的单一分支|是|否|必填，无默认；完整校验后的单一分支|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|在事务检查RUNNING、活动归属、原内容版本及可信LLMUse归属；与取消竞争PERSISTING门禁；数据变化：无|INF-TX；INF-GUIDE-REP；INF-REQ-REP；INF-DOC-REP|有效→P02；取消/终态→STATE_CONFLICT；正文变化→CONTENT_VERSION_CONFLICT|
|P02；门禁获胜|按Function分支执行结果映射表；只由INITIALIZE应用明确事实补丁；MODIFY只生成非空批次；ASK/REVIEW不写正文；数据变化：无|SHR-PATCH；OBJ-DOC；OBJ-BATCH；INF-FUNCTION|合法→P03；非法→OUTPUT_INVALID|
|P03；结果形成|同事务保存助手可见消息、Run结果与状态；正文变化时重校验评论；有批次则占用转SUGGESTION_REVIEWING，等待则保留GUIDE_ACTIVE，其他释放IDLE；数据变化：按结果分支原子提交|INF-MSG-REP；INF-GUIDE-REP；INF-DOC-REP；INF-BATCH-REP；APP-COMMENT-CMD-C06；INF-REQ-REP|AI_RESULT_PERSISTED|


#### 4.4 结果与完成范围

本能力完整内部data/details按本节结果表及[内部结果契约](#sync-be-22)；成功details=null，失败data=null，不以空对象代替正式载荷。

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|AI_RESULT_PERSISTED|成功|业务结果完整提交；仅此结果可向用户展示正式产物|同步完成；结果中的提交、无变化或失败范围以4.4为准。|
|OUTPUT_INVALID|拒绝|输出分支、权限或内容校验不成立|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|



**成功载荷 data**

|字段或结构|类型与出现条件|来源及约束|
|---|---|---|
|`{guide_run_id,status,assistant_message_id,current_document,suggestion_batch_id}`|成功时完整返回的对象；details=null|current_document为null或{id,content_version}；suggestion_batch_id为null或ID。内部初始化结果可保留未变化CURRENT用于卡片绑定；公开I16没有本次写入则版本为null。|

#### 4.5 关键执行要求

最终/等待分支按第4.7节完整冻结Schema及事实/卡片证据规则校验。写入失败不得留下半条正文、半批建议或孤立助手卡片。调用审计与业务提交是不同短事务，不把已发生Provider请求回滚成“未调用”。

采用 APP-EXEC-COMMON；参与Repository为 INF-BATCH-REP、INF-DOC-REP、INF-GUIDE-REP、INF-MSG-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/guide/commands.py|persist_ai_result|APP-GUIDE-CMD-C07|
|backend/app/guide/contracts.py|persist_ai_result_input / persist_ai_result_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-guide-cmd-c08"></a>
### APP-GUIDE-CMD-C08 记录运行失败

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-GUIDE-CMD-C08 记录运行失败|
|处理目标|记录运行失败的完整应用结果|
|主要对象或过程|OBJ-GUIDE、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|guide_run_id|ID|可信内部调用；活动运行|是|否|必填，无默认；活动运行|
|error_code|ErrorCode|可信内部调用；确定失败原因|是|否|必填，无默认；确定失败原因|
|safe_message|Text|可信内部调用；安全错误摘要|是|否|必填，无默认；安全错误摘要|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|事务读取Run并确认尚未被取消或成功提交；数据变化：无|INF-TX；INF-GUIDE-REP|仍RUNNING→P02；已终态→RUN_FINAL_UNCHANGED|
|P02；仍运行|写FAILED/FINISHED及error/ended_at，结束未完成调用；仅在占用仍指本Run时释放IDLE；数据变化：运行失败；CURRENT不变|INF-GUIDE-REP；INF-REQ-REP|RUN_FAILED|


#### 4.4 结果与完成范围

本能力完整内部data/details按本节结果表及[内部结果契约](#sync-be-22)；成功details=null，失败data=null，不以空对象代替正式载荷。

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|RUN_FAILED|成功|失败已持久化，允许用户重新运行|同步完成；结果中的提交、无变化或失败范围以4.4为准。|
|RUN_FINAL_UNCHANGED|成功|未覆盖已经形成的终态|同步完成；结果中的提交、无变化或失败范围以4.4为准。|



**成功载荷 data**

|字段或结构|类型与出现条件|来源及约束|
|---|---|---|
|`{guide_run_id,status,ended_at,occupancy_released}`|成功时完整返回的对象；details=null|适用于RUN_FAILED及RUN_FINAL_UNCHANGED成功结果；字段来自实际终态，occupancy_released为boolean。|

#### 4.5 关键执行要求

失败落库自身也失败时由恢复能力处理，不伪报已释放占用。

采用 APP-EXEC-COMMON；参与Repository为 INF-GUIDE-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/guide/commands.py|fail_guide_run|APP-GUIDE-CMD-C08|
|backend/app/guide/contracts.py|fail_guide_run_input / fail_guide_run_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-guide-cmd-c09"></a>
### APP-GUIDE-CMD-C09 恢复中断与超时占用

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-GUIDE-CMD-C09 恢复中断与超时占用|
|处理目标|恢复中断与超时占用的完整应用结果|
|主要对象或过程|OBJ-BATCH、OBJ-GUIDE、OBJ-REQ|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|recovery_reason|RecoveryReason|可信内部调用；STARTUP或NO_PROGRESS|是|否|必填，无默认；STARTUP或NO_PROGRESS|
|live_run_ids|Set[ID]|可信内部调用；当前单进程实际运行集合|是|否|必填，无默认；当前单进程实际运行集合|
|operation_time|UtcTime|可信内部调用；服务端当前时间|是|否|必填，无默认；服务端当前时间|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；启动或监测触发|读取运行与活动占用；STARTUP对数据库RUNNING且无本进程任务者判中断，NO_PROGRESS对RUNNING且15分钟无进展者判超时；数据变化：无|INF-GUIDE-REP；INF-REQ-REP；SHR-TIME|确定失败→P02；终态占用→P03；等待或正常→RECOVERY_NO_CHANGE|
|P02；确定失败|事务重检后将Run及未结束调用标失败，记录INTERRUPTED或EXECUTION_TIMEOUT，释放所属占用；不自动调用模型；数据变化：失败状态及占用|INF-TX；INF-GUIDE-REP；INF-REQ-REP|RECOVERED|
|P03；占用指向已终态对象|有唯一可信批次则切换到该PENDING批次；无待处理批次且对象已终态则清占用；活动对象缺失/跨需求或多候选拒绝猜测；数据变化：确定性修复或不修改|INF-TX；INF-BATCH-REP；INF-GUIDE-REP；INF-REQ-REP|可确定→RECOVERED；否则WORK_STATE_INCONSISTENT|


#### 4.4 结果与完成范围

本能力完整内部data/details按本节结果表及[内部结果契约](#sync-be-22)；成功details=null，失败data=null，不以空对象代替正式载荷。

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|RECOVERED|成功|已修复可确定的中断或终态占用|同步完成；结果中的提交、无变化或失败范围以4.4为准。|
|RECOVERY_NO_CHANGE|成功|等待用户、待处理批次和人工草稿原样保留|同步完成；结果中的提交、无变化或失败范围以4.4为准。|



**成功载荷 data**

|字段或结构|类型与出现条件|来源及约束|
|---|---|---|
|`{recovery_reason,operation_time,recovered_run_ids,repaired_requirement_ids,unchanged_requirement_ids}`|成功时完整返回的对象；details=null|recovery_reason为STARTUP/NO_PROGRESS，时间为服务端UTC；ID数组不可null，空用[]。|

#### 4.5 关键执行要求

启动恢复须先于接受新业务请求。监测触发周期、最大检测延迟与worker租约机制见[Q-08](#q-08)；单用户不等于允许多进程同时把对方任务判为中断。

采用 APP-EXEC-COMMON；参与Repository为 INF-BATCH-REP、INF-GUIDE-REP、INF-REQ-REP。共同原子范围是4.3声明共同成立的全部变更；各步骤的占用和版本判断在实际提交事务内执行。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/guide/commands.py|recover_runs|APP-GUIDE-CMD-C09|
|backend/app/guide/contracts.py|recover_runs_input / recover_runs_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-guide-orch-c01"></a>
### APP-GUIDE-ORCH-C01 推进AI运行

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-GUIDE-ORCH-C01 推进AI运行|
|处理目标|推进AI运行的完整应用结果|
|主要对象或过程|OBJ-GUIDE|
|完成方式|后台执行至可信结果、等待用户、失败或取消；WAITING_USER交回用户输入入口。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|guide_run_id|ID|可信内部调用；已提交RUNNING运行|是|否|必填，无默认；已提交RUNNING运行|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|S01；后台取得运行|调用只读能力取得运行上下文和冻结资源；检查任务仍可执行；数据变化：无|APP-GUIDE-QUERY-C03；INF-FUNCTION|有效→S02；缺配置→APP-GUIDE-CMD-C08|
|S02；上下文可组装|按冻结模板/输入Schema组装；按第4.7节裁剪及v3精确Tokenization＋1024余量预检，计数失败或超限不发Chat；计数独立审计，不占写事务|APP-GUIDE-QUERY-C03；INF-FUNCTION|通过→S03；失败→APP-GUIDE-CMD-C08|
|S03；输入通过|每次Chat尝试重新计数并核对序列化身份；短事务记录LLMUse后再调Gateway；每真实请求一条审计；计数失败不发Chat|INF-TX；INF-GUIDE-REP；INF-MODEL|返回→S04；技术失败→S06|
|S04；Provider返回|先留实际审计，再复核精确model、整数usage、各预算及0—1024封装差值；异常CONFIG_INVALID且不重试。通过才解析单JSON、校验Schema/分支/权限及事实证明；合格才写trusted_output|INF-FUNCTION；SHR-SCOPE；SHR-PATCH；INF-GUIDE-REP|合格→S05；不合格→S06|
|S05；完整可信结果|调用唯一业务提交能力，不在Orchestrator重复实现正文写入；数据变化：由下级能力负责|APP-GUIDE-CMD-C07|成功→AI_FINISHED或AI_WAITING_USER；终态冲突→AI_STOPPED；失败→S06|
|S06；调用/解析/校验失败|重试前重检Run和占用；同call_no最多3次真实请求。只对可重试分类重新计数再执行S03；实际usage拒绝不可重试；其他失败或额度耗尽调用失败能力；数据变化：尝试审计；最后一次错误为Run最终错误|APP-GUIDE-CMD-C08；INF-GUIDE-REP|可重试→S03；已终态→AI_STOPPED；失败已记→AI_FAILED|


#### 4.4 结果与完成范围

本能力完整内部data/details按本节结果表及[内部结果契约](#sync-be-22)；成功details=null，失败data=null，不以空对象代替正式载荷。

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|AI_FINISHED|成功|Run完成，用户通过轮询和消息/正文查询观察|后台执行至可信结果、等待用户、失败或取消；WAITING_USER交回用户输入入口。|
|AI_WAITING_USER|成功|原Run等待补充，持续占用|后台执行至可信结果、等待用户、失败或取消；WAITING_USER交回用户输入入口。|
|AI_STOPPED|成功|取消或终态先获胜，没有迟到业务写入|后台执行至可信结果、等待用户、失败或取消；WAITING_USER交回用户输入入口。|
|AI_FAILED|已知失败|运行失败并保留审计|按处理路径终止；拒绝默认无业务变化，明确例外见4.5。|



**成功载荷 data**

|字段或结构|类型与出现条件|来源及约束|
|---|---|---|
|`{guide_run_id,status,current_step,last_call_no}`|成功时完整返回的对象；details=null|适用于AI_FINISHED/AI_WAITING_USER/AI_STOPPED；AI_FAILED的data=null、details={guide_run_id,error_code}，不穿透Provider内容。|

#### 4.5 关键执行要求

V1非流式，无Tool Calling、无自动工具轮次。自动尝试上限属于本编排器；Gateway及SDK各真实调用1次，禁止嵌套放大。两次重试间隔为2秒、5秒；v3计数或实际usage复核失败不自动重试。WAITING_USER新输入产生新的call_no，不沿用前次失败额度；用户等待不计执行超时。

|状态或事件|确定处理|入口|
|---|---|---|
|RUNNING且任务存在|按S01～S06推进|BND-WORKER|
|WAITING_USER|暂停，不自动过期；回复后新call_no并沿用冻结协议|APP-GUIDE-CMD-C02或C06|
|服务启动遗留RUNNING|记中断失败，不重发模型|APP-GUIDE-CMD-C09|
|15分钟无进展|执行超时终止并拒绝迟到写入|APP-GUIDE-CMD-C09|
|可重试错误|网络暂时失败、超时、限流、服务端暂时失败、解析或输出校验失败共用至多3次真实请求|S06|
|不可重试错误|认证、权限、余额、配额、模型未开通、输入超长、安全拒绝、取消、业务状态变化及v3计数/实际usage复核失败直接结束；见[正式模型规则](#sync-be-18)及[实用预算控制](#sync-be-19)|S06|
|用户取消|PERSISTING前争用同一状态门禁|APP-GUIDE-CMD-C03|
|已支付/已请求Provider|不能事务回滚Provider用量；保留LLMUse，不自动退款或补发|INF-MODEL|

|字段|确定定义|
|---|---|
|最大尝试次数|每call_no为3；Gateway单次1，SDK自动重试0；总数上界=逻辑调用数×3；用户显式继续次数不设置自动循环|
|执行超时|没有覆盖用户等待的整体截止时间；连接10秒、读取180秒来自INF-PROFILE；无进展阈值15分钟|
|取消|业务逻辑取消，尝试关闭连接；不承诺远端停止|
|恢复检查周期|每30秒不重叠扫描，错过不并发补跑，卡顿无墙钟硬上限|
|重试间隔|2秒、5秒；最多3次含首次，实际usage异常不重试|

#### 4.7 AI任务补充

|AI调用编号|FunctionType|ActionType|SourceType|输入Schema|输出Schema|ContextTemplate|产物|应用方式|
|---|---|---|---|---|---|---|---|---|
|<a id="app-guide-orch-c01-ai01"></a>APP-GUIDE-ORCH-C01-AI01|INITIALIZE_REQUIREMENT|INITIALIZE|USER_INSTRUCTION|INITIALIZE_INPUT@v1|INITIALIZE_OUTPUT@v1|INITIALIZE_CONTEXT@v2|已确认事实的文档补丁、文本或卡片|程序校验后应用；AI未知信息不能写为事实|
|<a id="app-guide-orch-c01-ai02"></a>APP-GUIDE-ORCH-C01-AI02|ANSWER_REQUIREMENT|ASK|USER_INSTRUCTION|ASK_INPUT@v1|ASK_OUTPUT@v1|ASK_CONTEXT@v2|回答或澄清问题/卡片|只保存消息及Run结果|
|<a id="app-guide-orch-c01-ai03"></a>APP-GUIDE-ORCH-C01-AI03|REVIEW_REQUIREMENT|REVIEW|USER_INSTRUCTION|REVIEW_INPUT@v1|REVIEW_OUTPUT@v1|REVIEW_CONTEXT@v2|轻量检查结果或澄清|只保存消息及Run结果，无独立检查对象|
|<a id="app-guide-orch-c01-ai04"></a>APP-GUIDE-ORCH-C01-AI04|MODIFY_REQUIREMENT|MODIFY|USER_INSTRUCTION|MODIFY_INPUT@v1|MODIFY_OUTPUT@v1|MODIFY_CONTEXT@v2|非空建议批次、无修改说明或澄清|用户整批确认后应用|
|<a id="app-guide-orch-c01-ai05"></a>APP-GUIDE-ORCH-C01-AI05|MODIFY_FROM_REVIEW|MODIFY|REVIEW_RESULT|MODIFY_FROM_REVIEW_INPUT@v1|MODIFY_OUTPUT@v1|MODIFY_FROM_REVIEW_CONTEXT@v2|以历史检查作依据重新生成建议|读取最新CURRENT，不执行旧检查中的Patch|
|<a id="app-guide-orch-c01-ai06"></a>APP-GUIDE-ORCH-C01-AI06|MODIFY_FROM_COMMENT|MODIFY|COMMENT|MODIFY_FROM_COMMENT_INPUT@v1|MODIFY_OUTPUT@v1|MODIFY_FROM_COMMENT_CONTEXT@v2|在来源评论锚点授权范围内生成建议|用户整批确认后应用，不自动解决评论|

**Prompt与上下文**

|字段|确定定义|
|---|---|
|Prompt标识|新运行FunctionType@v2；旧运行按原冻结版本；已使用资源不可原地修改，冻结版本缺失直接CONFIG_INVALID|
|消息结构|非流式Chat Completions；System承载固定协议和不可信输入边界；System/User精确字段按本节固定资源及[上下文规则](#sync-be-17)|
|事实解释顺序|后端状态/授权约束→CURRENT→本轮真实用户输入→少量历史消息。新用户变更意图可以提出修改CURRENT，不能因事实优先级被忽略；只有程序完成正文写入后才成为新正式事实。|
|上下文最小事实|需求与CURRENT身份及content_version、固定模板、Scope、Allowed Targets、当前用户输入；MODIFY_FROM_REVIEW/COMMENT额外带来源快照|
|局部读取|BLOCK读取目标、所属标题及相邻Block；读取权限可以大于修改权限；邻域左右各2块、历史最多10条；SECTION边界按SHR-SCOPE|
|排除内容|人工草稿、未应用Suggestion、历史Revision正文、无关Comment、LLMUse原始记录、内部推理/运行日志、AI未选推荐|
|清单|记录Document id/version、Block IDs、实际Message IDs、模板键版本、来源对象、ContextTemplate版本；LLMUse保存实际清单|
|Token预算|总32768、输入24576、输出8192；System/当前输入/来源/模板各4096、历史2048；先删最老完整历史再删非必要邻域；必要事实不可裁剪|
|输出模式|一个JSON对象，schema_version整数；Schema Draft 2020-12；每层对象additionalProperties=false；response_type互斥分支|
|输出处理|传输→单一JSON解析→输出Schema→业务状态/Scope/目标校验→对象有效性→APP-GUIDE-CMD-C07|
|输出修复|不去围栏、不猜字段、不删未知字段、不自动补默认值；可在剩余尝试额度内把安全校验摘要追加到原协议，要求重生成完整对象|
|AI安全|用户文本、评论和文档内容作为业务数据，不能改变系统权限或协议；模型对象ID须回查；模型SQL、命令、路径不直接执行；V1不暴露Tool或任意文件访问|
|调用记录|每次真实请求对应LLMUse；快照不得含API Key；reasoning内容不进消息/final_result/trusted_output；原始响应脱敏范围见[Q-09](#q-09)|

**输出分支与持久化去向**

|Function|结果分支|业务写入|GuideRun终态/中间态|Requirement占用|
|---|---|---|---|---|
|INITIALIZE|INITIALIZE_TEXT / INITIALIZE_CARDS，带confirmed_fact_patches|同事务保存正文变化、区块状态、助手消息及Run结果；无补丁不更新正文版本|COMPLETED|IDLE|
|ASK/REVIEW/MODIFY|CLARIFY_TEXT / CLARIFY_CARDS|保存文本问题或卡片；正文不变|WAITING_USER|GUIDE_ACTIVE|
|ASK|ANSWER|助手消息与Run结果|COMPLETED|IDLE|
|REVIEW|REVIEW_RESULT及review_result|助手消息与Run结果|COMPLETED|IDLE|
|MODIFY各来源|NO_CHANGE|助手消息与Run结果；不建空批次|COMPLETED|IDLE|
|MODIFY各来源|SUGGESTIONS及非空suggestions|同事务创建批次、全部建议及消息/Run结果；不写CURRENT|COMPLETED|SUGGESTION_REVIEWING|

最终回答、澄清、初始化补丁/卡片及review_result完整字段按以下正式资源和互斥分支定义；不以摘要取代完整冻结Schema。




<a id="sync-be-15"></a>

**六类AI正式资源和v2版本关系**

新运行冻结 Function/Prompt/Context v2；十份输入/输出 Schema 和模板本身继续 v1。同运行继续恢复原冻结版本，旧 v1 运行不得改为 v2 或“最新”；缺失/签名不符 CONFIG_INVALID。完整资源位于 `backend/resources/v1`、`backend/resources/v2`，Manifest 校验全部内容。完整资源按下表及固定目录读取。

| FunctionType | 输入 Schema（不改版本） | 输出 Schema（不改版本） | 新运行 Context / Prompt |
| --- | --- | --- | --- |
| INITIALIZE_REQUIREMENT | INITIALIZE_INPUT@v1 | INITIALIZE_OUTPUT@v1 | INITIALIZE_CONTEXT@v2 / INITIALIZE_REQUIREMENT@v2 |
| ANSWER_REQUIREMENT | ASK_INPUT@v1 | ASK_OUTPUT@v1 | ASK_CONTEXT@v2 / ANSWER_REQUIREMENT@v2 |
| REVIEW_REQUIREMENT | REVIEW_INPUT@v1 | REVIEW_OUTPUT@v1 | REVIEW_CONTEXT@v2 / REVIEW_REQUIREMENT@v2 |
| MODIFY_REQUIREMENT | MODIFY_INPUT@v1 | MODIFY_OUTPUT@v1 | MODIFY_CONTEXT@v2 / MODIFY_REQUIREMENT@v2 |
| MODIFY_FROM_REVIEW | MODIFY_FROM_REVIEW_INPUT@v1 | MODIFY_OUTPUT@v1 | MODIFY_FROM_REVIEW_CONTEXT@v2 / MODIFY_FROM_REVIEW@v2 |
| MODIFY_FROM_COMMENT | MODIFY_FROM_COMMENT_INPUT@v1 | MODIFY_OUTPUT@v1 | MODIFY_FROM_COMMENT_CONTEXT@v2 / MODIFY_FROM_COMMENT@v2 |

补齐互斥分支：INITIALIZE_TEXT 为 `{schema_version,response_type,message,confirmed_fact_patches}`，INITIALIZE_CARDS 另带 cards；ASK 最终 ANSWER，REVIEW 最终 REVIEW_RESULT 且带 review_result，MODIFY 为 NO_CHANGE 或非空 SUGGESTIONS（message/title/summary/suggestions）；非初始化任务可用 CLARIFY_TEXT/CLARIFY_CARDS 进入 WAITING_USER。`review_result` 必含 schema_version=1、summary、issues，具体 issue 结构引用 `REVIEW_OUTPUT.v1.json#/$defs/review_result` 的完整定义，不另编字段。所有层级拒绝未知字段，仍只接受单个完整 JSON，原分支持久化去向不变。

**确认依据**：D-005、D-010；[完整 v2 候选审查稿](../proposals/output-evidence-resources-v2-review.md)。**代码对应**：`infrastructure/resources.py::{ResourceCatalog,FrozenFunction}`、`backend/resources/v2/functions.v2.json`、`schemas/`、`contexts/`、`prompts/`、`guide/result_persistence.py`。


<a id="sync-be-16"></a>

**“已确认事实”和卡片文本等价证明**

INITIALIZE 非空事实补丁不能仅凭用户消息包含关键词通过。程序按真实目标、完整章节、操作、完整原文及完整新正文构造固定“确认事实变更”声明，五种操作全部适用，表格行声明额外包含完整原表及实际行选择器。声明完整格式以已批准 [事实证据补充稿](../proposals/output-evidence-equivalence-v1.md)“一”为准，作为本条正式引用。

证据仅接受两路：已实际读取 USER TEXT 的整条内容为完整声明；或真实 USER CARD_RESPONSE 对不可变原 CONFIRM 卡明确选择 confirm，该卡完整问题为声明＋固定确认问句、选项 confirm/defer、单选、自定义关闭、无推荐，并包含实际目标完整原块。defer、跳过、助手话语、未选推荐、截取短语、拼接消息不算确认。正式回答证据按整条摘要每 10000 码点连续分片、最多 10 片，顺序完整且同一实际 message_id；该消息必须在本次 Read Manifest。每项 Patch 分别证明，仍共同检查组合和事务采用。

声明比较仅采用 SHR-TEXT 换行及外侧空白规范化；Patch 原字节、权限和选区外不变等检查不放宽。原 message 必须逐字等于固定 `card_text(cards)`：按卡片顺序列 card_key、question/context/card_type/required/selection_rule/custom_answer、全部 option 字段、完整 recommendation 或 null、全部 related_spec_context 完整原文；JSON 字符串转义、固定标签顺序及 LF 分隔。不得接收后替换 message、删字段或补默认来修成成功。超既有容量拒绝，短证据不降级采用。

**确认依据**：D-010，完整算法与 v2 候选同时批准。**代码对应**：`guide/output_evidence.py::{fact_declaration,validate_fact_patches,card_text,validate_card_output}`、`trusted_output.py`、`result_persistence.py`、`backend/resources/v2/OUTPUT-EVIDENCE-EQUIVALENCE.v1.md`。此证明确认用户是否认可具体变更，不证明现实世界事实本身真实。


<a id="sync-be-17"></a>

**上下文字段、预算及传输Schema派生**

完整 User 对象为 `schema_version,function_type,action_type,source_type,requirement,current_document,template,scope,allowed_targets,user_input,history,source,read_manifest`，字段和来源按固定输入 Schema；最多最近 10 条正式可读历史，左右各 2 个邻域块，禁止草稿、未采用建议、历史正文、无关评论、原始调用、推理及未选推荐进入事实。

预算总量 32768、输入 24576、输出 8192 token；System、当前用户输入、来源和模板分别最多 4096，历史最多 2048。仅先删最老完整历史消息，再删非必要完整邻域块；目标、祖先、必要来源、模板及当前输入不可裁剪。仍超限 CONTEXT_LIMIT_EXCEEDED，不发 Chat，不用模型大窗口替代业务预算。

发送给模型的输出 Schema 仅移除根不可达本地 `$defs`，保留全部可达约束；动态/外部/递归或不支持的解析机制拒绝 CONFIG_INVALID。程序验证仍用完整签名 Schema，私有审计保存原 Schema 和派生 Schema 的独立 SHA-256、实际 System/User、协议和 Read Manifest。正式计数如何执行、余量如何承诺以 [BE-19](#sync-be-19) 为准；已冻结 Context 中的旧 `budget.counting` 标签保留为历史字节，不能把它当作当前运行的唯一计数策略，也不应原地改冻结资源。

**确认依据**：D-005、D-011、D-015。**代码对应**：`guide/{model_context,context_builder,counted_context}.py`、`infrastructure/schema_transport.py`、`backend/resources/v2/contexts/`、`backend/resources/counting/v3/strategy.json`。


<a id="sync-be-19"></a>

**正式实用预算控制及其保证边界**

DeepSeek 正式新调用采用独立 counting/v3，模式 `exact_text_empirical_framing_v1`。每次候选和 Chat 尝试重新执行实际模型的 Tokenization，核对精确模型、六项文本回执和实际序列化身份；输入预检为 System＋完整 User 的实测 token 数＋1024 固定余量，原总/分项预算和裁剪不扩大。计数失败、未知、版本不符或超限不发 Chat，不回退字节估计或其他模型。计数等待不占 SQLite 写事务。

**必须直接写明**：这一模式不保证发送前实际输入永不超过 24576；封装异常可能在已付费响应返回后才发现，事后拒绝不能追回费用。`provider_compatibility_proved` 始终为 false。不能将六次样本成功改写为通用封装上界证明，也不能把旧模型的 256 候选余量当新模型证明。

收到响应先保留实际调用审计，再复核精确 model、整数 usage、prompt≤24576、completion≤8192、total=prompt+completion≤32768，以及实际 prompt 减 System/User 文本计数的差值在 0—1024。缺失/不一致/越界按 CONFIG_INVALID 结束，不进入 C07、不自动重试；可信产物和最终采用再次复查。准入须独立固定配置绑定批准记录、策略和计划身份；环境布尔值或自动发现测试报告不能开放。旧 v1/v2 计数及其历史审计不原地改契约。

**确认依据**：D-015 对 D-011/014 严格封装前提作出的明确变更；[实用预算补充稿](../proposals/deepseek-availability-v1.md)。**代码对应**：`guide/counted_context.py`、`infrastructure/{tokenization,production_ai,practical_usage}.py`、`guide/{orchestrator,trusted_output,result_persistence}.py`、`backend/resources/counting/v3/{strategy,admission}.json`。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/guide/orchestrator.py|execute_guide_run|APP-GUIDE-ORCH-C01|
|backend/app/guide/contracts.py|execute_guide_run_input / execute_guide_run_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-req-query-c01"></a>
### APP-REQ-QUERY-C01 查询需求列表

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-REQ-QUERY-C01 查询需求列表|
|处理目标|查询需求列表的完整应用结果|
|主要对象或过程|OBJ-REQ；关联和来源按4.6。|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|keyword|Text|调用参数；单个已提交关键词|否|是|去首尾空白后 0～100 个 Unicode 码点；不含内部换行；匹配规则见下表；缺失：不按关键词筛选；解析后字符串；未传为 null；能力执行关键词标准化|
|status|List[RequirementStatus]|调用参数；状态多值|否|否|INITIALIZING / ACTIVE / COMPLETED；重复参数名传多值，空值拒绝，重复合法值去重；缺失：不限制该项；解析后的数组；未传为 []；能力去重并验证业务枚举|
|requirement_type|List[ConfiguredType]|调用参数；类型多值|否|否|NEW：需求新增；CHANGE：需求改造；区分大小写；重复参数名传多值，空值拒绝，重复合法值去重；缺失：不限制该项；解析后的数组；未传为 []；能力去重并验证业务枚举|
|page|PositiveInt|调用参数；默认为1|否|否|1～100000；仅十进制正整数，不带前导零、符号、小数或空白；缺失：1；1（未传时）|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|解析查询输入并校验确定枚举、页码或游标；数据变化：无|SHR-PAGE；SHR-SERIALIZE|合法→P02；否则INVALID_INPUT|
|P02；输入合法|调用只读Repository取得一致读取结果，组装本能力读取模型；数据变化：无|INF-READ|成功（含空列表）→READ_OK；存储失败→STORAGE_UNAVAILABLE|


**入口绑定的业务约束**

- 关键词按完整编号精确匹配（忽略编号英文大小写）；其他关键词按标题字面值包含匹配（区分大小写），% 和 _ 不作通配符。编号未命中不回退标题搜索。

- 同字段多值采用“或”，不同筛选字段与关键词采用“且”；全选等同不限制该项。

- 排序 updated_at DESC、id DESC；每页 20 条；空结果与越界页均成功，保留请求页码。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|READ_OK|成功|items含id、requirement_no、title、requirement_type、status、updated_at；分页放边界meta.pagination；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

|字段路径|类型或定义引用|含义|出现条件及可空性|确定限制|
|---|---|---|---|---|
|items|[RequirementListItem[]](#requirementlistitem)（APP-REQ-QUERY-C01）|需求列表|始终存在；不可为null|—|


data 同时含 page、page_size、total、total_pages，均为整数且不可空；值由 SHR-PAGE 与本次同快照查询确定。

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.6 查询补充

|查询规则|确定定义|
|---|---|
|查询条件与匹配|完整REQ+六位数字忽略大小写精确查编号；其他关键词仅查标题包含；同字段多值OR、字段间AND；空白关键词不参与；未提供或全选数组不参与；空筛选数组表示不参与过滤，HTTP省略参数|
|条件标准化|文本先执行SHR-TEXT；未知枚举拒绝；缺省页码为1；按单项查询定义处理缺省筛选|
|排序|updated_at DESC,id DESC|
|分页|固定20条，page从1开始；公共计算见SHR-PAGE|
|空结果|空列表/越界页均READ_OK|
|数据来源|OBJ-REQ|


本能力若返回列表与总数，二者采用同一读取快照；复合结果中的对象与派生字段必须来自一致读取。关联异常按4.3及4.4处理，不在查询中修复。

<a id="requirementlistitem"></a>
**读取模型：RequirementListItem**

|字段|类型或定义引用|出现条件及可空性|数据来源、计算或转换|
|---|---|---|---|
|id|Int|每个元素必有；不可为null|OBJ-REQ.id直接投影；正整数|
|requirement_no|Text|每个元素必有；不可为null|OBJ-REQ.requirement_no直接投影；REQ 加六位数字|
|title|Text|每个元素必有；不可为null|OBJ-REQ.title直接投影；标准化后 1～20 个 Unicode 码点，不含换行|
|requirement_type|Text|每个元素必有；不可为null|OBJ-REQ.requirement_type直接投影；NEW：需求新增；CHANGE：需求改造|
|status|Text|每个元素必有；不可为null|OBJ-REQ.status直接投影；INITIALIZING / ACTIVE / COMPLETED|
|updated_at|UtcTime|每个元素必有；不可为null|OBJ-REQ.updated_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|


编号精确匹配未命中即空结果，不降级成标题检索。标题包含匹配区分大小写，%和_按字面处理，不能成为SQL通配符。未提供或选择全部合法枚举不限制该字段。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/requirements/queries.py|list_requirements|APP-REQ-QUERY-C01|
|backend/app/requirements/contracts.py|list_requirements_input / list_requirements_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-req-query-c02"></a>
### APP-REQ-QUERY-C02 查询需求详情

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-REQ-QUERY-C02 查询需求详情|
|处理目标|查询需求详情的完整应用结果|
|主要对象或过程|OBJ-REQ；关联和来源按4.6。|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验本能力4.2列出的ID、筛选及分页输入；数据变化：无|SHR-PAGE；SHR-SERIALIZE|合法→P02；否则INVALID_INPUT|
|P02；输入合法|调用只读Repository取得一致读取结果，组装本能力读取模型；数据变化：无|INF-READ|成功→READ_OK；单对象不存在→NOT_FOUND；存储失败→STORAGE_UNAVAILABLE|


**入口绑定的业务约束**

- 直接返回需求属性及活动类型/ID，正文通过 I08 读取。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|READ_OK|成功|Requirement全部业务字段和活动类型/ID；不嵌套正文；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[RequirementReadModel](#requirementreadmodel)（APP-REQ-QUERY-C02）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.6 查询补充

|查询规则|确定定义|
|---|---|
|查询条件与匹配|按内部ID精确|
|条件标准化|仅校验本能力4.2实际接收的输入，不额外引入筛选或分页参数。|
|排序|单对象|
|分页|不分页；公共计算见SHR-PAGE|
|空结果|不存在NOT_FOUND|
|数据来源|OBJ-REQ|


本能力若返回列表与总数，二者采用同一读取快照；复合结果中的对象与派生字段必须来自一致读取。关联异常按4.3及4.4处理，不在查询中修复。

<a id="requirementreadmodel"></a>
**读取模型：RequirementReadModel**

|字段|类型或定义引用|出现条件及可空性|数据来源、计算或转换|
|---|---|---|---|
|id|Int|始终存在；不可为null|OBJ-REQ.id直接投影；正整数|
|requirement_no|Text|始终存在；不可为null|OBJ-REQ.requirement_no直接投影；REQ 加六位数字|
|requirement_type|Text|始终存在；不可为null|OBJ-REQ.requirement_type直接投影；NEW：需求新增；CHANGE：需求改造|
|initialization_mode|Text|始终存在；不可为null|OBJ-REQ.initialization_mode直接投影；IDEATION：灵感模式；DESIGN：设计模式|
|title|Text|始终存在；不可为null|OBJ-REQ.title直接投影；标准化后 1～20 个 Unicode 码点，不含换行|
|template_key|Text|始终存在；不可为null|OBJ-REQ.template_key直接投影；创建时固定的模板资源键；示例键需由实际模板目录提供|
|template_version|Text|始终存在；不可为null|OBJ-REQ.template_version直接投影；创建时固定的模板版本|
|status|Text|始终存在；不可为null|OBJ-REQ.status直接投影；INITIALIZING / ACTIVE / COMPLETED|
|document_work_state|Text|始终存在；不可为null|OBJ-REQ.document_work_state直接投影；IDLE / MANUAL_EDITING / GUIDE_ACTIVE / SUGGESTION_REVIEWING|
|active_operation_type|Text|始终存在；可为null|OBJ-REQ.active_operation_type直接投影；IDLE 时 null；否则为 MANUAL_DRAFT / GUIDE_RUN / SUGGESTION_BATCH|
|active_operation_id|Int|始终存在；可为null|OBJ-REQ.active_operation_id直接投影；IDLE 时 null；否则引用当前占用对象|
|created_at|UtcTime|始终存在；不可为null|OBJ-REQ.created_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|updated_at|UtcTime|始终存在；不可为null|OBJ-REQ.updated_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|completed_at|UtcTime|始终存在；可为null|OBJ-REQ.completed_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|state_started_at|UtcTime|始终存在；可为null|OBJ-REQ.state_started_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|


#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/requirements/queries.py|get_requirement|APP-REQ-QUERY-C02|
|backend/app/requirements/contracts.py|get_requirement_input / get_requirement_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-doc-query-c01"></a>
### APP-DOC-QUERY-C01 读取当前正文

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-DOC-QUERY-C01 读取当前正文|
|处理目标|读取当前正文的完整应用结果|
|主要对象或过程|OBJ-DOC；关联和来源按4.6。|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验本能力4.2列出的ID、筛选及分页输入；数据变化：无|SHR-PAGE；SHR-SERIALIZE|合法→P02；否则INVALID_INPUT|
|P02；输入合法|调用只读Repository取得一致读取结果，组装本能力读取模型；数据变化：无|INF-READ|成功→READ_OK；需求不存在→NOT_FOUND；有需求无CURRENT→WORK_STATE_INCONSISTENT；存储失败→STORAGE_UNAVAILABLE|


**入口绑定的业务约束**

- document_type 固定 CURRENT。需求存在但 CURRENT 缺失或不唯一是状态不一致，不伪装成空文档。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|READ_OK|成功|id、requirement_id、document_type、markdown_content、block_state_json对象、content_version、created_at、updated_at；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[DocumentReadModel](#documentreadmodel)（APP-DOC-QUERY-C01）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|需求存在但没有唯一 CURRENT；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.6 查询补充

|查询规则|确定定义|
|---|---|
|查询条件与匹配|本需求document_type=CURRENT|
|条件标准化|仅校验本能力4.2实际接收的输入，不额外引入筛选或分页参数。|
|排序|单对象|
|分页|不分页；公共计算见SHR-PAGE|
|空结果|需求不存在NOT_FOUND；需求存在但无CURRENT为WORK_STATE_INCONSISTENT|
|数据来源|OBJ-DOC|


本能力若返回列表与总数，二者采用同一读取快照；复合结果中的对象与派生字段必须来自一致读取。关联异常按4.3及4.4处理，不在查询中修复。

<a id="documentreadmodel"></a>
**读取模型：DocumentReadModel**

|字段|类型或定义引用|出现条件及可空性|数据来源、计算或转换|
|---|---|---|---|
|id|Int|始终存在；不可为null|OBJ-DOC.id直接投影；正整数|
|requirement_id|Int|始终存在；不可为null|OBJ-DOC.requirement_id直接投影；正整数|
|document_type|Text|始终存在；不可为null|OBJ-DOC.document_type直接投影；CURRENT：正式正文；MANUAL_DRAFT：独立人工草稿|
|markdown_content|Text|始终存在；不可为null|OBJ-DOC.markdown_content直接投影；完整内容，允许空字符串；不可将对象转义后塞入此字段|
|block_state_json|[BlockState](#shr-block)|始终存在；不可为null|OBJ-DOC.block_state_json直接投影；JSON 对象；与 markdown_content 对应同一快照|
|content_version|Int|始终存在；不可为null|OBJ-DOC.content_version直接投影；CURRENT 与 MANUAL_DRAFT 各自独立递增|
|created_at|UtcTime|始终存在；不可为null|OBJ-DOC.created_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|updated_at|UtcTime|始终存在；不可为null|OBJ-DOC.updated_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|


#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/documents/queries.py|get_current_document|APP-DOC-QUERY-C01|
|backend/app/documents/contracts.py|get_current_document_input / get_current_document_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-doc-query-c02"></a>
### APP-DOC-QUERY-C02 读取人工草稿

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-DOC-QUERY-C02 读取人工草稿|
|处理目标|读取人工草稿的完整应用结果|
|主要对象或过程|OBJ-DOC；关联和来源按4.6。|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验本能力4.2列出的ID、筛选及分页输入；数据变化：无|SHR-PAGE；SHR-SERIALIZE|合法→P02；否则INVALID_INPUT|
|P02；输入合法|调用只读Repository取得一致读取结果，组装本能力读取模型；数据变化：无|INF-READ|成功→READ_OK；无草稿→MANUAL_DRAFT_NOT_FOUND；活动引用异常→WORK_STATE_INCONSISTENT；存储失败→STORAGE_UNAVAILABLE|


**入口绑定的业务约束**

- document_type 固定 MANUAL_DRAFT。没有草稿且没有活动草稿引用时返回 MANUAL_DRAFT_NOT_FOUND；引用悬空返回 WORK_STATE_INCONSISTENT。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|READ_OK|成功|与CURRENT同构的DocumentReadModel，document_type=MANUAL_DRAFT；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[DocumentReadModel](#documentreadmodel)（APP-DOC-QUERY-C01）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`MANUAL_DRAFT_NOT_FOUND`|需求存在且没有草稿或草稿占用；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`WORK_STATE_INCONSISTENT`|声称存在活动草稿但实体缺失，或有草稿但占用关系不一致；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.6 查询补充

|查询规则|确定定义|
|---|---|
|查询条件与匹配|本需求唯一草稿，返回前核对活动引用|
|条件标准化|仅校验本能力4.2实际接收的输入，不额外引入筛选或分页参数。|
|排序|单对象|
|分页|不分页；公共计算见SHR-PAGE|
|空结果|无草稿MANUAL_DRAFT_NOT_FOUND；有草稿但占用不一致WORK_STATE_INCONSISTENT|
|数据来源|OBJ-DOC|


本能力若返回列表与总数，二者采用同一读取快照；复合结果中的对象与派生字段必须来自一致读取。关联异常按4.3及4.4处理，不在查询中修复。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/documents/queries.py|get_manual_draft|APP-DOC-QUERY-C02|
|backend/app/documents/contracts.py|get_manual_draft_input / get_manual_draft_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-rev-query-c01"></a>
### APP-REV-QUERY-C01 查询版本列表

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-REV-QUERY-C01 查询版本列表|
|处理目标|查询版本列表的完整应用结果|
|主要对象或过程|OBJ-REV；关联和来源按4.6。|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|page|PositiveInt|调用参数；默认为1|否|否|1～100000；仅十进制正整数，不带前导零、符号、小数或空白；缺失：1；1（未传时）|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验本能力4.2列出的ID、筛选及分页输入；数据变化：无|SHR-PAGE；SHR-SERIALIZE|合法→P02；否则INVALID_INPUT|
|P02；输入合法|调用只读Repository取得一致读取结果，组装本能力读取模型；数据变化：无|INF-READ|成功→READ_OK；单对象不存在→NOT_FOUND；存储失败→STORAGE_UNAVAILABLE|


**入口绑定的业务约束**

- 排序 version_no DESC、id DESC，每页 20 条；没有版本时返回空列表。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|READ_OK|成功|id、requirement_id、version_no、revision_type、description、source_content_version、created_at；不返回正文；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

|字段路径|类型或定义引用|含义|出现条件及可空性|确定限制|
|---|---|---|---|---|
|items|[RevisionSummary[]](#revisionsummary)（APP-REV-QUERY-C01）|版本列表|始终存在；不可为null|—|


data 同时含 page、page_size、total、total_pages，均为整数且不可空；值由 SHR-PAGE 与本次同快照查询确定。

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.6 查询补充

|查询规则|确定定义|
|---|---|
|查询条件与匹配|仅本需求|
|条件标准化|仅校验本能力4.2实际接收的输入，不额外引入筛选或分页参数。|
|排序|version_no DESC，id DESC（API I24已明确）。|
|分页|固定20条；公共计算见SHR-PAGE|
|空结果|无版本READ_OK空数组|
|数据来源|OBJ-REV|


本能力若返回列表与总数，二者采用同一读取快照；复合结果中的对象与派生字段必须来自一致读取。关联异常按4.3及4.4处理，不在查询中修复。

<a id="revisionsummary"></a>
**读取模型：RevisionSummary**

|字段|类型或定义引用|出现条件及可空性|数据来源、计算或转换|
|---|---|---|---|
|id|Int|每个元素必有；不可为null|OBJ-REV.id直接投影；正整数|
|requirement_id|Int|每个元素必有；不可为null|OBJ-REV.requirement_id直接投影；正整数|
|version_no|Int|每个元素必有；不可为null|OBJ-REV.version_no直接投影；正整数|
|revision_type|Text|每个元素必有；不可为null|OBJ-REV.revision_type直接投影；BASELINE：初始化基线且 version_no=1；MANUAL：手动版本|
|description|Text|每个元素必有；可为null|OBJ-REV.description直接投影；可为 null|
|source_content_version|Int|每个元素必有；不可为null|OBJ-REV.source_content_version直接投影；正整数|
|created_at|UtcTime|每个元素必有；不可为null|OBJ-REV.created_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|


#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/revisions/queries.py|list_revisions|APP-REV-QUERY-C01|
|backend/app/revisions/contracts.py|list_revisions_input / list_revisions_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-rev-query-c02"></a>
### APP-REV-QUERY-C02 读取版本快照

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-REV-QUERY-C02 读取版本快照|
|处理目标|读取版本快照的完整应用结果|
|主要对象或过程|OBJ-REV；关联和来源按4.6。|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|revision_id|ID|调用参数；版本身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验本能力4.2列出的ID、筛选及分页输入；数据变化：无|SHR-PAGE；SHR-SERIALIZE|合法→P02；否则INVALID_INPUT|
|P02；输入合法|调用只读Repository取得一致读取结果，组装本能力读取模型；数据变化：无|INF-READ|成功→READ_OK；单对象不存在→NOT_FOUND；存储失败→STORAGE_UNAVAILABLE|


**入口绑定的业务约束**

- markdown_snapshot 输出为 markdown_content，block_state_snapshot_json 输出为 block_state_json 对象；读取历史快照不混入当前正文或当前评论。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|READ_OK|成功|Revision字段；markdown_snapshot映射markdown_content，block_state_snapshot_json映射block_state_json对象；不含当前评论或当前正文；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[RevisionReadModel](#revisionreadmodel)（APP-REV-QUERY-C02）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|版本记录不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.6 查询补充

|查询规则|确定定义|
|---|---|
|查询条件与匹配|按Revision id|
|条件标准化|仅校验本能力4.2实际接收的输入，不额外引入筛选或分页参数。|
|排序|单对象|
|分页|不分页；公共计算见SHR-PAGE|
|空结果|不存在NOT_FOUND|
|数据来源|OBJ-REV|


本能力若返回列表与总数，二者采用同一读取快照；复合结果中的对象与派生字段必须来自一致读取。关联异常按4.3及4.4处理，不在查询中修复。

<a id="revisionreadmodel"></a>
**读取模型：RevisionReadModel**

完整包含 [RevisionSummary](#revisionsummary) 的全部7个字段，再增加 markdown_content: Text（不可空，来自OBJ-REV.markdown_snapshot）、block_state_json: [BlockState](#shr-block)（不可空，来自OBJ-REV.block_state_snapshot_json）。不返回当前评论。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/revisions/queries.py|get_revision|APP-REV-QUERY-C02|
|backend/app/revisions/contracts.py|get_revision_input / get_revision_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-comment-query-c01"></a>
### APP-COMMENT-QUERY-C01 查询评论列表

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-COMMENT-QUERY-C01 查询评论列表|
|处理目标|查询评论列表的完整应用结果|
|主要对象或过程|OBJ-COMMENT；关联和来源按4.6。|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|page|PositiveInt|调用参数；默认为1|否|否|1～100000；仅十进制正整数，不带前导零、符号、小数或空白；缺失：1；1（未传时）|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验本能力4.2列出的ID、筛选及分页输入；数据变化：无|SHR-PAGE；SHR-SERIALIZE|合法→P02；否则INVALID_INPUT|
|P02；输入合法|调用只读Repository取得一致读取结果，组装本能力读取模型；数据变化：无|INF-READ|成功→READ_OK；单对象不存在→NOT_FOUND；存储失败→STORAGE_UNAVAILABLE|


**入口绑定的业务约束**

- 仅返回 deleted_at=null 的评论，无状态筛选；排序 created_at ASC、id ASC，每页 20 条。

- location 是对当前正文的只读定位结果；失败时 block_id/start_offset/end_offset=null，不更新持久化 anchor_status。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|READ_OK|成功|未删除Comment字段；anchor_ref_json映射anchor_ref；每条可定位信息由SHR-ANCHOR只读计算；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

|字段路径|类型或定义引用|含义|出现条件及可空性|确定限制|
|---|---|---|---|---|
|items|[CommentListItem[]](#commentlistitem)（APP-COMMENT-QUERY-C01）|未删除评论|始终存在；不可为null|—|


data 同时含 page、page_size、total、total_pages，均为整数且不可空；值由 SHR-PAGE 与本次同快照查询确定。

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.6 查询补充

|查询规则|确定定义|
|---|---|
|查询条件与匹配|requirement_id相等且deleted_at IS NULL；无状态筛选定义|
|条件标准化|仅校验本能力4.2实际接收的输入，不额外引入筛选或分页参数。|
|排序|created_at ASC,id ASC|
|分页|固定20条；公共计算见SHR-PAGE|
|空结果|无评论READ_OK空数组|
|数据来源|OBJ-COMMENT|


本能力若返回列表与总数，二者采用同一读取快照；复合结果中的对象与派生字段必须来自一致读取。关联异常按4.3及4.4处理，不在查询中修复。

<a id="commentlistitem"></a>
**读取模型：CommentListItem**

完整包含 [CommentReadModel](#commentreadmodel) 的全部字段，再增加不可空 location 对象：status 为 ATTACHED／ORPHANED；block_id、start_offset、end_offset 均必有且允许null。ATTACHED时block_id为原区块；SELECTION偏移为半开区间[start_offset,end_offset)，BLOCK偏移为空；ORPHANED三项为空。读取时以当前快照计算location，可以与持久化anchor_status不同；偏移单位及文本投影按[共同锚点规则](#sync-be-11)。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/comments/queries.py|list_comments|APP-COMMENT-QUERY-C01|
|backend/app/comments/contracts.py|list_comments_input / list_comments_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-comment-query-c02"></a>
### APP-COMMENT-QUERY-C02 读取评论详情

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-COMMENT-QUERY-C02 读取评论详情|
|处理目标|读取评论详情的完整应用结果|
|主要对象或过程|OBJ-COMMENT；关联和来源按4.6。|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|comment_id|ID|调用参数；评论身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验本能力4.2列出的ID、筛选及分页输入；数据变化：无|SHR-PAGE；SHR-SERIALIZE|合法→P02；否则INVALID_INPUT|
|P02；输入合法|调用只读Repository取得一致读取结果，组装本能力读取模型；数据变化：无|INF-READ|成功→READ_OK；单对象不存在→NOT_FOUND；存储失败→STORAGE_UNAVAILABLE|


**入口绑定的业务约束**

- 允许读取已软删除评论，deleted_at 非空表示软删除；记录不存在才返回 NOT_FOUND。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|READ_OK|成功|Comment字段含deleted_at，anchor_ref解析为对象；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[CommentReadModel](#commentreadmodel)（APP-COMMENT-QUERY-C02）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|评论 ID 不存在；软删除本身不触发此错误；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.6 查询补充

|查询规则|确定定义|
|---|---|
|查询条件与匹配|按ID；允许读已软删除记录|
|条件标准化|仅校验本能力4.2实际接收的输入，不额外引入筛选或分页参数。|
|排序|单对象|
|分页|不分页；公共计算见SHR-PAGE|
|空结果|不存在NOT_FOUND|
|数据来源|OBJ-COMMENT|


本能力若返回列表与总数，二者采用同一读取快照；复合结果中的对象与派生字段必须来自一致读取。关联异常按4.3及4.4处理，不在查询中修复。

<a id="commentreadmodel"></a>
**读取模型：CommentReadModel**

|字段|类型或定义引用|出现条件及可空性|数据来源、计算或转换|
|---|---|---|---|
|id|Int|始终存在；不可为null|OBJ-COMMENT.id直接投影；正整数|
|requirement_id|Int|始终存在；不可为null|OBJ-COMMENT.requirement_id直接投影；正整数|
|content|Text|始终存在；不可为null|OBJ-COMMENT.content直接投影；纯文本，标准化后 1～2000 个码点，可换行|
|anchor_type|Text|始终存在；不可为null|OBJ-COMMENT.anchor_type直接投影；BLOCK / SELECTION|
|block_id|Int|始终存在；不可为null|OBJ-COMMENT.block_id直接投影；正整数|
|anchor_ref|[AnchorRef](#shr-anchor)|始终存在；不可为null|OBJ-COMMENT.anchor_ref_json 解码；按 anchor_type 选择对应字段；由 anchor_ref_json 转为对象|
|anchor_status|Text|始终存在；不可为null|OBJ-COMMENT.anchor_status直接投影；ATTACHED / ORPHANED|
|status|Text|始终存在；不可为null|OBJ-COMMENT.status直接投影；OPEN / RESOLVED|
|resolved_at|UtcTime|始终存在；可为null|OBJ-COMMENT.resolved_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|deleted_at|UtcTime|始终存在；可为null|OBJ-COMMENT.deleted_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|created_at|UtcTime|始终存在；不可为null|OBJ-COMMENT.created_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|updated_at|UtcTime|始终存在；不可为null|OBJ-COMMENT.updated_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|


#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/comments/queries.py|get_comment|APP-COMMENT-QUERY-C02|
|backend/app/comments/contracts.py|get_comment_input / get_comment_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-comment-query-c03"></a>
### APP-COMMENT-QUERY-C03 读取全文评论索引

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-COMMENT-QUERY-C03 读取全文评论索引|
|处理目标|给出同一CURRENT快照下全文未删除评论总数、未解决数、区块标记及跨页定位索引|
|主要对象或过程|OBJ-REQ、OBJ-DOC、OBJ-COMMENT；只读，不修复持久锚点|
|完成方式|同步完成；不分页、不截断，不返回正文或完整评论内容|

<a id="sync-be-23"></a>

本能力与I37经D-004批准新增；原I01—I36编号及I27/I28职责不变。

#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991的整数；不接受REQ展示编号；缺失拒绝|

#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验requirement_id；数据变化：无|SHR-ID|合法→P02；否则INVALID_INPUT|
|P02；输入合法|同一读事务检查需求，取得唯一CURRENT及完整未删除评论集合；数据变化：无|INF-READ、INF-DOC-REP、INF-COMMENT-REP|不存在→NOT_FOUND；CURRENT关系不一致→WORK_STATE_INCONSISTENT；合法→P03|
|P03；快照一致|计算各评论当前location、全文统计和OPEN+ATTACHED区块标记；数据变化：无|SHR-ANCHOR、CommentIndexReadModel|成功→READ_OK；存储不可用→STORAGE_UNAVAILABLE；异常→INTERNAL_ERROR|

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|READ_OK|成功|CommentIndexReadModel完整对象；details=null|同一读取快照的索引和统计，不表示持久anchor_status已修正|

**成功载荷 data**

[CommentIndexReadModel](#commentindexreadmodel)。

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|INVALID_INPUT|需求身份不合法；data=null，details按SHR-RESULT；不执行查询|
|NOT_FOUND|需求不存在；data=null，details=null|
|WORK_STATE_INCONSISTENT|CURRENT关系不一致；不猜造正文或修复状态|
|STORAGE_UNAVAILABLE|存储不可用；不返回假空索引|
|INTERNAL_ERROR|未预期异常、核心结构损坏或转换失败；仅返回安全错误|

#### 4.6 查询补充

|查询规则|确定定义|
|---|---|
|查询条件与匹配|指定需求全部deleted_at=null评论；包含OPEN与RESOLVED|
|条件标准化|只有requirement_id，不接收筛选或页码|
|排序|comments按created_at/id升序；blocks按CURRENT区块顺序；comment_ids保留对应comments顺序|
|分页|不分页，不截断，不返回meta.pagination|
|空结果|需求和CURRENT合法且无未删除评论时，计数0、两个数组均[]|
|数据来源|同一读事务的需求、CURRENT身份/版本、完整未删除评论和SHR-ANCHOR投影|

<a id="commentindexreadmodel"></a>
**读取模型：CommentIndexReadModel**

|字段|类型或定义引用|出现条件及可空性|数据来源、计算或转换|
|---|---|---|---|
|requirement_id|ID|始终存在；不可null|当前需求身份|
|document_id|ID|始终存在；不可null|本次CURRENT身份|
|content_version|PositiveInt|始终存在；不可null|本次CURRENT内容版本|
|total_count|Int|始终存在；不可null|全部未删除评论数量，非负|
|open_count|Int|始终存在；不可null|全部OPEN评论数量，包含当前不能定位者|
|blocks|array[object]|始终存在；不可null|仅有OPEN且location.status=ATTACHED评论的区块|
|blocks[].block_id|BlockId|每项必有；不可null|CURRENT内区块身份，不重复|
|blocks[].open_count|PositiveInt|每项必有；不可null|等于本项comment_ids长度|
|blocks[].comment_ids|array[ID]|每项必有；不可null|该区块当前可定位的OPEN评论ID|
|comments|array[object]|始终存在；不可null|完整未删除评论索引，不返回完整评论正文|
|comments[].id|ID|每项必有；不可null|评论身份，不重复|
|comments[].status|Text|每项必有；不可null|OPEN/RESOLVED|
|comments[].anchor_status|Text|每项必有；不可null|持久ATTACHED/ORPHANED，允许与当前location.status不同|
|comments[].location|object|每项必有；不可null|SHR-ANCHOR当前投影，字段见下三行|
|comments[].location.status|Text|每项必有；不可null|ATTACHED/ORPHANED|
|comments[].location.block_id|BlockId|每项必有；可null|ATTACHED为原块ID；ORPHANED为null|
|comments[].location.start_offset/end_offset|Int|每项必有；可null|ATTACHED选区为Unicode码点半开区间；BLOCK或ORPHANED为null|

所有统计从同一完整集合计算；读取不更新anchor_status、updated_at或其他业务状态。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/comments/queries.py|get_comment_index|一致快照查询|
|backend/app/comments/contracts.py|get_comment_index_input / get_comment_index_result / comment_index_model|应用输入及完整索引验证|
|backend/app/infrastructure/comment_repository.py|all_live|全部未删除评论及稳定顺序|

<a id="app-batch-query-c01"></a>
### APP-BATCH-QUERY-C01 读取建议批次

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-BATCH-QUERY-C01 读取建议批次|
|处理目标|读取建议批次的完整应用结果|
|主要对象或过程|OBJ-BATCH；关联和来源按4.6。|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|batch_id|ID|调用参数；批次身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验本能力4.2列出的ID、筛选及分页输入；数据变化：无|SHR-PAGE；SHR-SERIALIZE|合法→P02；否则INVALID_INPUT|
|P02；输入合法|调用只读Repository取得一致读取结果，组装本能力读取模型；数据变化：无|INF-READ|成功→READ_OK；单对象不存在→NOT_FOUND；存储失败→STORAGE_UNAVAILABLE|


**入口绑定的业务约束**

- 返回全部 suggestions，不分页；按 order_no ASC、id ASC 排列；counts 根据同一读取快照中的建议计算。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|READ_OK|成功|SuggestionBatch字段、全部Suggestion与counts；counts由此次读取的明细推导；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[SuggestionBatchReadModel](#suggestionbatchreadmodel)（APP-BATCH-QUERY-C01）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|批次不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.6 查询补充

|查询规则|确定定义|
|---|---|
|查询条件与匹配|按批次id；包含各状态明细|
|条件标准化|仅校验本能力4.2实际接收的输入，不额外引入筛选或分页参数。|
|排序|Suggestion.order_no ASC|
|分页|单批次及明细不分页；容量上限见[Q-06](#q-06)；公共计算见SHR-PAGE|
|空结果|不存在NOT_FOUND；空持久化批次是数据异常，不能伪报正常空批|
|数据来源|OBJ-BATCH|


本能力若返回列表与总数，二者采用同一读取快照；复合结果中的对象与派生字段必须来自一致读取。关联异常按4.3及4.4处理，不在查询中修复。

<a id="suggestionreadmodel"></a>
**读取模型：SuggestionReadModel**

|字段|类型或定义引用|出现条件及可空性|数据来源、计算或转换|
|---|---|---|---|
|id|Int|始终存在；不可为null|OBJ-BATCH.Suggestion.id直接投影；正整数|
|batch_id|Int|始终存在；不可为null|OBJ-BATCH.Suggestion.batch_id直接投影；正整数|
|order_no|Int|始终存在；不可为null|OBJ-BATCH.Suggestion.order_no直接投影；正整数|
|title|Text|始终存在；不可为null|OBJ-BATCH.Suggestion.title直接投影；—|
|explanation|Text|始终存在；不可为null|OBJ-BATCH.Suggestion.explanation直接投影；—|
|impact|Text|始终存在；可为null|OBJ-BATCH.Suggestion.impact直接投影；可为 null|
|patch_operation|Text|始终存在；不可为null|OBJ-BATCH.Suggestion.patch_operation直接投影；REPLACE_BLOCK / INSERT_BEFORE / INSERT_AFTER / DELETE_BLOCK / REPLACE_TABLE_ROW|
|target_ref|[TargetRef](#shr-patch)|始终存在；不可为null|OBJ-BATCH.Suggestion.target_ref_json 解码；由 target_ref_json 解码|
|selector|[TableRowSelector](#shr-patch)|始终存在；可为null|OBJ-BATCH.Suggestion.selector_json 解码；仅 REPLACE_TABLE_ROW 非空；由 selector_json 解码|
|original_content|Text|始终存在；不可为null|OBJ-BATCH.Suggestion.original_content直接投影；用于与基线直接比较|
|proposed_markdown|Text|始终存在；可为null|OBJ-BATCH.Suggestion.proposed_markdown直接投影；Block 替换/插入时非空；删除/行替换时 null|
|proposed_data|[TableRowData](#shr-patch)|始终存在；可为null|OBJ-BATCH.Suggestion.proposed_data_json 解码；仅 REPLACE_TABLE_ROW 非空；由 proposed_data_json 解码|
|user_edited_content|Text|始终存在；可为null|OBJ-BATCH.Suggestion.user_edited_content直接投影；仅 EDITED 时非空；其他决策清空|
|status|Text|始终存在；不可为null|OBJ-BATCH.Suggestion.status直接投影；PENDING / ACCEPTED / REJECTED / EDITED|
|validation_status|Text|始终存在；不可为null|OBJ-BATCH.Suggestion.validation_status直接投影；本模块公开编码 VALID / INVALID；按最新已执行的建议校验投影|
|validation_error|Text|始终存在；可为null|OBJ-BATCH.Suggestion.validation_error直接投影；INVALID 时为安全提示；VALID 时 null|
|created_at|UtcTime|始终存在；不可为null|OBJ-BATCH.Suggestion.created_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|decided_at|UtcTime|始终存在；可为null|OBJ-BATCH.Suggestion.decided_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|updated_at|UtcTime|始终存在；不可为null|OBJ-BATCH.Suggestion.updated_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|


<a id="suggestionbatchmetadata"></a>
**读取模型：SuggestionBatchMetadata**

|字段|类型或定义引用|出现条件及可空性|数据来源、计算或转换|
|---|---|---|---|
|id|Int|始终存在；不可为null|OBJ-BATCH.SuggestionBatch.id直接投影；正整数|
|requirement_id|Int|始终存在；不可为null|OBJ-BATCH.SuggestionBatch.requirement_id直接投影；正整数|
|guide_run_id|Int|始终存在；不可为null|OBJ-BATCH.SuggestionBatch.guide_run_id直接投影；正整数|
|source_type|Text|始终存在；不可为null|OBJ-BATCH.SuggestionBatch.source_type直接投影；USER_INSTRUCTION / REVIEW_RESULT / COMMENT|
|source_id|Int|始终存在；可为null|OBJ-BATCH.SuggestionBatch.source_id直接投影；USER_INSTRUCTION 时 null|
|title|Text|始终存在；不可为null|OBJ-BATCH.SuggestionBatch.title直接投影；—|
|summary|Text|始终存在；不可为null|OBJ-BATCH.SuggestionBatch.summary直接投影；—|
|status|Text|始终存在；不可为null|OBJ-BATCH.SuggestionBatch.status直接投影；PENDING / COMPLETED / DISCARDED|
|completion_result|Text|始终存在；可为null|OBJ-BATCH.SuggestionBatch.completion_result直接投影；COMPLETED 时 CHANGES_APPLIED / NO_CHANGE；其余 null|
|error_message|Text|始终存在；可为null|OBJ-BATCH.SuggestionBatch.error_message直接投影；无错误时 null；安全提示|
|base_content_version|Int|始终存在；不可为null|OBJ-BATCH.SuggestionBatch.base_content_version直接投影；正整数|
|applied_content_version|Int|始终存在；可为null|OBJ-BATCH.SuggestionBatch.applied_content_version直接投影；只有 CHANGES_APPLIED 时非空|
|created_at|UtcTime|始终存在；不可为null|OBJ-BATCH.SuggestionBatch.created_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|completed_at|UtcTime|始终存在；可为null|OBJ-BATCH.SuggestionBatch.completed_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|updated_at|UtcTime|始终存在；不可为null|OBJ-BATCH.SuggestionBatch.updated_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|


<a id="suggestionbatchreadmodel"></a>
**读取模型：SuggestionBatchReadModel**

完整包含 [SuggestionBatchMetadata](#suggestionbatchmetadata) 的全部15个字段，再增加 suggestions: [SuggestionReadModel](#suggestionreadmodel)[]（不可空、至少1项，按order_no ASC、id ASC返回全部建议，无分页）以及 counts: [SuggestionCounts](#suggestioncounts)（不可空）。批次、建议与计数来自同一读取。

<a id="suggestioncounts"></a>
**读取模型：SuggestionCounts**

|字段|类型|计算规则|
|---|---|---|
|total|非负整数／始终存在／不可空|该批次全部Suggestion数量；等于pending+accepted+rejected+edited|
|pending|非负整数／始终存在／不可空|同批次status=PENDING的Suggestion数量|
|accepted|非负整数／始终存在／不可空|同批次status=ACCEPTED的Suggestion数量|
|rejected|非负整数／始终存在／不可空|同批次status=REJECTED的Suggestion数量|
|edited|非负整数／始终存在／不可空|同批次status=EDITED的Suggestion数量|


#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/suggestions/queries.py|get_batch|APP-BATCH-QUERY-C01|
|backend/app/suggestions/contracts.py|get_batch_input / get_batch_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-guide-query-c01"></a>
### APP-GUIDE-QUERY-C01 读取运行状态

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-GUIDE-QUERY-C01 读取运行状态|
|处理目标|读取运行状态的完整应用结果|
|主要对象或过程|OBJ-GUIDE；关联和来源按4.6。|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|guide_run_id|ID|调用参数；运行身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验本能力4.2列出的ID、筛选及分页输入；数据变化：无|SHR-PAGE；SHR-SERIALIZE|合法→P02；否则INVALID_INPUT|
|P02；输入合法|调用只读Repository取得一致读取结果，组装本能力读取模型；数据变化：无|INF-READ|成功→READ_OK；单对象不存在→NOT_FOUND；存储失败→STORAGE_UNAVAILABLE|


**入口绑定的业务约束**

- 运行 FAILED/CANCELLED 是被查询资源的状态，读取成功仍为READ_OK；只有本次查询失败才返回 error。

- final_result 为本模块定义的安全摘要投影；完整可见检查说明/回答由 latest_assistant_message_id 指向的消息取得。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|READ_OK|成功|id、requirement_id、action_type、function_type、source_type/source_id、scope、status、current_step、安全final_result、suggestion_batch_id、最近助手消息id、安全错误、运行时间；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

[GuideRunReadModel](#guiderunreadmodel)（APP-GUIDE-QUERY-C01）

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|运行不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.6 查询补充

|查询规则|确定定义|
|---|---|
|查询条件与匹配|按Run id；不穿透LLMUse、Prompt和原始响应|
|条件标准化|仅校验本能力4.2实际接收的输入，不额外引入筛选或分页参数。|
|排序|单对象|
|分页|不分页；公共计算见SHR-PAGE|
|空结果|不存在NOT_FOUND|
|数据来源|OBJ-GUIDE|


本能力若返回列表与总数，二者采用同一读取快照；复合结果中的对象与派生字段必须来自一致读取。关联异常按4.3及4.4处理，不在查询中修复。

<a id="guiderunaccepted"></a>
**读取模型：GuideRunAccepted**

|字段|类型或定义引用|出现条件及可空性|数据来源、计算或转换|
|---|---|---|---|
|id|Int|始终存在；不可为null|OBJ-GUIDE.id直接投影；正整数|
|requirement_id|Int|始终存在；不可为null|OBJ-GUIDE.requirement_id直接投影；正整数|
|status|Text|始终存在；不可为null|OBJ-GUIDE.status直接投影；RUNNING / WAITING_USER / COMPLETED / FAILED / CANCELLED|
|current_step|Text|始终存在；不可为null|OBJ-GUIDE.current_step直接投影；本模块统一公开编码：PREPARING / CALLING_MODEL / VALIDATING / PERSISTING / WAITING_USER / FINISHED|


<a id="guiderunreadmodel"></a>
**读取模型：GuideRunReadModel**

|字段|类型或定义引用|出现条件及可空性|数据来源、计算或转换|
|---|---|---|---|
|id|Int|始终存在；不可为null|OBJ-GUIDE.id直接投影；正整数|
|requirement_id|Int|始终存在；不可为null|OBJ-GUIDE.requirement_id直接投影；正整数|
|action_type|Text|始终存在；不可为null|OBJ-GUIDE.action_type直接投影；INITIALIZE / ASK / REVIEW / MODIFY|
|function_type|Text|始终存在；不可为null|OBJ-GUIDE.function_type直接投影；INITIALIZE_REQUIREMENT / ANSWER_REQUIREMENT / REVIEW_REQUIREMENT / MODIFY_REQUIREMENT / MODIFY_FROM_REVIEW / MODIFY_FROM_COMMENT|
|source_type|Text|始终存在；不可为null|OBJ-GUIDE.source_type直接投影；USER_INSTRUCTION / REVIEW_RESULT / COMMENT|
|source_id|Int|始终存在；可为null|OBJ-GUIDE.source_id直接投影；USER_INSTRUCTION 时 null；其他引用 REVIEW Run 或 Comment|
|scope|object|始终存在；不可为null|本能力读取规则；处理范围；—|
|scope.scope_type|Text|始终存在；不可为null|本能力读取规则；范围类型；DOCUMENT / SECTION / BLOCK / SELECTION|
|scope.scope_ref|ScopeRef（APP-GUIDE-CMD-C01）|始终存在；可为null|本能力读取规则；范围引用；DOCUMENT 时 null；SECTION/BLOCK 仅 block_id；SELECTION 含选区字段|
|status|Text|始终存在；不可为null|OBJ-GUIDE.status直接投影；RUNNING / WAITING_USER / COMPLETED / FAILED / CANCELLED|
|current_step|Text|始终存在；不可为null|OBJ-GUIDE.current_step直接投影；本模块统一公开编码：PREPARING / CALLING_MODEL / VALIDATING / PERSISTING / WAITING_USER / FINISHED|
|final_result|object|始终存在；可为null|本能力读取规则；安全结果摘要；仅 COMPLETED 时非空；公开投影，不直接返回模型结果 JSON|
|final_result.summary|Text|父对象非 null 时必有；不可为null|本能力读取规则；结果摘要；仅经验证的可读结果摘要|
|final_result.assistant_message_id|Int|父对象非 null 时必有；可为null|本能力读取规则；结果助手消息 ID；无消息时 null|
|final_result.current_document_version|Int|父对象非 null 时必有；可为null|本能力读取规则；本次写入的正文版本；本次未更新正文时 null，不代表当前最新版本|
|final_result.suggestion_batch_id|Int|父对象非 null 时必有；可为null|本能力读取规则；本次生成的建议批次 ID；未生成批次时 null|
|suggestion_batch_id|Int|始终存在；可为null|本能力读取规则；生成的建议批次 ID；无批次时 null|
|latest_assistant_message_id|Int|始终存在；可为null|本能力读取规则；最近助手消息 ID；仅本运行的助手消息；无则 null|
|error_code|Text|始终存在；可为null|OBJ-GUIDE.error_code直接投影；仅 FAILED 非空；采用已登记的安全任务错误码|
|error_message|Text|始终存在；可为null|OBJ-GUIDE.error_message直接投影；仅 FAILED 非空；不返回 Provider 原始错误、密钥或堆栈|
|cancel_reason|Text|始终存在；可为null|OBJ-GUIDE.cancel_reason直接投影；仅 CANCELLED 非空，例如 USER_REQUESTED|
|retry_of_guide_run_id|Int|始终存在；可为null|OBJ-GUIDE.retry_of_guide_run_id直接投影；非重试运行时 null|
|created_at|UtcTime|始终存在；不可为null|OBJ-GUIDE.created_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|started_at|UtcTime|始终存在；可为null|OBJ-GUIDE.started_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|waiting_user_at|UtcTime|始终存在；可为null|OBJ-GUIDE.waiting_user_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|ended_at|UtcTime|始终存在；可为null|OBJ-GUIDE.ended_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|updated_at|UtcTime|始终存在；不可为null|OBJ-GUIDE.updated_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|


#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/guide/queries.py|get_guide_run|APP-GUIDE-QUERY-C01|
|backend/app/guide/contracts.py|get_guide_run_input / get_guide_run_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-guide-query-c02"></a>
### APP-GUIDE-QUERY-C02 查询运行历史

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-GUIDE-QUERY-C02 查询运行历史|
|处理目标|查询运行历史的完整应用结果|
|主要对象或过程|OBJ-GUIDE；关联和来源按4.6。|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|status|List[GuideStatus]|调用参数；多值|否|否|RUNNING / WAITING_USER / COMPLETED / FAILED / CANCELLED；重复参数名传多值，空值拒绝，重复合法值去重；缺失：不限制该项；解析后的数组；未传为 []；能力去重并验证业务枚举|
|action_type|List[Action]|调用参数；多值|否|否|INITIALIZE / ASK / REVIEW / MODIFY；历史筛选不受当前需求动作许可限制；重复参数名传多值，空值拒绝，重复合法值去重；缺失：不限制该项；解析后的数组；未传为 []；能力去重并验证业务枚举|
|page|PositiveInt|调用参数；默认为1|否|否|1～100000；仅十进制正整数，不带前导零、符号、小数或空白；缺失：1；1（未传时）|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验本能力4.2列出的ID、筛选及分页输入；数据变化：无|SHR-PAGE；SHR-SERIALIZE|合法→P02；否则INVALID_INPUT|
|P02；输入合法|调用只读Repository取得一致读取结果，组装本能力读取模型；数据变化：无|INF-READ|成功→READ_OK；单对象不存在→NOT_FOUND；存储失败→STORAGE_UNAVAILABLE|


**入口绑定的业务约束**

- status 与 action_type 同字段多值“或”，不同字段“且”；排序 created_at DESC、id DESC，每页 20 条。历史摘要不含 final_result。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|READ_OK|成功|运行摘要字段，同详情但排除完整final_result与所有LLMUse；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

|字段路径|类型或定义引用|含义|出现条件及可空性|确定限制|
|---|---|---|---|---|
|items|[GuideRunSummary[]](#guiderunsummary)（APP-GUIDE-QUERY-C02）|运行历史|始终存在；不可为null|—|


data 同时含 page、page_size、total、total_pages，均为整数且不可空；值由 SHR-PAGE 与本次同快照查询确定。

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.6 查询补充

|查询规则|确定定义|
|---|---|
|查询条件与匹配|同条件多值OR、不同条件AND；只读本需求|
|条件标准化|文本先执行SHR-TEXT；未知枚举拒绝；缺省页码为1；按单项查询定义处理缺省筛选|
|排序|created_at DESC,id DESC|
|分页|固定20条；公共计算见SHR-PAGE|
|空结果|READ_OK空数组|
|数据来源|OBJ-GUIDE|


本能力若返回列表与总数，二者采用同一读取快照；复合结果中的对象与派生字段必须来自一致读取。关联异常按4.3及4.4处理，不在查询中修复。

<a id="guiderunsummary"></a>
**读取模型：GuideRunSummary**

完整包含 [GuideRunReadModel](#guiderunreadmodel) 的全部字段，但不包含 final_result；同样排除全部 LLMUse 与原始模型数据。其余字段含义、空值及来源不变。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/guide/queries.py|list_guide_runs|APP-GUIDE-QUERY-C02|
|backend/app/guide/contracts.py|list_guide_runs_input / list_guide_runs_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-guide-query-c03"></a>
### APP-GUIDE-QUERY-C03 读取模型业务上下文

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-GUIDE-QUERY-C03 读取模型业务上下文|
|处理目标|读取模型业务上下文的完整应用结果|
|主要对象或过程|OBJ-GUIDE；关联和来源按4.6。|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|guide_run_id|ID|可信内部调用；内部运行身份|是|否|必填，无默认；内部运行身份|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验本能力4.2列出的ID、筛选及分页输入；数据变化：无|SHR-PAGE；SHR-SERIALIZE|合法→P02；否则INVALID_INPUT|
|P02；输入合法|调用只读Repository取得一致读取结果，组装本能力读取模型；数据变化：无|INF-READ|成功→READ_OK；单对象不存在→NOT_FOUND；存储失败→STORAGE_UNAVAILABLE|


#### 4.4 结果与完成范围

本能力完整内部data/details按本节结果表及[内部结果契约](#sync-be-22)；成功details=null，失败data=null，不以空对象代替正式载荷。

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|READ_OK|成功|CURRENT快照、授权范围、所需模板/正式用户消息/当前来源；携带实际读取清单|同步完成；结果中的提交、无变化或失败范围以4.4为准。|



**成功载荷 data**

|字段或结构|类型与出现条件|来源及约束|
|---|---|---|
|`{run,requirement,current_document,template,scope,allowed_targets,user_input,history,source,read_manifest}`|成功时完整返回的对象；details=null|各成员采用冻结完整输入结构；具体字段、可空条件按第4.7节资源与Context构造，不允许任意JSON对象替代。|

#### 4.6 查询补充

|查询规则|确定定义|
|---|---|
|查询条件与匹配|只按冻结Function的ContextTemplate；排除人工草稿、未应用建议、历史Revision正文、无关评论、原始调用和未选推荐；精确预算及历史条数见[Q-02](#q-02)|
|条件标准化|仅校验本能力4.2实际接收的输入，不额外引入筛选或分页参数。|
|排序|正文按blocks数组；消息按sequence_no ASC|
|分页|内部确定范围，不使用前端分页；范围与预算见APP-GUIDE-ORCH-C01／4.7、[Q-02](#q-02)。|
|空结果|必要上下文缺失CONFIG_INVALID或SOURCE_INVALID|
|数据来源|OBJ-REQ；OBJ-DOC；OBJ-GUIDE；OBJ-MSG；OBJ-COMMENT|


本能力若返回列表与总数，二者采用同一读取快照；复合结果中的对象与派生字段必须来自一致读取。关联异常按4.3及4.4处理，不在查询中修复。

读取产物包含本节4.4的完整内部上下文；成员结构采用冻结输入Schema及[Scope授权规则](#sync-be-10)，User封装、读取清单和预算见[上下文规则](#sync-be-17)，正式计数见[实用预算控制](#sync-be-19)。完整资源已提供，不以任意JSON或缺省对象替代；读取权限不扩大Allowed Targets。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/guide/model_context.py|get_model_context|APP-GUIDE-QUERY-C03实际实现；queries.py重新导出入口|
|backend/app/guide/contracts.py|get_model_context_input / get_model_context_result|应用输入输出；不含HTTP或ORM对象|


<a id="app-msg-query-c01"></a>
### APP-MSG-QUERY-C01 查询对话消息

#### 4.1 能力说明

|内容|确定定义|
|---|---|
|能力引用与名称|APP-MSG-QUERY-C01 查询对话消息|
|处理目标|查询对话消息的完整应用结果|
|主要对象或过程|OBJ-MSG；关联和来源按4.6。|
|完成方式|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


#### 4.2 输入与来源

|输入项|类型或结构引用|来源与用途|必须提供|可为null|缺失、默认及校验规则|
|---|---|---|---|---|---|
|requirement_id|ID|调用参数；需求内部身份|是|否|1～9007199254740991 的整数；缺失：拒绝；必填值|
|before_sequence_no|PositiveInt|调用参数；排他上界|否|是|排他上界；十进制正整数，最大 9007199254740991；缺失：读取最新 20 条；解析后正整数；未传为 null|


#### 4.3 处理过程

|步骤与进入条件|处理与数据变化|输入来源、调用或规则引用|后续步骤或结果|
|---|---|---|---|
|P01；开始|校验本能力4.2列出的ID、筛选及分页输入；数据变化：无|SHR-PAGE；SHR-SERIALIZE|合法→P02；否则INVALID_INPUT|
|P02；输入合法|调用只读Repository取得一致读取结果，组装本能力读取模型；数据变化：无|INF-READ|成功→READ_OK；单对象不存在→NOT_FOUND；存储失败→STORAGE_UNAVAILABLE|


**入口绑定的业务约束**

- 无游标读取最新 20 条；有游标读取 sequence_no 小于游标的最近 20 条，再按 sequence_no ASC 返回。

- has_more=true 时 next_cursor 为本页最小 sequence_no；无更早记录时 next_cursor=null。消息为空时 items=[]、has_more=false、next_cursor=null。

- 历史结构化内容损坏时仍返回可读 content，将 structured_content 和 card_state 置 null，禁止提交该损坏卡片组；不返回原始损坏 JSON。

#### 4.4 结果与完成范围

|结果名称或编码|含义或公共定义引用|返回数据|调用方可确认的完成范围|
|---|---|---|---|
|READ_OK|成功|消息字段及解析后的结构化内容、卡片推导状态；无总数；损坏结构只用content降级并禁用卡片；完整成功载荷见本节。|同步完成；结果中的提交、无变化或失败范围以4.4为准。|


**成功载荷 data**

|字段路径|类型或定义引用|含义|出现条件及可空性|确定限制|
|---|---|---|---|---|
|items|[MessageReadModel[]](#messagereadmodel)（APP-MSG-QUERY-C01）|对话消息|始终存在；不可为null|—|


data 同时含 page_size: Int（不可空，固定20）、has_more: Bool（不可空）和 next_cursor: PositiveInt 或 null。只有仍有更早消息时 next_cursor 才为本批最小 sequence_no；无更早消息或空列表为 null。

**拒绝与已知失败**

|结果编码|本能力条件与失败后果|
|---|---|
|`INVALID_INPUT`|参数未满足请求定义；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`NOT_FOUND`|需求不存在；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`STORAGE_UNAVAILABLE`|读取、写入或事务提交未能完成；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|
|`INTERNAL_ERROR`|未预期异常、结果转换失败或未登记结果编码；按SHR-RESULT返回，附加数据变化仅限4.5明确例外。|


#### 4.6 查询补充

|查询规则|确定定义|
|---|---|
|查询条件与匹配|无游标取最新20条；有游标取sequence_no小于游标的最近20条，再升序返回|
|条件标准化|仅校验本能力4.2实际接收的输入，不额外引入筛选或分页参数。|
|排序|sequence_no ASC（截取窗口时DESC）|
|分页|排他游标固定20条；has_more通过更早记录存在性判断；仅has_more=true时next_cursor为本批最小sequence_no，否则null；不提供total。|
|空结果|无消息READ_OK空数组、has_more=false、next_cursor=null|
|数据来源|OBJ-MSG|


本能力若返回列表与总数，二者采用同一读取快照；复合结果中的对象与派生字段必须来自一致读取。关联异常按4.3及4.4处理，不在查询中修复。

<a id="messagereadmodel"></a>
**读取模型：MessageReadModel**

|字段|类型或定义引用|出现条件及可空性|数据来源、计算或转换|
|---|---|---|---|
|id|Int|每个元素必有；不可为null|OBJ-MSG.id直接投影；正整数|
|requirement_id|Int|每个元素必有；不可为null|OBJ-MSG.requirement_id直接投影；正整数|
|guide_run_id|Int|每个元素必有；可为null|OBJ-MSG.guide_run_id直接投影；尚无运行关联时 null|
|sequence_no|Int|每个元素必有；不可为null|OBJ-MSG.sequence_no直接投影；正整数|
|role|Text|每个元素必有；不可为null|OBJ-MSG.role直接投影；USER / ASSISTANT|
|content|Text|每个元素必有；不可为null|OBJ-MSG.content直接投影；结构化内容无效时使用本字段展示|
|message_type|Text|每个元素必有；不可为null|OBJ-MSG.message_type直接投影；TEXT / INTERACTION_CARDS / CARD_RESPONSE|
|structured_content|[卡片组或回答](#shr-cards)|每个元素必有；可为null|OBJ-MSG.structured_content_json 解码；损坏结构为null，content保留；由 structured_content_json 解码并按公开协议投影；TEXT 或历史结构损坏时 null|
|reply_to_message_id|Int|每个元素必有；可为null|OBJ-MSG.reply_to_message_id直接投影；仅 CARD_RESPONSE 非空|
|created_at|UtcTime|每个元素必有；不可为null|OBJ-MSG.created_at直接投影；UTC时间值；传输序列化见API-COM-RESPONSE|
|card_state|Text|每个元素必有；可为null|本能力读取规则；卡片组状态；仅有效卡片组为 AVAILABLE / ANSWERED / EXPIRED；TEXT、响应消息或损坏结构为 null|


card_state的推导按SHR-CARDS与APP-GUIDE-CMD-C06：已有正式CARD_RESPONSE为ANSWERED；当前仍可提交的唯一有效组为AVAILABLE；状态、占用或后续输入使其失效为EXPIRED。TEXT、回答消息及损坏结构返回null。整组可用性和过期细则以该命令过程为准，不由前端猜测。

#### 4.8 实现定位

|所属模块或关键路径|关键入口或资源|承载内容|
|---|---|---|
|backend/app/messages/queries.py|list_messages|APP-MSG-QUERY-C01|
|backend/app/messages/contracts.py|list_messages_input / list_messages_result|应用输入输出；不含HTTP或ORM对象|


<a id="api-com"></a>

## 6. 接口与其他入口

### 6.1 HTTP公共契约

**公共契约：API-COM；适用范围：BND-REQ/DOC/REV/COMMENT/GUIDE/BATCH/MSG-API 的 I01—I37。**

单用户、无认证，不构造未经定义的操作者身份。所有路径以`/api/v1`开头，资源名复数kebab-case，JSON字段snake_case，无尾斜杠；requirement_id是内部数字身份。媒体类型application/json。前端请求格式或业务失败均按以下规则处理。

<a id="api-com-request"></a>
**API-COM-REQUEST 公共请求约定**

|项目|定义|
|---|---|
|请求分组|每个参数的Path、Query、Header或Body位置由6.2明确。未列出的查询参数和 JSON 字段拒绝，不能把常规浏览器/HTTP 请求头一并当成未知参数拒绝。|
|JSON|有请求体时使用 application/json，根必须是对象；每层按字段表校验，拒绝重复 JSON 键、未知字段、错误类型；整数不接受 boolean、字符串或小数。无请求体的接口不要求 Content-Type。|
|格式错误|不合法 JSON、字段类型错误均按 INVALID_INPUT 映射；无法识别的方法/路径属于 HTTP 路由层，不作为某个应用能力的业务错误。|
|身份和版本|ID、区块 ID、内容版本、消息序号统一为 1～9007199254740991 的 JSON 整数；路径/查询传输使用不带前导零的十进制正整数文本。requirement_no 不能代替 requirement_id。|
|页码|page 默认 1，范围 1～100000，每页固定 20；拒绝 0、01、+1、1.0、1e2、空值和带空白的值。超过实际页数但未超过上限仍成功返回空列表。|
|数组|Query 数组通过重复参数名传递；合法值去重并保留首次顺序。空值、逗号拼接、JSON 数组文本不接受；省略表示无筛选。JSON 请求体中的数组使用真正 JSON 数组。|
|单值重复|单值 Query 参数重复出现时拒绝，即使值相同；Path 参数由路由唯一绑定。|
|缺省与 null|仅标明可空的字段接受 null；未传的 PATCH 字段保持原值，不能按 null 覆盖。URL 文本 null 不等于 JSON null。|
|枚举|英文编码区分大小写，不自动去除空白。需求类型 NEW/CHANGE；初始化模式 IDEATION/DESIGN；其他枚举按字段定义。|
|字符计数|接口长度按 Unicode 码点计，不按 UTF-8 字节或 UTF-16 单元计。普通文本先把 CRLF/CR 统一为 LF 再去首尾 Unicode 空白；不做 NFC/NFKC 或全半角转换。Markdown、原文快照和定位片段不 trim、不做 Unicode 归一化，避免破坏原文匹配。|
|已定文本上限|title 1～20；initial_idea、instruction 1～10000；Comment.content 1～2000；keyword 标准化后 0～100；Revision.description 0～1000。title/keyword 不允许内部换行，其余允许。|
|大文本|完整HTTP请求路径、查询、头与Body应用可见字节合计最多8MiB；Markdown1000000码点、BlockState4MiB/10000块、单建议100000码点/批次100项；不截断，小字段上限不变|
|请求体缺省|无 Body 参数的接口使用空请求体；有 Body 参数时必须提交 JSON 对象，即使全部字段为可选也不能省略必需的业务内容。I04 至少提供一个可修改字段。|
|幂等头|仅标有 Idempotency-Key 的接口要求该头；大小写按 HTTP 头名规则处理；重复提供多个值拒绝；具体语义见 API-COM-IDEMPOTENCY。|


<a id="api-com-response"></a>
**API-COM-RESPONSE 公共响应约定**

|项目|定义|
|---|---|
|外层|所有正常生成的 API JSON 响应包含 success、data、error、meta。成功 success=true、error=null；失败 success=false、data=null。|
|请求编号|meta.request_id 为服务端生成的小写 UUID v4 字符串，含连字符；同一次请求日志使用同一值；幂等重放产生本次请求的新 request_id。|
|结果编码|READ_OK、CREATED 等为应用结果分支标识，用于决定状态码和响应内容，不自动新增到响应根对象；错误码放 error.code。|
|日期时间|UTC 字符串 YYYY-MM-DDTHH:mm:ss.SSSZ，精度毫秒；可空时间返回 null，不返回空字符串。|
|JSON 对象|数据库 *_json 列先解码，再按响应字段白名单投影；不返回转义 JSON 字符串，不穿透 ORM 对象。|
|页码分页|成功时 meta.pagination 包含 page、page_size、total、total_pages；无匹配 total=0、total_pages=0；越界页保留请求 page；列表和 total 基于同一次读取快照。|
|游标分页|I35 的 meta.pagination 只含 page_size、next_cursor、has_more；没有 total、total_pages；无更早消息时 next_cursor=null。|
|失败分页|所有失败响应省略 meta.pagination，不伪造 total=0。|
|异步接受|I02、I14、I15、I18、I34、I36 的201/202确认AI接受事务；最终运行结果由 I16 查询。其他同步创建入口的201按各自能力确认资源创建完成。运行自身为 FAILED 不等于查询接口失败，读取成功仍返回 200。|
|应用结果|统一 result={code,data,details}。成功 details=null；失败 data=null。分页能力在 result.data 中返回 items 与分页字段，由接口移动到 meta.pagination。|
|安全投影|运行/消息响应只输出表中字段；不返回 LLMUse、Prompt、密钥、原始供应商响应、内部推理或诊断快照。合法存储的核心结构若无法转换为接口定义，按内部错误处理；仅 I35 明确允许损坏结构化消息降级。|


<a id="api-com-error"></a>
**API-COM-ERROR 公共错误结构与映射**

|参数名称|所属对象|含义|类型|出现条件|可为 null|说明|
|---|---|---|---|---|---|---|
|code|error|错误码|string|失败时必有|否|见下表|
|message|error|错误提示|string|失败时必有|否|安全的中文提示；客户端按 code 判断分支|
|details|error|错误详情|object|失败时必有|是|没有补充信息时 null|
|field_errors|error.details|字段错误|array[object]|输入校验失败时必有|否|至少一项|
|field|error.details.field_errors[]|参数路径|string|每项必有|否|例如 page、status[1]、responses[0].card_key；数组从 0 开始|
|reason|error.details.field_errors[]|原因编码|string|每项必有|否|REQUIRED / INVALID_TYPE / INVALID_FORMAT / INVALID_ENUM / TOO_SHORT / TOO_LONG / OUT_OF_RANGE / UNKNOWN_FIELD / DUPLICATE_PARAMETER|
|message|error.details.field_errors[]|字段错误提示|string|每项必有|否|说明要求，不回显密钥或整段用户内容|
|response_message_id|error.details|已有正式回答 ID|integer|CARD_ALREADY_ANSWERED 时必有|否|引用已有 CARD_RESPONSE，不覆盖已有答案|
|suggestion_errors|error.details|本次建议校验错误|array[object]|I21/I22适用PATCH_INVALID/TARGET_STALE时可有|否|只读本次失败详情，不反写validation_status/error|
|suggestion_id / code / message|error.details.suggestion_errors[]|目标建议ID及安全错误|integer / string / string|每项必有|否|ID为正安全整数；code仅PATCH_INVALID/TARGET_STALE；message使用公共安全文案|

|应用结果或异常分类|HTTP 状态码|error.code|error.message|details|
|---|---|---|---|---|
|INVALID_INPUT|422|VALIDATION_FAILED|请求参数不合法|字段错误明细见 API-COM-ERROR|
|NOT_FOUND|404|NOT_FOUND|资源不存在|null|
|MANUAL_DRAFT_NOT_FOUND|404|MANUAL_DRAFT_NOT_FOUND|人工草稿不存在|null|
|STATE_CONFLICT|409|STATE_CONFLICT|当前状态不允许此操作|null|
|WORK_STATE_CONFLICT|409|WORK_STATE_CONFLICT|当前已有其他操作占用正文|null|
|WORK_STATE_INCONSISTENT|409|WORK_STATE_INCONSISTENT|工作状态与活动对象不一致|null|
|CONTENT_VERSION_CONFLICT|409|CONTENT_VERSION_CONFLICT|内容已更新，请刷新后重试|null|
|TEMPLATE_INVALID|422|TEMPLATE_INVALID|模板不存在、不适用或结构不符合要求|null|
|DOCUMENT_INVALID|422|DOCUMENT_INVALID|正文与区块快照不合法|null|
|ANCHOR_INVALID|422|ANCHOR_INVALID|评论锚点无法唯一定位|null|
|SCOPE_INVALID|422|SCOPE_INVALID|指定范围无法确定或已失效|null|
|SOURCE_INVALID|422|SOURCE_INVALID|来源对象无效|null|
|PATCH_INVALID|422|PATCH_INVALID|修改建议结构不合法或不能组合应用|I21/I22适用时可含suggestion_errors，其他为null|
|TARGET_STALE|409|TARGET_STALE|修改目标或原内容已变化|I21/I22适用时可含suggestion_errors，其他为null|
|BATCH_PENDING|422|BATCH_PENDING|仍有未决定的建议|null|
|COMMENT_ORPHANED|409|COMMENT_ORPHANED|评论锚点已失效|null|
|CARD_ALREADY_ANSWERED|409|CARD_ALREADY_ANSWERED|该组卡片已提交回答|{response_message_id:正整数}|
|CARD_EXPIRED|409|CARD_EXPIRED|该组卡片已失效|null|
|CAPACITY_EXHAUSTED|503|CAPACITY_EXHAUSTED|编号或版本容量已用尽|null|
|CONFIG_INVALID|503|CONFIG_INVALID|所需协议或模板资源不可用|null|
|STORAGE_UNAVAILABLE|503|STORAGE_UNAVAILABLE|数据暂时无法访问，请稍后重试|null|
|IDEMPOTENCY_CONFLICT|409|IDEMPOTENCY_CONFLICT|同一幂等键对应了不同请求|null|
|REQUEST_IN_PROGRESS|409|REQUEST_IN_PROGRESS|同一请求仍在处理中|null|
|INTERNAL_ERROR|500|INTERNAL_ERROR|系统处理失败，请稍后重试|null|

每个接口只引用实际可达的错误项；本表不意味着所有接口都能返回所有错误。未预期异常以及未登记的结果编码均按 INTERNAL_ERROR 处理；不得把映射错误伪装为成功或普通业务拒绝。


<a id="api-com-idempotency"></a>
**API-COM-IDEMPOTENCY 幂等请求契约**

|项目|定义|
|---|---|
|键格式|客户端生成的 UUID v4 字符串；同一用户动作的网络重试使用同一键，新动作使用新键。|
|作用域|单用户范围内，以“能力编号＋完整目标资源身份＋幂等键”定位一条动作记录；创建需求的目标为需求集合。|
|请求比较|比较完成类型解析、默认值处理后的业务输入；包含文本、版本、来源和范围。JSON 键顺序无关，数组顺序保留，忽略头本身和请求编号。可选字段是否提供对 PATCH 有意义，不与 null 混同。|
|已成功|相同键与相同输入重放原成功的 HTTP 状态码和业务 data，不再次执行业务、不按当前资源拼装新结果；meta.request_id 使用本次请求值。|
|相同键不同输入|返回 IDEMPOTENCY_CONFLICT，不覆盖原记录。|
|正在执行|返回 REQUEST_IN_PROGRESS，不并行启动第二次动作。|
|拒绝及提交前失败|不登记为已成功；重试重新检查业务条件。已提交成功但响应丢失必须可重放，不能执行第二次副作用。|
|事务归属|由被调用 APP 能力统一编排，幂等成功记录与业务提交必须原子一致；接口层不另写一套幂等存储。|
|实现依赖|持久表与owner_epoch按SHR-IDEMPOTENCY；PROCESSING短事务领取，业务与SUCCEEDED同事务提交，成功永久保留；未知提交不得当回滚释放|




**公共处理顺序**

1. 路由匹配后按6.2的明确字段集合读取输入；校验媒体类型、JSON根对象、未知字段和重复参数。
2. 解析基础类型及条件结构，补齐正式默认值；构造该入口唯一APP能力的输入。状态、存在性、版本、授权及事务仍由能力处理。
3. 调用指定APP能力一次。接入校验失败不调用能力；应用幂等成功重放同样经过响应映射。
4. 已登记成功结果按6.2投影data；时间依API-COM-RESPONSE序列化，分页从result.data移动到meta.pagination；加入本次request_id。
5. 失败按API-COM-ERROR输出。任一步未预期异常、未登记结果、核心结构无法转换均为INTERNAL_ERROR；不伪装为空对象或成功。唯一损坏消息降级在APP-MSG-QUERY-C01明确。

**外层结构**：success为不可空boolean；data为各入口成功载荷或null；error为API-COM-ERROR对象或null；meta为不可空对象，request_id必有。page_size固定20；page、total和total_pages按SHR-PAGE。游标分页的has_more不可空boolean、next_cursor为正整数或null。无其他根字段。

**公共实现定位**

|构造编号|认证|主要代码|接口范围|
|---|---|---|---|
|BND-REQ-API|无，单用户|backend/app/requirements/api.py :: req_router|BND-REQ-API-I02,BND-REQ-API-I04,BND-REQ-API-I05,BND-REQ-API-I06,BND-REQ-API-I07,BND-REQ-API-I01,BND-REQ-API-I03|
|BND-DOC-API|无，单用户|backend/app/documents/api.py :: doc_router|BND-DOC-API-I09,BND-DOC-API-I11,BND-DOC-API-I12,BND-DOC-API-I13,BND-DOC-API-I08,BND-DOC-API-I10|
|BND-REV-API|无，单用户|backend/app/revisions/api.py :: rev_router|BND-REV-API-I26,BND-REV-API-I24,BND-REV-API-I25|
|BND-COMMENT-API|无，单用户|backend/app/comments/api.py :: comment_router|BND-COMMENT-API-I29,BND-COMMENT-API-I30,BND-COMMENT-API-I31,BND-COMMENT-API-I32,BND-COMMENT-API-I33,BND-COMMENT-API-I27,BND-COMMENT-API-I28,BND-COMMENT-API-I37|
|BND-GUIDE-API|无，单用户|backend/app/guide/api.py :: guide_router|BND-GUIDE-API-I14,BND-GUIDE-API-I15,BND-GUIDE-API-I17,BND-GUIDE-API-I18,BND-GUIDE-API-I34,BND-GUIDE-API-I16,BND-GUIDE-API-I19|
|BND-BATCH-API|无，单用户|backend/app/suggestions/api.py :: batch_router|BND-BATCH-API-I21,BND-BATCH-API-I22,BND-BATCH-API-I23,BND-BATCH-API-I20|
|BND-MSG-API|无，单用户|backend/app/messages/api.py :: message_router|BND-MSG-API-I36,BND-MSG-API-I35|

公共HTTP边界在backend/app/shared/http_boundary.py、http_commands.py、http_errors.py及service.py中绑定FastAPI；各入口的HTTP模型及函数定位见6.2。

### 6.2 HTTP接口


<a id="bnd-req-api-i01"></a>
#### BND-REQ-API-I01 查询需求列表

|内容|确定定义|
|---|---|
|接口引用与名称|BND-REQ-API-I01 查询需求列表|
|方法与路径|`GET` `/api/v1/requirements`|
|用途与响应方式|按关键词、需求状态和类型筛选需求，分页返回列表。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-REQ-QUERY-C01](#app-req-query-c01)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`keyword`|Query／string|必传：否；可为null：否；未传：不按关键词筛选|APP-REQ-QUERY-C01／4.2 的 keyword；解析后字符串；未传为 null；能力执行关键词标准化|
|`status`|Query／array[string]|必传：否；可为null：否；未传：不限制该项|APP-REQ-QUERY-C01／4.2 的 status；解析后的数组；未传为 []；能力去重并验证业务枚举；重复参数名，不接受逗号或JSON文本；去重保留首次顺序|
|`requirement_type`|Query／array[string]|必传：否；可为null：否；未传：不限制该项|APP-REQ-QUERY-C01／4.2 的 requirement_type；解析后的数组；未传为 []；能力去重并验证业务枚举；重复参数名，不接受逗号或JSON文本；去重保留首次顺序|
|`page`|Query／integer|必传：否；可为null：否；未传：1|APP-REQ-QUERY-C01／4.2 的 page；同名参数；1（未传时）|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`READ_OK` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-REQ-QUERY-C01／4.4成功载荷投影，内部 UTC 时间转为约定字符串。result.data.items → data.items；result.data.page/page_size/total/total_pages → meta.pagination 的同名字段。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-REQ-QUERY-C01／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/requirements/api.py`|`list_requirements_http`|
|HTTP 请求与响应结构|`backend/app/requirements/http_models.py`|`ListRequirementsRequest` / `ListRequirementsResponse`|


<a id="bnd-req-api-i02"></a>
#### BND-REQ-API-I02 创建需求

|内容|确定定义|
|---|---|
|接口引用与名称|BND-REQ-API-I02 创建需求|
|方法与路径|`POST` `/api/v1/requirements`|
|用途与响应方式|创建需求及正式文档，并接受首轮初始化任务。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-REQ-CMD-C01](#app-req-cmd-c01)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C01／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|
|`title`|Body／string|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C01／4.2 的 title；同名参数；必填值|
|`requirement_type`|Body／string|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C01／4.2 的 requirement_type；同名参数；必填值|
|`template_key`|Body／string|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C01／4.2 的 template_key；同名参数；必填值|
|`template_version`|Body／string|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C01／4.2 的 template_version；同名参数；必填值|
|`initial_idea`|Body／string|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C01／4.2 的 initial_idea；同名参数；必填值|
|`initialization_mode`|Body／string|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C01／4.2 的 initialization_mode；同名参数；必填值|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-REQ-CMD-C01／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`CREATED` → HTTP 201。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-REQ-CMD-C01／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`TEMPLATE_INVALID`、`CONFIG_INVALID`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`、`CAPACITY_EXHAUSTED`|逐项采用API-COM-ERROR|触发条件完整引用APP-REQ-CMD-C01／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


接受后按返回的运行关联读取BND-GUIDE-API-I16，消息读取BND-MSG-API-I35；HTTP接受不表示模型成功或正文已经更新。

**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/requirements/api.py`|`create_requirement_http`|
|HTTP 请求与响应结构|`backend/app/requirements/http_models.py`|`CreateRequirementRequest` / `CreateRequirementResponse`|


<a id="bnd-req-api-i03"></a>
#### BND-REQ-API-I03 查询需求详情

|内容|确定定义|
|---|---|
|接口引用与名称|BND-REQ-API-I03 查询需求详情|
|方法与路径|`GET` `/api/v1/requirements/{requirement_id}`|
|用途与响应方式|读取需求属性、生命周期和当前占用信息。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-REQ-QUERY-C02](#app-req-query-c02)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-REQ-QUERY-C02／4.2 的 requirement_id；同名参数；必填值|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`READ_OK` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-REQ-QUERY-C02／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-REQ-QUERY-C02／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/requirements/api.py`|`get_requirement_http`|
|HTTP 请求与响应结构|`backend/app/requirements/http_models.py`|`GetRequirementRequest` / `GetRequirementResponse`|


<a id="bnd-req-api-i04"></a>
#### BND-REQ-API-I04 修改需求属性

|内容|确定定义|
|---|---|
|接口引用与名称|BND-REQ-API-I04 修改需求属性|
|方法与路径|`PATCH` `/api/v1/requirements/{requirement_id}`|
|用途与响应方式|仅修改标题；初始化模式创建后只读。一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-REQ-CMD-C02](#app-req-cmd-c02)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C02／4.2 的 requirement_id；同名参数；必填值|
|`title`|Body／string|必传：是；可为null：否；未传：拒绝|APP-REQ-CMD-C02／4.2的title；唯一可更新字段|


Body为JSON对象，唯一允许且必填的根字段为title；空对象、null、initialization_mode（含同值或标题混合）在HTTP输入边界整体422／VALIDATION_FAILED，不调用属性写入，不更改updated_at。创建I02及完整读取I03仍保留initialization_mode。嵌套字段完整采用APP-REQ-CMD-C02／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`UPDATED` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-REQ-CMD-C02／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-REQ-CMD-C02／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/requirements/api.py`|`update_requirement_http`|
|HTTP 请求与响应结构|`backend/app/requirements/http_models.py`|`UpdateRequirementRequest` / `UpdateRequirementResponse`|



<a id="bnd-req-api-i05"></a>
#### BND-REQ-API-I05 完成初始化

|内容|确定定义|
|---|---|
|接口引用与名称|BND-REQ-API-I05 完成初始化|
|方法与路径|`POST` `/api/v1/requirements/{requirement_id}/complete-initialization`|
|用途与响应方式|将初始化正文保存为基线版本，并进入可维护阶段。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-REQ-CMD-C03](#app-req-cmd-c03)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C03／4.2 的 requirement_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C03／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|
|`expected_content_version`|Body／integer|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C03／4.2 的 expected_content_version；同名参数；必填值|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-REQ-CMD-C03／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`INITIALIZATION_COMPLETED` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-REQ-CMD-C03／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`CONTENT_VERSION_CONFLICT`、`DOCUMENT_INVALID`、`TEMPLATE_INVALID`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`、`CAPACITY_EXHAUSTED`|逐项采用API-COM-ERROR|触发条件完整引用APP-REQ-CMD-C03／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/requirements/api.py`|`complete_initialization_http`|
|HTTP 请求与响应结构|`backend/app/requirements/http_models.py`|`CompleteInitializationRequest` / `CompleteInitializationResponse`|


<a id="bnd-req-api-i06"></a>
#### BND-REQ-API-I06 完成需求

|内容|确定定义|
|---|---|
|接口引用与名称|BND-REQ-API-I06 完成需求|
|方法与路径|`POST` `/api/v1/requirements/{requirement_id}/complete`|
|用途与响应方式|将可维护需求标记为完成。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-REQ-CMD-C04](#app-req-cmd-c04)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C04／4.2 的 requirement_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C04／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|
|`expected_version`|Body／integer|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C04／4.2 的 expected_content_version；请求 expected_version；指 CURRENT 内容版本，改名传入|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-REQ-CMD-C04／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`REQUIREMENT_COMPLETED` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-REQ-CMD-C04／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`CONTENT_VERSION_CONFLICT`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-REQ-CMD-C04／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/requirements/api.py`|`complete_requirement_http`|
|HTTP 请求与响应结构|`backend/app/requirements/http_models.py`|`CompleteRequirementRequest` / `CompleteRequirementResponse`|


<a id="bnd-req-api-i07"></a>
#### BND-REQ-API-I07 重新激活需求

|内容|确定定义|
|---|---|
|接口引用与名称|BND-REQ-API-I07 重新激活需求|
|方法与路径|`POST` `/api/v1/requirements/{requirement_id}/reactivate`|
|用途与响应方式|将已完成需求重新设为可维护。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-REQ-CMD-C05](#app-req-cmd-c05)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C05／4.2 的 requirement_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-REQ-CMD-C05／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`REACTIVATED` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-REQ-CMD-C05／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-REQ-CMD-C05／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/requirements/api.py`|`reactivate_requirement_http`|
|HTTP 请求与响应结构|`backend/app/requirements/http_models.py`|`ReactivateRequirementRequest` / `ReactivateRequirementResponse`|


<a id="bnd-doc-api-i08"></a>
#### BND-DOC-API-I08 读取当前正文

|内容|确定定义|
|---|---|
|接口引用与名称|BND-DOC-API-I08 读取当前正文|
|方法与路径|`GET` `/api/v1/requirements/{requirement_id}/current-document`|
|用途与响应方式|读取需求当前正式正文与区块状态。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-DOC-QUERY-C01](#app-doc-query-c01)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-DOC-QUERY-C01／4.2 的 requirement_id；同名参数；必填值|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`READ_OK` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-DOC-QUERY-C01／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`WORK_STATE_INCONSISTENT`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-DOC-QUERY-C01／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/documents/api.py`|`get_current_document_http`|
|HTTP 请求与响应结构|`backend/app/documents/http_models.py`|`GetCurrentDocumentRequest` / `GetCurrentDocumentResponse`|


<a id="bnd-doc-api-i09"></a>
#### BND-DOC-API-I09 开始人工编辑

|内容|确定定义|
|---|---|
|接口引用与名称|BND-DOC-API-I09 开始人工编辑|
|方法与路径|`POST` `/api/v1/requirements/{requirement_id}/manual-draft`|
|用途与响应方式|从当前正文创建独立人工草稿并取得编辑占用。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-DOC-CMD-C01](#app-doc-cmd-c01)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-DOC-CMD-C01／4.2 的 requirement_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-DOC-CMD-C01／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|
|`expected_version`|Body／integer|必传：是；可为null：否；未传：不适用|APP-DOC-CMD-C01／4.2 的 expected_content_version；请求 expected_version；指 CURRENT 内容版本，改名传入|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-DOC-CMD-C01／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`DRAFT_STARTED` → HTTP 201。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-DOC-CMD-C01／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`CONTENT_VERSION_CONFLICT`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`、`CAPACITY_EXHAUSTED`|逐项采用API-COM-ERROR|触发条件完整引用APP-DOC-CMD-C01／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/documents/api.py`|`start_manual_draft_http`|
|HTTP 请求与响应结构|`backend/app/documents/http_models.py`|`StartManualDraftRequest` / `StartManualDraftResponse`|


<a id="bnd-doc-api-i10"></a>
#### BND-DOC-API-I10 读取人工草稿

|内容|确定定义|
|---|---|
|接口引用与名称|BND-DOC-API-I10 读取人工草稿|
|方法与路径|`GET` `/api/v1/requirements/{requirement_id}/manual-draft`|
|用途与响应方式|读取当前人工草稿及其内容版本。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-DOC-QUERY-C02](#app-doc-query-c02)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-DOC-QUERY-C02／4.2 的 requirement_id；同名参数；必填值|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`READ_OK` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-DOC-QUERY-C02／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`MANUAL_DRAFT_NOT_FOUND`、`WORK_STATE_INCONSISTENT`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-DOC-QUERY-C02／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/documents/api.py`|`get_manual_draft_http`|
|HTTP 请求与响应结构|`backend/app/documents/http_models.py`|`GetManualDraftRequest` / `GetManualDraftResponse`|


<a id="bnd-doc-api-i11"></a>
#### BND-DOC-API-I11 保存人工草稿

|内容|确定定义|
|---|---|
|接口引用与名称|BND-DOC-API-I11 保存人工草稿|
|方法与路径|`PUT` `/api/v1/requirements/{requirement_id}/manual-draft`|
|用途与响应方式|保存编辑器提交的完整草稿快照。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-DOC-CMD-C02](#app-doc-cmd-c02)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-DOC-CMD-C02／4.2 的 requirement_id；同名参数；必填值|
|`expected_version`|Body／integer|必传：是；可为null：否；未传：不适用|APP-DOC-CMD-C02／4.2 的 expected_version；同名参数；必填值|
|`markdown_content`|Body／string|必传：是；可为null：否；未传：不适用|APP-DOC-CMD-C02／4.2 的 markdown_content；同名参数；必填值|
|`block_state_json`|Body／object|必传：是；可为null：否；未传：不适用|APP-DOC-CMD-C02／4.2 的 block_state_json；同名参数；必填值|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-DOC-CMD-C02／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`DRAFT_SAVED` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-DOC-CMD-C02／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`CONTENT_VERSION_CONFLICT`、`DOCUMENT_INVALID`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`、`CAPACITY_EXHAUSTED`|逐项采用API-COM-ERROR|触发条件完整引用APP-DOC-CMD-C02／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/documents/api.py`|`save_manual_draft_http`|
|HTTP 请求与响应结构|`backend/app/documents/http_models.py`|`SaveManualDraftRequest` / `SaveManualDraftResponse`|


<a id="bnd-doc-api-i12"></a>
#### BND-DOC-API-I12 完成人工编辑

|内容|确定定义|
|---|---|
|接口引用与名称|BND-DOC-API-I12 完成人工编辑|
|方法与路径|`POST` `/api/v1/requirements/{requirement_id}/manual-draft/complete`|
|用途与响应方式|将草稿提交为当前正式正文并结束人工编辑。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-DOC-CMD-C03](#app-doc-cmd-c03)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-DOC-CMD-C03／4.2 的 requirement_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-DOC-CMD-C03／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|
|`expected_version`|Body／integer|必传：是；可为null：否；未传：不适用|APP-DOC-CMD-C03／4.2 的 expected_version；同名参数；必填值|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-DOC-CMD-C03／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`DRAFT_COMPLETED` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-DOC-CMD-C03／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`CONTENT_VERSION_CONFLICT`、`DOCUMENT_INVALID`、`TEMPLATE_INVALID`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`、`CAPACITY_EXHAUSTED`|逐项采用API-COM-ERROR|触发条件完整引用APP-DOC-CMD-C03／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/documents/api.py`|`complete_manual_draft_http`|
|HTTP 请求与响应结构|`backend/app/documents/http_models.py`|`CompleteManualDraftRequest` / `CompleteManualDraftResponse`|


<a id="bnd-doc-api-i13"></a>
#### BND-DOC-API-I13 取消人工编辑

|内容|确定定义|
|---|---|
|接口引用与名称|BND-DOC-API-I13 取消人工编辑|
|方法与路径|`DELETE` `/api/v1/requirements/{requirement_id}/manual-draft`|
|用途与响应方式|删除当前人工草稿并结束人工编辑。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-DOC-CMD-C04](#app-doc-cmd-c04)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-DOC-CMD-C04／4.2 的 requirement_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-DOC-CMD-C04／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|
|`expected_version`|Body／integer|必传：是；可为null：否；未传：不适用|APP-DOC-CMD-C04／4.2 的 expected_version；同名参数；必填值|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-DOC-CMD-C04／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`DRAFT_CANCELLED` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-DOC-CMD-C04／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`CONTENT_VERSION_CONFLICT`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-DOC-CMD-C04／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


DELETE仍必须携带JSON Body.expected_version；其比较对象是MANUAL_DRAFT。

**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/documents/api.py`|`cancel_manual_draft_http`|
|HTTP 请求与响应结构|`backend/app/documents/http_models.py`|`CancelManualDraftRequest` / `CancelManualDraftResponse`|


<a id="bnd-guide-api-i14"></a>
#### BND-GUIDE-API-I14 创建AI运行

|内容|确定定义|
|---|---|
|接口引用与名称|BND-GUIDE-API-I14 创建AI运行|
|方法与路径|`POST` `/api/v1/requirements/{requirement_id}/guide-runs`|
|用途与响应方式|按指定动作、范围和来源接受一次 AI 任务。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-GUIDE-CMD-C01](#app-guide-cmd-c01)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C01／4.2 的 requirement_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C01／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|
|`expected_version`|Body／integer|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C01／4.2 的 expected_content_version；请求 expected_version；指 CURRENT 内容版本，改名传入|
|`action_type`|Body／string|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C01／4.2 的 action_type；同名参数；必填值|
|`instruction`|Body／string|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C01／4.2 的 instruction；同名参数；必填值|
|`scope_type`|Body／string|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C01／4.2 的 scope_type；同名参数；必填值|
|`scope_ref`|Body／object|必传：条件；可为null：是；未传：DOCUMENT 时 null|APP-GUIDE-CMD-C01／4.2 的 scope_ref；同名参数；DOCUMENT 时 null（未传时）|
|`source_type`|Body／string|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C01／4.2 的 source_type；同名参数；必填值|
|`source_id`|Body／integer|必传：条件；可为null：是；未传：USER_INSTRUCTION 时 null|APP-GUIDE-CMD-C01／4.2 的 source_id；同名参数；USER_INSTRUCTION 时 null（未传时）|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-GUIDE-CMD-C01／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`GUIDE_ACCEPTED` → HTTP 202。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-GUIDE-CMD-C01／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`CONTENT_VERSION_CONFLICT`、`SOURCE_INVALID`、`SCOPE_INVALID`、`CONFIG_INVALID`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`、`CAPACITY_EXHAUSTED`|逐项采用API-COM-ERROR|触发条件完整引用APP-GUIDE-CMD-C01／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


接受后按返回的运行关联读取BND-GUIDE-API-I16，消息读取BND-MSG-API-I35；HTTP接受不表示模型成功或正文已经更新。

**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/guide/api.py`|`create_guide_run_http`|
|HTTP 请求与响应结构|`backend/app/guide/http_models.py`|`CreateGuideRunRequest` / `CreateGuideRunResponse`|


<a id="bnd-guide-api-i15"></a>
#### BND-GUIDE-API-I15 继续等待中的运行

|内容|确定定义|
|---|---|
|接口引用与名称|BND-GUIDE-API-I15 继续等待中的运行|
|方法与路径|`POST` `/api/v1/guide-runs/{guide_run_id}/continue`|
|用途与响应方式|提交补充说明，继续等待中的原运行。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-GUIDE-CMD-C02](#app-guide-cmd-c02)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`guide_run_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C02／4.2 的 guide_run_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C02／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|
|`instruction`|Body／string|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C02／4.2 的 instruction；同名参数；必填值|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-GUIDE-CMD-C02／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`GUIDE_CONTINUED` → HTTP 202。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-GUIDE-CMD-C02／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`CONFIG_INVALID`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`、`CAPACITY_EXHAUSTED`|逐项采用API-COM-ERROR|触发条件完整引用APP-GUIDE-CMD-C02／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


接受后按返回的运行关联读取BND-GUIDE-API-I16，消息读取BND-MSG-API-I35；HTTP接受不表示模型成功或正文已经更新。

**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/guide/api.py`|`continue_guide_run_http`|
|HTTP 请求与响应结构|`backend/app/guide/http_models.py`|`ContinueGuideRunRequest` / `ContinueGuideRunResponse`|


<a id="bnd-guide-api-i16"></a>
#### BND-GUIDE-API-I16 读取运行状态

|内容|确定定义|
|---|---|
|接口引用与名称|BND-GUIDE-API-I16 读取运行状态|
|方法与路径|`GET` `/api/v1/guide-runs/{guide_run_id}`|
|用途与响应方式|读取运行进度、结果摘要及资源引用。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-GUIDE-QUERY-C01](#app-guide-query-c01)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`guide_run_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-GUIDE-QUERY-C01／4.2 的 guide_run_id；同名参数；必填值|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`READ_OK` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-GUIDE-QUERY-C01／4.4成功载荷投影，内部 UTC 时间转为约定字符串。final_result_json/scope_ref_json 由能力按安全投影转换，接口不直接序列化存储字段。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-GUIDE-QUERY-C01／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/guide/api.py`|`get_guide_run_http`|
|HTTP 请求与响应结构|`backend/app/guide/http_models.py`|`GetGuideRunRequest` / `GetGuideRunResponse`|


<a id="bnd-guide-api-i17"></a>
#### BND-GUIDE-API-I17 取消AI运行

|内容|确定定义|
|---|---|
|接口引用与名称|BND-GUIDE-API-I17 取消AI运行|
|方法与路径|`POST` `/api/v1/guide-runs/{guide_run_id}/cancel`|
|用途与响应方式|取消尚未进入最终提交阶段的运行。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-GUIDE-CMD-C03](#app-guide-cmd-c03)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`guide_run_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C03／4.2 的 guide_run_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C03／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`GUIDE_CANCELLED` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-GUIDE-CMD-C03／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-GUIDE-CMD-C03／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/guide/api.py`|`cancel_guide_run_http`|
|HTTP 请求与响应结构|`backend/app/guide/http_models.py`|`CancelGuideRunRequest` / `CancelGuideRunResponse`|


<a id="bnd-guide-api-i18"></a>
#### BND-GUIDE-API-I18 重新运行失败任务

|内容|确定定义|
|---|---|
|接口引用与名称|BND-GUIDE-API-I18 重新运行失败任务|
|方法与路径|`POST` `/api/v1/guide-runs/{guide_run_id}/retry`|
|用途与响应方式|基于失败任务及最新正文接受一次新的运行。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-GUIDE-CMD-C04](#app-guide-cmd-c04)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`guide_run_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C04／4.2 的 guide_run_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C04／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`GUIDE_RETRY_ACCEPTED` → HTTP 202。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-GUIDE-CMD-C04／4.4成功载荷投影，内部 UTC 时间转为约定字符串。final_result_json/scope_ref_json 由能力按安全投影转换，接口不直接序列化存储字段。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`SOURCE_INVALID`、`SCOPE_INVALID`、`CONFIG_INVALID`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`、`CAPACITY_EXHAUSTED`|逐项采用API-COM-ERROR|触发条件完整引用APP-GUIDE-CMD-C04／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


接受后按返回的运行关联读取BND-GUIDE-API-I16，消息读取BND-MSG-API-I35；HTTP接受不表示模型成功或正文已经更新。

**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/guide/api.py`|`retry_guide_run_http`|
|HTTP 请求与响应结构|`backend/app/guide/http_models.py`|`RetryGuideRunRequest` / `RetryGuideRunResponse`|


<a id="bnd-guide-api-i19"></a>
#### BND-GUIDE-API-I19 查询运行历史

|内容|确定定义|
|---|---|
|接口引用与名称|BND-GUIDE-API-I19 查询运行历史|
|方法与路径|`GET` `/api/v1/requirements/{requirement_id}/guide-runs`|
|用途与响应方式|按状态和动作分页查询需求的运行历史。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-GUIDE-QUERY-C02](#app-guide-query-c02)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-GUIDE-QUERY-C02／4.2 的 requirement_id；同名参数；必填值|
|`status`|Query／array[string]|必传：否；可为null：否；未传：不限制该项|APP-GUIDE-QUERY-C02／4.2 的 status；解析后的数组；未传为 []；能力去重并验证业务枚举；重复参数名，不接受逗号或JSON文本；去重保留首次顺序|
|`action_type`|Query／array[string]|必传：否；可为null：否；未传：不限制该项|APP-GUIDE-QUERY-C02／4.2 的 action_type；解析后的数组；未传为 []；能力去重并验证业务枚举；重复参数名，不接受逗号或JSON文本；去重保留首次顺序|
|`page`|Query／integer|必传：否；可为null：否；未传：1|APP-GUIDE-QUERY-C02／4.2 的 page；同名参数；1（未传时）|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`READ_OK` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-GUIDE-QUERY-C02／4.4成功载荷投影，内部 UTC 时间转为约定字符串。result.data.items → data.items；result.data.page/page_size/total/total_pages → meta.pagination 的同名字段。final_result_json/scope_ref_json 由能力按安全投影转换，接口不直接序列化存储字段。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-GUIDE-QUERY-C02／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/guide/api.py`|`list_guide_runs_http`|
|HTTP 请求与响应结构|`backend/app/guide/http_models.py`|`ListGuideRunsRequest` / `ListGuideRunsResponse`|


<a id="bnd-batch-api-i20"></a>
#### BND-BATCH-API-I20 读取建议批次

|内容|确定定义|
|---|---|
|接口引用与名称|BND-BATCH-API-I20 读取建议批次|
|方法与路径|`GET` `/api/v1/suggestion-batches/{batch_id}`|
|用途与响应方式|读取批次、全部建议及决策计数。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-BATCH-QUERY-C01](#app-batch-query-c01)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`batch_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-BATCH-QUERY-C01／4.2 的 batch_id；同名参数；必填值|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`READ_OK` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-BATCH-QUERY-C01／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-BATCH-QUERY-C01／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/suggestions/api.py`|`get_batch_http`|
|HTTP 请求与响应结构|`backend/app/suggestions/http_models.py`|`GetBatchRequest` / `GetBatchResponse`|


<a id="bnd-batch-api-i21"></a>
#### BND-BATCH-API-I21 处理建议决策

|内容|确定定义|
|---|---|
|接口引用与名称|BND-BATCH-API-I21 处理建议决策|
|方法与路径|`PUT` `/api/v1/suggestions/{suggestion_id}/decision`|
|用途与响应方式|保存一条建议的接受、拒绝或编辑后接受决定。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-BATCH-CMD-C01](#app-batch-cmd-c01)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`suggestion_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-BATCH-CMD-C01／4.2 的 suggestion_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-BATCH-CMD-C01／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|
|`decision`|Body／string|必传：是；可为null：否；未传：不适用|APP-BATCH-CMD-C01／4.2 的 decision；同名参数；必填值|
|`edited_content`|Body／string|必传：条件；可为null：是；未传：非 EDITED 时 null|APP-BATCH-CMD-C01／4.2 的 edited_content；同名参数；非 EDITED 时 null（未传时）|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-BATCH-CMD-C01／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`SUGGESTION_DECIDED` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-BATCH-CMD-C01／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`PATCH_INVALID`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-BATCH-CMD-C01／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/suggestions/api.py`|`decide_suggestion_http`|
|HTTP 请求与响应结构|`backend/app/suggestions/http_models.py`|`DecideSuggestionRequest` / `DecideSuggestionResponse`|


<a id="bnd-batch-api-i22"></a>
#### BND-BATCH-API-I22 完成建议批次

|内容|确定定义|
|---|---|
|接口引用与名称|BND-BATCH-API-I22 完成建议批次|
|方法与路径|`POST` `/api/v1/suggestion-batches/{batch_id}/complete`|
|用途与响应方式|校验并提交整批建议，返回是否实际改变正文的结果。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-BATCH-CMD-C02](#app-batch-cmd-c02)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`batch_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-BATCH-CMD-C02／4.2 的 batch_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-BATCH-CMD-C02／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|
|`expected_content_version`|Body／integer|必传：是；可为null：否；未传：不适用|APP-BATCH-CMD-C02／4.2 的 expected_content_version；同名参数；必填值|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-BATCH-CMD-C02／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`BATCH_APPLIED` → HTTP 200；`BATCH_NO_CHANGE` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-BATCH-CMD-C02／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`CONTENT_VERSION_CONFLICT`、`BATCH_PENDING`、`TARGET_STALE`、`PATCH_INVALID`、`DOCUMENT_INVALID`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`、`CAPACITY_EXHAUSTED`|逐项采用API-COM-ERROR|触发条件完整引用APP-BATCH-CMD-C02／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/suggestions/api.py`|`complete_batch_http`|
|HTTP 请求与响应结构|`backend/app/suggestions/http_models.py`|`CompleteBatchRequest` / `CompleteBatchResponse`|


<a id="bnd-batch-api-i23"></a>
#### BND-BATCH-API-I23 放弃建议批次

|内容|确定定义|
|---|---|
|接口引用与名称|BND-BATCH-API-I23 放弃建议批次|
|方法与路径|`POST` `/api/v1/suggestion-batches/{batch_id}/discard`|
|用途与响应方式|放弃当前待处理批次，保留历史决定。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-BATCH-CMD-C03](#app-batch-cmd-c03)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`batch_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-BATCH-CMD-C03／4.2 的 batch_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-BATCH-CMD-C03／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`BATCH_DISCARDED` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-BATCH-CMD-C03／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-BATCH-CMD-C03／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/suggestions/api.py`|`discard_batch_http`|
|HTTP 请求与响应结构|`backend/app/suggestions/http_models.py`|`DiscardBatchRequest` / `DiscardBatchResponse`|


<a id="bnd-rev-api-i24"></a>
#### BND-REV-API-I24 查询版本列表

|内容|确定定义|
|---|---|
|接口引用与名称|BND-REV-API-I24 查询版本列表|
|方法与路径|`GET` `/api/v1/requirements/{requirement_id}/revisions`|
|用途与响应方式|分页读取需求的版本摘要。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-REV-QUERY-C01](#app-rev-query-c01)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-REV-QUERY-C01／4.2 的 requirement_id；同名参数；必填值|
|`page`|Query／integer|必传：否；可为null：否；未传：1|APP-REV-QUERY-C01／4.2 的 page；同名参数；1（未传时）|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`READ_OK` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-REV-QUERY-C01／4.4成功载荷投影，内部 UTC 时间转为约定字符串。result.data.items → data.items；result.data.page/page_size/total/total_pages → meta.pagination 的同名字段。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-REV-QUERY-C01／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/revisions/api.py`|`list_revisions_http`|
|HTTP 请求与响应结构|`backend/app/revisions/http_models.py`|`ListRevisionsRequest` / `ListRevisionsResponse`|


<a id="bnd-rev-api-i25"></a>
#### BND-REV-API-I25 读取版本快照

|内容|确定定义|
|---|---|
|接口引用与名称|BND-REV-API-I25 读取版本快照|
|方法与路径|`GET` `/api/v1/revisions/{revision_id}`|
|用途与响应方式|读取某个不可变历史版本的完整快照。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-REV-QUERY-C02](#app-rev-query-c02)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`revision_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-REV-QUERY-C02／4.2 的 revision_id；同名参数；必填值|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`READ_OK` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-REV-QUERY-C02／4.4成功载荷投影，内部 UTC 时间转为约定字符串。持久化 markdown_snapshot / block_state_snapshot_json 由 Query 分别转换为 markdown_content / block_state_json。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-REV-QUERY-C02／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/revisions/api.py`|`get_revision_http`|
|HTTP 请求与响应结构|`backend/app/revisions/http_models.py`|`GetRevisionRequest` / `GetRevisionResponse`|


<a id="bnd-rev-api-i26"></a>
#### BND-REV-API-I26 保存手动版本

|内容|确定定义|
|---|---|
|接口引用与名称|BND-REV-API-I26 保存手动版本|
|方法与路径|`POST` `/api/v1/requirements/{requirement_id}/revisions`|
|用途与响应方式|将当前正式正文保存为一个手动版本。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-REV-CMD-C01](#app-rev-cmd-c01)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-REV-CMD-C01／4.2 的 requirement_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-REV-CMD-C01／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|
|`expected_version`|Body／integer|必传：是；可为null：否；未传：不适用|APP-REV-CMD-C01／4.2 的 expected_content_version；请求 expected_version；指 CURRENT 内容版本，改名传入|
|`description`|Body／string|必传：否；可为null：是；未传：null|APP-REV-CMD-C01／4.2 的 description；同名参数；null（未传时）|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-REV-CMD-C01／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`REVISION_CREATED` → HTTP 201。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-REV-CMD-C01／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`CONTENT_VERSION_CONFLICT`、`DOCUMENT_INVALID`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`、`CAPACITY_EXHAUSTED`|逐项采用API-COM-ERROR|触发条件完整引用APP-REV-CMD-C01／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/revisions/api.py`|`create_manual_revision_http`|
|HTTP 请求与响应结构|`backend/app/revisions/http_models.py`|`CreateManualRevisionRequest` / `CreateManualRevisionResponse`|


<a id="bnd-comment-api-i27"></a>
#### BND-COMMENT-API-I27 查询评论列表

|内容|确定定义|
|---|---|
|接口引用与名称|BND-COMMENT-API-I27 查询评论列表|
|方法与路径|`GET` `/api/v1/requirements/{requirement_id}/comments`|
|用途与响应方式|分页读取未删除评论及其当前定位信息。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-COMMENT-QUERY-C01](#app-comment-query-c01)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-COMMENT-QUERY-C01／4.2 的 requirement_id；同名参数；必填值|
|`page`|Query／integer|必传：否；可为null：否；未传：1|APP-COMMENT-QUERY-C01／4.2 的 page；同名参数；1（未传时）|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`READ_OK` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-COMMENT-QUERY-C01／4.4成功载荷投影，内部 UTC 时间转为约定字符串。result.data.items → data.items；result.data.page/page_size/total/total_pages → meta.pagination 的同名字段。anchor_ref_json 由能力转为公开 anchor_ref。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-COMMENT-QUERY-C01／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/comments/api.py`|`list_comments_http`|
|HTTP 请求与响应结构|`backend/app/comments/http_models.py`|`ListCommentsRequest` / `ListCommentsResponse`|


<a id="bnd-comment-api-i28"></a>
#### BND-COMMENT-API-I28 读取评论详情

|内容|确定定义|
|---|---|
|接口引用与名称|BND-COMMENT-API-I28 读取评论详情|
|方法与路径|`GET` `/api/v1/comments/{comment_id}`|
|用途与响应方式|读取指定评论，包括软删除记录。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-COMMENT-QUERY-C02](#app-comment-query-c02)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`comment_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-COMMENT-QUERY-C02／4.2 的 comment_id；同名参数；必填值|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`READ_OK` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-COMMENT-QUERY-C02／4.4成功载荷投影，内部 UTC 时间转为约定字符串。anchor_ref_json 由能力转为公开 anchor_ref。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-COMMENT-QUERY-C02／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/comments/api.py`|`get_comment_http`|
|HTTP 请求与响应结构|`backend/app/comments/http_models.py`|`GetCommentRequest` / `GetCommentResponse`|


<a id="bnd-comment-api-i29"></a>
#### BND-COMMENT-API-I29 创建评论

|内容|确定定义|
|---|---|
|接口引用与名称|BND-COMMENT-API-I29 创建评论|
|方法与路径|`POST` `/api/v1/requirements/{requirement_id}/comments`|
|用途与响应方式|在当前正式正文的区块或选区上创建评论。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-COMMENT-CMD-C01](#app-comment-cmd-c01)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-COMMENT-CMD-C01／4.2 的 requirement_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-COMMENT-CMD-C01／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|
|`expected_content_version`|Body／integer|必传：是；可为null：否；未传：不适用|APP-COMMENT-CMD-C01／4.2 的 expected_content_version；同名参数；必填值|
|`content`|Body／string|必传：是；可为null：否；未传：不适用|APP-COMMENT-CMD-C01／4.2 的 content；同名参数；必填值|
|`anchor_type`|Body／string|必传：是；可为null：否；未传：不适用|APP-COMMENT-CMD-C01／4.2 的 anchor_type；同名参数；必填值|
|`block_id`|Body／integer|必传：是；可为null：否；未传：不适用|APP-COMMENT-CMD-C01／4.2 的 block_id；同名参数；必填值|
|`selection`|Body／object|必传：条件；可为null：是；未传：BLOCK 时 null|APP-COMMENT-CMD-C01／4.2 的 selection；同名参数；BLOCK 时 null（未传时）|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-COMMENT-CMD-C01／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`COMMENT_CREATED` → HTTP 201。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-COMMENT-CMD-C01／4.4成功载荷投影，内部 UTC 时间转为约定字符串。anchor_ref_json 由能力转为公开 anchor_ref。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`CONTENT_VERSION_CONFLICT`、`ANCHOR_INVALID`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`、`CAPACITY_EXHAUSTED`|逐项采用API-COM-ERROR|触发条件完整引用APP-COMMENT-CMD-C01／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/comments/api.py`|`create_comment_http`|
|HTTP 请求与响应结构|`backend/app/comments/http_models.py`|`CreateCommentRequest` / `CreateCommentResponse`|


<a id="bnd-comment-api-i30"></a>
#### BND-COMMENT-API-I30 编辑评论

|内容|确定定义|
|---|---|
|接口引用与名称|BND-COMMENT-API-I30 编辑评论|
|方法与路径|`PATCH` `/api/v1/comments/{comment_id}`|
|用途与响应方式|修改未解决评论的文字。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-COMMENT-CMD-C02](#app-comment-cmd-c02)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`comment_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-COMMENT-CMD-C02／4.2 的 comment_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-COMMENT-CMD-C02／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|
|`content`|Body／string|必传：是；可为null：否；未传：不适用|APP-COMMENT-CMD-C02／4.2 的 content；同名参数；必填值|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-COMMENT-CMD-C02／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`COMMENT_UPDATED` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-COMMENT-CMD-C02／4.4成功载荷投影，内部 UTC 时间转为约定字符串。anchor_ref_json 由能力转为公开 anchor_ref。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-COMMENT-CMD-C02／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/comments/api.py`|`edit_comment_http`|
|HTTP 请求与响应结构|`backend/app/comments/http_models.py`|`EditCommentRequest` / `EditCommentResponse`|


<a id="bnd-comment-api-i31"></a>
#### BND-COMMENT-API-I31 解决评论

|内容|确定定义|
|---|---|
|接口引用与名称|BND-COMMENT-API-I31 解决评论|
|方法与路径|`POST` `/api/v1/comments/{comment_id}/resolve`|
|用途与响应方式|将评论标记为已解决。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-COMMENT-CMD-C03](#app-comment-cmd-c03)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`comment_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-COMMENT-CMD-C03／4.2 的 comment_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-COMMENT-CMD-C03／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`COMMENT_UPDATED` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-COMMENT-CMD-C03／4.4成功载荷投影，内部 UTC 时间转为约定字符串。anchor_ref_json 由能力转为公开 anchor_ref。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-COMMENT-CMD-C03／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/comments/api.py`|`resolve_comment_http`|
|HTTP 请求与响应结构|`backend/app/comments/http_models.py`|`ResolveCommentRequest` / `ResolveCommentResponse`|


<a id="bnd-comment-api-i32"></a>
#### BND-COMMENT-API-I32 重新打开评论

|内容|确定定义|
|---|---|
|接口引用与名称|BND-COMMENT-API-I32 重新打开评论|
|方法与路径|`POST` `/api/v1/comments/{comment_id}/reopen`|
|用途与响应方式|将已解决评论重新设为未解决。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-COMMENT-CMD-C04](#app-comment-cmd-c04)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`comment_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-COMMENT-CMD-C04／4.2 的 comment_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-COMMENT-CMD-C04／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`COMMENT_UPDATED` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-COMMENT-CMD-C04／4.4成功载荷投影，内部 UTC 时间转为约定字符串。anchor_ref_json 由能力转为公开 anchor_ref。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-COMMENT-CMD-C04／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/comments/api.py`|`reopen_comment_http`|
|HTTP 请求与响应结构|`backend/app/comments/http_models.py`|`ReopenCommentRequest` / `ReopenCommentResponse`|


<a id="bnd-comment-api-i33"></a>
#### BND-COMMENT-API-I33 删除评论

|内容|确定定义|
|---|---|
|接口引用与名称|BND-COMMENT-API-I33 删除评论|
|方法与路径|`DELETE` `/api/v1/comments/{comment_id}`|
|用途与响应方式|软删除评论。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-COMMENT-CMD-C05](#app-comment-cmd-c05)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`comment_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-COMMENT-CMD-C05／4.2 的 comment_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-COMMENT-CMD-C05／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`COMMENT_UPDATED` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-COMMENT-CMD-C05／4.4成功载荷投影，内部 UTC 时间转为约定字符串。anchor_ref_json 由能力转为公开 anchor_ref。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-COMMENT-CMD-C05／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/comments/api.py`|`delete_comment_http`|
|HTTP 请求与响应结构|`backend/app/comments/http_models.py`|`DeleteCommentRequest` / `DeleteCommentResponse`|


<a id="bnd-guide-api-i34"></a>
#### BND-GUIDE-API-I34 从评论发起修改

|内容|确定定义|
|---|---|
|接口引用与名称|BND-GUIDE-API-I34 从评论发起修改|
|方法与路径|`POST` `/api/v1/comments/{comment_id}/guide-runs`|
|用途与响应方式|以评论为来源，在后端确定的锚点范围内接受修改任务。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-GUIDE-CMD-C05](#app-guide-cmd-c05)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`comment_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C05／4.2 的 comment_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C05／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|
|`expected_content_version`|Body／integer|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C05／4.2 的 expected_content_version；同名参数；必填值|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-GUIDE-CMD-C05／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`GUIDE_ACCEPTED` → HTTP 202。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-GUIDE-CMD-C05／4.4成功载荷投影，内部 UTC 时间转为约定字符串。final_result_json/scope_ref_json 由能力按安全投影转换，接口不直接序列化存储字段。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STATE_CONFLICT`、`WORK_STATE_CONFLICT`、`WORK_STATE_INCONSISTENT`、`CONTENT_VERSION_CONFLICT`、`COMMENT_ORPHANED`、`CONFIG_INVALID`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`、`CAPACITY_EXHAUSTED`|逐项采用API-COM-ERROR|触发条件完整引用APP-GUIDE-CMD-C05／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


接受后按返回的运行关联读取BND-GUIDE-API-I16，消息读取BND-MSG-API-I35；HTTP接受不表示模型成功或正文已经更新。

COMMENT_ORPHANED响应可能伴随已经提交的锚点状态校正；其完整边界见APP-GUIDE-CMD-C05／4.5。

**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/guide/api.py`|`modify_from_comment_http`|
|HTTP 请求与响应结构|`backend/app/guide/http_models.py`|`ModifyFromCommentRequest` / `ModifyFromCommentResponse`|


<a id="bnd-msg-api-i35"></a>
#### BND-MSG-API-I35 查询对话消息

|内容|确定定义|
|---|---|
|接口引用与名称|BND-MSG-API-I35 查询对话消息|
|方法与路径|`GET` `/api/v1/requirements/{requirement_id}/messages`|
|用途与响应方式|使用向前游标读取连续对话消息。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-MSG-QUERY-C01](#app-msg-query-c01)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`requirement_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-MSG-QUERY-C01／4.2 的 requirement_id；同名参数；必填值|
|`before_sequence_no`|Query／integer|必传：否；可为null：否；未传：读取最新 20 条|APP-MSG-QUERY-C01／4.2 的 before_sequence_no；解析后正整数；未传为 null|


不提交请求体，不要求Content-Type。

**响应与结果映射**

成功状态：`READ_OK` → HTTP 200。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-MSG-QUERY-C01／4.4成功载荷投影，内部 UTC 时间转为约定字符串。result.data.items → data.items；result.data.page_size/next_cursor/has_more → meta.pagination 的同名字段。structured_content_json 解码为 structured_content，按消息类型输出；坏结构仅按 I35 降级规则处理。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`|逐项采用API-COM-ERROR|触发条件完整引用APP-MSG-QUERY-C01／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/messages/api.py`|`list_messages_http`|
|HTTP 请求与响应结构|`backend/app/messages/http_models.py`|`ListMessagesRequest` / `ListMessagesResponse`|


<a id="bnd-msg-api-i36"></a>
#### BND-MSG-API-I36 提交整组卡片

|内容|确定定义|
|---|---|
|接口引用与名称|BND-MSG-API-I36 提交整组卡片|
|方法与路径|`POST` `/api/v1/conversation-messages/{message_id}/responses`|
|用途与响应方式|原子提交原消息的整组卡片回答，并推进对应运行。 一次性JSON响应。|
|公共契约|API-COM全部约定；只有下列参数与结果可用。|
|应用绑定|[APP-GUIDE-CMD-C06](#app-guide-cmd-c06)，输入见4.2、业务与结果见4.3—4.5。|


**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|`message_id`|Path／integer|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C06／4.2 的 message_id；同名参数；必填值|
|`Idempotency-Key`|Header／string|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C06／4.2 的 idempotency_key；请求头 Idempotency-Key，映射为应用字段 idempotency_key|
|`schema_version`|Body／integer|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C06／4.2 的 schema_version；同名参数；必填值|
|`responses`|Body／array[object]|必传：是；可为null：否；未传：不适用|APP-GUIDE-CMD-C06／4.2 的 responses；同名参数；必填值|


Body为JSON对象，允许的根字段仅为上表Body字段；嵌套字段完整采用APP-GUIDE-CMD-C06／4.2引用的结构。每层未知字段拒绝，不接收JSON字符串代替对象。

**响应与结果映射**

成功状态：`CARDS_ACCEPTED` → HTTP 202。应用结果编码仅用于分支判断。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|已登记成功结果|采用上列成功状态；不在响应根追加业务code|设置 success=true、error=null；result.data 中本接口的同名业务字段按APP-GUIDE-CMD-C06／4.4成功载荷投影，内部 UTC 时间转为约定字符串。写入本次 meta.request_id。|
|该能力拒绝与已知失败：`INVALID_INPUT`、`NOT_FOUND`、`SOURCE_INVALID`、`CARD_ALREADY_ANSWERED`、`CARD_EXPIRED`、`WORK_STATE_INCONSISTENT`、`CONFIG_INVALID`、`IDEMPOTENCY_CONFLICT`、`REQUEST_IN_PROGRESS`、`STORAGE_UNAVAILABLE`、`INTERNAL_ERROR`、`CAPACITY_EXHAUSTED`|逐项采用API-COM-ERROR|触发条件完整引用APP-GUIDE-CMD-C06／4.4；success=false，data=null，error及request_id必有，省略分页。|
|未预期异常、结果转换失败或未登记结果|500／INTERNAL_ERROR|仅安全错误；不返回内部细节。|


接受后按返回的运行关联读取BND-GUIDE-API-I16，消息读取BND-MSG-API-I35；HTTP接受不表示模型成功或正文已经更新。

**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/messages/api.py`|`submit_card_responses_http`|
|HTTP 请求与响应结构|`backend/app/messages/http_models.py`|`SubmitCardResponsesRequest` / `SubmitCardResponsesResponse`|


<a id="bnd-comment-api-i37"></a>
#### BND-COMMENT-API-I37 读取全文评论索引

|内容|确定定义|
|---|---|
|接口引用与名称|BND-COMMENT-API-I37 读取全文评论索引|
|方法与路径|`GET` `/api/v1/requirements/{requirement_id}/comment-index`|
|用途与响应方式|读取全文统计、正文区块标记和跨页定位索引；一次性JSON响应|
|公共契约|API-COM全部约定；无Body、Query或Idempotency-Key要求|
|应用绑定|[APP-COMMENT-QUERY-C03](#app-comment-query-c03)，输入见4.2，处理及结果见4.3/4.4|

**请求与输入绑定**

|参数或参数集合|位置及传输结构|必传、可空与缺失规则|应用输入映射及附加接入限制|
|---|---|---|---|
|requirement_id|Path／integer|必传：是；可null：否；未传：不适用|APP-COMMENT-QUERY-C03／4.2同名身份；规范十进制正安全整数文本|

不提交请求体，不要求Content-Type；未知Query参数按API-COM拒绝。

**响应与结果映射**

成功状态：`READ_OK` → HTTP 200。

|应用结果或边界失败|HTTP状态与外部编码|响应结构及字段转换|
|---|---|---|
|READ_OK|200|success=true、error=null；data为[CommentIndexReadModel](#commentindexreadmodel)全部字段；写本次meta.request_id，不返回meta.pagination|
|INVALID_INPUT|422／VALIDATION_FAILED|success=false、data=null；字段错误按API-COM-ERROR|
|NOT_FOUND|404／NOT_FOUND|需求不存在；安全错误、details=null|
|WORK_STATE_INCONSISTENT|409／WORK_STATE_INCONSISTENT|CURRENT关系不一致；不修复或猜造状态|
|STORAGE_UNAVAILABLE|503／STORAGE_UNAVAILABLE|存储不可用；不伪造空索引|
|INTERNAL_ERROR及未预期/转换异常|500／INTERNAL_ERROR|仅安全错误，data=null，不暴露内部细节|

**实现定位**

|实现职责|文件路径|函数或类型|
|---|---|---|
|请求解析、调用与响应转换|`backend/app/comments/api.py`|`get_comment_index_http`|
|HTTP请求与响应结构|`backend/app/comments/http_models.py`|`GetCommentIndexRequest` / `GetCommentIndexResponse`|

<a id="bnd-worker"></a>

### 6.4 BND-WORKER 后台执行与恢复入口

|内容|确定定义|
|---|---|
|入口与类型|BND-WORKER；服务进程内后台触发及启动、无进展监测入口，不是客户端HTTP接口|
|来源与触发|创建、继续或整组回答事务已提交的RUNNING运行交给后台推进；服务启动触发恢复；无进展监测触发超时恢复|
|接入与信任|guide_run_id、当前实际任务集合及operation_time均来自服务端可信上下文；不接受客户端伪造live_run_ids或恢复原因|
|推进输入与绑定|guide_run_id：SHR-ID，必须指向已提交运行；绑定APP-GUIDE-ORCH-C01同名输入。领取、重复触发去重及多执行者协调机制见[Q-08](#q-08)|
|恢复输入与绑定|APP-GUIDE-CMD-C09：recovery_reason为STARTUP或NO_PROGRESS；live_run_ids为本进程实际运行ID集合；operation_time为服务端UtcTime；均必传且不可null|
|结果与观察|编排返回AI_FINISHED、AI_WAITING_USER、AI_STOPPED或AI_FAILED；恢复返回RECOVERED或RECOVERY_NO_CHANGE，以及能力明确拒绝。外部通过I16运行、I35消息及对应正文、建议读取观察；没有另一份HTTP成功包装|

|输入失败、应用结果或入口异常|接收处置|执行时点与后续动作|
|---|---|---|
|业务事务未提交|不得启动模型请求|接受与执行必须分离；提交后才可推进|
|运行已取消或已终态|AI_STOPPED，不采用迟到结果|每次真实请求前及业务提交时重新判断；不得仅凭排队时状态写入|
|AI_WAITING_USER|保留运行及GUIDE_ACTIVE占用，暂停|等待显式继续；不自动过期、不自动继续、不累计用户等待为执行超时|
|AI_FAILED或确定中断|按APP-GUIDE-CMD-C08/C09记录安全错误、未结束调用状态并释放所属占用|保留已发生模型调用审计；不自动重发整个任务|
|存储或未预期异常|不伪装为成功；持久化后果按INF-TX与应用阶段判断|入口异常捕获、记录及进程关闭的具体机制见[Q-08](#q-08)、[Q-BASELINE](#q-baseline)；不得猜测资源已回滚|

**启动与监测补充**

|事项|确定定义|
|---|---|
|启动顺序|STARTUP恢复完成在接受新业务请求之前；数据库RUNNING且不在本进程任务集合中的运行按INTERRUPTED处理，不重发模型|
|无进展|仅RUNNING连续15分钟无进展进入EXECUTION_TIMEOUT；事务内重检，拒绝迟到业务写入|
|保留范围|WAITING_USER、人工草稿、待处理建议原样保留；终态占用只按C09唯一可信关联修复，缺失、跨需求或多个候选返回WORK_STATE_INCONSISTENT|
|时间计划|每30秒不重叠扫描，错过不并发补跑；15分钟为判断阈值，正常下一扫描检测，进程卡顿不承诺墙钟硬上限|
|实例与重叠|当前恢复依据是单进程实际集合；不能部署多个互不知情的进程并将对方任务判为中断。领取、租约、重叠与停止等待后的处置见[Q-08](#q-08)|
|重试组合|每call_no最多3次真实请求由APP-GUIDE-ORCH-C01控制；入口不得另加自动业务重试；Gateway单次1、SDK重试0|

入口实现定位：应用执行在`backend/app/guide/orchestrator.py :: execute_guide_run`，恢复在`backend/app/guide/commands.py :: recover_runs`；后台触发、监测及关闭在guide/worker.py::GuideWorker，由service.py绑定进程锁及执行租约。内部普通应用函数不是额外对外入口。

## 7. 数据存储与外部依赖

<a id="inf-db"></a>

### 7.1 INF-DB 数据库与聚合存储映射

|内容|确定定义|
|---|---|
|数据范围|第3章7个聚合根、9个实体全部持久字段，以及SHR-IDEMPOTENCY所要求的成功记录与处理状态|
|产品、版本、连接|Python 3.13.5内置SQLite、本机文件数据库；单进程、uvicorn单worker/no reload；默认data/wall-e.sqlite，WALLE_DATABASE_PATH可指定绝对路径|
|结构正式来源|逻辑结构按第3章；物理DDL位于backend/app/infrastructure/migrations/001_initial.sql至004_manual_identity_proofs.sql，当前结构版本4|
|关键配置|STRICT；WAL、foreign_keys=ON、synchronous=FULL、read_uncommitted=OFF、busy_timeout=5000ms；写BEGIN IMMEDIATE、读BEGIN；物理类型及迁移见本节|


<a id="sync-be-02"></a>

**SQLite物理存储和事务机制**

采用 STRICT 表；ID/版本/序号为有正安全整数 CHECK 的 INTEGER，UTC 毫秒时间及普通文本为 TEXT，JSON 为带合法性约束的 TEXT，SQL NULL 对应逻辑 null。DDL 位于 `backend/app/infrastructure/migrations/001_initial.sql` 至 `004_manual_identity_proofs.sql`，当前结构版本 4。第 3 章对象约束继续有效，多态来源和工作占用须由同事务应用复查，不只依赖外键。

连接启用 WAL、`foreign_keys=ON`、`synchronous=FULL`、`read_uncommitted=OFF`、`busy_timeout=5000ms`。写事务 `BEGIN IMMEDIATE`，一致查询 `BEGIN`；一次能力内 Repository 共用外层事务连接，禁止内部提前提交，Provider 请求在短事务之外。锁等待失败转换 STORAGE_UNAVAILABLE；提交异常与已知回滚区分，不因异常直接宣称未写入。

初始化/迁移核对版本与 SQL SHA-256；同版本只核验，未知、较新版本或结构不匹配拒绝。升级前使用 SQLite backup API 保存副本，迁移失败回滚，不删除旧数据或猜造历史。人工来源与身份证明的追加表见 [BE-08](#sync-be-08)/09。原对象不变字段、不可变消息/快照、唯一性和无默认值约束继续保留。

**确认依据**：D-003、D-008、D-009。**代码对应**：`infrastructure/database.py::{Database,CommitOutcomeUnknown}`、迁移 001—004、各 `*_repository.py`、`documents/guards.py`、`documents/sources.py`。

**对象与存储范围**

|对象或技术记录|Repository与关联键|持久化字段范围|未存储字段及恢复来源|
|---|---|---|---|
|OBJ-REQ.Requirement|INF-REQ-REP；id；模板以key+version定位|第3章Requirement全部字段；不可变身份、模板引用与工作占用同样保存|前端展示文本、可操作状态不作为额外事实字段|
|OBJ-DOC.RequirementDocument|INF-DOC-REP；id、requirement_id、document_type|第3章全部字段；markdown_content与block_state_json及content_version同一快照保存|编辑器临时节点和浏览器未确认内容不进入CURRENT|
|OBJ-REV.Revision|INF-REV-REP；id、requirement_id、version_no|第3章全部字段；Markdown与BlockState不可变快照|评论不属于Revision快照；读取名称转换见RevisionReadModel|
|OBJ-MSG.ConversationMessage|INF-MSG-REP；id、requirement_id、sequence_no、reply_to_message_id|第3章全部字段；消息创建后不可改|structured_content为structured_content_json解析投影；card_state在查询时推导，不反写消息|
|OBJ-GUIDE.GuideRun、LLMUse|INF-GUIDE-REP；根id，成员guide_run_id、call_no、attempt_no|第3章两个实体全部字段；每次真实请求独立审计|LLMUse没有独立业务写Repository；未知用量保留null，不补0；cost/cost_currency表示见第7.3节，当前未知为null|
|OBJ-BATCH.SuggestionBatch、Suggestion|INF-BATCH-REP；根id、guide_run_id，成员batch_id、order_no|第3章两个实体全部字段；固定补丁、目标、原内容与用户决定|counts由同一批次成员状态计算，不持久化为对象字段；Suggestion通过根访问修改|
|OBJ-COMMENT.Comment|INF-COMMENT-REP；id、requirement_id、block_id|第3章全部字段；原始anchor_ref_json与软删除deleted_at保留|location为读取投影；block_id是文档内身份，不能因Block暂失删除评论或级联消除孤立状态|
|幂等技术记录|SHR-IDEMPOTENCY及API-COM-IDEMPOTENCY的能力、完整目标、key范围|须能恢复原业务输入比较、进行中与原成功结果，且成功记录与业务数据同事务提交|物理字段及恢复按SHR-IDEMPOTENCY；成功永久保留，独占锁后清前进程未成功记录，不自动重执行业务|
|草稿基线manual_draft_context|INF-DOC-REP；draft_id关联MANUAL_DRAFT，current_document_id关联原CURRENT|base_content_version、baseline_block_state_json及operation_time；独立保留原CURRENT基线|完成时事务内复查原身份/版本；随草稿结束清理，不交换文档类型，见[基线规则](#sync-be-08)|
|人工来源manual_edit_sessions|以draft_id永久标识会话，关联同需求及原CURRENT|EDITING/COMPLETED/CANCELLED、started_at及closed_at；身份和开始时间不可改|开始与草稿同建，结束与草稿删除同事务关闭；永久保留最小来源、不保存会话正文，见[来源规则](#sync-be-08)|
|临时身份证明manual_block_allocation_ranges / manual_block_origins|同一draft_id；区间起点或block_id构成各自键|成功保存的高水位区间及服务器接受时间；实际出现新块的不可变创建事实|与草稿同事务，结束时清理；不展开大区间，不猜旧历史；CURRENT/Revision由永久会话证明来源，见[分配规则](#sync-be-09)|
|人工修改原因document_change_audits|关联需求、原CURRENT及编辑会话source_id|source_type=MANUAL_EDIT、reason_code=USER_MANUAL_EDIT、前后版本及服务器时间|仅ACTIVE人工完成且Markdown实际变化时同事务写入；不增加前端原因输入或I12字段，见[原因规则](#sync-be-08)|

**字段映射与约束**

物理映射已确定为本节[SQLite存储方案](#sync-be-02)：ID/版本/序号使用带正安全整数CHECK的INTEGER，UTC毫秒时间及文本使用TEXT，JSON使用带合法性约束的TEXT，空值使用SQL NULL；默认值生效位置和恢复校验遵守对象及创建能力。已有对象的“无默认值”不得被数据库默认值掩盖；创建时间、初始状态和初始版本由第4章对应创建能力赋值。JSON恢复必须还原所引用的完整逻辑结构，不得把损坏记录静默替换为合法空对象。消息损坏结构的只读降级仅按APP-MSG-QUERY-C01执行。

|必要约束|字段、条件与技术行为|对应要求|违反或失效时的结果|
|---|---|---|---|
|实体身份与需求编号|各实体id唯一；requirement_no唯一且不可变；分配原子性与耗尽见[Q-ID](#q-id)|SHR-ID、OBJ-REQ|不得产生重复合法对象；底层冲突向负责能力转换，不能覆盖原记录|
|文档类型唯一|requirement_id+document_type唯一；CURRENT和MANUAL_DRAFT为独立实例|OBJ-DOC-V01、APP-DOC-CMD-C01|并发创建只允许一份草稿，失败事务不留下占用或半份数据|
|历史序号与基线|requirement_id+version_no唯一；每需求最多一个BASELINE且version_no=1|OBJ-REV|竞争不覆盖快照；分配和创建处于所属事务|
|消息顺序与回答唯一|requirement_id+sequence_no唯一；每卡片组最多一个正式CARD_RESPONSE，且关联同需求|OBJ-MSG、APP-GUIDE-CMD-C06|并发回答不得产生第二个正式答案或重复运行；按幂等/已回答结果处理|
|真实请求尝试唯一|guide_run_id+call_no+attempt_no唯一，均为正整数|OBJ-GUIDE.LLMUse|不得合并两次真实请求或重复记录同一尝试；具体竞争技术见[Q-08](#q-08)/[Q-DB](#q-db)|
|建议批次与顺序|每GuideRun最多一个批次；batch_id+order_no唯一且正整数|OBJ-BATCH|禁止重复批次及无法确定应用顺序的成员|
|工作占用关联|非IDLE的类型、id、开始时间与同需求活动对象一致；IDLE三者全null|OBJ-REQ、SHR-CONCURRENCY|事务内不一致返回WORK_STATE_INCONSISTENT；只允许C09做明确恢复|
|评论关联|同锚点允许不同身份评论；软删除保留字段；锚点不随Block物理消失级联删除|OBJ-COMMENT|定位失效表达为ORPHANED；不能删除事实或强制迁往另一Block|

上述必须保证的唯一性需要实际数据库约束或可证明的原子机制；DDL实现见本节001—004迁移。普通性能索引与SQL组织由实现者决定，但不能改变第4章固定筛选、排序、分页和一致读取语义。

**初始化**

|事项|确定定义|
|---|---|
|结构与初始资源|须能承载上述对象与幂等记录，并取得固定模板、Function/Prompt/Schema资源；不产生示例业务需求作为默认事实|
|入口、空库与结构缺失|python -m backend.app.infrastructure.database init显式初始化；check只核验；正式启动不自动重建缺失结构|
|重复及版本不匹配|同版本核验SQL SHA-256及结构；未知、较新版本或结构不匹配拒绝；升级前SQLite backup API保存副本|
|失败与再执行|迁移失败回滚，不删除旧数据或猜造历史；再次执行先核验版本/结构；旧人工草稿来源或分配历史无法证明则拒绝迁移|

<a id="inf-req-rep"></a><a id="inf-doc-rep"></a><a id="inf-rev-rep"></a><a id="inf-msg-rep"></a><a id="inf-guide-rep"></a><a id="inf-batch-rep"></a><a id="inf-comment-rep"></a>

实现定位：INF-REQ-REP、INF-DOC-REP、INF-REV-REP、INF-MSG-REP、INF-GUIDE-REP、INF-BATCH-REP、INF-COMMENT-REP分别服务于上表聚合；对象字段/快照/来源验证位置在各对象3.5。适配器在backend/app/infrastructure/*_repository.py，DDL在同目录migrations/001—004；不另造Repository方法。

<a id="inf-tx"></a><a id="inf-read"></a>

### 7.2 INF-TX、INF-READ 关键读写与一致性保证

|访问或保证|输入、作用范围与执行语义|成功结果|失败、冲突或未知结果|
|---|---|---|---|
|命令短事务|按APP-EXEC-COMMON及各4.5列出的对象共同写入；各Repository共享本次事务连接/上下文，不各自提前提交|只有外层提交成功才代表持久完成|任一映射、写入或提交失败，不保留部分多对象写入；确切隔离与锁策略见[Q-DB](#q-db)|
|内部锚点重校验|APP-COMMENT-CMD-C06加入正文提交事务；更改anchor_status而不伪改updated_at|正文与评论锚点结果同时提交|重校验失败导致所属正文事务失败；无自行嵌套提交。单独来源评论校正例外见下一行|
|评论来源失效校正|APP-GUIDE-CMD-C05发现来源无法定位时，只提交该评论ORPHANED校正，再拒绝创建运行|已明确允许的部分完成，不创建Run或正文变化|该拒绝不能套用“一切拒绝绝不写入”；其余事务后果仍按能力定义|
|版本与占用原子比较|事务内重读目标CURRENT或MANUAL_DRAFT版本及占用，再执行受保护写入|仅满足版本和状态者提交；版本递增按对应能力|CONTENT_VERSION_CONFLICT、WORK_STATE_CONFLICT或INCONSISTENT按实际原因区分；不得先查后无条件写。原子实现见[Q-DB](#q-db)|
|完整文档保存|Markdown、BlockState、版本同一写入范围；完成人工编辑写回原CURRENT身份并删除草稿、释放占用|读取恢复同一快照；不得交换类型替代提交|失败不出现半份快照；不把未知响应判为“未保存”|
|不可变快照和消息|Revision、ConversationMessage创建后不更新；GuideRun冻结协议及成员固定字段遵守第3章|恢复时字段意义保持|不通过写时“修复”篡改历史事实|
|一致查询|INF-READ按第4章查询条件、稳定排序和投影读取；需要items/total或建议counts一致时保证同一读取结果|只读模型，不暴露ORM或原始审计；无副作用|对象不存在与合法空列表区分；损坏、存储不可用不伪装空成功；技术快照采用BEGIN一致读事务|
|安全查询绑定|用户值作为绑定参数；枚举、字段与排序仅用已定义允许集合|标题中的%和_按字面包含，不扩大查询含义|未知枚举、非法页码/游标被拒绝；不得拼接不受控SQL|
|幂等成功提交|幂等成功记录与业务写入同一事务；原键原输入重复取原结果|不重复分配资源或调用模型|中间态、保留与崩溃策略见[Q-03](#q-03)；不能用相似输入猜测已执行|
|提交结果未知|连接断开等导致无法确认提交的情况需与已知回滚区分；客户端依具体资源读取及原请求复查|确知后按原成功结果或实际现状继续|未核实前不宣称回滚；应用/存储适配的未知结果类型及恢复机制见[Q-DB](#q-db)、[Q-03](#q-03)|

数据库连接由infrastructure/database.py管理；写BEGIN IMMEDIATE、读BEGIN快照、共享外层连接，锁等待5秒失败映射STORAGE_UNAVAILABLE，未知提交用CommitOutcomeUnknown区分。这里保留应用要求的原子结果，不将其表述为已验证的技术事实。Provider调用位于短事务外，不能把Provider已发生用量作为数据库回滚内容。实现位置同7.1及各应用4.8。

<a id="inf-model"></a>

### 7.3 INF-MODEL 模型网关与 INF-PROFILE 配置

|内容|确定定义|
|---|---|
|依赖与用途|INF-MODEL接收4.7冻结任务形成的非流式Chat Completions请求；只取得模型结果，不直接执行正文采用或业务提交|
|协议及SDK|非流式，一次请求返回assistant.content；不启用Tool Calling。供应方、端点、SDK和精确版本及兼容证据见[Q-07](#q-07)|
|连接与认证|由正式模型配置提供；密钥不得进入快照、日志或对外错误。变量名、有效配置来源与覆盖优先级见[Q-07](#q-07)|
|能力依据|正式模型及实用准入按本节Profile及第4.7节v3策略；provider_compatibility_proved=false，不具备通用封装上界证明；JSON Schema由程序验证，不等于供应方原生支持全部限制|

|使用能力|内部输入与外部请求映射|内部输出与响应映射|技术失败与完成范围|
|---|---|---|---|
|一次真实模型请求|4.7的System协议及按冻结ContextTemplate组装的数据；Function/Schema/Scope权限由程序决定。精确消息字段和参数集见[Q-02](#q-02)/[Q-07](#q-07)|仅assistant.content进入单一JSON解析；原始响应、调用状态、Provider请求标识及可得用量进入LLMUse；解析与业务校验分阶段记录|认证/权限/余额/输入过长/安全拒绝与网络/限流/服务端暂时失败分类由编排处理；错误不转换为空合法业务结果|
|逻辑取消|接收应用取消事实并尝试关闭连接；不能承诺供应方停止|迟到结果仍受Run终态与PERSISTING门禁限制，不采用|可能已经计费用量，不能退款、回滚或无条件补发|

|调用事项|确定定义|
|---|---|
|超时|连接10秒、读取180秒；无进展15分钟由运行恢复负责，等待用户不计入；SDK具体计时绑定见[Q-07](#q-07)|
|真实请求次数|Gateway一次调用只发一次；SDK自动重试0；APP-GUIDE-ORCH-C01每call_no最多3次，包含首次请求；不允许网关嵌套放大|
|可重试类别|网络暂时失败、超时、限流、服务端暂时失败、解析或输出校验失败共用3次额度；重试前重检Run与占用；间隔见[Q-07](#q-07)|
|不可重试类别|认证、权限、余额、配额、模型未开通、输入超长、安全拒绝、取消、业务状态变化及v3计数/实际usage复核失败直接结束；不换模型绕过限制|
|未知结果|超时或断开不证明供应方未执行；保留该真实请求LLMUse。再次尝试产生新attempt_no及独立记录，外部用量不作回滚|
|调用记录|请求发送前先短事务提交本次LLMUse开始记录；保留实际配置快照、读取清单、传输/解析/校验状态、可取得用量及耗时；未知用量为null。reasoning不进入消息、final_result或trusted_output；脱敏与保留见[Q-09](#q-09)|
|备用策略|无备用自动切换；旧Doubao Profile仅验证历史，不用于失败降级；配置缺失/失效CONFIG_INVALID|

<a id="inf-profile"></a>


<a id="sync-be-18"></a>

**正式模型、参数、错误映射和密钥来源**

默认正式模型为火山方舟北京端点上的 `deepseek-v4-1-flash-260910`，版本 `260910`；Chat 端点为 `https://ark.cn-beijing.volces.com/api/v3/chat/completions`。旧 `doubao-seed-2-1-pro-260915`/260915 保留精确 Profile 用于历史核对，不是失败备用模型。Profile 只接受已批准 model/version/端点组合；同一逻辑调用不换模型，历史请求按原快照恢复。

通过 httpx 非流式两角色 System/User 调用，thinking.disabled、temperature=0、max_tokens=8192、stream=false，不加工具或任意任务参数。连接/读/写/池超时分别为 10/180/10/10 秒；Gateway 一次、传输重试 0；ORCH 每 call_no 最多 3 次 Chat，间隔 2/5 秒，原重试与取消条件保留，[BE-19](#sync-be-19) 的实际用量拒绝不重试。

错误按精确供应方 code 白名单优先分类，认证/权限/余额/配额/模型未开通/输入超长/安全拒绝等不可重试，暂时网络/超时/429/指定临时 5xx 可按总额度重试，未知 code 不根据报错文字猜。配置变量为 `WALLE_MODEL_BASE_URL/ID/VERSION/API_KEY`，不接受任意端点/模型。密钥来自启动子进程环境；显式 `tools/ai-service.py --start` 在环境缺 key 时只按单赋值数据解析本机忽略的 `.env.local`，不执行文件、不回显或持久导出 key；基础入口不自动加载该文件。

**确认依据**：D-006/007 为旧模型决定，D-014 正式切换，D-015 准入；[DeepSeek 正式接入稿](../proposals/deepseek-production-v1.md)。**代码对应**：`infrastructure/{model_profile,model_gateway,local_credentials}.py`、`guide/orchestrator.py`、`tools/ai-service.py`。


<a id="sync-be-20"></a>

**外部追踪ID、费用和审计保留**

`provider_request_id` 为 nullable Text，原值保存，最多 1024 码点，不转整数、不截断。费用字段为 nullable `cost`（定点十进制字符串）和 `cost_currency`；费用与币种成对存在或均 null，只依据供应方明确给出的计费事实，不根据 token、价格表或 cache 推算，不把未知填 0。当前网关没有取得费用，正常审计写入两者均 null；不能写成已实现自动计费统计。不得自拟金额小数位或币种。

原始请求/响应保存前递归剔除认证字段及 reasoning/reasoning_content 等敏感推理字段，实际密钥及其可逆表示不得留存。非法 assistant.content 可私有诊断保存，不对外暴露。nullable raw_response_json/parsed_output_json 满 30 天后清空；必要请求快照、协议、Read Manifest、用量和可信结果长期保留，仍可能含敏感业务文本。只允许本机数据库权限主体读取，没有新增 HTTP 审计接口；备份须按同一保留策略管理，不能把在线清理描述成自动清理所有离线备份。

**确认依据**：D-005，公共决策稿 C。**代码对应**：迁移 001 的 llm_uses 列/费用配对 CHECK；`infrastructure/{audit_data,audit_repository,model_gateway}.py`、`guide/worker.py`。独立计数审计清理见 `infrastructure/counting_journal.py`。

**模型配置 INF-PROFILE**

|内容|确定定义|
|---|---|
|模型标识、版本与参数来源|deepseek-v4-1-flash-260910/260910，经Ark北京端点，固定参数按本节模型配置；每次调用保存实际快照|
|已定配置|thinking.disabled、temperature=0、max_tokens=8192、stream=false，无Tool；httpx连接/读/写/池10/180/10/10秒；传输重试0、Gateway每次1|
|任务级覆盖|Function、Prompt、上下文及Schema采用4.7冻结版本；不允许任意任务参数覆盖固定Profile，不透传用户或模型参数|

依赖实现定位：业务调用责任在`backend/app/guide/orchestrator.py :: execute_guide_run`；Gateway、Profile、Tokenization及实际usage验证分别位于infrastructure/model_gateway.py、model_profile.py、tokenization.py、practical_usage.py；provider_request_id按Text原值保存。

<a id="inf-template"></a><a id="inf-function"></a>

### 7.4 INF-TEMPLATE、INF-FUNCTION 固定版本资源

|内容|确定定义|
|---|---|
|依赖类型与范围|固定模板、Function、Prompt、输入/输出Schema及ContextTemplate资源；不是新的对外文件上传或消息队列|
|模板身份|template_key+template_version共同定位；需求创建时校验类型适用性，创建后不替换；实际目录、完整骨架及锁定规则见[Q-01](#q-01)|
|任务资源身份|新运行Function/Prompt/Context为v2，十份输入/输出Schema及模板自身仍v1；旧运行按原冻结版本恢复，不原地修改历史|
|数据结构与编码|输出Schema使用Draft 2020-12，各层对象additionalProperties=false，单个JSON对象及互斥response_type；完整Prompt、输入和输出字段、预算及文件内容见[Q-02](#q-02)，不能仅用资源名代替协议|


<a id="sync-be-06"></a>

**正式模板和初始化结构锁**

正式目录为 `templates/catalog.v1.json`，NEW 使用 `new-requirement@v1`，CHANGE 使用 `change-requirement@v1`；完整 Markdown 和锁定标题列表分别引用同目录模板 `.md/.json`，不得根据摘要重建模板。需求创建后 key/version 不变。INITIALIZING 锁定标题文本、级别、相对顺序和原 block_id，允许补写标题下内容；ACTIVE 解除结构锁。未知信息保持“待确认”，模板占位不构成业务事实。模板随固定资源发布并校验，不新增配置 HTTP 接口。

**确认依据**：D-004/005，D-010 保留原模板版本。**代码对应**：`backend/resources/v2/templates/`、`infrastructure/resources.py::ResourceCatalog.template`、`requirements/commands.py`、`documents/patch_application.py`、前端 `documents/template-lock.ts`。

|技术操作|输入与范围|成功输出及保证|失败与完成范围|
|---|---|---|---|
|读取需求模板|创建输入的type、template_key、template_version|返回适用的固定模板；创建完整模板骨架，INITIALIZING期间锁定模板主结构，完成初始化后解除该结构锁定；未知事实保持未知，不删减必需结构|不存在或不适用TEMPLATE_INVALID；不回退另一模板|
|冻结运行协议|程序依据ActionType、SourceType和初始化模式选择Function映射；引用4.7 AI01—AI06|冻结function_type、context_template_key/version及prompt_version；同Run继续沿用，用户重跑另建Run重新冻结|配置缺失或无效CONFIG_INVALID；模型不能改Function或权限|
|恢复冻结资源|使用Run已记录的版本读取内容|同一版本内容不被原地替换；Builder依准确协议组装|缺失直接CONFIG_INVALID，不用“最新版本”替换|
|解析与校验资源|依冻结Schema校验输入、单一JSON输出和业务分支|只有传输、解析、Schema和状态/Scope/目标/对象校验全部通过的产物进入C07|不去围栏、不猜字段、不删未知字段、不补默认值；按编排额度重生成或失败|

完整资源位于[历史v1目录](../../backend/resources/v1/)和[正式v2目录](../../backend/resources/v2/)，新运行映射见[functions.v2.json](../../backend/resources/v2/functions.v2.json)，完整输入/输出定义见[v2 schemas目录](../../backend/resources/v2/schemas/)，上下文与Prompt见[contexts](../../backend/resources/v2/contexts/)及[prompts](../../backend/resources/v2/prompts/)；由ResourceCatalog和Manifest校验全部内容，缺失/签名不符CONFIG_INVALID；运行触发和交付机制属于BND-WORKER／[Q-08](#q-08)，不凭空增加消息队列或跨资源事务。


<a id="backend-acceptance"></a>

## 8. 验证与验收

执行记录约定：只在docs/verification/*.md记录日期、规格/实现版本、环境、范围、方法、结果、失败原因及未覆盖项；不留存测试JSON、截图、录像或原始日志。实际浏览器观察、焦点、几何、颜色及故障判定要求保留，正常业务数据库/审计不作测试报告删除。本次文档合并不执行这些场景。

### 8.1 验收场景

本章规定实现必须提供的验证证据，不记录当前通过率。每个场景独立准备和清理数据，不依赖上一用例。正文中的未决协议、物理存储和AI资源使相关场景暂不可执行；解决对应Q事项后，用同一规格目标实施，不降低要求。

**测试数据与生成规则**

以下编号与时间只用于可重建的验收夹具，不是产品默认值。T0=2026-09-21T08:30:00.000Z；需求id=101、编号REQ000001；CURRENT id=201，草稿id=202，版本快照id=301，运行id=501，消息id从601递增，批次id=701，建议id从801递增，评论id从901递增。每次隔离数据库可重用这些值；真实创建入口生成的ID则以响应关联继续断言，不强迫实现分配指定ID。幂等键使用合法UUID v4 `00000000-0000-4000-8000-000000000001`，第二个键尾数为2。

|夹具|独立生成规则|
|---|---|
|F-A 活跃需求|建立满足OBJ-REQ的ACTIVE需求、固定模板引用和BASELINE序号1；CURRENT版本3。正文取已确认模板完整骨架，在其中一个paragraph放入“审批人为部门经理。”；BlockState按SHR-BLOCK与该正文一一对应。模板及解析按第7.4节与SHR-BLOCK固定资源版本，不能用简化骨架绕过合法性。工作状态IDLE、活动引用及state_started_at全null|
|F-I 初始化需求|从独立数据准备INITIALIZING需求，无BASELINE；其余可重建字段同F-A；初始化模式IDEATION。此处不依赖F-A先执行|
|F-D 人工编辑|独立建立F-A事实，再建立MANUAL_DRAFT id=202、content_version=1，继承CURRENT区块身份和来源；占用MANUAL_EDITING/MANUAL_DRAFT/202及开始时间T0。变化版本2时正文仅在指定段落增加“时限为2天。”并同步BlockState|
|F-C 评论|独立F-A正文，评论content=“请说明审批人”，OPEN、ATTACHED，created_at=updated_at=T0，resolved_at/deleted_at=null；BLOCK锚点取该段，SELECTION取唯一“部门经理”，其上下文来自CURRENT。其他状态场景逐个改变与状态相应的时间字段，保留原锚点|
|F-G 运行|独立F-A或F-I；Run id=501、RUNNING/PREPARING、call_no=1，冻结4.7允许的Function/Prompt/Schema/ContextTemplate组合；需求占用GUIDE_ACTIVE/GUIDE_RUN/501。完成分支、等待分支和取消分支按各场景建立一致关联；模型资源受[Q-02](#q-02)约束|
|F-B 建议|独立F-A；MODIFY运行已完成，至少两项建议，批次PENDING、base_content_version=3，需求占用SUGGESTION_REVIEWING/SUGGESTION_BATCH/701；目标与original_content来自CURRENT。分别准备合法区块替换、表格行替换/追加、删除以及不相容组合；精确Patch内容按SHR-PATCH，算法按SHR-PATCH|
|F-K 卡片|独立准备同需求助手INTERACTION_CARDS；card_key为c1、c2，选项键o1、o2，问题分别“审批人是否确定？”与“是否补充时限？”，所有说明字段为可见文本；c1为required=true单选，c2为required=false单选；selection_rule min/max=1，custom_answer.enabled=false/max_length=0，recommendation=null，related_spec_context=[]。合法回答c1选择o1；c2分别选择o2或显式skipped=true、空选项、custom_answer=null。扩展到1/5张及越界0/6张时按相同规则产生唯一键|
|F-M 消息|建立同需求序号1～45，每条content为“消息N”；按消息角色/类型补齐第3章约束。查询无游标应返回26～45，有before_sequence_no=26返回6～25，再取before=6返回1～5且has_more=false、next_cursor=null；空查询也返回null游标。结构损坏用旧记录注入，仅验证读取降级，不把它作为合法创建输入|
|F-L 列表|独立创建41条合法需求；含NEW/CHANGE、三种status和四种document_work_state的合法组合；前两条updated_at相同以检查id降序平局。标题包含“A%_甲”“a甲”，编号分别REQ000001/REQ000002；测试大小写、%/_字面匹配、组合过滤、空结果与page=4越界；每页20条|
|F-FIELD 边界变体|每个接口字段以4.2/6.2所列合法集合为基准：依次缺失、null、错误JSON类型、未知字段、重复键；整数用0、1、9007199254740991及其上界外值、boolean；page用0/1/100000/100001；文本按该字段最大码点n生成“甲”×n及×(n+1)，另用非BMP字符验证码点计数，使用空白、CRLF、内部换行；枚举逐一允许值和一个未登记值。只改变本例目标条件，其余满足相应能力前置|

**对象有效性场景**

对每项约束分别运行有效实例，以及只破坏该约束的实例：唯一性用两个相同组合键，状态约束用每个合法状态及错配字段，时间用T0与T0前1毫秒，引用用同需求、跨需求和不存在目标。预期来自第3章，不调用被测对象生成预期值。数据库唯一性另按8.2使用真实存储验证。


|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-REQ-OBJ-01|OBJ-REQ／OBJ-REQ-V01|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|id与requirement_no不可变且不同；编号满足SHR-ID；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-REQ-OBJ-02|OBJ-REQ／OBJ-REQ-V02|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|经SHR-TEXT标准化后1～20个字符且无换行；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-REQ-OBJ-03|OBJ-REQ／OBJ-REQ-V03|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|需求类型来自配置；template_key+template_version共同定位固定模板，创建后不替换；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-REQ-OBJ-04|OBJ-REQ／OBJ-REQ-V04|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|status为INITIALIZING/ACTIVE/COMPLETED；COMPLETED必须有completed_at，其余为null；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-REQ-OBJ-05|OBJ-REQ／OBJ-REQ-V05|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|IDLE的active_operation_type/id/state_started_at全部null；MANUAL_EDITING对应MANUAL_DRAFT；GUIDE_ACTIVE对应GUIDE_RUN；SUGGESTION_REVIEWING对应SUGGESTION_BATCH；非IDLE引用与开始时间非空；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-REQ-OBJ-06|OBJ-REQ／OBJ-REQ-V06|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|initialization_mode为IDEATION或DESIGN；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-DOC-OBJ-01|OBJ-DOC／OBJ-DOC-V01|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|document_type为CURRENT或MANUAL_DRAFT；同需求同类型唯一；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-DOC-OBJ-02|OBJ-DOC／OBJ-DOC-V02|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|markdown_content与block_state_json描述同一时点、同顺序的顶层区块；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-DOC-OBJ-03|OBJ-DOC／OBJ-DOC-V03|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|content_version为正整数；CURRENT和MANUAL_DRAFT分别计数；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-DOC-OBJ-04|OBJ-DOC／OBJ-DOC-V04|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|BlockState符合SHR-BLOCK；每区块身份唯一，next_block_id大于全部当前ID；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-DOC-OBJ-05|OBJ-DOC／OBJ-DOC-V05|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|创建时间不晚于最近修改时间；作者及来源合法；已有创建来源不可改；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-REV-OBJ-01|OBJ-REV／OBJ-REV-V01|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|requirement_id+version_no唯一；version_no正整数；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-REV-OBJ-02|OBJ-REV／OBJ-REV-V02|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|BASELINE为version_no=1；每需求最多一条；其他类型MANUAL；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-REV-OBJ-03|OBJ-REV／OBJ-REV-V03|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|Markdown快照与区块快照同一时点；source_content_version为正整数；创建后所有字段不可变；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-MSG-OBJ-01|OBJ-MSG／OBJ-MSG-V01|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|requirement_id+sequence_no唯一且正整数；创建后消息不可变；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-MSG-OBJ-02|OBJ-MSG／OBJ-MSG-V02|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|USER或ASSISTANT；TEXT/INTERACTION_CARDS/CARD_RESPONSE；卡片组只属ASSISTANT、响应只属USER；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-MSG-OBJ-03|OBJ-MSG／OBJ-MSG-V03|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|TEXT的structured_content_json与reply_to_message_id为null；卡片组结构完整；CARD_RESPONSE必须指同需求助手卡片组；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-MSG-OBJ-04|OBJ-MSG／OBJ-MSG-V04|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|每条卡片组至多一条CARD_RESPONSE；答案满足SHR-CARDS；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-MSG-OBJ-05|OBJ-MSG／OBJ-MSG-V05|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|用户提交的消息有idempotency_key；助手消息为null；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-GUIDE-OBJ-01|OBJ-GUIDE／OBJ-GUIDE-V01|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|Action/Source/Function组合符合INF-FUNCTION；INITIALIZE有mode_snapshot；非初始化模式为空；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-GUIDE-OBJ-02|OBJ-GUIDE／OBJ-GUIDE-V02|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|context_template_key/version及prompt_version创建后不变；function_type不得被模型改变；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-GUIDE-OBJ-03|OBJ-GUIDE／OBJ-GUIDE-V03|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|COMPLETED/FAILED/CANCELLED有ended_at；FAILED有安全error_code/message；CANCELLED有cancel_reason；取消不产生final_result_json；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-GUIDE-OBJ-04|OBJ-GUIDE／OBJ-GUIDE-V04|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|LLMUse只属于一个GuideRun；guide_run_id+call_no+attempt_no唯一；序号为正整数；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-GUIDE-OBJ-05|OBJ-GUIDE／OBJ-GUIDE-V05|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|call_status与parse_status、validation_status分别表示传输、解析和校验；trusted_output_json仅在validation_status=SUCCEEDED时非空；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-GUIDE-OBJ-06|OBJ-GUIDE／OBJ-GUIDE-V06|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|retry_of_guide_run_id不能指自身，须同需求更早的FAILED运行；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-GUIDE-OBJ-07|OBJ-GUIDE／OBJ-GUIDE-V07|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|Token与duration_ms为非负整数或null；未知不填0；cost/cost_currency成对或均null，仅使用供应方明确费用，不从token推算；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-BATCH-OBJ-01|OBJ-BATCH／OBJ-BATCH-V01|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|至少一条Suggestion；同GuideRun最多一批且来源必须为MODIFY；Suggestion只能随根访问修改；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-BATCH-OBJ-02|OBJ-BATCH／OBJ-BATCH-V02|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|Suggestion状态为PENDING/ACCEPTED/REJECTED/EDITED；EDITED有合法user_edited_content；其他不用它作为应用内容；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-BATCH-OBJ-03|OBJ-BATCH／OBJ-BATCH-V03|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|PENDING/COMPLETED/DISCARDED；COMPLETED有CHANGES_APPLIED或NO_CHANGE；只有CHANGES_APPLIED有applied_content_version；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-BATCH-OBJ-04|OBJ-BATCH／OBJ-BATCH-V04|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|base_content_version正整数；order_no在批次内唯一且正整数；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-BATCH-OBJ-05|OBJ-BATCH／OBJ-BATCH-V05|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|patch_operation属于SHR-PATCH支持集合；目标和内容结构必须匹配操作；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-BATCH-OBJ-06|OBJ-BATCH／OBJ-BATCH-V06|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|counts是读取结果，不是持久化对象字段；total等于四类单项状态数量之和；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-COMMENT-OBJ-01|OBJ-COMMENT／OBJ-COMMENT-V01|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|SHR-TEXT标准化后1～2000字符，纯文本可换行；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-COMMENT-OBJ-02|OBJ-COMMENT／OBJ-COMMENT-V02|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|anchor_type为BLOCK或SELECTION；block_id正整数；anchor_ref符合SHR-ANCHOR；不得含指纹；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-COMMENT-OBJ-03|OBJ-COMMENT／OBJ-COMMENT-V03|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|status为OPEN/RESOLVED；anchor_status为ATTACHED/ORPHANED；两维独立；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-COMMENT-OBJ-04|OBJ-COMMENT／OBJ-COMMENT-V04|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|RESOLVED有resolved_at；OPEN为null；deleted_at非空表示软删除；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|
|TC-COMMENT-OBJ-05|OBJ-COMMENT／OBJ-COMMENT-V05|第3章该对象完整字段；本节F-A/F-D/F-C/F-G/F-B/F-K中相应对象，按上述单约束变体生成|构造、变更或恢复对象；涉及不可变字段时尝试更改；唯一性用竞争创建|requirement_id固定；同一锚点允许多条不同身份评论；有效实例保持该约束，违反者不能形成合法对象或覆盖既有事实|对象测试；涉及持久关系时真实数据库集成（8.2）|


**应用能力场景**

每项能力的结果场景采用下列前置基础，按本能力4.3中产生该结果的进入条件作独立参数变体；每一条明确拒绝条件单独触发。各场景执行完整顶层能力，记录code/data/details及事务前后数据，不仅Mock返回结果码。测试用模型响应由4.7正式Schema构造；所有分支以冻结完整Schema构造，不得自行编造或放宽通过样本。

除已列结果外，每项命令还参数化验证其4.4全部声明且在路径实际触发的拒绝与已知失败，以及4.5的回滚/并发条件；逐个注入到对应检查或写入点。查询则验证4.6全部筛选、排序、空结果与损坏数据处理。拒绝不改数据的通用结论以SHR-RESULT为准，包含C05锚点校正这一明确例外。


**APP-REQ-CMD-C01 创建需求**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-REQ-CMD-C01-01 CREATED|APP-REQ-CMD-C01／4.3—4.6|空测试需求集合；title=“需求甲”、type=NEW、idea=“整理报销需求”、initialization_mode=IDEATION；模板取已确认且适用于NEW的固定资源（[Q-01](#q-01)）；结果变体取4.3中通向CREATED的明确条件|调用APP-REQ-CMD-C01；按产生CREATED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回Requirement、CURRENT id、GuideRun id；仅表示创建及接受AI任务；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-REQ-CMD-C01-02 TEMPLATE_INVALID|APP-REQ-CMD-C01／4.3—4.6|空测试需求集合；title=“需求甲”、type=NEW、idea=“整理报销需求”、initialization_mode=IDEATION；模板取已确认且适用于NEW的固定资源（[Q-01](#q-01)）；结果变体取4.3中通向TEMPLATE_INVALID的明确条件|调用APP-REQ-CMD-C01；按产生TEMPLATE_INVALID的步骤执行；有写事务时在各共同写入点另行注入存储失败|模板不存在或不适用于所选需求类型；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/requirements/test_create_requirement.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-REQ-CMD-C02 修改需求**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-REQ-CMD-C02-01 UPDATED|APP-REQ-CMD-C02／4.3—4.6|F-A或F-I；title原为“需求甲”，分别提交“需求乙”、原值；合法仅title；结果变体取4.3中通向UPDATED的明确条件|调用APP-REQ-CMD-C02；按产生UPDATED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回更新后的Requirement；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-REQ-CMD-C02-02 IMMUTABLE_MODE|APP-REQ-CMD-C02／4.2—4.5、OBJ-REQ.initialization_mode|INITIALIZING／ACTIVE／COMPLETED及各占用；记录原title、mode、updated_at及已存在运行快照|直接命令收到仅模式、同值模式、标题＋模式、缺title或null；合法标题另在不同占用下提交|非法输入INVALID_INPUT且事实不变；合法标题保持INITIALIZING／ACTIVE许可，同值不写updated_at；COMPLETED拒绝；不迁移旧数据|隔离应用／HTTP基础检查，既有实际检查见迭代V2第13—14节；本次未新执行|

验证定位：`backend/tests/requirements/test_commands.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-REQ-CMD-C03 完成初始化**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-REQ-CMD-C03-01 INITIALIZATION_COMPLETED|APP-REQ-CMD-C03／4.3—4.6|F-I，IDLE；CURRENT版本=3；expected_content_version=3；无BASELINE；结果变体取4.3中通向INITIALIZATION_COMPLETED的明确条件|调用APP-REQ-CMD-C03；按产生INITIALIZATION_COMPLETED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回Requirement、baseline_revision和current_document身份/版本；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/requirements/test_initialization.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-REQ-CMD-C04 完成需求**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-REQ-CMD-C04-01 REQUIREMENT_COMPLETED|APP-REQ-CMD-C04／4.3—4.6|F-A，IDLE；CURRENT版本=3；expected_content_version=3；结果变体取4.3中通向REQUIREMENT_COMPLETED的明确条件|调用APP-REQ-CMD-C04；按产生REQUIREMENT_COMPLETED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回Requirement；正文、版本记录不变；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/requirements/test_lifecycle.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-REQ-CMD-C05 重新激活需求**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-REQ-CMD-C05-01 REACTIVATED|APP-REQ-CMD-C05／4.3—4.6|F-A改为COMPLETED且completed_at=T0，IDLE；结果变体取4.3中通向REACTIVATED的明确条件|调用APP-REQ-CMD-C05；按产生REACTIVATED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回Requirement；CURRENT及其版本不变；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/requirements/test_lifecycle.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-DOC-CMD-C01 开始人工编辑**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-DOC-CMD-C01-01 DRAFT_STARTED|APP-DOC-CMD-C01／4.3—4.6|F-A，IDLE，CURRENT版本=3；expected_content_version=3；结果变体取4.3中通向DRAFT_STARTED的明确条件|调用APP-DOC-CMD-C01；按产生DRAFT_STARTED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回草稿和需求占用；编辑器改为读取草稿；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/documents/test_commands.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-DOC-CMD-C02 保存人工草稿**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-DOC-CMD-C02-01 DRAFT_SAVED|APP-DOC-CMD-C02／4.3—4.6|F-D；草稿版本=1；完整Markdown/BlockState成对变化；expected_content_version=1；结果变体取4.3中通向DRAFT_SAVED的明确条件|调用APP-DOC-CMD-C02；按产生DRAFT_SAVED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回后端确认的草稿和版本；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/documents/test_commands.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-DOC-CMD-C03 完成人工编辑**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-DOC-CMD-C03-01 DRAFT_COMPLETED|APP-DOC-CMD-C03／4.3—4.6|F-D；草稿最新已确认版本=2；expected_content_version=2；CURRENT版本=3；评论使用F-C；结果变体取4.3中通向DRAFT_COMPLETED的明确条件|调用APP-DOC-CMD-C03；按产生DRAFT_COMPLETED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回完整CURRENT；不自动创建Revision；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/documents/test_commands.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-DOC-CMD-C04 取消人工编辑**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-DOC-CMD-C04-01 DRAFT_CANCELLED|APP-DOC-CMD-C04／4.3—4.6|F-D；expected_content_version=1；分别测试匹配、陈旧和原请求重放；结果变体取4.3中通向DRAFT_CANCELLED的明确条件|调用APP-DOC-CMD-C04；按产生DRAFT_CANCELLED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回requirement_id、manual_draft_id及cancelled=true；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/documents/test_commands.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-REV-CMD-C01 保存手动版本**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-REV-CMD-C01-01 REVISION_CREATED|APP-REV-CMD-C01／4.3—4.6|F-A，IDLE，已有BASELINE序号1；CURRENT版本=3；description=“人工版本”；结果变体取4.3中通向REVISION_CREATED的明确条件|调用APP-REV-CMD-C01；按产生REVISION_CREATED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回Revision摘要；CURRENT和评论不变；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/revisions/test_commands.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-COMMENT-CMD-C01 创建评论**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-COMMENT-CMD-C01-01 COMMENT_CREATED|APP-COMMENT-CMD-C01／4.3—4.6|F-A，CURRENT版本=3；content=“请说明审批人”；分别BLOCK和唯一单Block选区锚点；结果变体取4.3中通向COMMENT_CREATED的明确条件|调用APP-COMMENT-CMD-C01；按产生COMMENT_CREATED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回Comment；CURRENT、区块状态、Revision不变；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-COMMENT-CMD-C01-02 ANCHOR_INVALID|APP-COMMENT-CMD-C01／4.3—4.6|F-A，CURRENT版本=3；content=“请说明审批人”；分别BLOCK和唯一单Block选区锚点；结果变体取4.3中通向ANCHOR_INVALID的明确条件|调用APP-COMMENT-CMD-C01；按产生ANCHOR_INVALID的步骤执行；有写事务时在各共同写入点另行注入存储失败|区块不存在、跨区块或选区不能唯一定位；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/comments/test_commands.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-COMMENT-CMD-C02 编辑评论**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-COMMENT-CMD-C02-01 COMMENT_UPDATED|APP-COMMENT-CMD-C02／4.3—4.6|F-C，未软删除；content由“请说明审批人”改为“请说明审批人与时限”；结果变体取4.3中通向COMMENT_UPDATED的明确条件|调用APP-COMMENT-CMD-C02；按产生COMMENT_UPDATED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回当前Comment；不改正文或Revision；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/comments/test_commands.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-COMMENT-CMD-C03 解决评论**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-COMMENT-CMD-C03-01 COMMENT_UPDATED|APP-COMMENT-CMD-C03／4.3—4.6|F-C；分别OPEN、RESOLVED及ATTACHED/ORPHANED组合；结果变体取4.3中通向COMMENT_UPDATED的明确条件|调用APP-COMMENT-CMD-C03；按产生COMMENT_UPDATED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回当前Comment；不改正文或Revision；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/comments/test_commands.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-COMMENT-CMD-C04 重新打开评论**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-COMMENT-CMD-C04-01 COMMENT_UPDATED|APP-COMMENT-CMD-C04／4.3—4.6|F-C；分别RESOLVED和已OPEN；resolved_at有值/null与状态一致；结果变体取4.3中通向COMMENT_UPDATED的明确条件|调用APP-COMMENT-CMD-C04；按产生COMMENT_UPDATED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回当前Comment；不改正文或Revision；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/comments/test_commands.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-COMMENT-CMD-C05 删除评论**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-COMMENT-CMD-C05-01 COMMENT_UPDATED|APP-COMMENT-CMD-C05／4.3—4.6|F-C；分别未删和deleted_at=T0，保留原请求与幂等键；结果变体取4.3中通向COMMENT_UPDATED的明确条件|调用APP-COMMENT-CMD-C05；按产生COMMENT_UPDATED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回当前Comment；不改正文或Revision；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/comments/test_commands.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-COMMENT-CMD-C06 重校验评论锚点**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-COMMENT-CMD-C06-01 ANCHORS_UPDATED|APP-COMMENT-CMD-C06／4.3—4.6|F-C；开启正文写事务；准备原Block存在且可唯一定位、Block删除、选区重复，以及原Block重新可定位的快照；结果变体取4.3中通向ANCHORS_UPDATED的明确条件|调用APP-COMMENT-CMD-C06；按产生ANCHORS_UPDATED的步骤执行；有写事务时在各共同写入点另行注入存储失败|全部未删除评论与新正文对应；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/comments/test_revalidate_anchors.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-BATCH-CMD-C01 处理建议决策**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-BATCH-CMD-C01-01 SUGGESTION_DECIDED|APP-BATCH-CMD-C01／4.3—4.6|F-B；同一建议分别决定ACCEPTED、REJECTED、EDITED；EDITED使用符合该操作的内容；结果变体取4.3中通向SUGGESTION_DECIDED的明确条件|调用APP-BATCH-CMD-C01；按产生SUGGESTION_DECIDED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回Suggestion和counts；CURRENT不变；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-BATCH-CMD-C01-02 PATCH_INVALID|APP-BATCH-CMD-C01／4.3—4.6|F-B；同一建议分别决定ACCEPTED、REJECTED、EDITED；EDITED使用符合该操作的内容；结果变体取4.3中通向PATCH_INVALID的明确条件|调用APP-BATCH-CMD-C01；按产生PATCH_INVALID的步骤执行；有写事务时在各共同写入点另行注入存储失败|编辑后内容不符合本建议操作的结构；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/suggestions/test_decision.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-BATCH-CMD-C02 完成建议批次**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-BATCH-CMD-C02-01 BATCH_APPLIED|APP-BATCH-CMD-C02／4.3—4.6|F-B；expected_content_version、CURRENT.content_version与base_content_version均为3；分别全拒绝、含接受、含编辑及保留一项PENDING；结果变体取4.3中通向BATCH_APPLIED的明确条件|调用APP-BATCH-CMD-C02；按产生BATCH_APPLIED的步骤执行；有写事务时在各共同写入点另行注入存储失败|整批产生一次CURRENT更新；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-BATCH-CMD-C02-02 BATCH_NO_CHANGE|APP-BATCH-CMD-C02／4.3—4.6|F-B；expected_content_version、CURRENT.content_version与base_content_version均为3；分别全拒绝、含接受、含编辑及保留一项PENDING；结果变体取4.3中通向BATCH_NO_CHANGE的明确条件|调用APP-BATCH-CMD-C02；按产生BATCH_NO_CHANGE的步骤执行；有写事务时在各共同写入点另行注入存储失败|所有建议拒绝或最终无实际变化；CURRENT版本不变；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-BATCH-CMD-C02-03 BATCH_PENDING|APP-BATCH-CMD-C02／4.3—4.6|F-B；expected_content_version、CURRENT.content_version与base_content_version均为3；分别全拒绝、含接受、含编辑及保留一项PENDING；结果变体取4.3中通向BATCH_PENDING的明确条件|调用APP-BATCH-CMD-C02；按产生BATCH_PENDING的步骤执行；有写事务时在各共同写入点另行注入存储失败|仍存在未决Suggestion；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-BATCH-CMD-C02-04 TARGET_STALE|APP-BATCH-CMD-C02／4.3—4.6|F-B；expected_content_version、CURRENT.content_version与base_content_version均为3；分别全拒绝、含接受、含编辑及保留一项PENDING；结果变体取4.3中通向TARGET_STALE的明确条件|调用APP-BATCH-CMD-C02；按产生TARGET_STALE的步骤执行；有写事务时在各共同写入点另行注入存储失败|目标不存在或原内容/权限不再匹配；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-BATCH-CMD-C02-05 PATCH_INVALID|APP-BATCH-CMD-C02／4.3—4.6|F-B；expected_content_version、CURRENT.content_version与base_content_version均为3；分别全拒绝、含接受、含编辑及保留一项PENDING；结果变体取4.3中通向PATCH_INVALID的明确条件|调用APP-BATCH-CMD-C02；按产生PATCH_INVALID的步骤执行；有写事务时在各共同写入点另行注入存储失败|Patch结构或组合不能合法应用；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/suggestions/test_complete.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-BATCH-CMD-C03 放弃建议批次**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-BATCH-CMD-C03-01 BATCH_DISCARDED|APP-BATCH-CMD-C03／4.3—4.6|F-B；PENDING批次；分别首次与原请求重复放弃；结果变体取4.3中通向BATCH_DISCARDED的明确条件|调用APP-BATCH-CMD-C03；按产生BATCH_DISCARDED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回批次和counts；CURRENT及来源Comment不变；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/suggestions/test_discard.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-GUIDE-CMD-C01 创建AI运行**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-GUIDE-CMD-C01-01 GUIDE_ACCEPTED|APP-GUIDE-CMD-C01／4.3—4.6|F-A或F-I，IDLE；CURRENT版本=3；action/source/scope按本能力4.2允许组合分别参数化；instruction=“检查当前需求”；结果变体取4.3中通向GUIDE_ACCEPTED的明确条件|调用APP-GUIDE-CMD-C01；按产生GUIDE_ACCEPTED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回新GuideRun id/status/current_step及用户消息；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-GUIDE-CMD-C01-02 SCOPE_INVALID|APP-GUIDE-CMD-C01／4.3—4.6|F-A或F-I，IDLE；CURRENT版本=3；action/source/scope按本能力4.2允许组合分别参数化；instruction=“检查当前需求”；结果变体取4.3中通向SCOPE_INVALID的明确条件|调用APP-GUIDE-CMD-C01；按产生SCOPE_INVALID的步骤执行；有写事务时在各共同写入点另行注入存储失败|范围无效或引用不能确定；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-GUIDE-CMD-C01-03 SOURCE_INVALID|APP-GUIDE-CMD-C01／4.3—4.6|F-A或F-I，IDLE；CURRENT版本=3；action/source/scope按本能力4.2允许组合分别参数化；instruction=“检查当前需求”；结果变体取4.3中通向SOURCE_INVALID的明确条件|调用APP-GUIDE-CMD-C01；按产生SOURCE_INVALID的步骤执行；有写事务时在各共同写入点另行注入存储失败|来源不属于本需求或不是已完成REVIEW结果；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-GUIDE-CMD-C01-04 CONFIG_INVALID|APP-GUIDE-CMD-C01／4.3—4.6|F-A或F-I，IDLE；CURRENT版本=3；action/source/scope按本能力4.2允许组合分别参数化；instruction=“检查当前需求”；结果变体取4.3中通向CONFIG_INVALID的明确条件|调用APP-GUIDE-CMD-C01；按产生CONFIG_INVALID的步骤执行；有写事务时在各共同写入点另行注入存储失败|冻结协议资源缺失或无效；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/guide/test_acceptance.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-GUIDE-CMD-C02 继续等待中的运行**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-GUIDE-CMD-C02-01 GUIDE_CONTINUED|APP-GUIDE-CMD-C02／4.3—4.6|F-G改为WAITING_USER且占用仍指该Run；instruction=“审批人为部门经理”；结果变体取4.3中通向GUIDE_CONTINUED的明确条件|调用APP-GUIDE-CMD-C02；按产生GUIDE_CONTINUED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回同一GuideRun id；继续使用冻结协议；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/guide/test_acceptance.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-GUIDE-CMD-C03 取消AI运行**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-GUIDE-CMD-C03-01 GUIDE_CANCELLED|APP-GUIDE-CMD-C03／4.3—4.6|F-G；分别PREPARING、调用中及PERSISTING；取消后再请求一次；结果变体取4.3中通向GUIDE_CANCELLED的明确条件|调用APP-GUIDE-CMD-C03；按产生GUIDE_CANCELLED的步骤执行；有写事务时在各共同写入点另行注入存储失败|业务层不再采用输出；已保存消息和历史调用保留；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/guide/test_cancel.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-GUIDE-CMD-C04 重新运行失败任务**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-GUIDE-CMD-C04-01 GUIDE_RETRY_ACCEPTED|APP-GUIDE-CMD-C04／4.3—4.6|F-G改为FAILED并释放占用；来源、范围仍有效；重复失败运行保持原记录；结果变体取4.3中通向GUIDE_RETRY_ACCEPTED的明确条件|调用APP-GUIDE-CMD-C04；按产生GUIDE_RETRY_ACCEPTED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回新运行；原FAILED运行不可改回RUNNING；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-GUIDE-CMD-C04-02 SCOPE_INVALID|APP-GUIDE-CMD-C04／4.3—4.6|F-G改为FAILED并释放占用；来源、范围仍有效；重复失败运行保持原记录；结果变体取4.3中通向SCOPE_INVALID的明确条件|调用APP-GUIDE-CMD-C04；按产生SCOPE_INVALID的步骤执行；有写事务时在各共同写入点另行注入存储失败|原范围不能映射到当前正文；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-GUIDE-CMD-C04-03 SOURCE_INVALID|APP-GUIDE-CMD-C04／4.3—4.6|F-G改为FAILED并释放占用；来源、范围仍有效；重复失败运行保持原记录；结果变体取4.3中通向SOURCE_INVALID的明确条件|调用APP-GUIDE-CMD-C04；按产生SOURCE_INVALID的步骤执行；有写事务时在各共同写入点另行注入存储失败|评论或REVIEW来源已失效；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/guide/test_retry.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-GUIDE-CMD-C05 从评论发起修改**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-GUIDE-CMD-C05-01 GUIDE_ACCEPTED|APP-GUIDE-CMD-C05／4.3—4.6|F-C，OPEN且未删，F-A/IDLE；分别可定位与无法定位来源；expected_content_version=3；结果变体取4.3中通向GUIDE_ACCEPTED的明确条件|调用APP-GUIDE-CMD-C05；按产生GUIDE_ACCEPTED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回Run；前端不可覆盖评论正文、来源或可写范围；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-GUIDE-CMD-C05-02 COMMENT_ORPHANED|APP-GUIDE-CMD-C05／4.3—4.6|F-C，OPEN且未删，F-A/IDLE；分别可定位与无法定位来源；expected_content_version=3；结果变体取4.3中通向COMMENT_ORPHANED的明确条件|调用APP-GUIDE-CMD-C05；按产生COMMENT_ORPHANED的步骤执行；有写事务时在各共同写入点另行注入存储失败|锚点失效，不创建消息和运行；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/guide/test_comment_acceptance.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-GUIDE-CMD-C06 提交整组卡片**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-GUIDE-CMD-C06-01 CARDS_ACCEPTED|APP-GUIDE-CMD-C06／4.3—4.6|F-K；完整覆盖所有card_key的responses；INITIALIZE已完成卡片组和其他动作WAITING_USER分别准备；结果变体取4.3中通向CARDS_ACCEPTED的明确条件|调用APP-GUIDE-CMD-C06；按产生CARDS_ACCEPTED的步骤执行；有写事务时在各共同写入点另行注入存储失败|返回正式响应、运行id/status和ANSWERED状态；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-GUIDE-CMD-C06-02 CARD_ALREADY_ANSWERED|APP-GUIDE-CMD-C06／4.3—4.6|F-K；完整覆盖所有card_key的responses；INITIALIZE已完成卡片组和其他动作WAITING_USER分别准备；结果变体取4.3中通向CARD_ALREADY_ANSWERED的明确条件|调用APP-GUIDE-CMD-C06；按产生CARD_ALREADY_ANSWERED的步骤执行；有写事务时在各共同写入点另行注入存储失败|已存在正式响应，不覆盖已有答案；返回已有响应的安全引用；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-GUIDE-CMD-C06-03 CARD_EXPIRED|APP-GUIDE-CMD-C06／4.3—4.6|F-K；完整覆盖所有card_key的responses；INITIALIZE已完成卡片组和其他动作WAITING_USER分别准备；结果变体取4.3中通向CARD_EXPIRED的明确条件|调用APP-GUIDE-CMD-C06；按产生CARD_EXPIRED的步骤执行；有写事务时在各共同写入点另行注入存储失败|该组卡片已不再属于当前待回复流程；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-GUIDE-CMD-C06-04 SOURCE_INVALID|APP-GUIDE-CMD-C06／4.3—4.6|F-K；完整覆盖所有card_key的responses；INITIALIZE已完成卡片组和其他动作WAITING_USER分别准备；结果变体取4.3中通向SOURCE_INVALID的明确条件|调用APP-GUIDE-CMD-C06；按产生SOURCE_INVALID的步骤执行；有写事务时在各共同写入点另行注入存储失败|来源不是有效助手卡片组；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/guide/test_cards.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-GUIDE-CMD-C07 提交可信AI结果**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-GUIDE-CMD-C07-01 AI_RESULT_PERSISTED|APP-GUIDE-CMD-C07／4.3—4.6|F-G；4.7各分支的可信输出；Schema与完整产物按第4.7节冻结资源；状态、来源、版本按提交前真实值重检；结果变体取4.3中通向AI_RESULT_PERSISTED的明确条件|调用APP-GUIDE-CMD-C07；按产生AI_RESULT_PERSISTED的步骤执行；有写事务时在各共同写入点另行注入存储失败|业务结果完整提交；仅此结果可向用户展示正式产物；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-GUIDE-CMD-C07-02 OUTPUT_INVALID|APP-GUIDE-CMD-C07／4.3—4.6|F-G；4.7各分支的可信输出；Schema与完整产物按第4.7节冻结资源；状态、来源、版本按提交前真实值重检；结果变体取4.3中通向OUTPUT_INVALID的明确条件|调用APP-GUIDE-CMD-C07；按产生OUTPUT_INVALID的步骤执行；有写事务时在各共同写入点另行注入存储失败|输出分支、权限或内容校验不成立；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/guide/test_result_persistence.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-GUIDE-CMD-C08 记录运行失败**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-GUIDE-CMD-C08-01 RUN_FAILED|APP-GUIDE-CMD-C08／4.3—4.6|F-G及一条已开始未结束LLMUse；传入安全错误分类；另准备已终态Run；结果变体取4.3中通向RUN_FAILED的明确条件|调用APP-GUIDE-CMD-C08；按产生RUN_FAILED的步骤执行；有写事务时在各共同写入点另行注入存储失败|失败已持久化，允许用户重新运行；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-GUIDE-CMD-C08-02 RUN_FINAL_UNCHANGED|APP-GUIDE-CMD-C08／4.3—4.6|F-G及一条已开始未结束LLMUse；传入安全错误分类；另准备已终态Run；结果变体取4.3中通向RUN_FINAL_UNCHANGED的明确条件|调用APP-GUIDE-CMD-C08；按产生RUN_FINAL_UNCHANGED的步骤执行；有写事务时在各共同写入点另行注入存储失败|未覆盖已经形成的终态；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/guide/test_fail.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-GUIDE-CMD-C09 恢复中断与超时占用**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-GUIDE-CMD-C09-01 RECOVERED|APP-GUIDE-CMD-C09／4.3—4.6|独立准备RUNNING无本进程任务、RUNNING无进展15分钟、WAITING_USER、人工草稿、PENDING批次和终态占用组合；operation_time=T0+15分钟；结果变体取4.3中通向RECOVERED的明确条件|调用APP-GUIDE-CMD-C09；按产生RECOVERED的步骤执行；有写事务时在各共同写入点另行注入存储失败|已修复可确定的中断或终态占用；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-GUIDE-CMD-C09-02 RECOVERY_NO_CHANGE|APP-GUIDE-CMD-C09／4.3—4.6|独立准备RUNNING无本进程任务、RUNNING无进展15分钟、WAITING_USER、人工草稿、PENDING批次和终态占用组合；operation_time=T0+15分钟；结果变体取4.3中通向RECOVERY_NO_CHANGE的明确条件|调用APP-GUIDE-CMD-C09；按产生RECOVERY_NO_CHANGE的步骤执行；有写事务时在各共同写入点另行注入存储失败|等待用户、待处理批次和人工草稿原样保留；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/guide/test_recovery.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-GUIDE-ORCH-C01 推进AI运行**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-GUIDE-ORCH-C01-01 AI_FINISHED|APP-GUIDE-ORCH-C01／4.3—4.6|F-G；可控Gateway按场景返回合格、解析失败、校验失败、技术异常；记录每次真实请求与LLMUse；结果变体取4.3中通向AI_FINISHED的明确条件|调用APP-GUIDE-ORCH-C01；按产生AI_FINISHED的步骤执行；有写事务时在各共同写入点另行注入存储失败|Run完成，用户通过轮询和消息/正文查询观察；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-GUIDE-ORCH-C01-02 AI_WAITING_USER|APP-GUIDE-ORCH-C01／4.3—4.6|F-G；可控Gateway按场景返回合格、解析失败、校验失败、技术异常；记录每次真实请求与LLMUse；结果变体取4.3中通向AI_WAITING_USER的明确条件|调用APP-GUIDE-ORCH-C01；按产生AI_WAITING_USER的步骤执行；有写事务时在各共同写入点另行注入存储失败|原Run等待补充，持续占用；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-GUIDE-ORCH-C01-03 AI_STOPPED|APP-GUIDE-ORCH-C01／4.3—4.6|F-G；可控Gateway按场景返回合格、解析失败、校验失败、技术异常；记录每次真实请求与LLMUse；结果变体取4.3中通向AI_STOPPED的明确条件|调用APP-GUIDE-ORCH-C01；按产生AI_STOPPED的步骤执行；有写事务时在各共同写入点另行注入存储失败|取消或终态先获胜，没有迟到业务写入；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|
|TC-GUIDE-ORCH-C01-04 AI_FAILED|APP-GUIDE-ORCH-C01／4.3—4.6|F-G；可控Gateway按场景返回合格、解析失败、校验失败、技术异常；记录每次真实请求与LLMUse；结果变体取4.3中通向AI_FAILED的明确条件|调用APP-GUIDE-ORCH-C01；按产生AI_FAILED的步骤执行；有写事务时在各共同写入点另行注入存储失败|运行失败并保留审计；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/guide/test_orchestrator.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-REQ-QUERY-C01 查询需求列表**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-REQ-QUERY-C01-01 READ_OK|APP-REQ-QUERY-C01／4.3—4.6|F-A、F-I及F-L；对照存在与不存在id；结果变体取4.3中通向READ_OK的明确条件|调用APP-REQ-QUERY-C01；按产生READ_OK的步骤执行；有写事务时在各共同写入点另行注入存储失败|items含id、requirement_no、title、requirement_type、status、updated_at；分页放边界meta.pagination；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/requirements/test_queries.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-REQ-QUERY-C02 查询需求详情**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-REQ-QUERY-C02-01 READ_OK|APP-REQ-QUERY-C02／4.3—4.6|F-A、F-I及F-L；对照存在与不存在id；结果变体取4.3中通向READ_OK的明确条件|调用APP-REQ-QUERY-C02；按产生READ_OK的步骤执行；有写事务时在各共同写入点另行注入存储失败|Requirement全部业务字段和活动类型/ID；不嵌套正文；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/requirements/test_queries.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-DOC-QUERY-C01 读取当前正文**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-DOC-QUERY-C01-01 READ_OK|APP-DOC-QUERY-C01／4.3—4.6|F-A及F-D，CURRENT与草稿身份和版本不同；结果变体取4.3中通向READ_OK的明确条件|调用APP-DOC-QUERY-C01；按产生READ_OK的步骤执行；有写事务时在各共同写入点另行注入存储失败|id、requirement_id、document_type、markdown_content、block_state_json对象、content_version、created_at、updated_at；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/documents/test_queries.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-DOC-QUERY-C02 读取人工草稿**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-DOC-QUERY-C02-01 READ_OK|APP-DOC-QUERY-C02／4.3—4.6|F-A及F-D，CURRENT与草稿身份和版本不同；结果变体取4.3中通向READ_OK的明确条件|调用APP-DOC-QUERY-C02；按产生READ_OK的步骤执行；有写事务时在各共同写入点另行注入存储失败|与CURRENT同构的DocumentReadModel，document_type=MANUAL_DRAFT；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/documents/test_queries.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-REV-QUERY-C01 查询版本列表**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-REV-QUERY-C01-01 READ_OK|APP-REV-QUERY-C01／4.3—4.6|F-A；BASELINE序号1、MANUAL序号2及3，快照正文不同；结果变体取4.3中通向READ_OK的明确条件|调用APP-REV-QUERY-C01；按产生READ_OK的步骤执行；有写事务时在各共同写入点另行注入存储失败|id、requirement_id、version_no、revision_type、description、source_content_version、created_at；不返回正文；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/revisions/test_queries.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-REV-QUERY-C02 读取版本快照**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-REV-QUERY-C02-01 READ_OK|APP-REV-QUERY-C02／4.3—4.6|F-A；BASELINE序号1、MANUAL序号2及3，快照正文不同；结果变体取4.3中通向READ_OK的明确条件|调用APP-REV-QUERY-C02；按产生READ_OK的步骤执行；有写事务时在各共同写入点另行注入存储失败|Revision字段；markdown_snapshot映射markdown_content，block_state_snapshot_json映射block_state_json对象；不含当前评论或当前正文；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/revisions/test_queries.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-COMMENT-QUERY-C01 查询评论列表**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-COMMENT-QUERY-C01-01 READ_OK|APP-COMMENT-QUERY-C01／4.3—4.6|F-C；OPEN/RESOLVED、ATTACHED/ORPHANED及已软删除记录；列表超过20条；结果变体取4.3中通向READ_OK的明确条件|调用APP-COMMENT-QUERY-C01；按产生READ_OK的步骤执行；有写事务时在各共同写入点另行注入存储失败|未删除Comment字段；anchor_ref_json映射anchor_ref；每条可定位信息由SHR-ANCHOR只读计算；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/comments/test_queries.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-COMMENT-QUERY-C02 读取评论详情**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-COMMENT-QUERY-C02-01 READ_OK|APP-COMMENT-QUERY-C02／4.3—4.6|F-C；OPEN/RESOLVED、ATTACHED/ORPHANED及已软删除记录；列表超过20条；结果变体取4.3中通向READ_OK的明确条件|调用APP-COMMENT-QUERY-C02；按产生READ_OK的步骤执行；有写事务时在各共同写入点另行注入存储失败|Comment字段含deleted_at，anchor_ref解析为对象；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/comments/test_queries.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-BATCH-QUERY-C01 读取建议批次**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-BATCH-QUERY-C01-01 READ_OK|APP-BATCH-QUERY-C01／4.3—4.6|F-B；四种建议状态各有成员，order_no与id顺序刻意不同；结果变体取4.3中通向READ_OK的明确条件|调用APP-BATCH-QUERY-C01；按产生READ_OK的步骤执行；有写事务时在各共同写入点另行注入存储失败|SuggestionBatch字段、全部Suggestion与counts；counts由此次读取的明细推导；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/suggestions/test_queries.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-GUIDE-QUERY-C01 读取运行状态**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-GUIDE-QUERY-C01-01 READ_OK|APP-GUIDE-QUERY-C01／4.3—4.6|F-G；RUNNING/WAITING_USER/COMPLETED/FAILED/CANCELLED及不同action运行；内部上下文另外准备应排除的草稿、未采用建议和原始审计；结果变体取4.3中通向READ_OK的明确条件|调用APP-GUIDE-QUERY-C01；按产生READ_OK的步骤执行；有写事务时在各共同写入点另行注入存储失败|id、requirement_id、action_type、function_type、source_type/source_id、scope、status、current_step、安全final_result、suggestion_batch_id、最近助手消息id、安全错误、运行时间；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/guide/test_queries.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-GUIDE-QUERY-C02 查询运行历史**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-GUIDE-QUERY-C02-01 READ_OK|APP-GUIDE-QUERY-C02／4.3—4.6|F-G；RUNNING/WAITING_USER/COMPLETED/FAILED/CANCELLED及不同action运行；内部上下文另外准备应排除的草稿、未采用建议和原始审计；结果变体取4.3中通向READ_OK的明确条件|调用APP-GUIDE-QUERY-C02；按产生READ_OK的步骤执行；有写事务时在各共同写入点另行注入存储失败|运行摘要字段，同详情但排除完整final_result与所有LLMUse；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/guide/test_history.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-GUIDE-QUERY-C03 读取模型业务上下文**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-GUIDE-QUERY-C03-01 READ_OK|APP-GUIDE-QUERY-C03／4.3—4.6|F-G；RUNNING/WAITING_USER/COMPLETED/FAILED/CANCELLED及不同action运行；内部上下文另外准备应排除的草稿、未采用建议和原始审计；结果变体取4.3中通向READ_OK的明确条件|调用APP-GUIDE-QUERY-C03；按产生READ_OK的步骤执行；有写事务时在各共同写入点另行注入存储失败|CURRENT快照、授权范围、所需模板/正式用户消息/当前来源；携带实际读取清单；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/guide/test_model_context.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**APP-MSG-QUERY-C01 查询对话消息**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-MSG-QUERY-C01-01 READ_OK|APP-MSG-QUERY-C01／4.3—4.6|F-M；消息序号1～45，包含TEXT、合法卡片与回答及结构损坏历史记录；结果变体取4.3中通向READ_OK的明确条件|调用APP-MSG-QUERY-C01；按产生READ_OK的步骤执行；有写事务时在各共同写入点另行注入存储失败|消息字段及解析后的结构化内容、卡片推导状态；无总数；损坏结构只用content降级并禁用卡片；data/details及持久后果采用本能力4.4；失败后不保留未声明的部分写入|应用自动化；多对象/版本/唯一性用8.2实际存储；外部模型采用可控响应|

验证定位：`backend/tests/messages/test_queries.py`；完整场景按[验收场景映射](../验收场景映射.md)核对。


**HTTP接口场景**

TC-HTTP-Ixx-PARAM、BIND、ERROR、IDEM采用以下四组公共过程。Ixx仅替换被测入口编号；各接口适用项和专属项在其下表展开，公共过程不另改变业务规则。

|过程|前置条件与输入|操作或故障|必须独立观察|
|---|---|---|---|
|PARAM|相应能力前置夹具；F-FIELD对本入口所有字段及嵌套结构生成变体；数组额外测试空数组、重复项、JSON字符串冒充对象|通过真实HTTP解析层发送；重复JSON键以原始报文发送，不能先用字典消除重复；重复Query按单值与筛选数组分别测试|合法映射；每项非法基础输入在能力前拒绝；缺失与null、Bool与Int不混同；具体错误采用6.1/6.2，不擅自统一为同一码|
|BIND|能力输入中的每个来源字段赋可辨识值；能力桩分别返回本入口全部成功结果的完整结构和一个未登记结果码|捕获唯一顶层能力调用，检查参数转换；检查HTTP成功投影、UTC毫秒、null与省略层级；另注入转换异常|只调用指定能力；无额外字段或原始审计泄漏；未登记码和转换异常500 INTERNAL_ERROR；AI接受与最终结果分离|
|ERROR|逐项取6.2该入口已知错误集合，能力返回相应安全details；另注入未预期异常|逐个调用HTTP入口并比对公共映射|状态码及error.code准确；success=false、data=null、error/meta.request_id存在且无分页；不泄漏密钥、堆栈、原始模型响应|
|IDEM|带Idempotency-Key的入口使用两个键及原输入；同一动作输入改变一个业务字段；在提交前和提交后响应发送前设故障点|同键同输入重放；同键不同输入；并发进行中；提交后丢响应再以原键原输入请求|原业务结果重放，不重复副作用；冲突和REQUEST_IN_PROGRESS正确；每次HTTP有新的request_id；真实存储证明成功记录与业务提交原子性，按[已确认持久幂等规则](#sync-be-04)实际验证前不可声称已通过|

接口测试定位保持原定的`backend/tests/shared/（对应test_http_*.py）；完整场景按验收场景映射核对`至`test_36.py`；对应应用测试采用上方能力定位。普通协议转换可用能力桩；专属事务、占用和持久后果必须实际调用应用及存储。


**BND-REQ-API-I01**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I01-PARAM|BND-REQ-API-I01；APP-REQ-QUERY-C01|相应F-A、F-I及F-L；对照存在与不存在id；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I01-BIND|BND-REQ-API-I01；APP-REQ-QUERY-C01|相应F-A、F-I及F-L；对照存在与不存在id；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I01-ERROR|BND-REQ-API-I01；APP-REQ-QUERY-C01|相应F-A、F-I及F-L；对照存在与不存在id；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I01-SPECIAL-1|BND-REQ-API-I01；APP-REQ-QUERY-C01|F-A、F-I及F-L；对照存在与不存在id；专属输入分支见右侧预期及F-FIELD|通过BND-REQ-API-I01执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|关键词 100/101 码点、纯空白、内部换行、编号大小写与标题字面值匹配|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I01-SPECIAL-2|BND-REQ-API-I01；APP-REQ-QUERY-C01|F-A、F-I及F-L；对照存在与不存在id；专属输入分支见右侧预期及F-FIELD|通过BND-REQ-API-I01执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|重复单值拒绝；重复筛选去重；非法枚举/空筛选/页码边界|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I01-SPECIAL-3|BND-REQ-API-I01；APP-REQ-QUERY-C01|F-A、F-I及F-L；对照存在与不存在id；专属输入分支见右侧预期及F-FIELD|通过BND-REQ-API-I01执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|全选和组合筛选、固定排序、空列表和越界页的分页数据|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-REQ-API-I02**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I02-PARAM|BND-REQ-API-I02；APP-REQ-CMD-C01|相应空测试需求集合；title=“需求甲”、type=NEW、idea=“整理报销需求”、initialization_mode=IDEATION；模板取已确认且适用于NEW的固定资源（[Q-01](#q-01)）；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I02-BIND|BND-REQ-API-I02；APP-REQ-CMD-C01|相应空测试需求集合；title=“需求甲”、type=NEW、idea=“整理报销需求”、initialization_mode=IDEATION；模板取已确认且适用于NEW的固定资源（[Q-01](#q-01)）；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I02-ERROR|BND-REQ-API-I02；APP-REQ-CMD-C01|相应空测试需求集合；title=“需求甲”、type=NEW、idea=“整理报销需求”、initialization_mode=IDEATION；模板取已确认且适用于NEW的固定资源（[Q-01](#q-01)）；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I02-IDEM|BND-REQ-API-I02；APP-REQ-CMD-C01|相应空测试需求集合；title=“需求甲”、type=NEW、idea=“整理报销需求”、initialization_mode=IDEATION；模板取已确认且适用于NEW的固定资源（[Q-01](#q-01)）；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I02-SPECIAL-1|BND-REQ-API-I02；APP-REQ-CMD-C01|空测试需求集合；title=“需求甲”、type=NEW、idea=“整理报销需求”、initialization_mode=IDEATION；模板取已确认且适用于NEW的固定资源（[Q-01](#q-01)）；专属输入分支见右侧预期及F-FIELD|通过BND-REQ-API-I02执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|模板不适用不创建资源；类型/模式必填|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I02-SPECIAL-2|BND-REQ-API-I02；APP-REQ-CMD-C01|空测试需求集合；title=“需求甲”、type=NEW、idea=“整理报销需求”、initialization_mode=IDEATION；模板取已确认且适用于NEW的固定资源（[Q-01](#q-01)）；专属输入分支见右侧预期及F-FIELD|通过BND-REQ-API-I02执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|创建事务同时形成需求、CURRENT、用户消息和初始化 Run|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I02-SPECIAL-3|BND-REQ-API-I02；APP-REQ-CMD-C01|空测试需求集合；title=“需求甲”、type=NEW、idea=“整理报销需求”、initialization_mode=IDEATION；模板取已确认且适用于NEW的固定资源（[Q-01](#q-01)）；专属输入分支见右侧预期及F-FIELD|通过BND-REQ-API-I02执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|201 与后台最终状态分离，同键重试不重复创建|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-REQ-API-I03**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I03-PARAM|BND-REQ-API-I03；APP-REQ-QUERY-C02|相应F-A、F-I及F-L；对照存在与不存在id；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I03-BIND|BND-REQ-API-I03；APP-REQ-QUERY-C02|相应F-A、F-I及F-L；对照存在与不存在id；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I03-ERROR|BND-REQ-API-I03；APP-REQ-QUERY-C02|相应F-A、F-I及F-L；对照存在与不存在id；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I03-SPECIAL-业务分支|BND-REQ-API-I03；APP-REQ-QUERY-C02|F-A、F-I及F-L；对照存在与不存在id；专属输入分支见右侧预期及F-FIELD|通过BND-REQ-API-I03执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|覆盖原 APP-REQ-QUERY-C02 中的状态许可、存在性及事务分支；结果满足本接口字段表|能力测试；按8.2选用实际存储或可控模型|


**BND-REQ-API-I04**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I04-PARAM|BND-REQ-API-I04；APP-REQ-CMD-C02|相应F-A或F-I；title原为“需求甲”，分别提交“需求乙”、原值；合法仅title；另构造模式同值／变值／标题混合的拒绝变体；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I04-BIND|BND-REQ-API-I04；APP-REQ-CMD-C02|相应F-A或F-I；title原为“需求甲”，分别提交“需求乙”、原值；合法仅title；另构造模式同值／变值／标题混合的拒绝变体；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I04-ERROR|BND-REQ-API-I04；APP-REQ-CMD-C02|相应F-A或F-I；title原为“需求甲”，分别提交“需求乙”、原值；合法仅title；另构造模式同值／变值／标题混合的拒绝变体；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I04-SPECIAL-1|BND-REQ-API-I04；APP-REQ-CMD-C02|F-A或F-I；title原为“需求甲”，分别提交“需求乙”、原值；合法仅title；另构造模式同值／变值／标题混合的拒绝变体；专属输入分支见右侧预期及F-FIELD|通过BND-REQ-API-I04执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|空 PATCH、null 与未提供字段分别处理|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I04-SPECIAL-2|BND-REQ-API-I04；APP-REQ-CMD-C02|F-A或F-I；title原为“需求甲”，分别提交“需求乙”、原值；合法仅title；另构造模式同值／变值／标题混合的拒绝变体；专属输入分支见右侧预期及F-FIELD|通过BND-REQ-API-I04执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|仅模式、同值模式及合法标题＋模式全部整体422／VALIDATION_FAILED；不部分写标题或updated_at|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I04-SPECIAL-3|BND-REQ-API-I04；APP-REQ-CMD-C02|F-A或F-I；title原为“需求甲”，分别提交“需求乙”、原值；合法仅title；另构造模式同值／变值／标题混合的拒绝变体；专属输入分支见右侧预期及F-FIELD|通过BND-REQ-API-I04执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|相同值不刷新 updated_at|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-REQ-API-I05**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I05-PARAM|BND-REQ-API-I05；APP-REQ-CMD-C03|相应F-I，IDLE；CURRENT版本=3；expected_content_version=3；无BASELINE；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I05-BIND|BND-REQ-API-I05；APP-REQ-CMD-C03|相应F-I，IDLE；CURRENT版本=3；expected_content_version=3；无BASELINE；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I05-ERROR|BND-REQ-API-I05；APP-REQ-CMD-C03|相应F-I，IDLE；CURRENT版本=3；expected_content_version=3；无BASELINE；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I05-IDEM|BND-REQ-API-I05；APP-REQ-CMD-C03|相应F-I，IDLE；CURRENT版本=3；expected_content_version=3；无BASELINE；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I05-SPECIAL-1|BND-REQ-API-I05；APP-REQ-CMD-C03|F-I，IDLE；CURRENT版本=3；expected_content_version=3；无BASELINE；专属输入分支见右侧预期及F-FIELD|通过BND-REQ-API-I05执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|BASELINE 唯一；重复键返回原结果|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I05-SPECIAL-2|BND-REQ-API-I05；APP-REQ-CMD-C03|F-I，IDLE；CURRENT版本=3；expected_content_version=3；无BASELINE；专属输入分支见右侧预期及F-FIELD|通过BND-REQ-API-I05执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|创建基线后 CURRENT 身份与内容版本不变|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-REQ-API-I06**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I06-PARAM|BND-REQ-API-I06；APP-REQ-CMD-C04|相应F-A，IDLE；CURRENT版本=3；expected_content_version=3；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I06-BIND|BND-REQ-API-I06；APP-REQ-CMD-C04|相应F-A，IDLE；CURRENT版本=3；expected_content_version=3；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I06-ERROR|BND-REQ-API-I06；APP-REQ-CMD-C04|相应F-A，IDLE；CURRENT版本=3；expected_content_version=3；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I06-IDEM|BND-REQ-API-I06；APP-REQ-CMD-C04|相应F-A，IDLE；CURRENT版本=3；expected_content_version=3；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I06-SPECIAL-业务分支|BND-REQ-API-I06；APP-REQ-CMD-C04|F-A，IDLE；CURRENT版本=3；expected_content_version=3；专属输入分支见右侧预期及F-FIELD|通过BND-REQ-API-I06执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|覆盖原 APP-REQ-CMD-C04 中的状态许可、存在性及事务分支；结果满足本接口字段表|能力测试；按8.2选用实际存储或可控模型|


**BND-REQ-API-I07**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I07-PARAM|BND-REQ-API-I07；APP-REQ-CMD-C05|相应F-A改为COMPLETED且completed_at=T0，IDLE；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I07-BIND|BND-REQ-API-I07；APP-REQ-CMD-C05|相应F-A改为COMPLETED且completed_at=T0，IDLE；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I07-ERROR|BND-REQ-API-I07；APP-REQ-CMD-C05|相应F-A改为COMPLETED且completed_at=T0，IDLE；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I07-IDEM|BND-REQ-API-I07；APP-REQ-CMD-C05|相应F-A改为COMPLETED且completed_at=T0，IDLE；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I07-SPECIAL-业务分支|BND-REQ-API-I07；APP-REQ-CMD-C05|F-A改为COMPLETED且completed_at=T0，IDLE；专属输入分支见右侧预期及F-FIELD|通过BND-REQ-API-I07执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|覆盖原 APP-REQ-CMD-C05 中的状态许可、存在性及事务分支；结果满足本接口字段表|能力测试；按8.2选用实际存储或可控模型|


**BND-DOC-API-I08**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I08-PARAM|BND-DOC-API-I08；APP-DOC-QUERY-C01|相应F-A及F-D，CURRENT与草稿身份和版本不同；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I08-BIND|BND-DOC-API-I08；APP-DOC-QUERY-C01|相应F-A及F-D，CURRENT与草稿身份和版本不同；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I08-ERROR|BND-DOC-API-I08；APP-DOC-QUERY-C01|相应F-A及F-D，CURRENT与草稿身份和版本不同；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I08-SPECIAL-业务分支|BND-DOC-API-I08；APP-DOC-QUERY-C01|F-A及F-D，CURRENT与草稿身份和版本不同；专属输入分支见右侧预期及F-FIELD|通过BND-DOC-API-I08执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|覆盖原 APP-DOC-QUERY-C01 中的状态许可、存在性及事务分支；结果满足本接口字段表|能力测试；按8.2选用实际存储或可控模型|


**BND-DOC-API-I09**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I09-PARAM|BND-DOC-API-I09；APP-DOC-CMD-C01|相应F-A，IDLE，CURRENT版本=3；expected_content_version=3；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I09-BIND|BND-DOC-API-I09；APP-DOC-CMD-C01|相应F-A，IDLE，CURRENT版本=3；expected_content_version=3；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I09-ERROR|BND-DOC-API-I09；APP-DOC-CMD-C01|相应F-A，IDLE，CURRENT版本=3；expected_content_version=3；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I09-IDEM|BND-DOC-API-I09；APP-DOC-CMD-C01|相应F-A，IDLE，CURRENT版本=3；expected_content_version=3；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I09-SPECIAL-1|BND-DOC-API-I09；APP-DOC-CMD-C01|F-A，IDLE，CURRENT版本=3；expected_content_version=3；专属输入分支见右侧预期及F-FIELD|通过BND-DOC-API-I09执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|创建草稿版本为 1，继承区块身份与来源|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I09-SPECIAL-2|BND-DOC-API-I09；APP-DOC-CMD-C01|F-A，IDLE，CURRENT版本=3；expected_content_version=3；专属输入分支见右侧预期及F-FIELD|通过BND-DOC-API-I09执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|占用和草稿创建原子提交|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-DOC-API-I10**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I10-PARAM|BND-DOC-API-I10；APP-DOC-QUERY-C02|相应F-A及F-D，CURRENT与草稿身份和版本不同；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I10-BIND|BND-DOC-API-I10；APP-DOC-QUERY-C02|相应F-A及F-D，CURRENT与草稿身份和版本不同；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I10-ERROR|BND-DOC-API-I10；APP-DOC-QUERY-C02|相应F-A及F-D，CURRENT与草稿身份和版本不同；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I10-SPECIAL-业务分支|BND-DOC-API-I10；APP-DOC-QUERY-C02|F-A及F-D，CURRENT与草稿身份和版本不同；专属输入分支见右侧预期及F-FIELD|通过BND-DOC-API-I10执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|覆盖原 APP-DOC-QUERY-C02 中的状态许可、存在性及事务分支；结果满足本接口字段表|能力测试；按8.2选用实际存储或可控模型|


**BND-DOC-API-I11**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I11-PARAM|BND-DOC-API-I11；APP-DOC-CMD-C02|相应F-D；草稿版本=1；完整Markdown/BlockState成对变化；expected_content_version=1；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I11-BIND|BND-DOC-API-I11；APP-DOC-CMD-C02|相应F-D；草稿版本=1；完整Markdown/BlockState成对变化；expected_content_version=1；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I11-ERROR|BND-DOC-API-I11；APP-DOC-CMD-C02|相应F-D；草稿版本=1；完整Markdown/BlockState成对变化；expected_content_version=1；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I11-SPECIAL-1|BND-DOC-API-I11；APP-DOC-CMD-C02|F-D；草稿版本=1；完整Markdown/BlockState成对变化；expected_content_version=1；专属输入分支见右侧预期及F-FIELD|通过BND-DOC-API-I11执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|用草稿版本校验，不误用 CURRENT 版本|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I11-SPECIAL-2|BND-DOC-API-I11；APP-DOC-CMD-C02|F-D；草稿版本=1；完整Markdown/BlockState成对变化；expected_content_version=1；专属输入分支见右侧预期及F-FIELD|通过BND-DOC-API-I11执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|陈旧版本拒绝；JSON 对象不能传转义文本|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I11-SPECIAL-3|BND-DOC-API-I11；APP-DOC-CMD-C02|F-D；草稿版本=1；完整Markdown/BlockState成对变化；expected_content_version=1；专属输入分支见右侧预期及F-FIELD|通过BND-DOC-API-I11执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|Markdown/区块不一致时整体拒绝；不改 CURRENT|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-DOC-API-I12**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I12-PARAM|BND-DOC-API-I12；APP-DOC-CMD-C03|相应F-D；草稿最新已确认版本=2；expected_content_version=2；CURRENT版本=3；评论使用F-C；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I12-BIND|BND-DOC-API-I12；APP-DOC-CMD-C03|相应F-D；草稿最新已确认版本=2；expected_content_version=2；CURRENT版本=3；评论使用F-C；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I12-ERROR|BND-DOC-API-I12；APP-DOC-CMD-C03|相应F-D；草稿最新已确认版本=2；expected_content_version=2；CURRENT版本=3；评论使用F-C；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I12-IDEM|BND-DOC-API-I12；APP-DOC-CMD-C03|相应F-D；草稿最新已确认版本=2；expected_content_version=2；CURRENT版本=3；评论使用F-C；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I12-SPECIAL-1|BND-DOC-API-I12；APP-DOC-CMD-C03|F-D；草稿最新已确认版本=2；expected_content_version=2；CURRENT版本=3；评论使用F-C；专属输入分支见右侧预期及F-FIELD|通过BND-DOC-API-I12执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|等待最新保存的版本；CURRENT 保持原 ID 并版本加 1|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I12-SPECIAL-2|BND-DOC-API-I12；APP-DOC-CMD-C03|F-D；草稿最新已确认版本=2；expected_content_version=2；CURRENT版本=3；评论使用F-C；专属输入分支见右侧预期及F-FIELD|通过BND-DOC-API-I12执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|正文、评论锚点、草稿删除和占用释放全部提交或全部回滚|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-DOC-API-I13**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I13-PARAM|BND-DOC-API-I13；APP-DOC-CMD-C04|相应F-D；expected_content_version=1；分别测试匹配、陈旧和原请求重放；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I13-BIND|BND-DOC-API-I13；APP-DOC-CMD-C04|相应F-D；expected_content_version=1；分别测试匹配、陈旧和原请求重放；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I13-ERROR|BND-DOC-API-I13；APP-DOC-CMD-C04|相应F-D；expected_content_version=1；分别测试匹配、陈旧和原请求重放；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I13-IDEM|BND-DOC-API-I13；APP-DOC-CMD-C04|相应F-D；expected_content_version=1；分别测试匹配、陈旧和原请求重放；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I13-SPECIAL-1|BND-DOC-API-I13；APP-DOC-CMD-C04|F-D；expected_content_version=1；分别测试匹配、陈旧和原请求重放；专属输入分支见右侧预期及F-FIELD|通过BND-DOC-API-I13执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|DELETE 请求体被完整解析|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I13-SPECIAL-2|BND-DOC-API-I13；APP-DOC-CMD-C04|F-D；expected_content_version=1；分别测试匹配、陈旧和原请求重放；专属输入分支见右侧预期及F-FIELD|通过BND-DOC-API-I13执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|同键重放与不同键访问已删除草稿区分|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-GUIDE-API-I14**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I14-PARAM|BND-GUIDE-API-I14；APP-GUIDE-CMD-C01|相应F-A或F-I，IDLE；CURRENT版本=3；action/source/scope按本能力4.2允许组合分别参数化；instruction=“检查当前需求”；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I14-BIND|BND-GUIDE-API-I14；APP-GUIDE-CMD-C01|相应F-A或F-I，IDLE；CURRENT版本=3；action/source/scope按本能力4.2允许组合分别参数化；instruction=“检查当前需求”；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I14-ERROR|BND-GUIDE-API-I14；APP-GUIDE-CMD-C01|相应F-A或F-I，IDLE；CURRENT版本=3；action/source/scope按本能力4.2允许组合分别参数化；instruction=“检查当前需求”；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I14-IDEM|BND-GUIDE-API-I14；APP-GUIDE-CMD-C01|相应F-A或F-I，IDLE；CURRENT版本=3；action/source/scope按本能力4.2允许组合分别参数化；instruction=“检查当前需求”；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I14-SPECIAL-1|BND-GUIDE-API-I14；APP-GUIDE-CMD-C01|F-A或F-I，IDLE；CURRENT版本=3；action/source/scope按本能力4.2允许组合分别参数化；instruction=“检查当前需求”；专属输入分支见右侧预期及F-FIELD|通过BND-GUIDE-API-I14执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|状态与 action 组合；source/范围条件字段校验|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I14-SPECIAL-2|BND-GUIDE-API-I14；APP-GUIDE-CMD-C01|F-A或F-I，IDLE；CURRENT版本=3；action/source/scope按本能力4.2允许组合分别参数化；instruction=“检查当前需求”；专属输入分支见右侧预期及F-FIELD|通过BND-GUIDE-API-I14执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|REVIEW_RESULT 跨需求、未完成、非 REVIEW 均拒绝|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I14-SPECIAL-3|BND-GUIDE-API-I14；APP-GUIDE-CMD-C01|F-A或F-I，IDLE；CURRENT版本=3；action/source/scope按本能力4.2允许组合分别参数化；instruction=“检查当前需求”；专属输入分支见右侧预期及F-FIELD|通过BND-GUIDE-API-I14执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|冻结协议失败不落用户消息；接受后轮询|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-GUIDE-API-I15**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I15-PARAM|BND-GUIDE-API-I15；APP-GUIDE-CMD-C02|相应F-G改为WAITING_USER且占用仍指该Run；instruction=“审批人为部门经理”；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I15-BIND|BND-GUIDE-API-I15；APP-GUIDE-CMD-C02|相应F-G改为WAITING_USER且占用仍指该Run；instruction=“审批人为部门经理”；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I15-ERROR|BND-GUIDE-API-I15；APP-GUIDE-CMD-C02|相应F-G改为WAITING_USER且占用仍指该Run；instruction=“审批人为部门经理”；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I15-IDEM|BND-GUIDE-API-I15；APP-GUIDE-CMD-C02|相应F-G改为WAITING_USER且占用仍指该Run；instruction=“审批人为部门经理”；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I15-SPECIAL-业务分支|BND-GUIDE-API-I15；APP-GUIDE-CMD-C02|F-G改为WAITING_USER且占用仍指该Run；instruction=“审批人为部门经理”；专属输入分支见右侧预期及F-FIELD|通过BND-GUIDE-API-I15执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|覆盖原 APP-GUIDE-CMD-C02 中的状态许可、存在性及事务分支；结果满足本接口字段表|能力测试；按8.2选用实际存储或可控模型|


**BND-GUIDE-API-I16**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I16-PARAM|BND-GUIDE-API-I16；APP-GUIDE-QUERY-C01|相应F-G；RUNNING/WAITING_USER/COMPLETED/FAILED/CANCELLED及不同action运行；内部上下文另外准备应排除的草稿、未采用建议和原始审计；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I16-BIND|BND-GUIDE-API-I16；APP-GUIDE-QUERY-C01|相应F-G；RUNNING/WAITING_USER/COMPLETED/FAILED/CANCELLED及不同action运行；内部上下文另外准备应排除的草稿、未采用建议和原始审计；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I16-ERROR|BND-GUIDE-API-I16；APP-GUIDE-QUERY-C01|相应F-G；RUNNING/WAITING_USER/COMPLETED/FAILED/CANCELLED及不同action运行；内部上下文另外准备应排除的草稿、未采用建议和原始审计；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I16-SPECIAL-1|BND-GUIDE-API-I16；APP-GUIDE-QUERY-C01|F-G；RUNNING/WAITING_USER/COMPLETED/FAILED/CANCELLED及不同action运行；内部上下文另外准备应排除的草稿、未采用建议和原始审计；专属输入分支见右侧预期及F-FIELD|通过BND-GUIDE-API-I16执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|FAILED/CANCELLED 运行正常读取为 200|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I16-SPECIAL-2|BND-GUIDE-API-I16；APP-GUIDE-QUERY-C01|F-G；RUNNING/WAITING_USER/COMPLETED/FAILED/CANCELLED及不同action运行；内部上下文另外准备应排除的草稿、未采用建议和原始审计；专属输入分支见右侧预期及F-FIELD|通过BND-GUIDE-API-I16执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|结果投影无 Prompt、LLMUse、原始响应或推理|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-GUIDE-API-I17**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I17-PARAM|BND-GUIDE-API-I17；APP-GUIDE-CMD-C03|相应F-G；分别PREPARING、调用中及PERSISTING；取消后再请求一次；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I17-BIND|BND-GUIDE-API-I17；APP-GUIDE-CMD-C03|相应F-G；分别PREPARING、调用中及PERSISTING；取消后再请求一次；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I17-ERROR|BND-GUIDE-API-I17；APP-GUIDE-CMD-C03|相应F-G；分别PREPARING、调用中及PERSISTING；取消后再请求一次；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I17-IDEM|BND-GUIDE-API-I17；APP-GUIDE-CMD-C03|相应F-G；分别PREPARING、调用中及PERSISTING；取消后再请求一次；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I17-SPECIAL-1|BND-GUIDE-API-I17；APP-GUIDE-CMD-C03|F-G；分别PREPARING、调用中及PERSISTING；取消后再请求一次；专属输入分支见右侧预期及F-FIELD|通过BND-GUIDE-API-I17执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|PERSISTING 拒绝取消；重复取消不改结束时间|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I17-SPECIAL-2|BND-GUIDE-API-I17；APP-GUIDE-CMD-C03|F-G；分别PREPARING、调用中及PERSISTING；取消后再请求一次；专属输入分支见右侧预期及F-FIELD|通过BND-GUIDE-API-I17执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|取消与提交竞争只允许一个业务结果获胜|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-GUIDE-API-I18**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I18-PARAM|BND-GUIDE-API-I18；APP-GUIDE-CMD-C04|相应F-G改为FAILED并释放占用；来源、范围仍有效；重复失败运行保持原记录；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I18-BIND|BND-GUIDE-API-I18；APP-GUIDE-CMD-C04|相应F-G改为FAILED并释放占用；来源、范围仍有效；重复失败运行保持原记录；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I18-ERROR|BND-GUIDE-API-I18；APP-GUIDE-CMD-C04|相应F-G改为FAILED并释放占用；来源、范围仍有效；重复失败运行保持原记录；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I18-IDEM|BND-GUIDE-API-I18；APP-GUIDE-CMD-C04|相应F-G改为FAILED并释放占用；来源、范围仍有效；重复失败运行保持原记录；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I18-SPECIAL-1|BND-GUIDE-API-I18；APP-GUIDE-CMD-C04|F-G改为FAILED并释放占用；来源、范围仍有效；重复失败运行保持原记录；专属输入分支见右侧预期及F-FIELD|通过BND-GUIDE-API-I18执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|新运行 ID 不等于失败运行 ID；来源/范围失效拒绝|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I18-SPECIAL-2|BND-GUIDE-API-I18；APP-GUIDE-CMD-C04|F-G改为FAILED并释放占用；来源、范围仍有效；重复失败运行保持原记录；专属输入分支见右侧预期及F-FIELD|通过BND-GUIDE-API-I18执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|不复制原用户消息，保留正式回答|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-GUIDE-API-I19**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I19-PARAM|BND-GUIDE-API-I19；APP-GUIDE-QUERY-C02|相应F-G；RUNNING/WAITING_USER/COMPLETED/FAILED/CANCELLED及不同action运行；内部上下文另外准备应排除的草稿、未采用建议和原始审计；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I19-BIND|BND-GUIDE-API-I19；APP-GUIDE-QUERY-C02|相应F-G；RUNNING/WAITING_USER/COMPLETED/FAILED/CANCELLED及不同action运行；内部上下文另外准备应排除的草稿、未采用建议和原始审计；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I19-ERROR|BND-GUIDE-API-I19；APP-GUIDE-QUERY-C02|相应F-G；RUNNING/WAITING_USER/COMPLETED/FAILED/CANCELLED及不同action运行；内部上下文另外准备应排除的草稿、未采用建议和原始审计；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I19-SPECIAL-业务分支|BND-GUIDE-API-I19；APP-GUIDE-QUERY-C02|F-G；RUNNING/WAITING_USER/COMPLETED/FAILED/CANCELLED及不同action运行；内部上下文另外准备应排除的草稿、未采用建议和原始审计；专属输入分支见右侧预期及F-FIELD|通过BND-GUIDE-API-I19执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|覆盖原 APP-GUIDE-QUERY-C02 中的状态许可、存在性及事务分支；结果满足本接口字段表|能力测试；按8.2选用实际存储或可控模型|


**BND-BATCH-API-I20**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I20-PARAM|BND-BATCH-API-I20；APP-BATCH-QUERY-C01|相应F-B；四种建议状态各有成员，order_no与id顺序刻意不同；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I20-BIND|BND-BATCH-API-I20；APP-BATCH-QUERY-C01|相应F-B；四种建议状态各有成员，order_no与id顺序刻意不同；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I20-ERROR|BND-BATCH-API-I20；APP-BATCH-QUERY-C01|相应F-B；四种建议状态各有成员，order_no与id顺序刻意不同；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I20-SPECIAL-1|BND-BATCH-API-I20；APP-BATCH-QUERY-C01|F-B；四种建议状态各有成员，order_no与id顺序刻意不同；专属输入分支见右侧预期及F-FIELD|通过BND-BATCH-API-I20执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|建议完整返回且按 order_no 排序|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I20-SPECIAL-2|BND-BATCH-API-I20；APP-BATCH-QUERY-C01|F-B；四种建议状态各有成员，order_no与id顺序刻意不同；专属输入分支见右侧预期及F-FIELD|通过BND-BATCH-API-I20执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|counts 与同快照明细一致|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-BATCH-API-I21**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I21-PARAM|BND-BATCH-API-I21；APP-BATCH-CMD-C01|相应F-B；同一建议分别决定ACCEPTED、REJECTED、EDITED；EDITED使用符合该操作的内容；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I21-BIND|BND-BATCH-API-I21；APP-BATCH-CMD-C01|相应F-B；同一建议分别决定ACCEPTED、REJECTED、EDITED；EDITED使用符合该操作的内容；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I21-ERROR|BND-BATCH-API-I21；APP-BATCH-CMD-C01|相应F-B；同一建议分别决定ACCEPTED、REJECTED、EDITED；EDITED使用符合该操作的内容；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I21-IDEM|BND-BATCH-API-I21；APP-BATCH-CMD-C01|相应F-B；同一建议分别决定ACCEPTED、REJECTED、EDITED；EDITED使用符合该操作的内容；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I21-SPECIAL-1|BND-BATCH-API-I21；APP-BATCH-CMD-C01|F-B；同一建议分别决定ACCEPTED、REJECTED、EDITED；EDITED使用符合该操作的内容；专属输入分支见右侧预期及F-FIELD|通过BND-BATCH-API-I21执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|EDITED 的条件字段、行 cells 结构、DELETE 禁止编辑|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I21-SPECIAL-2|BND-BATCH-API-I21；APP-BATCH-CMD-C01|F-B；同一建议分别决定ACCEPTED、REJECTED、EDITED；EDITED使用符合该操作的内容；专属输入分支见右侧预期及F-FIELD|通过BND-BATCH-API-I21执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|禁止覆盖目标/操作；非 EDITED 清空编辑内容|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I21-SPECIAL-3|BND-BATCH-API-I21；APP-BATCH-CMD-C01|F-B；同一建议分别决定ACCEPTED、REJECTED、EDITED；EDITED使用符合该操作的内容；专属输入分支见右侧预期及F-FIELD|通过BND-BATCH-API-I21执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|单项决定与 counts 同一事务一致|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-BATCH-API-I22**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I22-PARAM|BND-BATCH-API-I22；APP-BATCH-CMD-C02|相应F-B；expected_content_version、CURRENT.content_version与base_content_version均为3；分别全拒绝、含接受、含编辑及保留一项PENDING；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I22-BIND|BND-BATCH-API-I22；APP-BATCH-CMD-C02|相应F-B；expected_content_version、CURRENT.content_version与base_content_version均为3；分别全拒绝、含接受、含编辑及保留一项PENDING；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I22-ERROR|BND-BATCH-API-I22；APP-BATCH-CMD-C02|相应F-B；expected_content_version、CURRENT.content_version与base_content_version均为3；分别全拒绝、含接受、含编辑及保留一项PENDING；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I22-IDEM|BND-BATCH-API-I22；APP-BATCH-CMD-C02|相应F-B；expected_content_version、CURRENT.content_version与base_content_version均为3；分别全拒绝、含接受、含编辑及保留一项PENDING；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I22-SPECIAL-1|BND-BATCH-API-I22；APP-BATCH-CMD-C02|F-B；expected_content_version、CURRENT.content_version与base_content_version均为3；分别全拒绝、含接受、含编辑及保留一项PENDING；专属输入分支见右侧预期及F-FIELD|通过BND-BATCH-API-I22执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|BATCH_APPLIED 和 BATCH_NO_CHANGE 两条成功分支|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I22-SPECIAL-2|BND-BATCH-API-I22；APP-BATCH-CMD-C02|F-B；expected_content_version、CURRENT.content_version与base_content_version均为3；分别全拒绝、含接受、含编辑及保留一项PENDING；专属输入分支见右侧预期及F-FIELD|通过BND-BATCH-API-I22执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|未决项、三方版本冲突、过期目标和补丁冲突|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I22-SPECIAL-3|BND-BATCH-API-I22；APP-BATCH-CMD-C02|F-B；expected_content_version、CURRENT.content_version与base_content_version均为3；分别全拒绝、含接受、含编辑及保留一项PENDING；专属输入分支见右侧预期及F-FIELD|通过BND-BATCH-API-I22执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|任一补丁失败不部分提交，不升级行补丁范围|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-BATCH-API-I23**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I23-PARAM|BND-BATCH-API-I23；APP-BATCH-CMD-C03|相应F-B；PENDING批次；分别首次与原请求重复放弃；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I23-BIND|BND-BATCH-API-I23；APP-BATCH-CMD-C03|相应F-B；PENDING批次；分别首次与原请求重复放弃；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I23-ERROR|BND-BATCH-API-I23；APP-BATCH-CMD-C03|相应F-B；PENDING批次；分别首次与原请求重复放弃；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I23-IDEM|BND-BATCH-API-I23；APP-BATCH-CMD-C03|相应F-B；PENDING批次；分别首次与原请求重复放弃；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I23-SPECIAL-业务分支|BND-BATCH-API-I23；APP-BATCH-CMD-C03|F-B；PENDING批次；分别首次与原请求重复放弃；专属输入分支见右侧预期及F-FIELD|通过BND-BATCH-API-I23执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|覆盖原 APP-BATCH-CMD-C03 中的状态许可、存在性及事务分支；结果满足本接口字段表|能力测试；按8.2选用实际存储或可控模型|


**BND-REV-API-I24**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I24-PARAM|BND-REV-API-I24；APP-REV-QUERY-C01|相应F-A；BASELINE序号1、MANUAL序号2及3，快照正文不同；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I24-BIND|BND-REV-API-I24；APP-REV-QUERY-C01|相应F-A；BASELINE序号1、MANUAL序号2及3，快照正文不同；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I24-ERROR|BND-REV-API-I24；APP-REV-QUERY-C01|相应F-A；BASELINE序号1、MANUAL序号2及3，快照正文不同；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I24-SPECIAL-1|BND-REV-API-I24；APP-REV-QUERY-C01|F-A；BASELINE序号1、MANUAL序号2及3，快照正文不同；专属输入分支见右侧预期及F-FIELD|通过BND-REV-API-I24执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|按 version_no 降序，越界页成功|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I24-SPECIAL-2|BND-REV-API-I24；APP-REV-QUERY-C01|F-A；BASELINE序号1、MANUAL序号2及3，快照正文不同；专属输入分支见右侧预期及F-FIELD|通过BND-REV-API-I24执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|摘要不包含 Markdown 快照|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-REV-API-I25**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I25-PARAM|BND-REV-API-I25；APP-REV-QUERY-C02|相应F-A；BASELINE序号1、MANUAL序号2及3，快照正文不同；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I25-BIND|BND-REV-API-I25；APP-REV-QUERY-C02|相应F-A；BASELINE序号1、MANUAL序号2及3，快照正文不同；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I25-ERROR|BND-REV-API-I25；APP-REV-QUERY-C02|相应F-A；BASELINE序号1、MANUAL序号2及3，快照正文不同；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I25-SPECIAL-1|BND-REV-API-I25；APP-REV-QUERY-C02|F-A；BASELINE序号1、MANUAL序号2及3，快照正文不同；专属输入分支见右侧预期及F-FIELD|通过BND-REV-API-I25执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|快照字段改名和对象转换正确|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-REV-API-I26**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I26-PARAM|BND-REV-API-I26；APP-REV-CMD-C01|相应F-A，IDLE，已有BASELINE序号1；CURRENT版本=3；description=“人工版本”；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I26-BIND|BND-REV-API-I26；APP-REV-CMD-C01|相应F-A，IDLE，已有BASELINE序号1；CURRENT版本=3；description=“人工版本”；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I26-ERROR|BND-REV-API-I26；APP-REV-CMD-C01|相应F-A，IDLE，已有BASELINE序号1；CURRENT版本=3；description=“人工版本”；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I26-IDEM|BND-REV-API-I26；APP-REV-CMD-C01|相应F-A，IDLE，已有BASELINE序号1；CURRENT版本=3；description=“人工版本”；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I26-SPECIAL-业务分支|BND-REV-API-I26；APP-REV-CMD-C01|F-A，IDLE，已有BASELINE序号1；CURRENT版本=3；description=“人工版本”；专属输入分支见右侧预期及F-FIELD|通过BND-REV-API-I26执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|覆盖原 APP-REV-CMD-C01 中的状态许可、存在性及事务分支；结果满足本接口字段表|能力测试；按8.2选用实际存储或可控模型|


**BND-COMMENT-API-I27**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I27-PARAM|BND-COMMENT-API-I27；APP-COMMENT-QUERY-C01|相应F-C；OPEN/RESOLVED、ATTACHED/ORPHANED及已软删除记录；列表超过20条；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I27-BIND|BND-COMMENT-API-I27；APP-COMMENT-QUERY-C01|相应F-C；OPEN/RESOLVED、ATTACHED/ORPHANED及已软删除记录；列表超过20条；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I27-ERROR|BND-COMMENT-API-I27；APP-COMMENT-QUERY-C01|相应F-C；OPEN/RESOLVED、ATTACHED/ORPHANED及已软删除记录；列表超过20条；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I27-SPECIAL-1|BND-COMMENT-API-I27；APP-COMMENT-QUERY-C01|F-C；OPEN/RESOLVED、ATTACHED/ORPHANED及已软删除记录；列表超过20条；专属输入分支见右侧预期及F-FIELD|通过BND-COMMENT-API-I27执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|排除软删除，保留 OPEN/RESOLVED 两种状态|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I27-SPECIAL-2|BND-COMMENT-API-I27；APP-COMMENT-QUERY-C01|F-C；OPEN/RESOLVED、ATTACHED/ORPHANED及已软删除记录；列表超过20条；专属输入分支见右侧预期及F-FIELD|通过BND-COMMENT-API-I27执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|当前定位失败只影响 location，不写 anchor_status|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-COMMENT-API-I28**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I28-PARAM|BND-COMMENT-API-I28；APP-COMMENT-QUERY-C02|相应F-C；OPEN/RESOLVED、ATTACHED/ORPHANED及已软删除记录；列表超过20条；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I28-BIND|BND-COMMENT-API-I28；APP-COMMENT-QUERY-C02|相应F-C；OPEN/RESOLVED、ATTACHED/ORPHANED及已软删除记录；列表超过20条；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I28-ERROR|BND-COMMENT-API-I28；APP-COMMENT-QUERY-C02|相应F-C；OPEN/RESOLVED、ATTACHED/ORPHANED及已软删除记录；列表超过20条；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I28-SPECIAL-1|BND-COMMENT-API-I28；APP-COMMENT-QUERY-C02|F-C；OPEN/RESOLVED、ATTACHED/ORPHANED及已软删除记录；列表超过20条；专属输入分支见右侧预期及F-FIELD|通过BND-COMMENT-API-I28执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|已软删除记录可读，真正不存在才 404|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-COMMENT-API-I29**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I29-PARAM|BND-COMMENT-API-I29；APP-COMMENT-CMD-C01|相应F-A，CURRENT版本=3；content=“请说明审批人”；分别BLOCK和唯一单Block选区锚点；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I29-BIND|BND-COMMENT-API-I29；APP-COMMENT-CMD-C01|相应F-A，CURRENT版本=3；content=“请说明审批人”；分别BLOCK和唯一单Block选区锚点；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I29-ERROR|BND-COMMENT-API-I29；APP-COMMENT-CMD-C01|相应F-A，CURRENT版本=3；content=“请说明审批人”；分别BLOCK和唯一单Block选区锚点；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I29-IDEM|BND-COMMENT-API-I29；APP-COMMENT-CMD-C01|相应F-A，CURRENT版本=3；content=“请说明审批人”；分别BLOCK和唯一单Block选区锚点；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I29-SPECIAL-1|BND-COMMENT-API-I29；APP-COMMENT-CMD-C01|F-A，CURRENT版本=3；content=“请说明审批人”；分别BLOCK和唯一单Block选区锚点；专属输入分支见右侧预期及F-FIELD|通过BND-COMMENT-API-I29执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|BLOCK/SELECTION 条件字段；选区重复或跨区块拒绝|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I29-SPECIAL-2|BND-COMMENT-API-I29；APP-COMMENT-CMD-C01|F-A，CURRENT版本=3；content=“请说明审批人”；分别BLOCK和唯一单Block选区锚点；专属输入分支见右侧预期及F-FIELD|通过BND-COMMENT-API-I29执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|权威锚点快照来自 CURRENT|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-COMMENT-API-I30**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I30-PARAM|BND-COMMENT-API-I30；APP-COMMENT-CMD-C02|相应F-C，未软删除；content由“请说明审批人”改为“请说明审批人与时限”；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I30-BIND|BND-COMMENT-API-I30；APP-COMMENT-CMD-C02|相应F-C，未软删除；content由“请说明审批人”改为“请说明审批人与时限”；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I30-ERROR|BND-COMMENT-API-I30；APP-COMMENT-CMD-C02|相应F-C，未软删除；content由“请说明审批人”改为“请说明审批人与时限”；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I30-IDEM|BND-COMMENT-API-I30；APP-COMMENT-CMD-C02|相应F-C，未软删除；content由“请说明审批人”改为“请说明审批人与时限”；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I30-SPECIAL-业务分支|BND-COMMENT-API-I30；APP-COMMENT-CMD-C02|F-C，未软删除；content由“请说明审批人”改为“请说明审批人与时限”；专属输入分支见右侧预期及F-FIELD|通过BND-COMMENT-API-I30执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|覆盖原 APP-COMMENT-CMD-C02 中的状态许可、存在性及事务分支；结果满足本接口字段表|能力测试；按8.2选用实际存储或可控模型|


**BND-COMMENT-API-I31**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I31-PARAM|BND-COMMENT-API-I31；APP-COMMENT-CMD-C03|相应F-C；分别OPEN、RESOLVED及ATTACHED/ORPHANED组合；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I31-BIND|BND-COMMENT-API-I31；APP-COMMENT-CMD-C03|相应F-C；分别OPEN、RESOLVED及ATTACHED/ORPHANED组合；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I31-ERROR|BND-COMMENT-API-I31；APP-COMMENT-CMD-C03|相应F-C；分别OPEN、RESOLVED及ATTACHED/ORPHANED组合；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I31-IDEM|BND-COMMENT-API-I31；APP-COMMENT-CMD-C03|相应F-C；分别OPEN、RESOLVED及ATTACHED/ORPHANED组合；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I31-SPECIAL-1|BND-COMMENT-API-I31；APP-COMMENT-CMD-C03|F-C；分别OPEN、RESOLVED及ATTACHED/ORPHANED组合；专属输入分支见右侧预期及F-FIELD|通过BND-COMMENT-API-I31执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|重复解决不改时间；ORPHANED 允许人工解决|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-COMMENT-API-I32**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I32-PARAM|BND-COMMENT-API-I32；APP-COMMENT-CMD-C04|相应F-C；分别RESOLVED和已OPEN；resolved_at有值/null与状态一致；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I32-BIND|BND-COMMENT-API-I32；APP-COMMENT-CMD-C04|相应F-C；分别RESOLVED和已OPEN；resolved_at有值/null与状态一致；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I32-ERROR|BND-COMMENT-API-I32；APP-COMMENT-CMD-C04|相应F-C；分别RESOLVED和已OPEN；resolved_at有值/null与状态一致；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I32-IDEM|BND-COMMENT-API-I32；APP-COMMENT-CMD-C04|相应F-C；分别RESOLVED和已OPEN；resolved_at有值/null与状态一致；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I32-SPECIAL-1|BND-COMMENT-API-I32；APP-COMMENT-CMD-C04|F-C；分别RESOLVED和已OPEN；resolved_at有值/null与状态一致；专属输入分支见右侧预期及F-FIELD|通过BND-COMMENT-API-I32执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|重开清空 resolved_at，重复重开无额外变化|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-COMMENT-API-I33**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I33-PARAM|BND-COMMENT-API-I33；APP-COMMENT-CMD-C05|相应F-C；分别未删和deleted_at=T0，保留原请求与幂等键；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I33-BIND|BND-COMMENT-API-I33；APP-COMMENT-CMD-C05|相应F-C；分别未删和deleted_at=T0，保留原请求与幂等键；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I33-ERROR|BND-COMMENT-API-I33；APP-COMMENT-CMD-C05|相应F-C；分别未删和deleted_at=T0，保留原请求与幂等键；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I33-IDEM|BND-COMMENT-API-I33；APP-COMMENT-CMD-C05|相应F-C；分别未删和deleted_at=T0，保留原请求与幂等键；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I33-SPECIAL-1|BND-COMMENT-API-I33；APP-COMMENT-CMD-C05|F-C；分别未删和deleted_at=T0，保留原请求与幂等键；专属输入分支见右侧预期及F-FIELD|通过BND-COMMENT-API-I33执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|软删除和重复删除返回，列表排除但详情可读|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-GUIDE-API-I34**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I34-PARAM|BND-GUIDE-API-I34；APP-GUIDE-CMD-C05|相应F-C，OPEN且未删，F-A/IDLE；分别可定位与无法定位来源；expected_content_version=3；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I34-BIND|BND-GUIDE-API-I34；APP-GUIDE-CMD-C05|相应F-C，OPEN且未删，F-A/IDLE；分别可定位与无法定位来源；expected_content_version=3；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I34-ERROR|BND-GUIDE-API-I34；APP-GUIDE-CMD-C05|相应F-C，OPEN且未删，F-A/IDLE；分别可定位与无法定位来源；expected_content_version=3；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I34-IDEM|BND-GUIDE-API-I34；APP-GUIDE-CMD-C05|相应F-C，OPEN且未删，F-A/IDLE；分别可定位与无法定位来源；expected_content_version=3；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I34-SPECIAL-1|BND-GUIDE-API-I34；APP-GUIDE-CMD-C05|F-C，OPEN且未删，F-A/IDLE；分别可定位与无法定位来源；expected_content_version=3；专属输入分支见右侧预期及F-FIELD|通过BND-GUIDE-API-I34执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|锚点失败允许持久化 ORPHANED，但不创建消息/Run|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I34-SPECIAL-2|BND-GUIDE-API-I34；APP-GUIDE-CMD-C05|F-C，OPEN且未删，F-A/IDLE；分别可定位与无法定位来源；expected_content_version=3；专属输入分支见右侧预期及F-FIELD|通过BND-GUIDE-API-I34执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|仅评论确定的范围，不能通过额外字段扩大|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-MSG-API-I35**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I35-PARAM|BND-MSG-API-I35；APP-MSG-QUERY-C01|相应F-M；消息序号1～45，包含TEXT、合法卡片与回答及结构损坏历史记录；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I35-BIND|BND-MSG-API-I35；APP-MSG-QUERY-C01|相应F-M；消息序号1～45，包含TEXT、合法卡片与回答及结构损坏历史记录；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I35-ERROR|BND-MSG-API-I35；APP-MSG-QUERY-C01|相应F-M；消息序号1～45，包含TEXT、合法卡片与回答及结构损坏历史记录；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I35-SPECIAL-1|BND-MSG-API-I35；APP-MSG-QUERY-C01|F-M；消息序号1～45，包含TEXT、合法卡片与回答及结构损坏历史记录；专属输入分支见右侧预期及F-FIELD|通过BND-MSG-API-I35执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|排他游标，无重复/遗漏；取最新窗口后升序|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I35-SPECIAL-2|BND-MSG-API-I35；APP-MSG-QUERY-C01|F-M；消息序号1～45，包含TEXT、合法卡片与回答及结构损坏历史记录；专属输入分支见右侧预期及F-FIELD|通过BND-MSG-API-I35执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|最后一页和空页 next_cursor=null|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I35-SPECIAL-3|BND-MSG-API-I35；APP-MSG-QUERY-C01|F-M；消息序号1～45，包含TEXT、合法卡片与回答及结构损坏历史记录；专属输入分支见右侧预期及F-FIELD|通过BND-MSG-API-I35执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|坏结构降级为文本，卡片不可交互|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-MSG-API-I36**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I36-PARAM|BND-MSG-API-I36；APP-GUIDE-CMD-C06|相应F-K；完整覆盖所有card_key的responses；INITIALIZE已完成卡片组和其他动作WAITING_USER分别准备；公共PARAM过程|逐项执行公共PARAM过程，绑定本入口6.2完整字段和结果集合|基础类型、必填/可空、未知字段、重复参数；嵌套对象不得被字符串替代|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I36-BIND|BND-MSG-API-I36；APP-GUIDE-CMD-C06|相应F-K；完整覆盖所有card_key的responses；INITIALIZE已完成卡片组和其他动作WAITING_USER分别准备；公共BIND过程|逐项执行公共BIND过程，绑定本入口6.2完整字段和结果集合|本节输入映射、全部成功结果与字段层级；只调用指定 APP 能力|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I36-ERROR|BND-MSG-API-I36；APP-GUIDE-CMD-C06|相应F-K；完整覆盖所有card_key的responses；INITIALIZE已完成卡片组和其他动作WAITING_USER分别准备；公共ERROR过程|逐项执行公共ERROR过程，绑定本入口6.2完整字段和结果集合|覆盖本接口错误表的每个结果；HTTP 与 error.code 按公共表，失败无分页|接口测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I36-IDEM|BND-MSG-API-I36；APP-GUIDE-CMD-C06|相应F-K；完整覆盖所有card_key的responses；INITIALIZE已完成卡片组和其他动作WAITING_USER分别准备；公共IDEM过程|逐项执行公共IDEM过程，绑定本入口6.2完整字段和结果集合|同键同输入重放；不同输入冲突；执行中拒绝重复；成功提交后响应丢失不重复副作用|接口＋能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I36-SPECIAL-1|BND-MSG-API-I36；APP-GUIDE-CMD-C06|F-K；完整覆盖所有card_key的responses；INITIALIZE已完成卡片组和其他动作WAITING_USER分别准备；专属输入分支见右侧预期及F-FIELD|通过BND-MSG-API-I36执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|缺卡片/重复键/非法选项/必答跳过整组拒绝|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I36-SPECIAL-2|BND-MSG-API-I36；APP-GUIDE-CMD-C06|F-K；完整覆盖所有card_key的responses；INITIALIZE已完成卡片组和其他动作WAITING_USER分别准备；专属输入分支见右侧预期及F-FIELD|通过BND-MSG-API-I36执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|同键重放与不同键冲突；已有响应引用正确|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I36-SPECIAL-3|BND-MSG-API-I36；APP-GUIDE-CMD-C06|F-K；完整覆盖所有card_key的responses；INITIALIZE已完成卡片组和其他动作WAITING_USER分别准备；专属输入分支见右侧预期及F-FIELD|通过BND-MSG-API-I36执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|INITIALIZE 创建新运行，其余恢复原运行|接口或能力测试；按8.2选用实际存储或可控模型|
|TC-HTTP-I36-SPECIAL-4|BND-MSG-API-I36；APP-GUIDE-CMD-C06|F-K；完整覆盖所有card_key的responses；INITIALIZE已完成卡片组和其他动作WAITING_USER分别准备；专属输入分支见右侧预期及F-FIELD|通过BND-MSG-API-I36执行每个列明的独立分支；失败、重复或并发分支单独准备数据并比对前后状态|并发提交只有一条正式响应和一次运行推进|接口或能力测试；按8.2选用实际存储或可控模型|


**BND-COMMENT-API-I37**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-HTTP-I37-PARAM|I37；APP-COMMENT-QUERY-C03|合法/非法requirement_id，额外Query和Body|执行公共PARAM过程|身份格式严格；未知Query及非空Body拒绝；不要求Content-Type/幂等头|接口检查，结果仅记Markdown|
|TC-HTTP-I37-BIND|I37；CommentIndexReadModel|同需求OPEN/RESOLVED、可定位/孤立、软删及跨页评论|读取I37并与同一CURRENT身份/版本及完整集合对照|total/open/blocks一致；仅OPEN+ATTACHED成标记；索引完整有序，无meta.pagination；无写入|真实数据库读路径，查询前后业务数据对照|
|TC-HTTP-I37-ERROR|I37；API-COM-ERROR|需求不存在、CURRENT关系不一致、存储失败|逐项触发正式错误分支|404/409/503/500按契约；不返回假空索引或泄漏诊断|接口及能力检查|
|TC-HTTP-I37-SPECIAL-1|I37；前端全文评论定位|目标不在当前I27页；读取后发生并发变化|按索引计算目标页并核实，变化时重新读取|不挪到列表顶部、不漏标其他页、不把当前页数量当全文数|实际前后端串联；未执行不标通过|

**核心路径与关键故障串联**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|<a id="tc-e2e-01"></a>TC-E2E-01 创建至基线|I02、AI01、I05、I08、I24/I25|空需求集合；8.1创建输入；可控模型提供已确认事实补丁及卡片|POST创建→读取运行/消息→完成一轮初始化→以当前版本完成初始化→读取基线|201仅确认接受；初始化运行结束COMPLETED/IDLE，不进入WAITING_USER；只采纳明确事实；BASELINE唯一且version_no=1，完成初始化不替换CURRENT身份、不增加其内容版本|真实HTTP+应用+实际数据库，可控模型；模板/Schema按第7.4节完整资源|
|<a id="tc-e2e-02"></a>TC-E2E-02 人工编辑闭环|I09—I13、C06锚点重校验|F-A、F-C；CURRENT版本3|开始草稿1→保存到2→完成；另独立分支取消；在正文、锚点、草稿删除与占用释放之间逐点失败|保存仅改草稿；完成写回原CURRENT、版本加1，锚点与草稿删除/占用共同提交；失败全部回滚保留草稿；取消不改CURRENT或Revision|真实数据库事务故障注入；以最终实体集合和快照比对|
|<a id="tc-e2e-03"></a>TC-E2E-03 建议采用与无变化|AI04、I20—I23、SHR-PATCH|F-B；分别含接受/编辑、全部拒绝、仍有PENDING|决定单项→GET→完成；另测试原文/目标失效、三方版本不等、组合补丁失败与放弃|单项不改正文；BATCH_APPLIED一次正文更新；BATCH_NO_CHANGE不改版本且applied_content_version=null；失效或任一补丁失败不部分应用，决定保留；放弃只终结批次并释放占用|真实应用/数据库；独立参考快照计算预期，不调用被测Patch实现生成期望|
|<a id="tc-e2e-04"></a>TC-E2E-04 卡片两种继续路径|I36、APP-GUIDE-CMD-C06、SHR-CARDS|F-K；初始化已完成卡片组与非初始化WAITING_USER分别准备|整组回答→读取正式响应和运行；并发两次不同键提交；提交成功后丢响应再原键重放|初始化创建新Run，其余继续原Run并产生新call_no；每组一条正式响应、一次推进；必答缺失/重复卡/非法选项整组拒绝；已有回答返回安全引用|真实存储并发屏障；记录消息、Run及调用次数|
|<a id="tc-e2e-05"></a>TC-E2E-05 评论与正文变化|I29—I34、APP-COMMENT-CMD-C06|F-C；四种双状态组合；原Block删除后以原身份恢复且选区重新唯一|修改正文→读取评论→解决/重开→从评论发起MODIFY；另测试失效来源|锚点仅在规定写路径校验；只改anchor_status不改updated_at；可恢复ATTACHED；查询不写；失效来源可只提交ORPHANED然后拒绝，不能创建消息/Run；不自动解决来源评论|真实存储前后对照，四组合分别运行|
|<a id="tc-e2e-06"></a>TC-E2E-06 取消与提交竞争|I17、APP-GUIDE-CMD-C07、ORCH|F-G，合格输出即将进入PERSISTING|在进入门禁前让取消先提交；另让PERSISTING先获胜，再取消；供应方迟到响应|仅一方取得业务结果；取消先胜不得产生final_result、正文或批次；PERSISTING禁止取消；重复取消不刷新ended_at；已发生用量审计保留|实际数据库原子门禁+可控执行时序，不能仅顺序Mock|
|<a id="tc-e2e-07"></a>TC-E2E-07 中断与监测恢复|BND-WORKER、APP-GUIDE-CMD-C09|8.1恢复夹具；分别last_progress=T0、operation_time=T0+14分59秒与T0+15分；有效本进程集合|启动恢复先于HTTP接入；无进展扫描；包含唯一可信批次、缺失、跨需求、多候选占用|确定中断/超时失败并释放或切换唯一可信占用；不重发模型；等待/草稿/批次不清除；无法确定则INCONSISTENT且不猜测修复；不把阈值当扫描最大延迟|实际存储、受控时钟和启动入口；调度周期/实例机制按BND-WORKER|
|<a id="tc-e2e-08"></a>TC-E2E-08 重试与用量边界|ORCH／4.7、INF-MODEL|F-G；可控供应方分别给网络、超时、429、临时5xx、非法JSON、Schema/授权失败及不可重试错误|观察实际出站次数、call_no/attempt_no；首次后取消；持续可重试失败耗尽；等待后用户继续|同call_no最多3次真实请求，Gateway1、SDK重试0；每次一条LLMUse；不可重试不再发送；取消后无迟到采用；新继续新call_no；最终错误取最后失败，历史用量不抹除|可控HTTP服务+实际Gateway/SDK；供应方兼容另见8.2|
|<a id="tc-e2e-09"></a>TC-E2E-09 幂等与未知提交|API-COM-IDEMPOTENCY、INF-TX|创建需求、创建草稿、卡片提交和批次完成各独立准备；原键原输入|提交前失败、提交成功后丢响应、处理中重复和同键改输入；读取资源再重放|只一次业务效果；原成功数据重放但request_id新建；已知回滚与未知结果区分；不把404普遍当操作完成，软删评论由deleted_at确认|实际数据库与HTTP响应丢失注入；按SHR-IDEMPOTENCY及INF-DB确认机制验证|
|<a id="tc-e2e-10"></a>TC-E2E-10 查询无副作用|全部Query、I01/I19/I24/I27/I35|F-L/F-M及损坏结构历史消息、孤立评论、终态占用|重复查询、分页和游标前翻；保存读取前后数据库快照|筛选/稳定顺序/总数或游标正确；不更新状态、锚点、updated_at或创建模型请求；损坏消息仅文本降级，卡片禁用|真实数据库读路径，查询前后业务数据集合一致|

### 8.2 关键技术保证验证

|实际承诺|必须观察的证据|必要方法与完成判据|
|---|---|---|
|原子写入与唯一性|TC-E2E-02/03/04/06/09的每一步故障后真实对象集合、版本、关联、幂等记录及事务结果|采用[已确认运行基线](#sync-be-01)和[SQLite事务配置](#sync-be-02)；并发用屏障让请求在竞争点同时继续；用Mock Repository不能证明该保证|
|异步接受、恢复和取消|Run、LLMUse、占用、消息、批次和正文的提交时点；接受后可观察引用；迟到结果是否采用|TC-E2E-01/06/07/08使用可控调度、时钟和中断；等待明确状态谓词，不用固定sleep代替完成。按[进程协调规则](#sync-be-05)绑定30秒不重叠扫描、15分钟无进展阈值及10秒关闭宽限；不把正常调度周期当墙钟硬上限|
|真实模型协议及SDK配置|实际请求编码、模型标识、非流式返回、usage/请求标识、超时/取消与真实请求数|使用供应方真实集成或其能证明所需行为的环境；可控服务器补足错误分类；记录供应方/SDK版本；付费集成单独执行和记账，不能只用桩声称兼容|
|幂等崩溃恢复|执行中中断和提交后丢响应后的持久状态及资源复查|按[Q-03](#q-03)确定的保留与恢复机制证明；不能仅在同一进程内重放成功就宣布具备持久保证|
|初始化与运行控制|空库、重复初始化、配置缺失、版本不匹配、启动恢复和关闭时在途资源|从独立环境执行正式入口；按第2.3、7.1及BND-WORKER确认配置执行；未取得实际证据不能验收通过|

每个集成场景记录规格版本、实现版本、依赖产品/版本、关键配置、夹具版本、故障位置、完成判据、实际数据与请求次数；清理本场景创建的测试资源。证据存放于测试或验收记录，不写“已通过”到设计正文。未确定的外部调用结果保留为未知；不将未取到响应等价为未执行。


<a id="sync-be-24"></a>

**真实效果评测待确认与调用许可边界**

Q-EVAL 的正式样本、独立参考预期、评审人、评分规则、阈值和异常/重跑计入仍未完整确认。公共决策稿中的 48 样本/144 次/候选分数不是批准指标，不应直接写成正式要求。D-012 是旧模型单轮观测许可，D-013 是结束的短连通性测试，D-015 是独立六任务有界技术观测和限定离线检查；均不替代六类 AI 真实业务效果验收，也不产生额外自动调用额度。D-015 单轮已经执行完毕，不可重复使用。

Schema/权限/事实证明/采用与模型内容质量分别验证；当前实用准入仅表示按 [BE-19](#sync-be-19) 可发送，不能改写为严格兼容证明或效果合格。后续获准测试时，仅在 Markdown 中记录范围、命令、结果、失败原因、修复及未覆盖内容，不保存截图、JSON 报告、录像或原始日志；原验收的可观察行为与判定标准不因此降低；正常业务数据库和审计不作为测试报告删除。

**确认依据**：D-005/011/014 的明确排除、D-015 的限定授权，以及用户关于测试产物的后续要求。**代码对应**：`tools/deepseek-observation.py` 的固定单轮入口、`backend/resources/counting/v3/admission.json`；[正式 AI 接入进度](../正式AI接入进度.md)是实施状态来源，不是新增评分标准。

### 8.3 AI程序验证与效果评测

**AI程序验证**

|场景引用与名称|规格依据|前置条件与输入|操作或故障场景|预期结果|验证方式|
|---|---|---|---|---|---|
|TC-AI-CONTEXT 上下文边界|AI01—AI06、APP-GUIDE-QUERY-C03|F-G；CURRENT、当前用户输入及正式来源；额外加入草稿、未采用建议、无关评论、旧Revision、推理日志|逐任务捕获组装消息及Read Manifest；在文档/评论中放入要求越权或改变协议的文字|必需事实与正确来源可定位；排除内容不进入；数据文本不改变系统权限；读取清单准确；Scope读取范围不自动成为Allowed Targets|可控模型与组装检查；预算/裁剪按第4.7节，实用计数及usage复核单独验证|
|TC-AI-PARSE 单JSON与Schema|ORCH S04、INF-FUNCTION|同一冻结Schema；完整合法响应、围栏、多JSON、缺字段、未知字段、错误类型、错误互斥分支|逐个返回响应并检查parse_status、validation_status、trusted_output及重试|不剥围栏、不猜字段、不删未知、不补默认；仅完整通过才有trusted_output；失败不进入C07且计入同call_no尝试额度|可控模型；完整Schema按固定资源及Manifest读取|
|TC-AI-SCOPE 来源与采用|AI04—AI06、C07、SHR-PATCH|授权仅一个Block或选区；模型提供跨需求ID、越界目标、旧原文、扩大行补丁和合法输出|分别返回并执行采用；对来源/版本在调用后变更的情况重检|越权/失效拒绝；合法MODIFY只建建议，不写CURRENT；历史检查重新基于最新CURRENT生成；评论来源不自动解决|可控模型+实际业务提交；按SHR-SCOPE/SHR-PATCH确认算法验证|
|TC-AI-BRANCH 分支与事实|4.7输出分支表|每AI任务的最终、需要补充、无修改和有效建议允许分支；INITIALIZE含已确认/未知事实对照|返回各合法分支，再返回任务不允许分支|INITIALIZE完成并IDLE；其他澄清WAITING_USER/GUIDE_ACTIVE；ASK/REVIEW只写消息/结果；无修改不建空批次；建议分支转SUGGESTION_REVIEWING；未知事实不落为正文|可控模型；按独立预期快照检查，不由被测程序计算期望|
|TC-AI-AUDIT 记录与敏感内容|OBJ-GUIDE.LLMUse、[Q-09](#q-09)|可识别测试密钥标记、reasoning内容、已知usage与缺失usage响应|发送、解析失败、业务失败、取消、重试及读取对外运行结果|每真实请求独立记录；传输/解析/校验区分；未知token/duration为null；reasoning不入正式产物；密钥不入快照/对外结果；审计不因业务失败消失|实际Gateway边界与安全投影检查；原始响应脱敏按第7.3节|

**效果评测 EV-GUIDE-V1：六类需求任务**

|内容|确定定义|
|---|---|
|目标任务|AI01 INITIALIZE、AI02 ASK、AI03 REVIEW、AI04用户指令MODIFY、AI05检查来源MODIFY、AI06评论来源MODIFY分别形成评测子集，不以一个总体均分掩盖某项失效|
|运行配置|执行报告固定/记录Function、Prompt、输入输出Schema、ContextTemplate版本、模型精确配置和程序版本；资源与模型按第4.7及7.3节固定配置|
|评测样本|真实效果数据集、完整可重建生成规则及版本尚未提供，见[Q-EVAL](#q-eval)；程序夹具不能充当效果数据集|
|样本覆盖|须覆盖下表已定任务目标，以及缺失信息、局部范围、来源过时、无需修改、等待补充与失败情况；具体组成及数量见[Q-EVAL](#q-eval)|
|执行与重复|每样本次数、采样控制、重跑及汇总方法未确定，见[Q-EVAL](#q-eval)；不能挑选单次成功结果替代全部执行记录|
|判断方法|程序确定性结构/权限校验与任务内容质量分开；内容判断者、评分规则及是否采用模型裁判待[Q-EVAL](#q-eval)；未指定裁判模型|
|指标与通过条件|下表是既有语义约束；效果评分、阈值及关键样本要求尚未确定，不能由迁移工作自定合格率，见[Q-EVAL](#q-eval)|
|无输出与异常|执行记录保留超时、无效输出、评分失败及重跑，不仅保留成功样本；计分分母和重跑计入规则见[Q-EVAL](#q-eval)|

|任务子集|既有语义判定依据|适用样本|尚待确定的效果验收部分|
|---|---|---|---|
|EV-GUIDE-V1-AI01|只把已明确事实写入初始化正文；未知信息以问题/卡片处理；保留完整模板结构|初始化与逐轮补充|信息覆盖和澄清质量的样本、评分及阈值|
|EV-GUIDE-V1-AI02|基于CURRENT及合法输入回答；缺失信息可澄清；不改正文|需求问答|准确性、依据与回答可用性的判定规则|
|EV-GUIDE-V1-AI03|轻量检查结果或澄清，只写消息/运行结果|需求检查|问题发现质量、误报与可执行性标准|
|EV-GUIDE-V1-AI04|在Scope及Allowed Targets内产生非空建议或明确无修改/澄清；用户确认后采用|用户指令修改|指令满足程度、必要修改覆盖和无关改动标准|
|EV-GUIDE-V1-AI05|读取最新CURRENT，历史检查作为依据，不直接执行旧Patch|检查转修改|来源正确性及当前内容适配质量|
|EV-GUIDE-V1-AI06|建议限于评论锚点确定范围，不自动解决评论|评论转修改|评论诉求覆盖、局部修改质量和来源失效样本|

Prompt、模型、Schema、上下文或采用逻辑变化后，重新执行受影响的程序场景与对应效果子集。EV-GUIDE-V1在[Q-EVAL](#q-eval)关闭前不具备完整效果验收条件；程序校验通过不能代替真实模型效果达标。

### 8.4 质量与人工验证

|要求与范围|条件与测量对象|判定标准|验证方式及环境|
|---|---|---|---|
|调用时限与尝试数|实际Gateway/SDK连接、读取阶段及同call_no请求记录|连接10秒、读取180秒配置生效；每call_no最多3次真实请求；SDK0自动重试|TC-E2E-08；供应方兼容与可控连接/延迟环境分别记录|
|无进展恢复|RUNNING最后进展时间与可信operation_time；WAITING_USER对照|15分钟阈值符合C09；用户等待不超时；每30秒不重叠扫描；卡顿不承诺墙钟硬上限|受控时钟+正式监测入口；不以任意sleep替代判定|
|文本与结构一致性|码点边界、换行、Markdown/BlockState、序列化及读取投影|SHR-TEXT/SHR-BLOCK与HTTP契约全部满足；无静默截断或未知字段泄漏|F-FIELD、对象及HTTP场景；解析器使用[已确认方言与锁定版本](#sync-be-07)|
|分页与可见数据|41条需求、45条消息及混合状态对象|固定20、稳定顺序、空/越界/游标边界与各Query一致|真实读取路径及前端串联；合法容量采用[已确认上限](#sync-be-21)，不额外承诺响应时限、吞吐或已验证承载规模|

### 8.5 规格完成与实现验收

当前规格为DRAFT。只有附录A中影响业务、协议、资源、物理保证和验收的事项得到明确结论并回写正式条目，输入—处理—数据—结果及跨文档引用闭合，固定资源与必需验收场景可执行，才能转为EFFECTIVE。内部辅助函数命名和普通SQL组织在不改变设计的范围内由实现者决定。

实现验收需另外取得：目标代码/配置/资源符合正式契约；8.1全部适用场景、8.2真实技术保证、8.3模型效果与8.4质量要求的证据；未知结果、失败、部分完成和不支持功能的处置符合设计。证据关联规格及实现版本、环境、数据版本、执行方式与结果位置。本文不宣称已有软件测试通过或没有缺陷。


<a id="backend-issues"></a>

## 附录A. 已确认结论索引与剩余待确认项

|问题引用|确认结论与当前状态|影响位置|必须保留的约束|
|---|---|---|---|
|<a id="q-baseline"></a>Q-BASELINE|已确认；结论见[BE-01](#sync-be-01)|2.1/2.3、6.1、7.1、BND-WORKER|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-db"></a>Q-DB|已确认；结论见[BE-02](#sync-be-02)|7.1/7.2、所有Command及8.2|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-id"></a>Q-ID|已确认；结论见[BE-03](#sync-be-03)|SHR-ID、对象创建、INF-DB|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-01"></a>Q-01|已确认；结论见[BE-06](#sync-be-06)|INF-TEMPLATE、APP-REQ-CMD-C01、AI01、前端[FE-Q02](WALL-E.V1_0.6.前端设计文档.md#fe-q02)|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-02"></a>Q-02|已确认；结论见[BE-15](#sync-be-15)、[BE-16](#sync-be-16)|4.7 AI01—AI06、C07、INF-FUNCTION|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-02-context"></a>Q-02-CONTEXT|已确认；结论见[BE-17](#sync-be-17)、[BE-19](#sync-be-19)|APP-GUIDE-QUERY-C03、ORCH S02、4.7上下文|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-03"></a>Q-03|已确认；结论见[BE-04](#sync-be-04)|SHR-IDEMPOTENCY、6.1、INF-DB/TX|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-04"></a>Q-04|已确认；结论见[BE-13](#sync-be-13)|APP-COMMENT-CMD-C02—C05、I30—I33|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-05"></a>Q-05|已确认；结论见[BE-08](#sync-be-08)、[BE-09](#sync-be-09)|APP-DOC-CMD-C01—C03、OBJ-DOC、I09/I11/I12、前端DT-OP24/25|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-06"></a>Q-06|已确认；结论见[BE-07](#sync-be-07)|SHR-BLOCK、OBJ-DOC、INF-DB、AI与编辑器|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-06-identity"></a>Q-06-IDENTITY|已确认；结论见[BE-07](#sync-be-07)、[BE-09](#sync-be-09)|SHR-BLOCK、人工编辑、初始化和补丁采用|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-06-scope"></a>Q-06-SCOPE|已确认；结论见[BE-10](#sync-be-10)|SHR-SCOPE、APP-GUIDE-CMD-C01、QUERY-C03、AI04—06|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-06-anchor"></a>Q-06-ANCHOR|已确认；结论见[BE-11](#sync-be-11)|SHR-ANCHOR、APP-COMMENT-CMD-C01/C06、I27/I29/I34、前端[FE-Q08](WALL-E.V1_0.6.前端设计文档.md#fe-q08)|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-06-patch"></a>Q-06-PATCH|已确认；结论见[BE-12](#sync-be-12)|SHR-PATCH、APP-BATCH-CMD-C01/C02、C07|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-07"></a>Q-07|正式模型及实用计数准入已确认；不具备通用封装严格上界证明，见[BE-18](#sync-be-18)、[BE-19](#sync-be-19)|INF-MODEL/PROFILE、ORCH、8.2|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-08"></a>Q-08|已确认；结论见[BE-05](#sync-be-05)|BND-WORKER、APP-GUIDE-CMD-C09、2.3|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-09"></a>Q-09|已确认；结论见[BE-20](#sync-be-20)|OBJ-GUIDE.LLMUse、INF-MODEL|在线30天清理不自动遍历离线备份；备份按同一管理要求处理。|
|<a id="q-10"></a>Q-10|已确认；结论见[BE-21](#sync-be-21)|OBJ-DOC/OBJ-BATCH、各输入、6.1/7.1|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-13"></a>Q-13|费用/币种表示已确认；当前未知为 null，自动取得费用未实现，见[BE-20](#sync-be-20)|OBJ-GUIDE.LLMUse及审计|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-provider-id"></a>Q-PROVIDER-ID|已确认；结论见[BE-20](#sync-be-20)|OBJ-GUIDE.LLMUse.provider_request_id、INF-MODEL|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-internal-contract"></a>Q-INTERNAL-CONTRACT|已确认；结论见[BE-22](#sync-be-22)|APP-COMMENT-CMD-C06、GUIDE-CMD-C07/C08/C09、GUIDE-ORCH-C01、GUIDE-QUERY-C03／4.2/4.4|既有业务条件与验收要求保留；设计决定不等于已验证。|
|<a id="q-eval"></a>Q-EVAL|待确认正式样本、次数、判定者、评分、阈值与异常计入；见[BE-24](#sync-be-24)|8.3、六项AI任务的效果验收|候选48样本/144次及分数未获批准；程序校验与单轮观测不代替效果验收。|
|<a id="q-card-state"></a>Q-CARD-STATE|已确认；结论见[BE-14](#sync-be-14)|SHR-CARDS、APP-GUIDE-CMD-C06、APP-MSG-QUERY-C01.card_state|既有业务条件与验收要求保留；设计决定不等于已验证。|

本附录保留稳定问题锚点及已确认结论索引，避免旧引用失效；正文已写入的结论不再作为历史缺口阻塞。Q-EVAL仍待确认，模型通用封装上界没有成立，实际验收另按第8章记录。前端专属未定项见前端附录A；共同业务与协议以本文件为正式定义。
