# WALL-E V2.1 前端设计文档

## 1. 文档说明与系统范围

### 1.1 基本信息

| 字段 | 定义 |
| --- | --- |
| 规格编号 | WALL-E-FE-V21 |
| 系统名称 | WALL-E文档协作前端 |
| 规格类型 | 既有系统增量详细设计，采用共享统一需求规格模板 |
| 目标版本／规格修订／状态 | V2.1／0.1-draft-4／DRAFT |
| 更新日期 | 2026-11-14（Asia/Hong_Kong；2026-11-13开始编写） |
| 输入 | OUTLINE21-01／0.12 DRAFT，包含C21-01—03；后端0.1-draft-4共同契约 |
| 编写状态 | 第1—8章及附录完整初稿；仅设计输出，未实施／未产品验收 |

### 1.2 目标与范围

在现有需求详情的所属文档工作台中接入文档形成路线，支持查看／调整／目标选择、普通讨论、精确阶段性写入、支线恢复、人工修改后的复核及用户结束步骤。依现有360px最小／420px偏好进展面板与历史原型的纵向方向，补齐真实数据、分页、状态及失败恢复；不另建常驻全屏工作流产品。

共同业务类型、权限、状态、事务、HTTP、模型输入输出及共享A01—A76只在[后端详细规格](WALL-E.后端设计文档_V_2.1.md)定义。本文负责页面／组件／交互／浏览器状态，不能以按钮状态代替服务端授权。未变化的正文编辑、版本确认、评论、建议及V2.0 Coding／Testing沿原真实基线，不能因旧工作区无其代码而删除或重建。

### 1.3 文档与交付边界

文件保留在pending/v2.1，既是完整详细设计初稿的组成，也是待正式审定的独立迭代；不覆盖docs/design/v1.5或V2.0规格。本轮不修改产品代码、Schema、冻结资源或用户正文，不启动服务／模型／计数，不提交推送。实际代码接入／测试／产品验收分别登记，DRAFT不等于实现完成。

### 1.4 术语与状态

| 名称 | 精确定义 |
| --- | --- |
| server_focus | 后端current_step_ref＋active_branch_ref，正式当前讨论位置 |
| view_selection | 页面正在查看的Step／页签／来源，纯浏览状态 |
| next_target | 用户为下一次发送明确选择的完整步骤／支线／ENTER或RESUME依据 |
| accepted_target | 已接受在途GuideRun冻结目标，之后的本地选择不更改它 |
| receipt | 本次成功事实，版本可能已旧；不能替代最新查询 |
| current projection | 当前关系／最新评估／提案可用性；不回写历史Closure或原卡 |

### 1.5 稳定引用与定位

| 范围 | 既有入口 | 新增目标／职责 |
| --- | --- | --- |
| 需求文档工作台 | frontend/src/requirements/detail.tsx、detail-owner.ts、discussion-view.tsx／discussion-presentation.ts、discussion-progress.css | formation-owner.ts／formation-view.tsx／formation.css；文档级状态与面板 |
| 对话及草稿 | frontend/src/guide/composer.ts、composer-view.tsx、composer-drafts.ts | 扩展完整目标及调整意图；保留原输入草稿载体 |
| 卡片 | frontend/src/guide/cards-view.tsx、card-message.tsx、card-groups.ts、card-answers.ts、card-drafts.ts | 新用途的只读精确预览与程序采用，不造第二套普通卡 |
| API／协议 | frontend/src/api/client.ts、models.ts及具体API模块 | 新formation DTO严格decoder／方法；保持PreparedCommand快照机制 |
| 已有原工作区V2.0恢复库 | frontend/src/code-tasks/command-recovery-store.ts／command-recovery-model.ts，IndexedDB原单账本 | 抽取共享技术能力并扩展FORMATION联合，旧Coding／Testing调用同时承接；不另建平行数据库 |

上述新增文件仅为目标位置，当前没有产品实现。V2.0恢复载体只读来源及范围见[来源记录](../../../verification/v2.1/detailed-design-baseline-read-2026-11-14.md)，启动实现时必须核实实际源提交和全部调用方。

## 2. 技术基线与公共规则

### 2.1 技术与模块基线

沿本工作区package.json／锁文件：React19.3.0、TypeScript7.0.2、Vite8.3.2、Milkdown7.22.2、Prettier3.9.10。不为设计文档更新依赖。原路由`/requirements/{id}`和所属文档选择保持，formation不是新业务根路由；原URL文档参数及面板导航由既有router解析，本文不改名。已放弃节点、历史、展开视图等只读状态不触发AI。

### 2.2 公共交互规则

| 引用 | 唯一前端规则 |
| --- | --- |
| SHR-FE-OWNER | 一个所属文档一个owner；server_focus、view_selection、next_target、accepted_target分开存；组件只发意图，不局部伪写正式状态 |
| SHR-FE-ASYNC | 每次读带doc键／查询键／epoch，旧响应不覆盖新文档／新筛选；写回执即使晚到仍记原命令事实，不能抢焦点或改当前输入 |
| SHR-FE-FORM | 编辑值本地保留，缺失／null／空数组按后端；不trim精确正文，不为展示改变补丁原文。前端可作输入提示，后端严格校验为真 |
| SHR-FE-STATE | 加载／成功空数据／错误／无权限或不可用／字段损坏分开；成功空态统一EmptyState且模块给图标＋一句文案；不借空态自动发请求、建线、改正文或聚焦 |
| SHR-FE-ACTION | 用户明确点击或键盘触发才提交；新操作先冻结请求，禁用原因在相邻可读文本或可聚焦说明中可达。成功后读取失败保留成功；UNKNOWN只核实原动作 |
| SHR-FE-FOCUS | 可查看不等于可编辑；查看不更改正式讨论目标。展开／折叠／分页不重建正文编辑器、不丢选区，不因在途回复跳走 |
| SHR-FE-A11Y | 颜色同时有文字／图标；原生button／checkbox／select；标题语义、表单label、焦点可见，错误aria-describedby，处理结果aria-live=polite，禁用不只靠tooltip |

### 2.3 环境、配置及生命周期

API地址和同源策略沿原客户端。文档切换先保存本地输入和界面状态，再解绑旧owner的只读订阅；未决命令交共享恢复owner保留，不能因unmount销毁唯一原请求。GET可以AbortController取消并忽略旧epoch；提交Abort不是业务取消。后台运行继续由原GuideRun读取管理，主动取消沿原cancel入口，关闭面板不取消AI。Profile及资源是否可用由服务端投影，界面不提供隐藏模型切换／自动再生成。

## 3. 前端状态对象

共同业务对象直接采用后端OBJ-FORM-*，不复制其业务字段表。以下仅定义客户端拥有的状态；正式Step状态、Closure、Artifact来源、卡payload及可执行性都从严格DTO取得。

<a id="obj-fe-owner"></a>
### OBJ-FE-OWNER FormationViewState

#### 3.1 对象说明

同源＋requirement_id＋document_id定位的文档级owner，管理读取、查看选择、下一轮目标和待核实请求；不是服务端FormationState副本真源。

#### 3.2 字段

| 字段 | 类型 | 可空／默认 | 规则 |
| --- | --- | --- | --- |
| owner_key | origin＋ID＋ID | 否／无 | 不允许跨文档共享写状态 |
| summary | 后端Summary | 是／null | 可读缓存，附读epoch／F；加载失败不销毁已有快照 |
| pages | 按kind/filter/F键的PageCache | 否／空 | 只缓存真实已加载页、total及meta；不能推断全局不存在 |
| view_selection | {step_ref:null或StepRef,tab:OVERVIEW/RESULTS/ISSUES/BRANCHES/HISTORY} | 否／均未选时OVERVIEW | 只查看；选择的页外实体按ID加载，不需要先遍历所有页 |
| next_target | 后端TargetSelection＋local_selection_epoch | 是／null | 无人工新选择时沿最新有效server_focus；显式选择保持直到接受／冲突处理 |
| accepted_targets | guide_run_id→TargetSelection | 否／空 | 源自202／运行读取，冻结原目标 |
| ui_preferences | {expanded:boolean,show_cancelled:boolean,show_branches:boolean,scroll_anchor:null或StepRef} | 否／false,false,true,null | 只展示；不含正式完成事实 |
| query_states | key→IDLE/LOADING/READY/ERROR | 否／空 | ERROR保留last_good和独立error；无主线exists=false才显示未建线 |
| command_state | OBJ-FE-COMMAND引用/null | 是／null | 受共享原请求恢复owner管理 |

#### 3.3 关系与状态

切文档不把旧next_target套给新文档；恢复偏好先核实真实ID。目标被取消／支线非OPEN等不静默换到其他节点，保留原选择并显示需重新选择原因；输入可继续编辑，受影响发送被禁用。单纯读到新D不改变用户草稿，实际发送以最新读取D准备一次新操作。

#### 3.4 复杂操作

接受恢复成功只消费与该命令同selection_epoch／同支线依据的意图：更新为ENTER、basis=null。若用户之后已改为另一目标，旧回执仅记已接受事实、不覆盖新目标。UNKNOWN期间冻结该原意图，不能据刷新OPEN就改原body重发；确认成功后再归一化后续新操作。

#### 3.5 保存位置

owner内存＋7.4所列展示偏好／目标草稿载体；server_summary不当离线正式真源。

<a id="obj-fe-draft"></a>
### OBJ-FE-DRAFT PathEditDraft／TargetDraft

#### 3.1 对象说明

路线编辑草稿和下一轮选择是未提交用户输入，允许保存失败后继续停留编辑，不自动合入正式设计或正文。

#### 3.2 字段

| 字段 | 类型 | 可空／默认 | 约束 |
| --- | --- | --- | --- |
| path_draft | {schema_version:1,owner_key,base_D,base_F,base_V,based_on_proposal,changes,result_routes,reason,updated_at} | 是／null | changes及路由严格同后端；本地可保存未完成表单的raw字段，提交前转换严格DTO |
| preview | 后端PathPreview＋request_digest | 是／null | 仅对应完全相同草稿和D/F/V；任何编辑或版本变化标OUTDATED，不复用为授权 |
| target_draft | {schema_version:1,owner_key,selection:TargetSelection,selection_epoch,updated_at} | 是／null | RESUME基准原样保存，恢复时GET核实，未发送不消费 |
| validation | field→本地错误／服务端安全错误 | 否／空 | 只提示；不能覆盖用户原文 |
| draft_state | CLEAN/DIRTY/PREVIEWING/PREVIEW_READY/STALE/SAVING/UNKNOWN/SAVED | 否／CLEAN | SAVING/UNKNOWN原命令冻结，继续本地改写另成草稿，不替换原请求 |

#### 3.3 关系与状态

原路线卡payload不可变；“调整路线”复制到用户草稿，based_on_proposal指原卡。成功COMMIT由服务端明确处置旧卡及返回reference_map，前端按真实新ID定位；失败保留本地草稿。预览只展示temp标签，不能把标签当正式StepRef。未采用路线卡的临时身份保持卡内局部含义；只有成功采用回执reference_map才用于定位正式实体，不重写原卡／未决命令body。

#### 3.4 复杂操作

拆分／合并采用新增步＋取消旧步＋逐项ResultRoute，PathChange.ADD_STEP仅用temp_step_ref／replaces_step_refs；新成果去向使用已声明的PathResultRef，不伪造sN.oK。编辑器逐一列出旧成果去向／问题／支线／依赖影响。只为本次受影响范围加载完整关系，各关系仍分页；保存前程序全DB校验。没有完整去向不能提交取消，不能因当前页没显示问题默认它不存在。

#### 3.5 保存位置

sessionStorage文档级扩展键与内存；7.4定义版本／失败／清理。预览不持久为已提交事实。

<a id="obj-fe-command"></a>
### OBJ-FE-COMMAND FormationCommandState

#### 3.1 对象说明

一次明确用户动作的不可变请求及其已知完成范围；复用ApiClient PreparedCommand和原V2.0恢复账本机制，新增FORMATION类型分支，不借用代码任务REJECTED/CLOSED业务规则。

#### 3.2 字段

| 字段 | 类型 | 可空／默认 | 约束 |
| --- | --- | --- | --- |
| request_snapshot | {origin,method,path,body_text,idempotency_key,body_sha256,owner_key,intent_id} | 否／冻结时生成 | body原字节；重放同method/path/body/key；不含secret；intent_id为本地UUID，不当服务端授权 |
| status | PREPARED/SENDING/UNKNOWN/CONFIRMED/KNOWN_REJECTED | 否／PREPARED | 本地状态，服务端成功／明确拒绝才可终结 |
| receipt | 后端ProgramReceipt或RunAccepted | 是／null | 严格解码且匹配请求身份；CONFIRMED后读失败不改成UNKNOWN |
| last_error | 安全错误或本地传输原因 | 是／null | 传输未知与业务拒绝分开 |
| refresh_state | NOT_NEEDED/PENDING/READY/FAILED | 否／NOT_NEEDED | CONFIRMED＋FAILED仍“操作成功，显示待刷新” |
| affected_draft_epoch | 保存时输入版本 | 否／无 | 仅在当前草稿仍同版本时清空已接受输入；新输入永不被晚到回执清除 |

#### 3.3 关系与状态

本地账本PREPARED提交完成才允许网络send；同origin/intent重复调用复用冻结请求，跨标签只可核实同key，不生成第二操作。无幂等key的路径预览不写账本，纯只读失败可重新读取。

#### 3.4 复杂操作

UNKNOWN提供“核实原操作”；内部重放原请求，由服务端幂等先查旧成功回执；不提供自动重新生成或换版本后重试。原REQUEST_IN_PROGRESS仍待核实，不能当未执行。实际已知拒绝可以结束原动作，用户修改草稿后明确新提交，分配新key。

#### 3.5 保存位置

共享单IndexedDB账本保存不可变请求和终态摘要；原sessionStorage卡片／输入草稿仍只存未提交文字，不混入正式卡payload／API凭据。具体7.4。

## 4. 前端应用能力

<a id="app-fe-load"></a>
### APP-FE-LOAD 读取、分页及定位

#### 4.1 能力说明

文档级明确用户操作；输入与正式对象分离，完成条件是本能力已知事实及反馈，不等于产品全流程完成。

#### 4.2 输入与来源

| 输入 | 类型／来源 | 必传／可空／默认 |
| --- | --- | --- |
| owner | OBJ-FE-OWNER／当前所属文档 | 必传不可空；无选择时入口禁用并说明 |
| input | owner_key、PageQuery、查看选择 | 动作字段按后端联合；可空仅其明确允许项，无隐含默认目标 |
| endpoint | BND-FORM-SUMMARY／PAGE／STEP／RELATIONS／EVENTS／CLOSURE／EVIDENCE／MEMBERS／LINEAGE | 严格API adapter；不由组件拼任意路径 |

#### 4.3 处理过程

先读Summary；exists=true才按返回F读取首步页，exists=false显示未建线且不发任何/formation/*请求；只有展开节点／页签才取详情及关系页。所有计数沿服务端完整快照。后续页固定F和过滤；PATH_CHANGED仅重读受影响集合，保留选中ID及草稿，重新核实选中详情。

#### 4.4 输出与完成

渲染实际DTO／成功回执或安全错误，保留本地查看／输入；正式成功与刷新状态分别提供。只读返回仅说明读取覆盖，保存回执仅说明该次动作。

#### 4.5 失败、并发及生命周期

成功空态、页越界、错误分开。只查看不调用PATCH或AI；来源不可用可见原因。关闭弹层取消只读并增加epoch，晚到响应不覆盖。 所有异步结果还遵守SHR-FE-ASYNC及SHR-FE-FOCUS；组件卸载不取消已发送正式命令。

#### 4.8 实现定位

formation-owner／view及API decoder。当前为拟接入位置，代码尚未实现；前端不发起独立模型任务，4.7全部引用后端AI-FORM-DISCUSS。

<a id="app-fe-target"></a>
### APP-FE-TARGET 选择当前或下一轮完整讨论目标

#### 4.1 能力说明

文档级明确用户操作；输入与正式对象分离，完成条件是本能力已知事实及反馈，不等于产品全流程完成。

#### 4.2 输入与来源

| 输入 | 类型／来源 | 必传／可空／默认 |
| --- | --- | --- |
| owner | OBJ-FE-OWNER／当前所属文档 | 必传不可空；无选择时入口禁用并说明 |
| input | 真实Step／Branch与恢复依据、selection_epoch | 动作字段按后端联合；可空仅其明确允许项，无隐含默认目标 |
| endpoint | BND-FORM-COMMAND／DISCUSS | 严格API adapter；不由组件拼任意路径 |

#### 4.3 处理过程

空闲时明确进入可用原生SWITCH_STEP／ENTER_BRANCH／RESUME_BRANCH一次提交完整目标；正在运行时只设置next_target并显示“下一轮讨论”，不更改accepted_target或发额外Chat。步骤目标允许历史状态；非OPEN支线仅明确继续时准备RESUME及状态事件依据。

#### 4.4 输出与完成

渲染实际DTO／成功回执或安全错误，保留本地查看／输入；正式成功与刷新状态分别提供。只读返回仅说明读取覆盖，保存回执仅说明该次动作。

#### 4.5 失败、并发及生命周期

接受成功归一化ENTER；模型失败不退回RESUME。旧意图失效保留输入和选择并提示，不能自动重开父步骤／恢复新结果。普通暂停或结束其他步不抢下一轮目标。 所有异步结果还遵守SHR-FE-ASYNC及SHR-FE-FOCUS；组件卸载不取消已发送正式命令。

#### 4.8 实现定位

formation-owner／guide composer。当前为拟接入位置，代码尚未实现；前端不发起独立模型任务，4.7全部引用后端AI-FORM-DISCUSS。

<a id="app-fe-path"></a>
### APP-FE-PATH 编辑、预览并保存完整路线调整

#### 4.1 能力说明

文档级明确用户操作；输入与正式对象分离，完成条件是本能力已知事实及反馈，不等于产品全流程完成。

#### 4.2 输入与来源

| 输入 | 类型／来源 | 必传／可空／默认 |
| --- | --- | --- |
| owner | OBJ-FE-OWNER／当前所属文档 | 必传不可空；无选择时入口禁用并说明 |
| input | OBJ-FE-DRAFT、当前D/F/V、可空原路线卡引用 | 动作字段按后端联合；可空仅其明确允许项，无隐含默认目标 |
| endpoint | BND-FORM-PREVIEW／COMMAND | 严格API adapter；不由组件拼任意路径 |

#### 4.3 处理过程

按后端14型编辑，收集取消影响及逐项成果映射；先预览只读变化／取舍／来源，再由“保存路线”明确COMMIT，同业务校验重做。编辑后旧预览无效，原卡只读。

#### 4.4 输出与完成

渲染实际DTO／成功回执或安全错误，保留本地查看／输入；正式成功与刷新状态分别提供。只读返回仅说明读取覆盖，保存回执仅说明该次动作。

#### 4.5 失败、并发及生命周期

冲突／非法图／超单次预算保留全部草稿和错误定位；不截断。保存成功只按reference_map定位新实体；GET失败保留保存事实。 所有异步结果还遵守SHR-FE-ASYNC及SHR-FE-FOCUS；组件卸载不取消已发送正式命令。

#### 4.8 实现定位

formation-editor／owner目标文件。当前为拟接入位置，代码尚未实现；前端不发起独立模型任务，4.7全部引用后端AI-FORM-DISCUSS。

<a id="app-fe-apply"></a>
### APP-FE-APPLY 预览并确认精确内容或路线卡

#### 4.1 能力说明

文档级明确用户操作；输入与正式对象分离，完成条件是本能力已知事实及反馈，不等于产品全流程完成。

#### 4.2 输入与来源

| 输入 | 类型／来源 | 必传／可空／默认 |
| --- | --- | --- |
| owner | OBJ-FE-OWNER／当前所属文档 | 必传不可空；无选择时入口禁用并说明 |
| input | 原ProposalRef、最新D、原完整卡组定义 | 动作字段按后端联合；可空仅其明确允许项，无隐含默认目标 |
| endpoint | BND-FORM-APPLY | 严格API adapter；不由组件拼任意路径 |

#### 4.3 处理过程

从服务端不可变payload显示精确正文差异／原范围，单卡一个“确认写入”或“采用路线”。冻结原responses，不在body发送替换payload；程序执行，无第二次Chat。

#### 4.4 输出与完成

渲染实际DTO／成功回执或安全错误，保留本地查看／输入；正式成功与刷新状态分别提供。只读返回仅说明读取覆盖，保存回执仅说明该次动作。

#### 4.5 失败、并发及生命周期

正文V／来源／定义变化按真实原因禁用或冲突；COMPLETED或只切焦点不单独禁用。成功更新正式回答／来源和当前投影，步骤不自动结束。 所有异步结果还遵守SHR-FE-ASYNC及SHR-FE-FOCUS；组件卸载不取消已发送正式命令。

#### 4.8 实现定位

cards-view／card-message／owner。当前为拟接入位置，代码尚未实现；前端不发起独立模型任务，4.7全部引用后端AI-FORM-DISCUSS。

<a id="app-fe-disposition"></a>
### APP-FE-DISPOSITION 结束步骤、遗留处置及恢复

#### 4.1 能力说明

文档级明确用户操作；输入与正式对象分离，完成条件是本能力已知事实及反馈，不等于产品全流程完成。

#### 4.2 输入与来源

| 输入 | 类型／来源 | 必传／可空／默认 |
| --- | --- | --- |
| owner | OBJ-FE-OWNER／当前所属文档 | 必传不可空；无选择时入口禁用并说明 |
| input | 原生命令严格输入、可选显式去向 | 动作字段按后端联合；可空仅其明确允许项，无隐含默认目标 |
| endpoint | BND-FORM-COMMAND | 严格API adapter；不由组件拼任意路径 |

#### 4.3 处理过程

默认“结束本步骤”直接提交，当前已知缺口及未处置提示可读但不拦截；可选“结束并继续”明确next目标。高级遗留处置只在用户展开时填写，缺省KEEP_OPEN。暂缓问题与支线继续采用真实恢复动作。

#### 4.4 输出与完成

渲染实际DTO／成功回执或安全错误，保留本地查看／输入；正式成功与刷新状态分别提供。只读返回仅说明读取覆盖，保存回执仅说明该次动作。

#### 4.5 失败、并发及生命周期

无成果仍可结束；不强制理由／先开始／先写入／先重开。只有真实版本或关系冲突等程序保护拦截；Closure展示当时事实，后续写入不改旧历史。 所有异步结果还遵守SHR-FE-ASYNC及SHR-FE-FOCUS；组件卸载不取消已发送正式命令。

#### 4.8 实现定位

formation-detail／owner。当前为拟接入位置，代码尚未实现；前端不发起独立模型任务，4.7全部引用后端AI-FORM-DISCUSS。

<a id="app-fe-adjust"></a>
### APP-FE-ADJUST 暂缓写入、继续调整及撤回调整

#### 4.1 能力说明

文档级明确用户操作；输入与正式对象分离，完成条件是本能力已知事实及反馈，不等于产品全流程完成。

#### 4.2 输入与来源

| 输入 | 类型／来源 | 必传／可空／默认 |
| --- | --- | --- |
| owner | OBJ-FE-OWNER／当前所属文档 | 必传不可空；无选择时入口禁用并说明 |
| input | ProposalRef、用户输入、proposal_intent | 动作字段按后端联合；可空仅其明确允许项，无隐含默认目标 |
| endpoint | BND-FORM-COMMAND／DISCUSS | 严格API adapter；不由组件拼任意路径 |

#### 4.3 处理过程

暂缓及恢复写入均0Chat；继续调整先选原卡并把用户要求留在输入框，只有实际发送DISCUSS才建立正式调整状态。新卡成功保存后旧卡SUPERSEDED。

#### 4.4 输出与完成

渲染实际DTO／成功回执或安全错误，保留本地查看／输入；正式成功与刷新状态分别提供。只读返回仅说明读取覆盖，保存回执仅说明该次动作。

#### 4.5 失败、并发及生命周期

调整失败旧卡保持不可直接应用；撤回需重新核实相关basis，成功才可apply；输入不丢，不从旧摘要重新生成。 所有异步结果还遵守SHR-FE-ASYNC及SHR-FE-FOCUS；组件卸载不取消已发送正式命令。

#### 4.8 实现定位

cards／composer／formation owner。当前为拟接入位置，代码尚未实现；前端不发起独立模型任务，4.7全部引用后端AI-FORM-DISCUSS。

<a id="app-fe-recover"></a>
### APP-FE-RECOVER 未知命令核实及界面恢复

#### 4.1 能力说明

文档级明确用户操作；输入与正式对象分离，完成条件是本能力已知事实及反馈，不等于产品全流程完成。

#### 4.2 输入与来源

| 输入 | 类型／来源 | 必传／可空／默认 |
| --- | --- | --- |
| owner | OBJ-FE-OWNER／当前所属文档 | 必传不可空；无选择时入口禁用并说明 |
| input | OBJ-FE-COMMAND原快照、真实receipt | 动作字段按后端联合；可空仅其明确允许项，无隐含默认目标 |
| endpoint | 原同method/path/body/key；原Run读取 | 严格API adapter；不由组件拼任意路径 |

#### 4.3 处理过程

提交前共享账本事务完成；传输未知留原请求和输入，核实原动作；成功200/202持久记录终态摘要再只读刷新，运行继续按guide_run_id观察。

#### 4.4 输出与完成

渲染实际DTO／成功回执或安全错误，保留本地查看／输入；正式成功与刷新状态分别提供。只读返回仅说明读取覆盖，保存回执仅说明该次动作。

#### 4.5 失败、并发及生命周期

本地存储不可用则本次尚未发送，保留输入并说明“无法暂存原操作，请恢复本地存储后重试”；已经发送时存储异常保留内存快照、显示待核实，不改为失败或另发新动作。 所有异步结果还遵守SHR-FE-ASYNC及SHR-FE-FOCUS；组件卸载不取消已发送正式命令。

#### 4.8 实现定位

共享恢复技术层＋formation adapter。当前为拟接入位置，代码尚未实现；前端不发起独立模型任务，4.7全部引用后端AI-FORM-DISCUSS。

## 5. 页面与组件

### 5.1 共享视觉与可用性

沿项目现有颜色／间距／字体token及公共按钮、EmptyState、对话卡、来源弹层和编辑器，不创建另一套视觉库。形成路线使用纵向主线＋有序节点，支线单层缩进／虚线，编号表示当前顺序、StepRef为稳定身份；不用横向超长流程条／无限画布。主线行标题完整换行，状态／原因与按钮共用流式容器；文字与工具条间距使用公共token，不用绝对坐标或人为留白遮对齐。

面板沿360px最小／420px偏好，但窗口不足360时可收缩为可用宽度，外层工作台切换原单面板布局，不能强制横向滚动。展开视图外边距16px，最大宽1120px，高度最多calc(100dvh - 32px)，内部正文可滚动；可用宽度≥900px时左路线320px、右详情minmax(0,1fr)，间隔16px，低于900px单列。正文编辑器由原宿主保持，不因查看路线重挂载。交互目标至少32px高、窄屏主操作可整行，长按钮文案换行且不覆盖引用文字；不虚构手机专属交互路线。

| 事实 | 显示与来源 |
| --- | --- |
| 步骤状态 | PLANNED“未开始”、IN_PROGRESS“进行中”、PAUSED“已暂停”、COMPLETED“已结束”、CANCELLED“已放弃”；图标＋文字，依据实际status |
| 当前／查看／下一轮 | 正式焦点标“当前讨论”，正在查看用边框／aria-selected，未生效目标单列“下一轮讨论”；在途消息标签“本条回复：步骤名／支线名” |
| 支线 | OPEN“讨论中”、RESOLVED“已有结果”、DEFERRED“已暂缓”、DROPPED“已放弃”；固定“来自…”与“返回…”两行，来源未变不偷换为当前归属 |
| 成果 | 程序CURRENT“关联已核实”、NEEDS_REVIEW“待复核”（review_reason=CHANGED表示内容已变，UNVERIFIABLE表示暂无法核实）、REMOVED“原内容已移除”；AI SUFFICIENT“AI评估：基本充分”、GAPS_REMAIN“AI评估：仍有缺口”、UNCERTAIN“AI评估：材料不足，暂无法判断”；assessment=null才显示“尚未评估”，validity=STALE另标“评估依据已变化”分别显示 |
| AI建议 | recommendation=null显示“暂无建议”；CURRENT显示“当前建议”；STALE显示“历史建议，依据已变化”及所属原因，保留原说明和来源。独立手动操作不因旧建议过期而禁用 |
| 提案 | PENDING“待确认”、DEFERRED“已暂缓”、needs_revision“调整中／待重新核对”、APPLIED“已采用”、SUPERSEDED“已有新提案”；实际处置及availability为准 |
| 结束与文档 | “你结束了本步骤”，可附“仍有待处理事项”；不显示“文档已确认／需求已完成”，除非原真实确认事实存在 |

<a id="bnd-fe-workbench"></a>
### BND-FE-WORKBENCH 所属文档工作台／进展面板

#### 5.2 布局与区域

沿现有需求详情文档工作台导航，进展页顶部显示“文档形成路线”、展开视图；其下Goal摘要（可展开全文）、“已放弃节点N”复选框、“支线”复选框和“定位当前讨论”。路线列表一条纵轴、每步一行概要，下面可有支线摘要；节点点击只展开一个详情，状态、真实开始／结束事件及待写入／待复核计数可见。没有步骤编号的支线不伪造成主步骤。

详情固定页签“概览／成果／问题／支线／记录”。概览展示完整成果要求、依赖及替代关系摘要、真实触发事件、AI最新判断及带当前性标记的最新建议和可用主动作；成果页分开真实正文关联与分析依据；问题／支线页有全局总数及“加载更多”；记录页按事件高水位分页，结束记录进入历史快照详情。单项Closure只显示证据数／摘要，点击“查看证据”按EVIDENCE分页；事件成员集合用MEMBERS逐项加载，ORDER显示各节点原位置／新位置，禁止先取全部数组再在浏览器切页。成果复核／替代历史从该event的CHANGES中解码ARTIFACT_REVIEW，显示当时旧关联→新关联、触发回复与核实Revision；不向当前LINEAGE借值拼成旧事实。各关系页只有其自身加载提示，不遮现有正文与输入框。

#### 5.3 数据、字段与加载

| 区域／字段 | 数据源与读取时机 | 缺失／空／更新 |
| --- | --- | --- |
| Goal／正式焦点／全局计数 | BND-FORM-SUMMARY，首次进入和实际操作后定向刷新 | exists=false显示未建线；损坏／失败显示具体错误，不伪造空Goal |
| 节点行 | StepPage；初页20、按F继续 | position仅展示编号；已放弃节点标“原第N步”沿取消时位置，不当当前排序；页外选中实体按StepDetail读取 |
| 节点标题／状态／最近活动 | StepView及last_event | 长标题换行；无开始事件写“尚无开始记录”，不从结束倒推 |
| 详情／关系 | StepDetail＋RELATIONS，成果范围另按RANGES的role分页；首次展开相应页签 | 已加载与total分别展示；错误只阻止依赖该数据的操作 |
| 历史／Closure | EVENTS／CHANGES／CLOSURE，用户打开时 | 原当时版本／定义／Revision及EVIDENCE／MEMBERS固定event_id读取，不用最新状态或名称篡改历史 |
| 提案／待复核计数 | ProposalPage及Summary同快照计数 | 未加载的提案不能因当前列表空判没有；冲突重读相关集合 |

#### 5.4 用户操作与反馈

| 操作 | 触发与实际请求 | 反馈／焦点 |
| --- | --- | --- |
| 查看步骤／支线 | 点击标题，纯GET | 保持正式焦点／输入；可见“正在查看” |
| 讨论此步骤／整份文档 | 空闲明确SWITCH_STEP（整份为null），在途仅next_target | 已完成／放弃步骤可讨论，无自动重开；不要求依赖完成 |
| 讨论／继续支线 | 完整step/branch，OPEN进入；RESOLVED/DEFERRED显式RESUME并enter_after_resume=true | 一次原子选择；失配保留输入，不能先改主步后报支线失败 |
| 返回主线 | RETURN_FROM_BRANCH，明确当前支线 | 只清焦点，未解决支线仍OPEN；不可猜第一节点 |
| 结束本步骤 | COMPLETE_STEP，默认空处置数组、next=null；直接明确动作 | 不弹同义二次确认；缺内容／AI不足提示不拦截。非当前普通结束不抢目标 |
| 结束并继续 | 用户明确选择下一节点，再COMPLETE_STEP携带next | 回执后按同selection_epoch同步下一轮目标；保留输入、卡草稿及其他节点状态 |
| 暂停／恢复／重开 | 真实可用原生命令；理由仅业务规定的暂缓／放弃 | busy／版本冲突有具体原因，不用“不可用”统称 |
| 调整路线 | 打开BND-FE-PATH，带当前basis及可空原卡 | 不直接写正文；取消按完整编辑器处理 |
| 定位／筛选／更多 | 本地定位＋必要GET | 筛选变更只重置该页cursor，保留业务目标和草稿；选中被隐藏时显示过滤提示 |

#### 5.5 特殊状态与生命周期

| 状态 | 布局／说明与恢复 |
| --- | --- |
| 未选择文档 | EmptyState，文档图标，“选择文档后查看形成路线”；原文档导航保持可达 |
| 首次加载 | 面板骨架／“正在加载形成路线”，不显示成功空态；不自动建线 |
| 未建线 | EmptyState，路线图标，“尚未形成路线，可在讨论中明确目标”；不自动聚焦或发Chat |
| 正常空页／筛选无结果 | 对应列表EmptyState，“当前筛选下没有节点／问题／支线”；保留清除筛选入口 |
| 分页失效 | “路线已更新，正在重新读取”；保留节点ID／输入，重新取有效页；不错误显示历史已删 |
| 无记录／无成果 | 记录图标“本步骤暂无事件记录”；成果图标“尚未关联文档成果”；分析成果另为“尚未登记分析依据” |
| 失败／不支持来源 | 具体安全错误＋原重读入口；已有数据保留并标需刷新；不使用成功空态覆盖 |
| busy／UNKNOWN | 显示原占用／待核实动作原因，禁用实际受影响写操作，查看／滚动／编辑未提交文本可用 |
| 历史／已放弃 | 仍可查看和明确讨论；正式已结束事实只读，不把历史卡当新可用操作；是否可采用沿后端真实availability |
| 切换／关闭 | 保存展示偏好及草稿，释放只读请求；命令恢复由共享owner继续，运行不取消 |

<a id="bnd-fe-path"></a>
### BND-FE-PATH 路线编辑与预览视图

#### 5.2 布局

使用工作台内弹层／抽屉，标题“调整形成路线”，顶部当前基准及未保存状态，正文分“目标／步骤变化／受影响事项”，底部“预览调整”“保存路线”“返回”。预览数据按后端PathPreview完整字段解码，使用discussion_version／formation_version／content_version，不发送D/F/V缩写；affected_items及warnings各有独立slice／total／cursor，超过首屏可带原草稿按section加载更多。预览为只读差异、旧成果逐项去向、问题／支线返回点、依赖和替代关系；不在预览编辑Markdown，不增加“保存并结束”。长影响列表各自分页；不把20项用户变化额度画成终身节点配额。

#### 5.3 数据与输入

| 字段／控件 | 类型、来源及输入 | 校验与缺失 |
| --- | --- | --- |
| 目标 | SET_GOAL.text、真实source_refs，取当前Goal | 1—1000码点；改变Goal明确显示影响，不能由客户端伪造来源 |
| 步骤／成果 | 当前真实定义；新增使用temp标签 | 标题1—120，说明1—1000，每步成果1—20；成果kind不能偷换 |
| 顺序／依赖 | 可用上下移动和“置于…之前”原生select；StepRef稳定 | 不仅支持拖拽；不可见节点可用检索／分页选择，不静默忽略 |
| 取消／拆分／合并 | CANCEL＋ADD＋replaces＋ResultRoute | 列出每个旧成果REPLACED或NOT_REQUIRED及原因，不提供删一行就消失 |
| 问题／支线 | MOVE_ISSUE、SET_BRANCH_RETURN、显式处置 | 双OPEN归属核对由后端；UI不强迫非OPEN历史支线随问题搬动 |
| 已有内容复用 | LINK_CONTENT的当前Revision/block/results | 精确只读定位，内容来源不变；承接关系不表示本轮写入 |
| 原路线卡 | based_on_proposal＋原payload只读 | 用户编辑复制到草稿；原消息永久保持原提案 |

#### 5.4 操作、结果与失败

“预览调整”调用BND-FORM-PREVIEW，成功后显示对应D/F/V及changes_digest；修改任意字段、实际basis变化都使预览STALE。保存使用同一严格变化体经PATCH，按MANUAL_EDIT严格检查expected_F；即便based_on_proposal非空也不降低检查。直接采用不可变路线卡经responses按CARD_APPLY核实相关binding，不拿旧冻结F当expected_F。后端重新校验；预览成功不绕过服务端检查。保存期间防重复；UNKNOWN保留原冻结请求，后续草稿与原命令分别显示；保存成功按reference_map定位真实新节点，读失败只显示待刷新。超限原样保留所有输入并显示实际／上限，提示拆成完整可独立校验批次，不自动分段提交有跨批依赖的取舍。

关闭时有未保存草稿只保存本地并显示“已保留草稿”，再次打开以最新正式basis核对；本地存储失败保持当前内存并明确提示。不能以自动清草稿作为关闭动作；用户明确“放弃本地草稿”才删除本文件自己的键，未决原命令记录不可同时删。

#### 5.5 特殊状态

无主线时仅通过正常讨论建线，此编辑器不构造空正式头；加载影响范围失败保留编辑值并禁止依赖未核实取消的保存；旧卡过期允许保留文本作用户草稿但不可冒充新绑定。缺成果不是所有编辑的通用禁用理由，取消缺去向才是具体非法操作。历史快照只读，不能在当前编辑器回写旧Closure。

<a id="bnd-fe-proposal"></a>
### BND-FE-PROPOSAL 新用途卡片与精确预览

#### 5.2 布局

复用原卡片组，顶部“待确认写入”或“路线调整建议”，正文说明原目标／Step／基准Revision，来源可打开；预览区域明确现有内容及实际新增／替换片段。底部单一主要确认按钮、次操作“继续调整”，写卡另有“暂缓／恢复”。步骤详情的待写计数跳到同一张原卡，不复制可执行卡实例。预览只读，编辑需求回输入框，避免确认内容与实际请求不一致。

#### 5.3 数据与输入

只读来源为ProposalPage或已保存消息的不可变card payload；严格校验purpose与其payload联合，未知schema展示“不支持的卡片版本”并保留原消息。正式输入只按后端DTO构造一次apply回答；任何自定义答案／跳过／多选均不适用于新用途。卡片处置、expired原因及可执行性从最新服务端投影取得，浏览器不因当前F号不同自行将全部卡过期。

#### 5.4 操作与结果

确认写入／采用路线调用原`POST /conversation-messages/{message_id}/responses`；收到PROGRAM回执显示“已写入文档／已保存路线”，不画AI加载。步骤生命周期不改，已结束步骤仍可采用适用卡。继续调整选中原卡并显示目标说明；实际发送用户要求时才DISCUSS新增调整意图；新卡已保存才SUPERSEDED旧卡。撤回调整显示本次复核是否成功；成功只清调整标记，原发布绑定／原卡不替换。失败继续保持旧卡禁用，不提供忽略basis按钮；前端不提交binding／复核凭证。撤回回执确认后刷新失败只显示已成功、待刷新，未知状态只核实原key；后续apply仍以最新服务端许可为准，不能把撤回成功当永久授权。

#### 5.5 可用性与异常

| 情况 | 按钮／说明 |
| --- | --- |
| 有效PENDING且原文／定义／用途匹配 | 主要确认可用；仅焦点／D变化不失效，发送以最新D |
| COMPLETED步骤且提案仍适用 | 明确“写入不会改变已结束记录”，仍可确认，不要求重开 |
| DEFERRED | 显示恢复操作，不消耗apply；实际版本变化仍可使恢复后不可用 |
| needs_revision | 原确认禁用，显示“调整中／需重新核对”；撤回需后端依原发布绑定核实通过，不生成新执行绑定 |
| 相关内容／Goal／定义／来源变化 | 显示具体过期原因与“继续调整”，不在前端换V后apply |
| APPLIED／SUPERSEDED／正式已回答 | 显示原结果／新提案入口，无再次apply；原消息保持 |
| SENDING／UNKNOWN | 同一卡不可第二次确认；核实原操作，保留预览及输入 |
| 后续GET失败 | “操作成功，显示待刷新”，只有刷新入口，不重新确认 |

### 5.6 可复用组件契约

各组件是上述页面内部组件，调用同一owner。没有私有fetch／数据库／模型调用；在实际容器中检验窄宽、长内容、禁用／处理中／历史／占用／人工编辑状态。

| CMP编号／组件 | 输入与来源 | 输出／所有者 | 状态、焦点及复用 |
| --- | --- | --- | --- |
| CMP-FORM-ROUTE RouteList | StepView页、Summary计数、view_selection、next_target、筛选及query状态 | onView/onTarget/onMore/onFilter；owner执行 | 当前／查看／下一轮分别表达；上下键仅列表导航不发送；tab到原生操作按钮；复用面板和展开视图 |
| CMP-FORM-STEP StepDetail | StepDetail＋分页关系＋availability | onNative/onOpenSource/onRelationPage/onEditPath | 五页签，保持每签滚动；折叠不删草稿；异步成功不强制聚焦标题 |
| CMP-FORM-BRANCH BranchItem | Branch、来源／return可读名及可用原因 | view／enter／resume／return／dispose明确意图 | 来源失效保持原Ref与原因；继续恢复true／只恢复false是不同明确操作，无自动Chat |
| CMP-FORM-RESULT ResultEvidence | 成果定义、Artifact及最新AI assessment、实际覆盖 | openRevision/openSource/loadMore | 关联与充分性分列；遇ARTIFACT_SUPERSEDED保留原选择与输入，显示链末端入口，用户明确选择后才再次复核；不在render发复核请求；历史Revision只读；默认仅活动末端，历史关联标“已被替代”并按successor_ref／LINEAGE查看，边上的review_event_id可打开固定历史事件，不把旧待复核再次计入当前 |
| CMP-FORM-EVENT EventTimeline | EventPage、Closure／changes分页 | more／openEvent／openSource | 时间线不按页索引改事件ID；当前与历史快照区别；缺来源给原因；ARTIFACT_REVIEW按固定事件来源展示，PROPOSAL_CHECK仅显示当次撤回复核事实 |
| CMP-FORM-PREVIEW ExactProposalPreview | 原purpose/payload、scope、真实基准、availability | apply／adjust／defer／resume／withdraw | 只读精确内容；长补丁可折叠但可完整读；不重写卡原文 |
| CMP-FORM-PATH PathEditor | Draft、可用实体及影响页、Preview和保存状态 | edit／preview／commit／discardLocal | 所有字段有label；错误定位具体项；拖拽另有键盘等价；不自动关闭冲突草稿 |
| CMP-FORM-EXPANDED ExpandedFormation | 相同owner和selection | close／view等原意图 | role=dialog、aria-modal、标题、焦点圈定／Esc关闭；打开聚焦标题或首可用控件，关闭回原展开按钮；不挂载第二owner |
| CMP-FORM-TARGET ComposerTarget | server_focus／next_target／accepted_target、安全冲突原因 | select／clearLocal／send原输入 | 原输入框旁简短“下一轮讨论：…”；不增加技术basis详情；恢复未消费标待生效，接受后归一化 |
| CMP-FORM-RECOVERY CommandNotice | 原命令本地状态／安全receipt／刷新状态 | verifyOriginal／refresh | aria-live只播状态变化，不循环抢焦点；没有“忽略未知再执行” |

组件表中的来源弹层、按钮／EmptyState／编辑器／卡片外壳使用现有公共组件。新组件文件名可按现有模块拆分，但不得复制命令与恢复业务逻辑。错误原字段不可被通用“暂无内容”替代。

## 6. 交互与后端契约

### 6.1 公共API规则

唯一公开契约是[后端第6章](WALL-E.后端设计文档_V_2.1.md#6-对外与内部交互契约)。严格解码成功`{success:true,data,error:null,meta}`和失败`{success:false,data:null,error:{code,message,details},meta}`；meta.pagination承载page_size/has_more/next_cursor，不在根meta虚构这些字段。未知新字段／错类型／身份不匹配当响应不可核实：GET显示读取失败，已发写操作进入UNKNOWN，不能当已回滚。Safe integer、null、版本、来源及新错误details用显式联合，不用any绕过。

### 6.2 页面绑定与提交边界

| 页面／能力 | 入口及请求 | 正确消费 |
| --- | --- | --- |
| 工作台首次读取 | 先GET requirement expand=discussion＋document_id；仅exists=true再GET FORMATION steps首20并带known_f | Summary无主线／有主线使用相同键集，无target键；直接实体页返回FORMATION_NOT_INITIALIZED时重新读取Summary区分未建线与文档不存在；Summary及页同F；必要冲突重读，无额外Chat |
| 节点／关系 | 后端STEP／RELATIONS／RANGES／ARTIFACT／LINEAGE，known_f及kind/role | 只读、保留当前选择，不构造全量图 |
| 历史／Closure | EVENTS／CHANGES／CLOSURE／EVIDENCE／MEMBERS固定事件或upper_event_id | meta.pagination独立cursor，不用当前F覆盖历史 |
| 原生命令 | PATCH requirement，body为后端DTO-NATIVE | key只头，actor／时间／来源由程序；默认完成数组[]无强制处置 |
| 路线预览 | POST path-preview，ADJUST_PATH严格体，无key | 不保存正式事件／ID；body编辑后旧预览失效 |
| 确认提案 | POST conversation-messages/{id}/responses；原5字段body | 不加document_id、不传payload；两种新purpose都PROGRAM 200 |
| 文档讨论／调整 | POST requirement guide-runs；后端完整DISCUSS联合 | 原九个body字段＋四目标字段＋proposal_intent；proposal_ref沿原字段，不重复；202含accepted_target |
| 运行观察／取消 | GET guide-run；POST cancel原契约 | 202只接受，运行失败不反转已提交恢复；关闭面板不cancel |

原CreateGuideRun body完整为document_id、expected_discussion_version、operation、instruction、target、scope、source_refs、proposal_ref、acknowledge_source_changes；model_profile_id不在此body，沿可信Runtime。新增目标字段每次明确传null或值，不从当前高亮偷偷补齐；非DISCUSS保持原严格契约。确认apply body完整为schema_version、responses、expected_discussion_version、execution_selection，message_id在路径；卡payload仅来自原服务端卡。

建议读取采用后端RecommendationView的basis／validity／stale_reason，不从全局F或“最新一条”自行判断有效。STALE只作为历史说明，移除“按此建议操作”快捷动作；CURRENT仍须结合本次availability。用户独立的“结束本步骤／讨论此步骤”等原生入口按真实状态保留，不因旧建议失效增加门槛。查询更新可改变派生标签，不修改原消息／历史建议、不触发额外模型；前端不上传或自行修订RecommendationBasis。

### 6.3 请求状态与恢复顺序

1. 用户明确提交后，先从当前草稿形成完整严格body、冻结D及完整目标，生成key和PreparedCommand快照；将不可变快照存共享账本，事务complete才send。不以HTTP发送后补存作为正常保证。
2. 正常200／202严格解码、匹配原身份，先确认本地原动作，再更新事实；仅当草稿epoch仍对应已接受版本才清该份输入。之后定向读取Summary／受影响页／正文；失败独立记refresh_state=FAILED。
3. 明确业务拒绝保留用户草稿，显示对应字段或安全原因。版本冲突只刷新、待用户核对后新动作，不自动改旧body／key。非法图整批失败，不在UI留下已提交假节点。
4. 传输未知／解码失败／REQUEST_IN_PROGRESS进入UNKNOWN，“核实原操作”只重放冻结快照；同key已有成功直接取原回执，不重复写入／恢复／Chat。未知未核实前不自动发替代动作。
5. 在途用户改next_target只本地生效；晚到回执可更新原文档的已知事实，但其selection_epoch较旧时不覆盖新选择，不跳转当前页，不删除新输入。确认RESUME成功的后续目标用ENTER；原UNKNOWN快照永不修改。

### 6.4 内部事件与订阅

沿原owner读取／GuideRun观察，组件用现有React订阅模式。不新增SSE／WebSocket／供应方chunk展示。跨标签恢复变化只通知重读本地账本和必要服务端状态，不能靠BroadcastChannel宣布正式成功；页面visibilitychange可重读，不能自动Chat或自动提交草稿。卸载释放读请求／监听，等待中的写请求交共享恢复层持有。

## 7. 数据与技术依赖

### 7.1 客户端数据归属

正式对象、内容、Revision、原卡、Closure、来源及幂等以服务端数据库为真源；浏览器仅缓存有界页、未提交用户草稿、展示偏好及原请求恢复快照。不可把缓存Summary当最新允许操作；重新进入先显示已有缓存为待刷新，读取失败保留事实边界，不执行离线正文写入。

### 7.2 前端一致性与技术保证

| 保证 | 机制与边界 |
| --- | --- |
| 请求原样重放 | 扩展原PreparedCommand导出／恢复可信快照接口；校验method/path/key/body摘要、origin及FORMATION注册能力。不能通过普通prepare生成新key伪装重放 |
| 跨标签去重 | 复用单账本原事务认领／intent唯一索引；record_revision防旧标签覆盖新终态，服务端幂等仍是最终保证；通知不是锁 |
| 旧响应隔离 | doc/query/epoch比对；写命令事实与当前页面选择分开交付。卸载不丢唯一原body |
| 预览与提交 | 同草稿摘要＋D/F/V，预览变旧不可直接保存旧方案；服务端COMMIT重新校验，不信任客户端preview |
| 局部刷新 | 按receipt.effects及event定位刷新受影响Summary／页／文档，不重挂正文编辑器或全屏清空；F变化相关页重启游标 |
| 本地失败 | 新请求尚未发送且原快照落盘失败时不send；已发未知不删除记录／不换key，存储损坏保留原字节并提示，不能自动“清空恢复” |

### 7.3 模型及外部技术依赖

浏览器没有独立模型／计数端点或凭据，全部通过原后端GuideRun能力。Profile、Prompt、选材、重试／预算及真实usage以[后端4.7／7.3](WALL-E.后端设计文档_V_2.1.md#inf-form-model)为准；请求详情沿原真实快照，不能从当前正文拼一份“当时上下文”。PROGRAM明确0Chat，MODEL显示真实运行，卡片预览不触发网络模型。

### 7.4 INF-FE-STORAGE 浏览器存储与恢复

| 数据 | 载体、键／隔离及结构版本 | 读写、清理及恢复 |
| --- | --- | --- |
| 现有对话输入 | 原sessionStorage `walle:v1.5:document-composer:{requirement}:{document}`，schema1；仅instruction | 复用ComposerDrafts；输入1—10000码点沿原规则，发送接受后只清对应epoch；存储失败输入仍内存且提示 |
| 现有普通卡答案 | 原sessionStorage `walle:v1.5:document-cards:{requirement}:{document}:{message}`，schema2 | 原CardDrafts不改存储语义；新apply不持久原卡payload作替代真源；正式回答后再清 |
| 形成路线／目标草稿 | sessionStorage `walle:v2.1:formation-draft:{requirement}:{document}`，schema1 | 值为{schema_version,requirement_id,document_id,path_draft:null或OBJ-FE-DRAFT.path_draft,target_draft:null或OBJ-FE-DRAFT.target_draft}；原origin天然隔离，恢复先核实ID／schema／F与实际状态；旧预览不恢复为READY |
| 展示偏好 | localStorage `walle:v2.1:formation-view:{requirement}:{document}`，schema1 | 值为{schema_version,requirement_id,document_id,selected_step_ref:null或StepRef,tab,show_cancelled,show_branches,scroll_anchor:null或StepRef}；不存正文／命令／正式状态；损坏不覆盖，当前内存默认并提示；仅用户显式清除对应键 |
| 原路由位置 | 既有`walle:v1.5:route-position`命名空间 | 沿原router，不清空、不复用成formation草稿；历史和文档导航保持 |
| 未决正式命令／已知终态摘要 | 复用原IndexedDB `walle-v2-code-command-recovery`，对象仓库pending_commands／command_receipts及by_origin_intent索引，物理DB升级至version2，先完成下述兼容屏障 | 原行schema4及Coding／Testing保留，新bundle按原模块恢复；新增FORMATION使用schema_version=5类型分支，不把本地记录版本当物理库号。新增owner_module="FORMATION"，由共享技术层注册，旧模块不可误解新行 |

**跨版本连接屏障（INF-FE-LEDGER-UPGRADE）**：新bundle以open(name,2)打开原同名库，升级事务不改两仓库／原索引，不改写或删除记录4；仅完成物理版本屏障后，联合decoder才可读取4／5及写入5。升级前的原客户端以version1打开且onversionchange关闭连接；升级完成后旧脚本再open(name,1)得到VersionError，不能进入仓库扫描记录5。不能假设旧脚本会显示新文案；新页面显示“恢复记录升级中，请刷新或关闭旧版本标签页”。

升级blocked或失败时，不发起本轮任何新正式命令、不写记录5、不清账本；已有原请求和未提交输入保持，旧页面在升级完成前仍可按原协议核实原动作。升级需等待已有IDB事务完成或中止；旧页面已发送的HTTP可以继续返回，不能声称被取消。若它来不及保存本地终态，原记录4仍在，由新bundle按原module／method/path/body/key继续核实；严格区分旧模块的恢复规则与新FORMATION规则，不重新分配key或当未执行。新客户端重载后仍使用DB2，若检测到更高未知物理版本则停止写入并要求兼容客户端，不降级重建库。

兼容屏障只关闭旧IDB连接，不保证停止旧脚本已准备的网络请求；服务端原幂等保护仍必须保留。新bundle须识别记录4的原PREPARED／DISPATCHING／ACCEPTED／UNKNOWN等状态及旧已知终态，不把其重编码为FORMATION。跨标签总容量及事务认领在同一DB2进行。此为目标升级设计，本轮不实际打开／升级用户浏览器数据库。

新增FORMATION pending行的完整字段：schema_version=5、owner_module、origin、key、method、path、identity_sha256、body_sha256、body_text、intent_key、requirement_id、document_id、status:PREPARED/DISPATCHING/UNKNOWN、created_at、updated_at、submitted_at:null或UTC、dispatch_count:非负整数、dispatch_owner_id:null或UUID、record_revision:Version、recovery_mode="REPLAY_ORIGINAL"。identity_sha256按canonical {owner_module,origin,key,method,path}计算，body_sha256按原UTF-8 body_text计算；intent_key为同origin唯一用户动作标识，不能用版本变化自动派生第二intent。同库不同owner严格联合校验，不向新FORMATION行塞task_id/testing_task_id/operation_id，不套代码专用CLOSED_UNEXECUTED或服务端REJECTED账本语义。

FORMATION终态摘要字段为schema_version=5、owner_module、origin、key、method、path、identity_sha256、body_sha256、intent_key、requirement_id、document_id、final_state:CONFIRMED/KNOWN_REJECTED/CANCELLED_UNSENT、http_status:null或整数、result_code:null或安全code、guide_run_id:null或ID、user_message_id:null或ID、event_ids:EventID[]、resolved_at:UTC。200／202确认后可将pending原body移除并存对应终态摘要；若本地确认落盘失败，保留pending，服务端原key成功仍可核实。KNOWN_REJECTED指已知明确响应，只是客户端事实，不创建服务端REJECTED命令分支。CANCELLED_UNSENT仅确认从未send的PREPARED可用，UNKNOWN不能清除或关闭为未执行。

沿原账本本地待核实容量100条／128MiB、单元数据64KiB技术元数据边界；新增Formation body仍遵守完整请求8MiB，不能拿64KiB元数据上限拒绝合法精确正文。容量只限制尚未核实本地队列，不是业务历史上限；满时保留已有记录并提示先核实，不删旧UNKNOWN腾位置。原代码／测试及Formation共享全局队列计数，不能各留100条规避总量。已终结摘要不自动删除，显式本地维护仅可清已核实终态，不影响服务器历史。

sessionStorage成功不保证关闭浏览器后的永久保留，退出事件不承诺写盘成功；输入变更时即保存，不等beforeunload。恢复先严格版本／类型／owner核对，旧或坏值保留原字节并说明无法自动恢复，不迁移成正式数据、不清全部存储。IndexedDB不可用／quota／损坏／旧标签占用分别显示安全原因；不得偷偷降级成先发送再靠内存的未知恢复保证。原V2.0共享层抽取时必须同时验证旧调用不变，不复制第二套业务恢复流程。

## 8. 验证与验收

### 8.1 前端场景与共享验收映射

共同FBASE／FGROW及A01—A76采用[后端8.1](WALL-E.后端设计文档_V_2.1.md#8-验证与验收)；下表仅补真实浏览器操作与前端责任，不能以直接赋值事件代替真实点击／键盘。每行用独立隔离数据、不同用例不依赖上一步。

| 场景引用 | 前置与实际操作 | 明确预期 | 对应共享场景／证据 |
| --- | --- | --- | --- |
| TC-FE-01 路线查看 | FBASE工作台；点击s3标题，再点讨论此步骤；切回来查看s2 | 查看只改变view_selection；明确讨论才改变正式目标，依赖不阻止，其他步生命周期保持 | A01—A04、A51—A56；真实页面＋API事实 |
| TC-FE-02 跨步支线 | 当前s3，点击来自s1／返回s2的b4详情，再“讨论支线” | 来源与return分别展示，一次完整目标s2/b4；失败不留下半状态 | A11、A63、A66；真实点击及事务证据 |
| TC-FE-03 一次恢复 | RESOLVED b4；“继续讨论”，202成功后模型失败；刷新再发送 | 旧结果历史可查，当前OPEN；下次ENTER；旧RESUME不重发／不清新结果 | A64—A68；浏览器＋运行观察 |
| TC-FE-04 在途目标 | s2运行未回，选下一轮s3／待恢复b4；在输入框继续编辑；旧回复到达 | 消息仍归原accepted_target，无跳转、无清新文字；新发送才冻结新目标及消费恢复 | A54、A67—A68；真实焦点、请求及回执 |
| TC-FE-05 精确采用 | 展开m210只读补丁，用键盘Tab到确认并Enter | 原补丁精确写入，PROGRAM、0Chat，步骤未结束；重复点击只有一次效果 | A15—A23、A37、A76；页面＋真实链路 |
| TC-FE-06 结束有遗留 | s2无内容／AI不足且i1/b4 OPEN，直接“结束本步骤”；另选择“结束并继续s3” | 不弹强制理由表、不要求写入；Closure遗留可见；普通非当前结束不抢焦点；明确next才同步 | A04、A43—A44、A57—A60、A75；页面＋历史 |
| TC-FE-07 路线调整 | 用键盘select／上下移动拆s2；逐项映射成果、问题及支线；预览后改一项再保存 | 旧预览过时；无完整去向不能取消；保存原子，正文不变、原来源保留、新ID按reference_map定位 | A32—A36、A41—A42；真实原生菜单操作 |
| TC-FE-08 提案调整 | 暂缓→恢复；继续调整实际发送，模型失败；撤回分别basis匹配／不匹配 | apply未提前消费；旧卡仍禁用直到真实撤回通过；新卡成功才替代，输入保留 | A20、A45—A47；页面＋后端事实 |
| TC-FE-09 UNKNOWN | 网络断在服务端commit后；点击核实原操作，另收到200后GET失败 | 原method/path/body/key，零重复写入／Chat；成功后GET失败只待刷新 | A21—A22、A39；真实故障注入 |
| TC-FE-10 多页冲突 | 两标签读D30，另一页改V；本页确认旧卡；另只变D／焦点 | 改V明确过期且保留预览／草稿；只变焦点卡仍可核实；不能自动改旧请求重发 | A23、A55、A60；双标签 |
| TC-FE-11 成果复核 | 人工改b12，查看待复核，再一次相关普通讨论；材料充分／缺失两变体 | 当前关联与AI充分性分开；可核实提示消除，不足保持；旧结束记录不回写，无额外Chat | A24、A69—A71；页面＋真实内容提交 |
| TC-FE-12 大历史 | FGROW，隐藏／显示放弃节点、过滤事件、跨页定位实体，再版本变化 | total不等于loaded；页外真实对象不失踪；F变化重启该页但保留输入与选中ID | A26—A27、A38、A40、A72—A74；实际有界HTTP |
| TC-FE-13 本地恢复 | 草稿变更后刷新／换文档／返回；IndexedDB断存、quota、坏记录、旧schema4各变体 | 原文档隔离；坏值不覆盖；发送前落盘失败0网络写入；UNKNOWN保留原body；旧模块行可继续恢复 | A22、A30、A67；真实存储故障与刷新 |
| TC-FE-14 来源／历史 | 打开旧Closure，再打开当前成果及原Revision；缺来源变体 | 当时定义／遗留不被新状态替换；缺来源明确原因，不以空态隐藏；来源打开不调用模型 | A10、A25、A28—A29；页面＋原资源版本 |

| TC-FE-15 跨版本账本 | 旧bundle／DB1已有记录4且HTTP在途；新bundle open(name,2)，分别连接正常关闭／升级blocked／旧请求成功但本地终态来不及保存；升级后尝试旧脚本open(name,1) | blocked时0新正式发送／0记录5；完成后旧连接不能扫描5，新bundle完整读4并按原key核实；未决数据不删、不新发Chat，旧脚本VersionError不冒充请求未执行 | R21-04；真实跨版本双标签＋IndexedDB |
| TC-FE-16 类型与状态闭环 | 分别读取NEEDS_REVIEW两种原因、CURRENT、REMOVED；assessment=null／UNCERTAIN／validity=STALE；Summary两分支及所有关系／预览联合 | 与后端枚举、字段、空值一一对应；无“UNASSESSED”正常枚举；错误结构读取报错，已发写响应不可信则UNKNOWN | R21-01／02／05；decoder及实际页面 |

| TC-FE-17 路线临时身份 | 使用后端R22完整请求；路线卡发布／预览后关闭再打开，再明确采用；尝试旧字段别名及未声明去向 | 未采用只显示临时标签，无真实新节点；采用后按回执映射定位，原卡及原请求不改；形状错保留草稿与具体原因 | TC-FORM-R22-01／02；真实页面＋接口 |
| TC-FE-18 未建线读取 | 选择无主线文档，观察网络，再从独立直接实体页冲突恢复；选择已存在主线文档 | Summary顺序门禁明确，未建线无实体页请求／无AI；409重新核实Summary，真404错误不伪装空态 | TC-FORM-R22-03；页面＋HTTP |
| TC-FE-19 历史子项分页 | 一个结果1001条关联与每项范围；打开其Closure证据及1001节点ORDER事件，加载多页，再改当前正文／排序 | 页面和网络每次只取当前页，计数不按loaded算，完整不可变证据可追溯；不先取全部数组再本地分页 | TC-FORM-R22-04；浏览器＋真实历史 |
| TC-FE-20 成果替代导航 | a1→a2→a3链及旧review_of被拒，默认当前列表与开启历史，打开LINEAGE／原Revision | 当前只计活动a3，a1/a2标已被替代；不自动跳或改输入，用户可明确选择末端，旧Closure保持原证据 | TC-FORM-R22-05；页面＋事务证据 |

| TC-FE-21 撤回与复核凭证 | 调整失败后撤回，分别无关F变化／相关依据变化；成功200后GET失败；响应未知后按原key核实；撤回后正文再变再apply | 明确撤回结果但不把凭证当永久授权；原卡／原绑定不替换，失败保持禁用；成功后只刷新，UNKNOWN不改请求或清后来新输入；可以从事件看到当次校验版本 | TC-FORM-R23-01及REPLAY；真实页面／协议 |
| TC-FE-22 替代历史 | a1→a2(E1)→a3(E2)，之后当前状态再变；打开E1及当前LINEAGE边上的review_event_id | 历史仅显示E1原边／回复／Revision／来源，当前链按F显示，与旧事实分开；不依赖当前freshness推导过去，失去来源显示不可用 | TC-FORM-R23-02；页面＋固定事件读取 |
| TC-FE-23 建议当前性 | 无建议、CURRENT、三类以上STALE原因、新建议；只切焦点对照；在旧建议过期时独立手动结束 | null才暂无建议；过期显示历史及原因，取消“按此建议操作”快捷项；CURRENT还看availability；独立操作保留，原历史消息不改且0额外Chat | TC-FORM-R23-03及NEW；实际状态与浏览器 |

### 8.2 关键技术保证

严格DTO／错误解码用独立固定正反例，覆盖未知字段、空值、身份串文档、超过安全整数、非法恢复联合、新CARD_RESPONSE；不能仅用后端同一序列化函数生成全部期望。恢复账本用真实IndexedDB transaction complete／abort及两个标签的同intent认领；只有一个冻结请求，物理DB2联合读取旧schema4及新5各自正确，升级blocked与旧标签open(1)失败不丢原请求，响应已知与UNKNOWN不混淆。旧ApiClient不支持可信快照恢复的缺口必须在共享层解决，禁止从JSON重新prepare换key。

对异步用真实延迟／取消／切换顺序，观察DOM焦点、输入值、当前视图和实际请求，不只比较state对象。正文宿主不重建用组件实例／实际选区和输入连续性证明，HTTP200或磁盘代码正确不能代替运行页面可启动；若实施修改开发服务模块，按AGENTS的实际模块导出核对。

### 8.3 AI使用效果与证据

前端不另建模型评测集，采用后端EV-FORM-AI的60样本计划。浏览器验证用户看见的可读回复、结构拒绝、提案精确预览和真实可用原因；不能因文字“已完成”显示成功，effect_state及原事实优先。AI语义／供应商兼容按新授权单独执行，本轮无真实Chat／计数，无效果通过结论。

### 8.4 界面、空态与性能检查

| 维度 | 可重建环境／操作 | 通过条件 |
| --- | --- | --- |
| 窄宽布局 | 1440×900和1024×768工作台；面板360／420；窗口480×800、展开视图899／900阈值两侧；浏览器缩放200% | 标题长120码点、说明1000、多来源／多行按钮不覆盖；正常与禁用／处理中按钮中心、间距一致；无因绝对坐标遮挡正文 |
| 键盘／读屏 | Tab／ShiftTab逐控件、原生select打开选择关闭、Esc退出展开、Enter触发明确命令 | 可见焦点和label，弹层焦点圈定并正确返回，禁用原因可读，单次触发、选择不误提交 |
| 全状态 | 工作台／节点五页签／提案／编辑器／来源／历史各登记初始加载、成功空、正常、失败／无权限、筛选无匹配、分页失效及恢复 | 模块图标＋一句业务文案，空态不掩错、不发请求或转焦点；原导航／创建／筛选可达 |
| 长历史 | FGROW只加载当前页，展开一个详情，来回分页／过滤／关闭展开 | 初始不请求全量历史；DOM随已显示页有界，旧数据不撑整份终身JSON；count沿全量服务端 |
| 前端响应 | 同后端记录硬件／浏览器和数据规模，用户选择／展开到本地反馈20次测p95 | 不含网络时本地反馈p95≤100ms；读写性能沿后端目标，实际报告与目标分开 |
| 晚到与刷新 | 在途输入／切换文档／非当前节点结束、成功后读取失败 | 不闪整页、不重挂正文编辑器、不抢选择、不清新输入，成功事实仍在 |

实施时每个区域在Markdown登记检查位置、实际结果、未覆盖和原因；不逐项留截图／录像／原始JSON。必要临时浏览器产物成功／失败后都清理，正式资源／来源／配置不删。

### 8.5 本轮状态与接续

第1—8章为按统一模板形成的前端详细设计初稿，后端共同契约只读引用；待审定、未正式合并、未实现。静态结果见[详细设计修正核对](../../../verification/v2.1/detailed-design-r23-fixes-2026-11-14.md)。无产品测试、构建、浏览器或真实模型／计数执行。后续先固定真实V2.0源及共享恢复调用方，再按计划实现，不把本次文档完成当代码／验收完成。

## 附录A 接续事实

| 输入 | 已明确／接续要求 |
| --- | --- |
| 源代码 | 当前工作区旧基线与原工作区V2.0未提交实现不等价；已只读核实具体路由／卡片／恢复账本／依赖，完整源提交及调用方须实施前固定 |
| 公开契约 | 后端6章是新联合、分页、回执及错误唯一来源；需生成严格decoder及注册，并与新资源Schema一致；旧v5探索稿不采用 |
| 共享恢复层 | 原单账本DB1／记录4确已存在；目标升级DB2后才新增FORMATION记录5／adapter，物理DB2兼容屏障及共享抽取为目标，须保留旧调用和原记录，不据设计文件宣称已支持 |
| 产品证据 | 页面状态、按钮布局／键盘、存储故障／UNKNOWN、真实供应商均未执行；授权实施后分层取证 |

没有新增待定产品卡点。前后端数值／字段若在后续评审发现偏差，应修改实际单一定义及使用方，不能再复制第三份共同规格。
