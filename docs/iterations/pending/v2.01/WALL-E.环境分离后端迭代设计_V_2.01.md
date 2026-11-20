# WALL-E 环境分离后端迭代设计 V2.01

## 1. 文档说明与范围

### 1.1 基本信息

| 项目 | 定义 |
| --- | --- |
| 规格编号 | WALL-E-BE-ENV-201 |
| 目标版本／文档修订 | V2.01／1.0 |
| 状态／日期 | BASELINED，设计收口／附实施准入条件，2026-11-20（Asia/Hong_Kong） |
| 收口范围 | Linux普通业务、多环境管理／维护、执行与模型许可、工具与原结果恢复、原生控制与启动、检查与本地交付、分批依赖及共享验收 |
| 准入及后续边界 | 资源生成、执行来源／隔离原型、供应方补证、管理及恢复、云容量均待实现／验证；首期不提供任意跨结构转换，见第8.3节 |
| 文档职责 | 共同对象、应用规则、后端入口与共享验收；页面及浏览器存储见独立前端迭代设计 |

依据：[大纲修订1.19](WALL-E.开发与生产环境分离迭代V1_V_2.01.md)、[架构评审修订1.34](WALL-E.架构与平台技术选型评审_V_2.01.md)第6、10、11章。按2026-11-20用户“收口”要求，将当前独立迭代设计固定为1.0基线。BASELINED表示范围、业务契约及实施门槛收口，供后续实施引用；不表示各候选技术已验证、软件已完成或正式设计已合入。后续仅因实际实现冲突、原型失败或新增需求修订受影响条款，常规资源生成不重新开启整轮设计。

复用[V1.5后端正式设计](../../../design/v1.5/WALL-E.后端设计文档_V_1.5.md)的需求、文档、人工草稿、Revision、幂等及事务；[V2.0后端草稿](../../../design/v2.0/WALL-E.后端设计文档_V_2.0.md)及现行代码用于平台依赖、任务与恢复定位，各自状态保持。采用[统一模板](../../../templates/统一需求规格说明_完整模板_重构版.md)的八章职责，不复制原业务字段或创建第三份共同规格。

### 1.2 P1的完成范围

P1目标是：在Mac上的Linux中，以新隔离数据运行同一套WALL-E业务，实现创建需求、创建文档、人工编辑、保存草稿、完成编辑、关闭重启后重读，并证明未发生真实模型或计数调用。Windows用于远程开发与访问页面，产品数据库和业务进程位于Linux。

P1不以空页面、演示服务、SQL可建表或前端构建代替产品闭环。普通环境不启用Coding／Testing外部执行，但沿用其业务结构和必要恢复；以后完整环境继续使用同一业务规则。P1不接入旧Windows库、不启用生产，也不实现从已有完整环境直接降级成普通环境。

P1前后端共同完成后才能验收页面；本稿后端定义不单独证明P1完成。实施前建立本版本计划和需求映射，保留当前工作区改动；本稿不自动授予付费调用、用户服务更新、Git提交或推送权限。

## 2. 技术基线与公共规则

### 2.1 基线及复用边界

| 项目 | 本批要求 |
| --- | --- |
| 平台 | 首批Ubuntu24.04 ARM64／VM内ext4；云Linux x86_64重新构建和验证，不借ARM结果放行 |
| Python／SQLite | 采用架构6.2的固定组合；当前候选为Python3.13.18＋SQLite3.54.1，候选路径与摘要只在验证记录维护 |
| 业务依赖 | 原backend/requirements.lock的31项版本集合；第7.5节定义平台wheel／hash锁及离线安装，实际摘要待构建产物生成 |
| 前端构建 | 原锁文件及构建命令；输入包含frontend、shared和被引用的backend/resources，产物不得覆盖运行中目录 |
| 数据结构 | 保留Schema200业务表及校验机制；按第7章新增环境绑定元数据并发布新结构契约，旧db20-r50不覆盖 |
| 运行模型 | 一个活动应用、一个既有ProcessLock所有者；不增加第二个业务调度器或跨进程数据库写服务 |
| 平台分离 | 业务命令／恢复不直接导入Windows原生实现；可信启动装配选择平台实现，普通HTTP不能选择实现或传入宿主路径 |
| 权限范围 | 普通开发可修改本任务代码；此信任范围不宣称防御同UID恶意进程。完整候选和生产仍须独立身份与固定程序准入 |

第一批仅开放第4.3节列明的普通业务及其必要资源读取。其余既有路由保持存在并返回明确的未就绪原因，不能因导入失败静默消失；扩大开放范围前逐条核对实际副作用。此为P1交付范围，不是删减V2.01大纲要求。

### 2.2 SHR-ENV-IDENTITY 身份与配置

环境ID、数据代次、运行ID均采用规范小写UUID v4，不从名称、端口、路径、PID或分支计算。环境与数据身份由显式准备操作生成并持久保存；运行ID在每次启动尝试生成。配置版本为环境描述文件实际UTF-8字节的SHA256；描述只保存非秘密配置及凭据引用，不包含实际密钥。轮换凭据必须改变其受控引用版本并按运行配置生效，不原地换值却沿用旧配置身份。

所有启动字段来自一个受保护的环境描述文件；其路径及预期摘要由操作者或受信安装入口明确指定。通过参数指定哪份描述与通过HTTP提交任意描述不同。描述不得存于内部Agent可写目录；普通开发环境描述也只授予本任务环境权限。外层环境变量只用于兼容已有启动入口的显式传参，值与描述不符即拒绝，不设隐式覆盖优先级。

字段缺失、未知字段、类型错误、重复JSON键、非规范身份、不允许的根目录重叠或平台不符均拒绝。required_capabilities必须是enabled_capabilities的子集，关闭要求能力属于配置错误。运行中不热换数据库、身份、能力或密钥；更新为新期望配置，按停止／维护边界重启生效；P1不提供运行中配置切换接口。

### 2.3 固定运行包准入

平台运行包清单独立标识OS／CPU、CPython版本及ABI、解释器与_sqlite3产物摘要、SQLite库摘要／版本／source_id、完整编译选项及必要能力。包内路径只能相对已验证运行包根定位；受信入口另固定清单摘要，不接受清单自己声明自己可信。

Linux装配在读取业务库前完成以下检查：

1. 宿主受信入口先核对运行包，再按第7.4.3节构造允许环境并启动目标解释器；不继承PYTHONPATH、PYTHONHOME或动态加载控制变量。目标以-I -B -S启动，工作目录和site启动钩子不成为隐式模块来源；准入完成后才加载明确的应用根。开发源码按明确本任务根加载，完整环境只加载固定包。
2. 验证运行包根、文件字节、Python及SQLite绑定身份；加载后核对实际映射对象、版本、source_id、THREADSAFE及项目使用的能力／限值。不得在业务库打开后才切换SQLite。
3. 由同一个已准入上下文满足activate／require_active；后者不能仅检查“已导入sqlite3”。不关闭原Windows保护或用系统SQLite作为失败回退。
4. Schema发布清单明确关联本平台运行包摘要及逻辑结构摘要。清单读取、构造源码或资源校验失败即终止启动；修改被钉住的源码需要新发布清单。

私有SQLite不放入/usr/lib；原型用户目录候选只适用于本轮开发验证，不能因此视作生产不可篡改包。部署路径变化须重新构建或按明确可重定位方案重新验证；当前绝对RUNPATH候选不直接搬目录使用。

## 3. 共同对象与约束

### 3.1 OBJ-ENV-BINDING 应用数据归属

这是一个应用数据库的部署归属元数据，不是Coding／Testing任务对象，也不是环境管理平台的登记库。

| 字段 | 类型／来源 | 约束及生命周期 |
| --- | --- | --- |
| environment_id | UUID v4／显式准备操作 | 此数据库所属环境；普通重启、代码更新及负责人交接不变 |
| data_generation | UUID v4／显式准备操作 | 当前数据代次；正常写入不变，全新数据／恢复旧快照／替换数据集时另行生成 |
| initialized_at | UtcTime／程序时钟 | 初次建立归属的时间，按现有UTC毫秒格式 |
| singleton_id | 数据库存储常量1 | 恰好一行；缺失、多行或非规范值拒绝 |

初始化时在同一事务写入业务Schema来源标记和本绑定。启动期比较“环境描述中预期身份、实际打开的数据位置、库内绑定”，三者须一致。不能在不匹配时自动改库内绑定或采纳库返回的新身份。

现有code_environment_records保存内部任务的运行资源观察，code_schema_state保存建库／升级来源；均不承载应用部署归属。新增单行元数据有明确缺口依据，不重建需求、文档或内部任务对象。

库内标记可防止误接另一环境的库；它不能单独检测同代次旧备份被越权替换。恢复必须经过受控维护并推进代次，运行期依赖目录权限、文件身份及独占所有权；完整恢复协议仍是后续批次门槛。

### 3.2 OBJ-ENV-STARTUP 私有启动输入

后端装配输入由描述文件和外层预期摘要组成。下表除configuration_sha256外均为描述字段，序列化版本固定为1；configuration_sha256由外层调用提供。宿主安装工具可以引用而非重复存储运行包清单，但解析后必须得到这些确定值。

| 字段 | 类型与必填规则 |
| --- | --- |
| format_version | 整数1 |
| environment_id、data_generation | 第3.1节身份，必填 |
| purpose | DEVELOPMENT／INTEGRATION／CANDIDATE／PRODUCTION；P1仅开放前两种 |
| required_capabilities | 无重复能力编号数组；P1必须包含DOCUMENT_READ、DOCUMENT_WRITE |
| enabled_capabilities | 无重复能力编号数组；P1仅允许DOCUMENT_READ、DOCUMENT_WRITE |
| program_source | 明确工作区快照引用或固定包摘要；工作区未提交变化与固定产物分开标识，不谎报HEAD为已加载全部代码 |
| runtime_manifest_sha256、schema_manifest_sha256 | 64位小写十六进制摘要，必须匹配受信发布钉住的值 |
| lock_root、control_root、data_root、runtime_root、log_root、temporary_root、frontend_root | 明确目标宿主绝对路径；分别检查归属、可写性、用途及重叠关系 |
| database_relative_path | data_root内相对普通文件路径；拒绝空值、绝对路径、..、符号链接与其他别名 |
| access_policy_ref | 本环境访问策略固定引用；不含密码，不接受用任意来源URL代替 |
| model_permission_ref | P1必须显式为null；后续非null仍须验证原模型准入、环境许可与任务授权 |
| configuration_sha256 | 外层安装记录的配置摘要；对文件实际字节校验，不能将本字段纳入自摘要循环 |

lock_root为安装方维护的本环境固定锁命名空间，仅保存预建environment.lock；应用和专用维护程序可打开锁文件，但无权改写该目录及其祖先中的路径项。control_root保存第3.6节可原子更新的控制事实，与lock_root分开。两根均不进入数据恢复／工作区清理范围；lock_root不能放在应用可写的control_root或其他可改名祖先下。两者必须匹配外层受信安装登记的环境归属，不能仅信任描述内自报路径；普通配置更新不得另选锁根，改变宿主安装归属另走受信恢复。

configuration_sha256由描述外层持有，不要求把自身摘要写回JSON。各路径可以在明确受保护总根下分子目录，数据库／日志／临时／执行工作区不得互相包含；只读程序与运行包可以按原准入共享。

此对象不兼任公开配置，也不提供Web编辑接口。平台身份、文件权限及运行能力由现场检测得到，不能信任描述自报“已验证”。

### 3.3 OBJ-ENV-CAPABILITY 能力与运行观察

| 能力编号 | 含义 | P1状态 |
| --- | --- | --- |
| DOCUMENT_READ | 已有需求、文档、草稿和Revision的无外部执行读取 | 基础检查通过后READY |
| DOCUMENT_WRITE | 第4.3节无模型的人工业务操作 | 基础检查通过后READY |
| DOCUMENT_AI | 文档讨论／生成／修订及其计数 | DISABLED |
| TEST_PLAN_AI | Testing计划的模型生成 | DISABLED |
| INTERNAL_EXECUTION | 仓库受管操作、Coding运行及内部Git交付 | DISABLED |
| INDEPENDENT_CHECK | 独立检查与浏览器执行 | DISABLED |

能力状态为READY／DISABLED／UNAVAILABLE；分别表示准入通过、配置明确关闭、要求开启但前提不满足。状态附程序生成的reason_code，不直接返回异常原文：DISABLED固定CONFIG_DISABLED；UNAVAILABLE按实际原因使用RUNTIME_NOT_INSTALLED、RUNTIME_NOT_ADMITTED、DEPENDENCY_UNAVAILABLE或RECOVERY_REQUIRED；READY为null。同时有多个问题时，先报告阻止安全恢复的RECOVERY_REQUIRED，其余依上述顺序选择首项，详细诊断保留完整检查项。要求能力没有READY时，整个实例不得报就绪；非要求能力缺失只影响其动作，不把完整环境自动降级成普通环境。

进程观察包含run_id、observed_at、configuration_sha256及phase。phase采用STARTING、RECOVERING、READY、BLOCKED、STOPPING；进程已经退出或网络失联由管理观察层核实，不由旧进程永久自报STOPPED。phase与能力状态都不是业务任务状态或鉴权依据。

### 3.4 OBJ-ENV-MANAGER 独立管理身份与登记

管理程序是宿主上的固定受信工具，不从待开发工作区加载代码，不依赖任一业务实例在线。每宿主一份登记库、一个活动写入者；首期只管理本宿主已安装能力，不建设跨主机调度器。Mac虚拟机和以后云宿主各自登记、认证和观察，不能把Mac管理库复制到云上后直接接管同名资源。

| 对象／字段组 | 共同定义 |
| --- | --- |
| 管理身份 | manager_id、host_id为安装时生成的规范UUIDv4；registry_generation为登记数据代次；manager_run_id每次管理进程启动更新。管理数据恢复／重建必须显式换代，普通重启不换代 |
| 环境登记 | environment_id沿第2.2节，purpose、display_name、host_id、record_version、registration_state、preparation_state、configuration_sha256、program_source、profile_ref及第3.2节私有配置引用 |
| 登记／准备状态 | registration_state为ACTIVE／ARCHIVED；preparation_state为PREPARING／PREPARED／INCOMPLETE。归档仅退出活动列表；缺失工作区或数据必须标为INCOMPLETE，不能因旧PREPARED回执继续启动 |
| 外部开发工作包 | task_id为本管理域的UUID，goal、scope、baseline_commit、checks、owner_label与current_writer_principal；这是外部开发委派信息，不是产品CodingTask／TestingTask。开发环境一项工作包；集成环境记录本次集成批次及唯一负责人 |
| 交接版本 | assignment_generation从1递增，record_version随登记配置／归属改变递增；观察刷新不递增record_version。owner_label只用于显示，权限依据受信principal及当前分配；assignment_control_state=OPEN／FENCED及fence_operation_id持久记录是否允许该分配继续派发 |
| 资源归属 | resource_id、environment_id、kind、注册根下相对定位、首次取得操作、实际对象身份、状态及释放证据；私有定位不进入公共入口配置 |
| 运行观察 | 来源、环境／运行身份、manager_run_id、单调递增observation_seq、observed_at、最后成功时间、freshness、运行状态及原因；宿主进程观察与应用握手分别保存，不伪造原子快照 |

同一任务换Agent保留environment_id、data_generation及工作区；另一个开发任务新建environment_id。外部工作包不触发模型，也不代替用户在WALL-E内部创建业务任务。现有code_environment_records保存内部执行／检查的环境依据，不能承载上述登记、委派与管理操作；现有code_operations同样不加入虚假的CODING类型来运行管理命令。

freshness为FRESH／STALE／UNAVAILABLE；运行观察为RUNNING／STOPPED／UNKNOWN，应用phase继续使用第3.3节。宿主适配器核实整个受管进程组已退出且无未知子进程，才可记STOPPED；HTTP失败、心跳过期、PID不存在或Compose命令返回成功均不能单独证明停止。进程运行而握手失败显示“进程运行，应用未就绪”；旧run或旧manager_run的迟到结果只归原观察，不覆盖新运行。超过安装配置的观察有效期转STALE，不把历史READY继续用于准入。

### 3.5 OBJ-ENV-OPERATION 原管理操作与资源占用

管理操作固定绑定管理作用域、原请求键、请求者、动作、目标环境、原输入摘要、expected_record_version及expected_assignment_generation；创建时目标ID由服务端首次受理分配并固化。操作ID及原键回执永久跟随原目标，不能因名称／路径复用改绑。终态回执不因普通环境清理删除。

| 字段／状态 | 语义 |
| --- | --- |
| operation_id、request_key、intent_sha256 | UUIDv4原操作及请求键；摘要按固定动作Schema严格解码、确定序列化后生成，重复JSON键／额外字段拒绝；原有效输入、动作版本及摘要一并保存 |
| WAITING_CAPACITY | 尚未派发外部步骤；容量暂不足，保留原意图与排队时间，不占用尚未获准的内存／CPU额度 |
| ACCEPTED／RUNNING | 原意图和所需占用已提交／至少一个步骤已进入派发；受理不等于环境可用 |
| SUCCEEDED／FAILED／CANCELLED | 已知完成／已知失败／已核实不会继续执行；FAILED和CANCELLED均可能遗留资源，附逐项结果 |
| UNKNOWN | 至少一个已派发步骤的外部结果待核实；不得换键重做、释放其不明占用或归入可清理空闲环境 |
| cancel_requested | 独立取消请求标记；不能把“已要求取消”直接写为CANCELLED |
| steps | 每动作固定步骤表，ordinal、step_kind、状态、派发前外部身份、执行器身份和结果摘要；状态PLANNED／DISPATCHING／SUCCEEDED／FAILED／UNKNOWN／SKIPPED |

不另造通用流程编排器。基础管理登记CREATE、ATTACH、START、STOP、HANDOFF、REGISTER_DELIVERY、ARCHIVE、CLEANUP八类固定动作，第3.7节在同一机制扩展发布／恢复动作；观察、核对和取消是其控制行为。复用原代码的“先留意图、再派发、原结果核对”规则和可提取纯函数，不直接使用绑定业务Schema及Coding步骤注册的CommandReceiptStore。

资源的长期环境归属与操作的短期排他占用分开；同环境后续动作可引用其自有资源，但须另取动作互斥，资源不得同时归属两个环境。一个环境同时至多一个冲突管理动作；共享Git公共目录、分支、路径祖先关系、套接字和端口、运行／构建额度还须跨环境占用。排队意图只占原请求唯一性，获得容量时重新核对环境版本、权限和全部资源，原子取得动作互斥与额度；同环境不能排入多个相反的新动作，已有等待项应继续或取消。UNKNOWN保留已取得占用，不按超时自动释放。只读、原结果查询、核对及取消不被该互斥封死。

重复请求按“当前认证与原作用域校验→原键查找→请求内容比对→若首次才核对版本／准入”处理；相同输入返回同一操作，变更输入报冲突。交接后的旧负责人只在保留原结果读取权限时查看自己的原操作，无权借重复键继续派发。对外副作用不放进登记事务回调；登记事务提交不明时先查原键，不派发第二次。

### 3.6 OBJ-ENV-MAINTENANCE 持久准入与部署事实

维护不是业务任务第六种状态，也不是管理页面的内存开关。本环境的受保护control_root在工作区、data_root及备份还原目标之外，固定保存control.v1.json及不可变维护依据；应用、停机维护工具和受信启动器共同遵守。普通业务数据库的environment_binding仍为第3.1节结构，不为维护再复制一套任务账本。

| 事实 | 字段与责任 |
| --- | --- |
| 控制身份 | format_version=1、environment_id、control_revision（正安全整数，CAS单调递增）、maintenance_id（UUID或null）、operation_source（LOCAL_TOOL／MANAGER）、operation_id及plan_sha256（未使用计划时null）；MANAGER来源另绑定manager_id／registry_generation；不能仅凭操作名称取得维护权 |
| 当前部署 | deployment_id、program_ref、runtime_manifest_sha256、schema_manifest_sha256、configuration_sha256、data_generation、data_root_ref；构成一个完整选择，不分别切换“程序当前目录”和“当前数据库” |
| 准入状态 | admission=OPEN／DRAINING／CLOSED；closed_reason=NONE／NORMAL_STOP／MAINTENANCE／RECOVERY_REQUIRED。OPEN只允许在已核对完整部署后写入；缺失／损坏／未识别记录均阻断 |
| 收尾依据 | drain_manifest_ref、drain_manifest_sha256；固定进入维护时原操作集合及阶段，后续由原业务事实核对，不以快照静止代替实际停写 |
| 开放事实 | last_opened_deployment_id、open_receipt_ref（从未开放时均null）；记录曾经开放，不能因没有业务请求日志就当作新实例从未开放 |
| 恢复限制 | outbound_hold及其cause_operation_id；恢复数据后强制true，独立于被恢复业务库里的旧模型许可／预算；解除须具备新代次授权及原外发核对依据 |
| 模型许可 | 必填model_access={revision, active_permit_ref, last_operation_id, last_effect_ref}，按第3.9节；P1初值0及三个null，不允许据旧许可文件自动生成活动指针 |

首次显式准备按原初始化ID建立CLOSED／NORMAL_STOP控制记录，尚未形成数据库时不能启动；初始化成功仍不开业务。P1尚未部署管理服务时，受信本地启动工具以LOCAL_TOOL及固定原启动ID调用相同控制函数，完成锁内核验后开放；不要求先建M控制台，也不另造绕过维护的启动分支。M部署后使用MANAGER来源，业务进程不能自报新的管理授权。

控制记录是实际准入和部署选择的权威；管理库保存意图及其观察，不能把管理操作进入RUNNING当作应用已关闭准入。业务运行时仅当前应用锁所有者更新本环境控制记录；停机后由取得同一环境锁的专用工具更新。管理进程不同时写同一文件，不直接改业务表。两者没有跨文件／跨数据库原子事务，任何中断都按实际控制revision、部署元组和原操作回执核对。

全生命周期使用lock_root/environment.lock这一稳定锁对象，具体权限及Linux协议见7.2。同环境换data_root、恢复新代次或换程序都必须竞争此锁；不能随新库路径生成另一把锁。普通启动发现锁缺失不重建，lock_root／control_root不放入可恢复业务数据快照，正常清理也不删除。每次启动在打开业务库和启动后台前检查控制记录；维护关闭不会被重启或恢复旧业务库抹掉。

维护阶段由原管理operation.steps及实际观察投影为ENTERING、DRAINING、QUIESCENT、STOPPED、SWITCHING、VERIFYING、BLOCKED、COMPLETED／CANCELLED。QUIESCENT仅表示已核实不再产生业务／外部写入，仍可能有只读连接；STOPPED还要求应用及其受管写入者／连接实际退出，专用工具已取得稳定环境锁。阶段是进度，admission才是准入事实；BLOCKED附最后已知阶段和原因，不覆盖原证据。

### 3.7 OBJ-ENV-RELEASE 发布计划与恢复资产

复用第3.5节管理原操作和第6.5节plan机制，增加RELEASE、RECONFIGURE、BACKUP、RESTORE及ROLLBACK_CODE固定动作；STOP／START继续使用原动作，只是在完整／生产环境走本节维护流程。不给生产另造一套操作系统。

| 对象 | 固定内容 |
| --- | --- |
| 候选 | release_id、commit、目标OS／CPU、应用／前端包摘要、运行包／Schema及固定业务资源摘要、协议与维护契约版本、内容索引、已准入检查证据；不含数据、密钥、开发依赖或可变工作区 |
| 计划 | plan_id／sha256、目标环境／用途／当前部署／record_version／control_revision、源data_generation、目标候选及配置摘要、required_capabilities、兼容结论、容量及恢复策略、确认者与有效期 |
| 停写后准备事实 | maintenance_id、实际停止／锁证据、source_snapshot_sha256、恢复点及必要数据演练结果；绑定原计划，不能拿预览时还在变的数据库哈希做实际升级 |
| 恢复点 | backup_id、source_environment_id／data_generation／deployment_id、cutoff_at、数据库及库外资产清单摘要、固定程序与配置关联、原操作证据、完整性与恢复演练结论、存放位置和异机副本状态 |
| 切换回执 | 原operation／maintenance_id、切换前后完整部署元组、控制revision、数据处置结果、当前准入及开放事实；结果未知保留旧元组和待核对位置 |

首次受理以计划里的环境／控制版本做CAS；同一原操作自身的后续推进使用上一持久步骤返回的revision继续CAS，并把每次变化记入回执，不反复用初始revision误挡自己。其他操作造成的目标变化仍使计划失效，原请求重查仍先命中原键。

发布预览的5分钟有效期限制首次受理，不限制正常收尾耗时；受理后仍持续核对目标、候选、配置、许可与恢复策略。正常收尾造成的数据新增属于已确认计划的准备范围，不使计划因每次写入必然作废。涉及准确源数据的工具必须在STOPPED后固定真实快照并重做源相关核验；若改变候选、Schema转换、恢复范围或预计损失，原计划停止在已知安全阶段，重新展示并确认。更新后的计划沿原操作的REPLAN控制命令留新计划摘要，不能默换原输入；未知外部步骤不能REPLAN绕过。

首期明确准入SAME_SCHEMA：目标与当前实际DDL／objects契约一致，目标声明兼容当前数据、固定资源和未决记录。仅schema_version=200相同不够。结构改变只有对应源→目标转换及完整恢复方案已经在隔离有内容数据上演练通过才可登记；第7.7节FRESH_ONLY包不包含该能力，现有151→200工具不能被当作任意V2.01升级／降级器。缺少适用工具时发布阻断，保留该能力为待交付项，不悄悄清库升级。

### 3.8 OBJ-ENV-EXECUTION Linux执行归属与证据

沿用CodeTask／TestingTask、CodeOperation／步骤、原运行绑定、ModelWindow、LLMUse及原费用预留；新增的是Linux平台证据格式，不另建“Linux任务”。环境run_id、数据data_generation、任务control_generation与业务控制者owner_epoch分别表示应用本次运行、数据集、任务控制代次及业务控制者任期，不互相替代；宿主执行控制进程的生命周期由3.8.2的control_runtime_id另行固定。

| 证据组成 | 必须固定的内容及规则 |
| --- | --- |
| 原执行范围 | environment_id、data_generation、owner_kind、owner_id、operation_id、step_no、原nonce、control_generation；所有引用须同owner。恢复请求同时携带当前控制者和原目标，不能把目标改成当前同名任务 |
| 宿主控制身份 | 安装锚点、host_id、boot_id、固定执行控制程序发布摘要及control_runtime_id、原业务controller_id／owner_epoch与授权应用身份；boot_id仅作同次启动判据，不单独授予接管权 |
| 执行输入 | 固定执行包／OpenCode／运行时摘要、平台、已登记工作区身份、只读依据、网络策略和限额引用、原授权及输入摘要；HTTP不能提交任意Docker参数 |
| 运行资源 | 创建后固定完整容器ID、实际runtime配置、cgroup及网络资源身份、绑定根和控制端回执摘要；名字、标签、IP、PID只作定位线索 |
| 生命周期事实 | PREPARED、CREATED、START_DISPATCHED、RUNNING、STOP_REQUESTED、STOPPED、RELEASED；这是平台观察，不替换业务状态。每阶段附原意图／回执及KNOWN／UNKNOWN证据状态 |
| 停止事实 | 创建／启动已封闭、模型窗口已撤销、原运行及全部所属执行／检查子资源停止、受管写入关闭；分别记录核对依据，不能仅返回active_process_count=0 |
| 释放事实 | 在已核实停止及结果保全后，按原范围释放可释放资源；保留回执、工作成果与恢复资产。STOPPED不等于工作区已删除 |

原绑定与控制记录在沙箱外、受信控制程序可写目录保存；任务文件、标准输出和容器内日志均不能生成可信回执。应用保留原业务步骤和回执引用；控制程序保留实际资源与动作事实，不修改任务业务状态、正文或预算。原控制进程失联时，新控制者先核对原归属；不能通过新operation_id绕过未知创建／启动。

本稿定义跨平台不变量；Windows Guard格式继续只证明Windows结果。Linux不能编造Job／SID字段以通过原解码，也不能让原RuntimeTaskLaunch类型断言继续硬绑定Windows后偷偷返回模拟对象。


#### 3.8.1 原工具操作的持久身份

OC201-TOOL-OP-1是第3.8节执行证据的工具子记录格式，不新增业务根、业务Operation类型或任意OperationStep。现行operation_protocol及数据库步骤约束只允许已登记动作；task_records的观察文本不能替代派发记录。第4.15.3所称“映射到原operation／步骤”具体指下表关联，不是在已成功的START后追加步骤或改写其结果。

| 组成 | 完整身份及不变量 |
| --- | --- |
| 原键 | environment_id、data_generation、task_id、instance_id、execution_session_id、native_session_id、native_message_id、call_id；来自原受信执行上下文，native_message_id是本次工具所属消息，不替代ModelWindow的trigger_message_id。原键唯一映射一个tool_operation_id；不以工具名或输入摘要替代调用身份 |
| 业务关联 | parent_operation_id、parent_step_no、trigger_message_id、control_generation；沿原ModelWindow及已登记发送步骤核对：START/SEND_INITIAL、RESUME/CONTINUE_OR_OBSERVE、REPAIR/SEND_REPAIR、HANDOFF_ROLE/SEND_HANDOFF。角色交接／替换会话沿原目标会话证据关联，不强求parent的源session等于工具实际session |
| 控制与输入 | 原run_id、原controller／owner_epoch、固定包摘要、tool_name、action、input_sha256、受保护input_ref、对象前提、授权与配置摘要；原值不可变。恢复者另附当前控制身份，不能用新run_id改写旧键后再次派发。tool_operation_id为服务端生成的规范UUID，与6.7.1 operation_ref相同 |
| 派发与取消 | 独立保存dispatch_state=NOT_DISPATCHED／MAY_HAVE_DISPATCHED／ACKNOWLEDGED及cancel_requested事实。持久意图完成即进入MAY_HAVE_DISPATCHED；ACKNOWLEDGED仅表示原动作回执已核验，实际效果仍单独判断。不能因回执缺失退回NOT_DISPATCHED。取消不是效果结论 |
| 效果、输出与资源 | effect_state=NOT_STARTED／SETTLED／UNKNOWN；NOT_STARTED须有完整记录证明未进入动作提交点，SETTLED须原效果及相关写入者已核清，不能只凭工具返回。另保存outcome=null／SUCCEEDED／FAILED／CANCELLED／UNKNOWN及effect_receipt_ref、result_ref、result完整性和原资源范围；SETTLED的依据区分ORIGINAL_RECEIPT与RECOVERED_STATE，后者必须符合4.23.1，不能补造原回执；outcome仅按可靠执行事实填写，未执行取消与执行后取消分别保留原证据；输出损坏不改写已核实效果，资源停止不抹去文件修改 |
| 命令与公开观察 | 仅walle_command关联一个原CommandExecution.id，purpose=EXECUTION；文件工具不制造占位命令。ExecutionRecord仅保存安全观察及原业务来源，不作为唯一回执；原命令／观察ID的补记按7.11.4 |

固定输入、派发意图、效果与结果在control_root的原任务执行证据域保存，不随业务恢复点倒退；该域是第3.8节原控制记录的扩展，不增加常驻服务或第二套业务数据库。数据库保留原任务、会话、命令、等待和业务操作。原业务操作SUCCEEDED仅代表其已定义动作完成，不能据此关闭该操作所触发的工具等待；工具结果也不反向改写已成功的START／HANDOFF_ROLE。

原控制记录须先固定该任务的工具登记清单及已核清写入序号，才能判定“没有工具”或“全部已停止”。只有完整清单、全部已登记及可能迟到的资源、文件效果和未决记录均经核对，才允许后续写入／捕获／交接。清单缺失不能以空目录、数据库零命令行或原生空日志代替。

#### 3.8.2 原执行归属与当前控制接管

本稿区分三个进程角色：业务后端持有业务ProcessLock、模型网关和当前业务控制资格；宿主执行控制适配保留原运行资源／进程引用及受限平台动作；OpenCode是受控Agent根进程。三者都曾被简称“控制器”，实施中不得因此混用身份。首期模型网关留在业务后端；执行控制适配按7.11.9每原OpenCode实例一份，独立存活，沿既有第4.13节职责部署，不另建持久模型代理或Agent调度服务。

OC201-CONTROL-ATTACH-1为原执行控制记录的关联格式。原启动及工具证据中的controller_id／owner_epoch、run_id、输入和nonce保持原值；当前接管关系另外记录，不能把旧证据改成新后端发起。

| 身份／事实 | 生命周期及用途 |
| --- | --- |
| 原执行绑定 | 原环境／数据代次、任务／实例、启动操作／步骤／nonce、启动包、原根进程及工作区；接管不创建新实例、不变化原工具键 |
| 原后端／当前后端 | 分别固定实际进程身份、run_id、controller_id／owner_epoch及受信程序摘要；新后端须实际持有同环境单实例资格。新owner_epoch不是旧epoch续期，也不自动增加业务control_generation |
| control_runtime_id | 宿主执行控制适配本次进程生命周期的规范UUID，结合host／boot、程序／策略及连续持有的原句柄核验；不是从磁盘读回即可续用的“服务ID” |
| attachment_id、attachment_revision | 每次新后端绑定由控制侧分配规范UUID，revision为原实例下递增正安全整数；固定前一绑定／撤销证据和新接收者。相同请求查同一绑定，不能产生两个当前接收者 |
| 活能力与持久证据 | 原后端／OpenCode的pidfd、原生控制及内部模型凭据、已核验通道属于活控制对象；持久记录只保存身份、摘要、引用及撤销／接管事实，不保存FD数值当凭据，不落盘秘密供任意重建 |
| 业务窗口 | 原ModelWindow及control_generation仍沿原业务规则；新attachment只恢复受限观察／控制连接，明确RESUME才可在新绑定下建立新消息窗口 |

首期继续接管仅覆盖：宿主boot不变、原执行控制进程连续存活并保留原能力、原OpenCode仍为同一活进程、原业务数据代次及精确执行包／配置未变。执行控制重启、宿主重启、程序发布切换、数据恢复或原能力丢失均不进入该继续接管路径；仍可按原持久证据尝试观察／停止／保全，不能因此宣称全部停止或自动恢复执行。

### 3.9 OBJ-ENV-MODEL-PERMIT 环境模型许可

环境许可回答“当前环境／数据代次允许哪些模型用途”，不代替原任务授权、用户本次操作或费用限制。仅有许可不会启动Guide、Coding、Testing或计数。继续使用原LLMUse、CodeTaskReservation及CountingJournal；本版不新增环境钱包、不把用户约100元的云主机预算当作模型额度。

启动描述的model_permission_ref非null时，精确定义为{policy_id, sha256}，引用受信安装目录内不可变model-policy.v1.json；不是活动许可ID、URL或密钥。策略不包含当前configuration_sha256，避免描述引用策略而策略又引用描述形成摘要循环。P1仍为null。

| 策略字段 | 格式与规则 |
| --- | --- |
| format_version、policy_id、environment_id | 1、规范UUID v4、本环境UUID；额外字段拒绝 |
| allowed_uses | 非空、无重复的固定用途条目，每项purpose及model_profile_ref、provider_binding_ref、credential_version_ref、resource_set_ref；引用均含固定版本／摘要，不能只写供应方名或动态latest |
| purpose | GUIDE_CHAT／TOKEN_COUNT／CODING_CHAT／CODING_COMPACTION／TEST_PLAN_CHAT；不提供ANY或任意URL用途 |
| max_validity_seconds | 正安全整数；约束本环境单份许可最长有效时长，由受信部署策略明确给值，不默认为永不失效 |
| transport_retries | 固定0；连接、读取、SDK自动重试均须关闭，未知不自动重发 |

许可为不可变permit.v1对象，字段如下；UUID、摘要、UtcTime沿本稿规范，枚举及对象严格解码。

| 字段 | 规则 |
| --- | --- |
| format_version、permit_id | 1、服务器生成UUID v4 |
| environment_id、data_generation、configuration_sha256、policy_sha256 | 全部匹配当前部署及策略；换代／换配置不能沿用 |
| issued_by、issued_at、expires_at | 可信入口主体快照{principal_id, access_policy_sha256}、服务器时间、用户明确确认的UTC到期时间；到期晚于签发且不超过策略上限 |
| allowed_uses | 当前策略条目的非空子集，按完整引用比较；不含调用凭据值 |
| issue_operation_id、recovery_review_ref | 原许可命令UUID；新环境／普通续期时后者null，恢复专用时必须绑定完整审阅ID及摘要 |

许可生效事实在control记录的model_access对象，格式为{revision, active_permit_ref, last_operation_id, last_effect_ref}：revision从0开始单调递增，permit引用含ID和摘要，其他引用无值时显式null。只有当前指针指向、未过期、环境／代次／配置／策略匹配且outbound_hold=false的许可才可用；目录里存在许可文件不等于授权。许可状态NONE／ACTIVE／EXPIRED／STALE／REVOKED／PENDING_RECOVERY是投影，不写回不可变正文。判定顺序为无法核对→UNVERIFIABLE，当前hold→PENDING_RECOVERY，有指针但范围／配置不符→STALE，到期→EXPIRED，其余有效指针→ACTIVE；无指针时原最后许可效果为撤销则REVOKED，否则NONE。过期／过时等可另列reason_codes，不覆盖更高优先的恢复限制。

同一环境最多一份活动许可；替换只允许在没有在途外发／待发送预留的安静边界，不能静默给旧轮次扩大模型范围。紧急撤销无需等待该边界：先关闭后续外发，已有发送仍保留原费用及结果核对，不宣称已退款／已停止全部任务。到期与撤销不自动取消用户任务或删除输入；任务下一外发受阻，原取消与查询继续可用。

### 3.10 OBJ-ENV-OUTBOUND-REVIEW 恢复审阅

恢复审阅为只读事实快照，不是用户自报“已安全”的表单。review.v1包含format_version=1、review_id、environment_id、source_data_generations、target_data_generation、restore_operation_ref、deployment_id、configuration_sha256、policy_sha256、expected_control_revision、expected_model_access_revision、evidence_index_ref／sha256、evidence_high_water、created_at、expires_at、checks及blockers。审阅有效期5分钟；持久化后到期只禁止新确认，不删除原确认结果。全部来源、控制版本和证据高水位均由服务端取得，不能通过HTTP指定任意证据路径。

checks固定为OLD_EXECUTION_CLOSED、CALL_RANGE_COMPLETE、USAGE_RECONCILED、EXTERNAL_WRITES_RECONCILED四项，各值PASS／BLOCKED／UNKNOWN并附可信证据引用；缺记录不是PASS。blockers由程序生成固定code及安全说明，不接受前端回填。费用缺失、调用范围缺失、旧执行未撤销及原外部写入不明分别保留；范围已知但金额未知仍不能通过USAGE_RECONCILED。

审阅、许可与原恢复操作必须同环境／目标代次。只有全部PASS且证据未变化的审阅才能用于恢复放行；供应方账单查询或凭据轮换若需要外部操作，另走明确授权动作，GET审阅不暗中访问供应方或做付费验证。缺失历史事实时按第4.22节保全可核验资料。已经OPEN且未换代的环境能否继续人工业务，沿其既有范围、占用及闸门判断；不能将此例外用于CLOSED的新恢复代次。两者均不提供跳过核对的按钮。

补证阻塞复用blockers，不新增“供应方已成功”作为第五项放行检查。固定code新增PROVIDER_RESPONSE_ID_MISSING（缺查询所需原响应ID）、PROVIDER_IDENTITY_UNMATCHED（无法关联原调用）、PROVIDER_EXPORT_INCOMPLETE（导出未完成或截断）、PROVIDER_RANGE_UNPROVEN（未证明全部原调用范围）、PROVIDER_USAGE_UNFINALIZED（用量维度／最终性不足）、PROVIDER_EVIDENCE_CONFLICT（可信来源冲突）。每项使用安全说明对应具体原证据；未命中导出记录使用PROVIDER_RANGE_UNPROVEN，不表达未调用。查询已有结果而身份／范围未核清时仍保留相应UNKNOWN／BLOCKED。

### 3.11 OBJ-ENV-CHECK 检查目标与Linux执行证据

沿用CodeCandidate／CodeSnapshot、Verification／Item／CaseResult、TestingTask／TestReport、EnvironmentRecord与原Operation，不创建“Linux验收任务”。Coding的HANDOFF自检与Testing的独立验收保持不同owner和资格；项目命令退出0仅是PROJECT_COMMAND事实，不能生成受控用例通过。

Linux检查私有绑定check-binding.v1固定：environment_id、data_generation、owner_kind／owner_id、operation_id／step_no／control_generation、verification_id、item_id、case_id（项目命令时null）、command_execution_id、target_kind、target_ref、target_content_sha256、runner_ref、case_pack_ref（不适用为null）、fixture_ref、environment_refs、resource_claim_id及runtime_cohort_ref。所有ref均带固定版本／摘要；target_ref指原候选包或原Git快照，不接受客户端路径。资源组包含目标前端／后端、项目命令、可信driver、浏览器及其辅助进程，角色不得混用。

| 边界 | Linux必须核对的事实 |
| --- | --- |
| 产品输入 | 从固定目标物化的新副本；真实源树、路径、字节及100644／100755模式一致，产品目录只读且无可写别名 |
| 项目执行 | 候选命令／被测应用为不可信代码，在本次任务隔离范围运行；不与业务、driver、Git写入者共享可写身份 |
| 断言与预期 | 固定Runner／CasePack来自受保护资源，项目无法替换／读取私有预期或写权威结果通道；不import候选模块或测试插件作为检查器 |
| 页面与浏览器 | 浏览器渲染不可信内容；与权威断言通道分离，保留Chromium自身沙箱；实际Linux程序／架构另准入 |
| 原端点 | 每次请求固定endpoint_ref及原启动资源／连接证据；端口、域名、容器IP或HTTP200不能单独证明目标 |
| 收尾 | 所有原资源停止、产品输入完整性及临时数据清理分别有证据；完整结果、eligible与任务业务状态不互相替代 |

普通CodeSnapshot原起点不生成新备份包；独立检查CANDIDATE读封存包、SNAPSHOT读固定commit／tree及保留引用。当前模式、依赖及目标平台进入既有EnvironmentRecord／报告依据，ARM通过不自动适用于x86，开发模式通过不冒充固定生产构建通过。

### 3.12 OBJ-ENV-REPOSITORY 仓库归属与跨代次保留

产品登记的服务器仓库与开发WALL-E的外部Agent工作区分开。首期同一实际git_common_dir只归属一个WALL-E环境，登记时沿第3.5节管理资源归属核验实际根；linked worktree、路径别名或不同repository_id不能绕过。环境内多个任务共用该仓库时，写操作仍串行取得原仓库互斥。登记归属在环境空闲后不自动释放，UNKNOWN交付更不能交接。

仓库身份由host安装锚点、环境归属、登记根与实际git_common_dir身份共同固定；当前dev／inode只用于现场核对，不能单独当跨重启永久身份。允许负责人在明确合作窗口之外使用自己的Git，但不授予内部Agent仓库元数据写权。跨环境需要各自独立仓库副本，不能让开发／生产共享可写对象库。

**修正V2.0编号冲突：** 原refs/walle/baselines/{snapshot_id}只含数据库ID，恢复旧数据后可能撞到恢复点之后留下的引用。V2.01采用GIT201-BASELINE-1，保留引用固定为refs/walle/baselines/{origin_environment_id}/{origin_data_generation}/{snapshot_id}；两项origin在REGISTER_BASE首次受理时取可信当前绑定并持久固定。恢复时历史Snapshot保留原origin／retention_ref；仅新登记使用新代次，不按当前环境重算历史引用，不覆盖同名不同提交。

Git交付沿原Delivery，不增加第二套交付对象。新Linux交付协议GIT201-LOCAL-1沿原二进制引用事务，额外固定环境／原数据代次的外部依据与提交尾注；原完整提交输入、planned_oid及回执一经固定就不改写。旧记录只查原结果，新数据代次不得用相同数值ID认领旧Git写入。具体新Schema约束见第7.14节。


## 4. 应用能力

### 4.1 APP-ENV-INIT 显式新数据初始化

输入为原准备操作ID、已核验的环境描述、固定Schema发布、目标新数据目录及独立维护记录位置。准备操作ID使用UUID v4，在写入前以不可覆盖的受控记录固定目标、身份、配置／发布摘要。相同ID不同输入拒绝；原操作查询不触发初始化。

处理顺序：

1. 完成运行包、根及父目录权限检查，核对新目标与其他环境无重叠。先持有与应用相同的稳定ProcessLock，再检查或建立目标文件；不能先在未获锁时写空文件。
2. 只有本次新准备或原准备记录可证明归属的目标可以初始化。文件已存在不等于可覆盖；原操作ID、绑定或发布不同一律保留目标并拒绝。
3. 复用initialize_v20的WAL启用、BEGIN IMMEDIATE、二次空库核对、完整DDL、来源标记和完整性校验；同事务增加第3.1节绑定。不复制产品业务库、不创建测试正文、不请求模型。
4. 提交并关闭连接后，用新连接核对结构、来源、绑定及完整性；成功结果固定为INITIALIZED。相同原操作已完成时只核对并返回ALREADY_INITIALIZED，不重建。
5. 若提交结果不明，保留文件及原准备记录，返回PENDING_RECONCILIATION；同一操作的核对只能确认已提交或仍受控的未完成目标，不能据异常判断“可以删掉重来”。明确失败返回BLOCKED及安全reason_code。

SQLite事务、文件fsync及外层准备回执不是一个原子事务。回执未完成但库已提交时，以原操作固定输入和库内绑定核对补记；不能生成第二个环境。只有证据证明属于原操作且目标仍未初始化时，才可继续该操作的未完成步骤。无原意图的旧空文件同样不自动认领。

普通应用启动只验证库内已提交的完整初始化事实和受信配置，不调用本能力、不修复Schema或权限；维护工具尚未核实结果时不自动接着启动服务。Linux初始化适配优先复用现有维护规则和结果编码，不复制一套简化建表脚本。

### 4.2 APP-ENV-START 启动、恢复与接单

| 阶段 | 动作与退出条件 |
| --- | --- |
| 输入与平台检查 | 解析私有输入、核对程序／运行包／根目录与受信宿主恢复状态；宿主recovery_hold中尚未获逐环境恢复放行的目标拒绝普通启动。状态缺失／不可核验不得当作无hold；此时不建库、不启动任务、不监听可用业务入口 |
| 只读预检 | 原Database只读连接检查Schema、来源与环境绑定；连接关闭后才等待进程锁，避免拿着预检连接进入下一阶段 |
| 独占与二次核对 | GuideWorker继续成为服务级ProcessLock唯一所有者；锁内重查路径、结构、身份和持久限制，预检结果不是锁内事实 |
| 原状态恢复 | 保留Idempotency.recover_previous_process、recover_runs、recover_workspace_starts及recover_drafts中的适用数据库恢复；不派发新模型、重跑未知Git或启动新执行器 |
| 能力装配 | 根据实际准入绑定可用实现；普通模式不调用production_options，不构造模型／计数传输或启动Testing模型派发／原生执行注册循环；实际导入与生命周期拆分见7.3.1 |
| 最终开放 | 原恢复及要求能力通过后仍核对第3.6节持久准入与受信宿主恢复状态；目标已获宿主放行且本环境OPEN才接新业务，DRAINING／CLOSED仅发布获准读取／控制。GuideWorker不能先accepting再等待其他模块恢复或自动解除维护 |
| 失败清理 | 停接单，退休已经分配的租约，等待已开始的本地工作退出，关闭本批持有资源，最后释放进程锁与目录保护；不删除原数据或未决意图 |

只读预检不得用immutable选项跳过WAL；SQLite读取活动WAL所需的辅助文件行为仍受数据根权限约束，不能宣称无任何文件层活动。它不运行业务恢复或修改业务内容。

恢复适配要分开“纯数据库归并”和“需要原执行控制证明的恢复”。存在已启动子进程、未知Git写入、可能继续外发的意图或控制侧未核实资源时，普通环境不接管这些活动；启动BLOCKED，保留独立诊断／原结果核对方式。不能凭任务状态不是RUNNING就放行，也不能删除恢复函数来避开Windows导入。

P1支持新建普通环境及该环境自身无外部调用的重启。复制旧完整环境或改变用途不由本入口隐式处理；恢复快照按第4.12节，重新接入按第4.6节执行。完整环境仍需其实际执行控制及许可准入。

### 4.3 APP-ENV-DOCUMENT 普通业务闭环

复用现有应用命令、返回及事务，不增加Linux专用需求／文档接口：

| 用户动作 | 现有入口／实现 | 结果边界 |
| --- | --- | --- |
| 创建需求 | POST /api/v1/requirements；requirements.commands.create_requirement | 创建零文档需求，不派发GuideRun |
| 创建空白／框架文档 | POST /api/v1/requirements/{id}/documents；documents.commands.create_document | 原固定资源生成CURRENT及Revision，不调用模型 |
| 打开文档／草稿 | GET current-document、manual-draft及原需求／Revision读取 | 返回实际持久内容及版本 |
| 开始人工编辑 | POST manual-draft；start_manual_draft | 固定文档与版本，建立原草稿及占用 |
| 保存草稿 | PUT manual-draft；save_manual_draft | 只保存草稿版本，不冒充CURRENT已经更新 |
| 完成／取消编辑 | POST manual-draft/complete或DELETE manual-draft | 沿用完成时发布正文、Revision、审计或取消时保留原正文的规则 |

表中的manual-draft路径均位于/api/v1/requirements/{id}/manual-draft；document_id等原输入仍按现有契约提供。必要读取包含原需求列表／详情及文档目录、CURRENT／草稿、Revision列表／详情，以及GET /api/v1/requirements/{id}/comment-index；现有RequirementDetailRead把CURRENT与评论索引作为同一显示组合，不能禁用后者后伪造空索引。原消息／评论列表及详情可按DOCUMENT_READ读取已保存内容，不因此开放它们的写入或AI动作。固定资源由原ResourceCatalog及前端锁定资源提供；需要新增资源HTTP读取时先登记实际对象和无外发边界，不创建通用资源浏览接口，也不默认放行其他GET。

版本冲突、占用、请求幂等、内容校验、原回执与提交未知规则保持。验收必须分别读回草稿和完成后的CURRENT，验证真实Revision，不能只看“保存成功”提示或页面内存。重启保留原人工草稿及原业务恢复规则，不改成另一套自动采用流程。

### 4.4 APP-ENV-GATE 能力拒绝与原结果核对

能力检查同时覆盖HTTP、应用命令、后台派发及实际外发边界。配置关闭时不载入真实密钥、不创建新付费意图、不分配外部进程、不调用计数；禁用按钮和未安装OpenCode均不是后端保护。

| 实际路径 | 必须覆盖的位置 |
| --- | --- |
| 文档AI／计数 | guide.api的创建、继续、重试、评论修订；GuideWorker.dispatch；execute_guide_run及实际Chat／Tokenization传输 |
| Testing计划AI | 计划生成命令、planning_worker.claim_draft／serve_testing_plans／_send；不能只停一个HTTP入口 |
| Coding／Git／检查 | 仓库登记与观察、开始／继续／修复／交付、检查运行及对应后台推进；有外部动作的GET同样受控 |
| 纯人工业务 | 第4.3节按原业务权限和版本规则执行，无需模型配置 |
| 原动作查询／取消 | 先核对原环境、代次、身份及查看／取消权限；纯结果读取保留，实际需要原执行控制的核对不能伪造成普通读取 |

固定资源已通过供应方准入只证明资源可用，不构成新环境的调用许可。未来有效外发条件为：环境能力READY、原供应方准入、当前环境／数据代次的有效许可、原任务授权及预算同时成立。P1没有可启用真实调用的开关或Web接口。

重复提交先核对作用域和原幂等记录：已提交的原结果可按原契约返回；尚未执行的新意图必须经过当前能力检查。响应丢失后再收到“能力关闭”只说明这次交换未派发，不能据此抹掉上次未知结果、清除原键或换键重发。

#### 4.4.1 普通业务动作与提交后副作用

按实际应用动作分类，不能仅凭路由所在模块、HTTP方法或按钮文字推断。实施时在原调用路径登记所需能力与副作用，复用第6.2节错误及原命令机制，不另造一套可由请求指定的能力策略。P1开放清单如下；“原结果”始终是经认证、作用域和原权限核验的持久事实。

| 实际入口／分支 | P1与后续完整能力边界 |
| --- | --- |
| 第4.3节人工命令及必要读取 | 分别要求DOCUMENT_WRITE／DOCUMENT_READ，保留占用、版本、事务和幂等；评论索引失败仍是真实读取失败，不吞成空数据 |
| PATCH /requirements/{id}的元数据／discussion_command、PATCH /documents/{id}、独立Revision创建、评论／建议写入 | 现有人工业务不能仅因不付费就全部纳入P1；首批不在开放清单，按ENVIRONMENT_CAPABILITY_DISABLED拒绝。后续接入按实际分支和原契约验证，不改称模型动作、不删除原业务 |
| POST /conversation-messages/{id}/responses | card_commands.submit对CLARIFICATION或接受DOCUMENT_ACTION会创建GuideRun；其他分支是程序处理。P1不开放这个混合提交入口，不能只禁止自由输入AI。完整能力接入时由服务端依据原卡片和答案判定分支，在接受意图的事务内核对相应能力／许可，不信任客户端自报PROGRAM |
| GuideRun创建／继续／重试、评论发起AI | 新意图在持久受理前拒绝；实际dispatch、监测恢复、Chat／计数出口继续独立检查，不能靠接受后不启动来制造永久RUNNING |
| 原持久回执／已保存消息读取 | 不启动新工作；同键命令返回既有结果也不能再次唤起after_commit派发。原结果查不到仍保持未知，不以能力关闭或NOT_FOUND清除原键 |
| 原动作取消／需要控制器的核对、Coding／Testing有副作用读取 | 按原操作、能力和维护收尾规则单独处理，不归入普通GET白名单；当前环境无相应控制能力时明确受阻，不伪造取消成功 |
| complete-initialization旧入口 | 当前实现明确拒绝已移除的初始化动作，保持原STATE_CONFLICT；不把它重用为环境初始化或恢复模型入口 |

当前shared/http_boundary.read_http与handle_http为同一入口，成功应用结果会进入GuideWorker.after_commit；后者识别processing=MODEL、GUIDE_ACCEPTED、CARDS_ACCEPTED及继续／重试。因此只在HTTP响应投影后拦截已经太晚。能力校验必须先于新业务意图受理，并在提交后与实际外发处复核；只读查询及已提交结果回放不得根据旧成功码重新派发。回放资格来自原幂等执行结果及调用上下文，不能由客户端参数或结果文案决定。原已受理工作如需继续，只能走已定义的恢复／收尾路径。

本表限定首批开放范围，不缩减大纲或最终普通业务目标。后续人工元数据等能力接入时同步后端4.3、调用映射与前端动作判定，并完成受影响验收；不为暂未接入的动作增加产品模式、隐藏开关或一套新业务API。

### 4.5 APP-ENV-STOP 关闭与异常退出

正常停止先关闭新业务接单与派发，再处理已受理集合；人工草稿的“存在”不等于正在执行的工作，不要求用户先完成所有文档。已提交事实保持；仍在事务中的工作按原ExecutionLease与事务边界完成或回滚，提交不明保留原结果核对。

保留HTTP租约退休、后台关闭、GuideWorker关闭顺序；根保护必须覆盖全部SQLite连接。取消协程等待不证明底层线程已停；不得释放锁后让旧线程继续触及该库。超过等待边界时显示STOPPING／结果待核实，不报“停止成功”；若进程退出，重新启动仍按原恢复核对。现有10秒宽限不直接成为主动发布可丢弃工作的依据。

P1不提供发布按钮。停进程仅针对本次run_id与受管归属；不按python、node等进程名批量停止，也不停止Windows外部Agent、其他环境或现有用户服务。完整外部任务按第4.10节原工作分类收尾，具体Linux执行与停止证据仍待完整执行批次，不能拿本批无任务停止替代。

### 4.6 APP-MGT-REGISTER 创建、登记与启动

前提为管理员已完成固定程序、管理认证、允许根、仓库、依赖资源、入口和有限规格的宿主安装。管理API不能任意安装宿主软件、下载并执行URL、输入shell、指定任意绝对路径或开启模型。可选择项来自第6.5节受信目录。首期控制范围为普通DEVELOPMENT／INTEGRATION，规格必须保持第3.3节P1四项AI／执行能力关闭；候选和生产先只读登记，控制动作须同时具备第4.10—4.12节契约实现及对应实际准入；此前返回ACTION_NOT_AVAILABLE，不因文档补齐自动开放。

| 动作 | 固定顺序与完成条件 |
| --- | --- |
| CREATE | 校验工作包、仓库固定commit及规格→原事务登记ID和资源占用→准备独立工作区／配置／依赖→按第4.1、7.8节显式初始化新数据→离线校验→PREPARED。成功时应用仍未启动 |
| ATTACH | 从管理员预登记的候选ID选择已有资源→只读核对环境身份、根、配置、数据归属及实际占用→登记。不得借登记建库、升级、覆盖配置或把任意同名目录认作本环境 |
| START | 核对PREPARED及实际资源、当前归属和容量→保存新启动意图及受管执行身份→启动第4.2节应用→核对实际run_id、配置摘要和就绪。就绪前仅显示启动／恢复中 |
| STOP | 对固定原运行关闭接单→按第4.5节退出→核对整个受管应用进程集合及数据锁归属→释放已核实停止的运行额度。不会停止外部编辑器／Agent，不等于禁止工作区继续编辑 |

CREATE引用已存在的本地可信仓库和明确commit，不隐式fetch／pull／push／commit；新任务分支默认codex/前缀，不重置已有分支。采用Git worktree创建独立检出；共享Git目录操作由协调入口串行，任务只改自己的工作区。Git在受限开发身份下运行，受信公共配置与固定命令禁用工作区诱导的hooks、非准入filter／credential helper和自动递归；确需子模块／LFS／网络依赖的仓库须另外准入，不能在高权限管理进程执行仓库脚本。工作区独立不等于公共.git权限隔离。

CREATE中初始化子操作ID预先固定到管理步骤，调用第7.8节原意图协议；管理响应丢失只核对原初始化，不能再生成库／代次。未完成创建标INCOMPLETE，保留已形成资源。继续只执行已核实未做的步骤；路径存在但归属不明时阻断。放弃创建后清理须另走第4.9节，不自动删除整个父目录。

START失败须区分已知未启动、启动了但未就绪、启动结果未知；后两者保留运行额度和原身份，直到停止或核对证明可释放。已运行且配置一致的重复原START只返回原结果；另一个START不创建第二实例。START仍活动／未知时不另受理冲突STOP，而由原START的CANCEL控制请求停止其已登记进程并核对；查询／取消始终可达。STOP的目标可为实际run_id，或已明确结束但仍留有受管进程、尚未握手成功的原START操作；后一种只处理该启动步骤已登记的进程组，不能用任意PID代替。STOP发现目标已停止可返回核实结果；若当前已是新run则原STOP只核对旧run，不停止新run。任何命令响应都不能替代实际归属和存活核查。

#### 4.6.1 入口准备与客户端可达性

新环境的入口按第6.3节由environment_id生成，不能借用另一环境的域名／凭据。创建在最终PREPARED前必须完成服务端路由、独立认证策略、公开配置和私有上游的核对；entry_state分别为SETUP_REQUIRED／SERVER_READY／UNKNOWN。缺少该环境认证配置时，以ENTRY_SETUP_REQUIRED结束本次准备并标INCOMPLETE，保留已有工作区／新库；宿主受信安装入口补齐后，仅按原CREATE继续未完成的入口步骤。普通创建API不接收密码、不借用全局管理凭据、不隐式打开匿名站点。

入口变更由受信配置辅助工具从固定模板生成，范围仅限新环境登记站点；对共享Caddy配置另取宿主级互斥，先验证再采用。辅助工具无任意文本／上游参数，凭据通过专用安装入口在受保护配置中准备，不进业务工作区、管理API响应或使用说明。采用结果不明时核对实际配置版本／路由及原操作，不覆盖整份当前配置回滚，更不能删除其他环境站点。观察核对失败记UNKNOWN；未知期间不允许以同名站点重建来掩盖结果。

多个环境复用同一受信入口监听端口并按精确Host分流，该监听端口归入口组件，不由每个环境重复独占；环境只独占站点名和自己的上游资源。入口配置变更的互斥与环境生命周期占用分别处理。后端套接字／开发端口若已被不属于自己的对象占用，明确失败，不结束对方进程。

SERVER_READY只证明服务端配置已核对，不证明操作者电脑可达。首次使用需要Windows具备相应本地名称解析、Caddy根证书信任和SSH入口转发；新增环境可能需要增加该精确主机名。管理页提供已登记地址和准备说明，不能自动修改Windows的hosts／证书，也不能用跳过TLS验证作为恢复。客户端配置由实际访问验证；该前置与Linux创建成功分别报告。云端换成受控域名／入口后沿同一身份协议，不能携带本地.test配置上线。

### 4.7 APP-MGT-OWNERSHIP 交接、集成与交付依据

同任务交接保留未提交／未跟踪文件、原分支、数据库及data_generation，不强制先提交。新任务不能通过改名称、owner或task_id借用原环境来绕过初始化隔离。集成由唯一负责人选择明确commit组合并处理冲突，管理入口记录选择和检查依据，不自动合并、提交、推送或发布。

交接准备页返回当前环境／任务／负责人／assignment_generation、管理操作与未知项、工作区变更摘要，以及该任务获发的控制凭据／访问许可清单；只列许可标识和状态，不列秘密。交接计划与清理计划一样有效5分钟，绑定旧分配、新负责人和许可清单。必须由有交接权的用户确认旧Agent已停止写入。系统无法仅凭会话结束或应用停止证明同一SSH用户的外部进程不再改文件；该确认与实际可验证的停机证据分别记录。

交接依次执行：取得环境互斥→事务持久化FENCED及原交接ID、封闭旧分配的新管理派发→核对原操作及未知项→收回任务专属访问许可→重新核对工作区和原版本→单事务更新负责人、assignment_generation、record_version及新管理授权并恢复为OPEN。所有新派发均校验当前分配为OPEN；重启后不能丢失FENCED，继续原交接仅由有权MANAGER按原操作进行。未能收回任一已登记专属许可时停在交接待核实，不发新许可；失败也不自动恢复旧写权。查看原结果不产生继续执行权。共享的人类操作员SSH凭据不视为已撤销的任务凭据，界面明确保留这一协作边界。

首期不自动创建外部Agent或OS账号，不替Agent登录。专属SSH／业务Automation凭据如由宿主安装流程发放，交接前须有相应撤销检查；尚无检查能力的许可必须由管理员撤销并完成受信核验后再继续，单纯勾选“已停止”不能替代。若收回许可需要变更应用私有配置，先按普通STOP收尾，生成新配置版本，再由独立START生效；不热改已启动配置，也不以交接改变数据代次。外部Agent共享同一开发UID时只能承诺协作隔离，不能承诺抵御恶意互写。

REGISTER_DELIVERY接收当前分配的明确commit、固定资源引用、检查来源及未覆盖范围；先核对当前受管仓库和原环境／分配版本，读取commit及资源实际身份，再以原操作事务保存交付快照并递增record_version。该动作不执行检查、模型或Git写入，不承认未登记路径提供的“系统已通过”。交付快照包括commit、resource_refs、check_refs、manual_notes、not_covered、submitted_by及verified_at；check_refs只能引用受信证据目录已登记且匹配该commit的证据，人工声明独立保存在manual_notes。集成批次额外记录source_environment_ids／source_commits与当前组合commit；后续改稿提交需新意图登记，旧交付不被覆写。

交付记录只接受明确commit及固定资源引用、实际检查证据／未覆盖范围。工作区“无改动”不证明commit已在其他地方保留；清理前核对提交可在独立交付位置读取。人工声明的检查结论标明来源，不能显示为系统已验证。分支保留不等于已推送；交接／交付均不自动继承模型、生产或发布权限。

### 4.8 APP-MGT-CAPACITY 容量、观察与中断恢复

规格目录固定每种用途的内存／CPU／进程数上限、预计新增磁盘、同时运行／构建槽及准入能力。数值须由实际宿主配置和原型测量给出；当前VM是2CPU／4GB，不把Mac的16GB当作VM可用量，也不把两个工作区等同两个完整执行环境。完整执行初期串行，普通实例按需启动。

管理登记事务先按配置总额度、未释放占用和实际宿主余量核对，再原子预留；并发请求不能各自读到同一份空闲后都通过。磁盘只预留尚未落盘的预计增长，已落盘空间由真实可用量反映，避免重复扣减；实际写入仍可能失败，应保留原步骤和部分产物。外部不受管进程消耗也纳入实时余量，但管理登记不能替它们强制限额。生产预留不得借给开发；默认开发与生产位于不同宿主。

暂时不足返回WAITING_CAPACITY及缺少项、观察时间；首期只做可见等待和用户主动“继续原操作”，不建自动集群调度。每次继续重新检查准入，已排队不是长期授权。对同一受限资源按受理顺序处理已明确申请继续的等待项；陈旧权限／配置／预览须先处理，不能凭旧确认自动执行。过期或不可读的容量观察拒绝新建／启动／构建，不能自动杀掉运行实例腾位置。

管理程序取得宿主固定控制锁后才写登记；重启先查旧DISPATCHING／RUNNING／UNKNOWN及残留辅助进程，禁止从最后一条日志直接重放。执行前为辅助进程记录确定的服务／运行时对象身份；进程可能在管理程序退出后继续运行，必须核对其真实退出和资源结果后才能接管。只读查询可在恢复中开放，新变更等待相关冲突解开。管理库缺失／损坏进入控制阻断，不扫描端口认领、不自动建空库继续管理。

管理不可达时业务可继续原运行；已进入维护的业务不能因此自行解锁。旧观察随时间失效，网页失联不更新为STOPPED。管理恢复只能读取核对业务原事实，不能改业务任务为成功、清未知或重发模型。

### 4.9 APP-MGT-CLEANUP 分项清理与归档

停止、归档登记、删除工作区、删除数据、删除日志／临时文件是不同意图，默认均不互相勾选。归档要求无运行／在途管理操作／未知资源，保留所有持久文件和回执。归档后仍可按原身份查询及有权分项清理，重新运行需显式重新登记核对，不能直接沿旧可用标记启动。

清理先生成服务端plan_id，返回计划摘要、5分钟有效期、环境／归属版本、精确resource_id集合、用途及影响、未提交／未跟踪／被忽略文件摘要、数据代次和独立交付证据。预览只读取资源并保存计划，不删除；计划不是执行授权。确认提交固定plan_id、plan_sha256和用户明确选择项，不能通过任意路径扩大范围。预览失败的条目不得默认可删；过期后只可重新预览。

执行前及每个删除步骤前重新核对：环境与assignment_generation、原资源身份和允许根、工作区内容摘要、交付可读取性、全部受管写入已停及未知已解除；还需用户确认外部Agent／编辑器停写。根或内容改变即停止剩余删除，要求新预览。文件保护沿第7.2节，不跟随符号链接越界；同UID不守约的外部写入无法由预览消除，不能宣称具有完整OS隔离。不得按父目录递归扩删或依据名称处理后来替换的对象。

工作区通过Git正常移除；未提交、未跟踪及被忽略内容均须纳入预览，明确授权丢弃后才能使用相应强制移除。禁止越过他方worktree锁、删除主工作区或顺便清公共仓库。交付commit／资源必须在工作区之外仍可读取；共享仓库、正式发布资源、备份、独立检查证据与管理回执不属于工作区清理。清理数据只能针对当前登记的该代数据和附属文件，不能包含另一个环境、共享锁根或正常用户库。

每项记录NOT_STARTED／REMOVING／REMOVED／ABSENT_CONFIRMED／FAILED／UNKNOWN；已不存在只证明当前不存在，不伪造“本操作已删除”的历史因果。部分成功后保留结果，原操作核对后仅处理仍属于原计划且前提未变的项；已派发且不明的删除不得盲目重做。确认有效期只限制首次受理；已受理操作按原范围核对，任何扩大／替换或前提变化仍须新预览。前提变化且没有仍在执行／未知的步骤时，以FAILED结束当前清理，释放动作互斥但保留尚存资源的环境归属，随后可对剩余资源生成新计划；不能用新计划绕过旧UNKNOWN。删除工作区／数据后更新为INCOMPLETE，原环境ID和回执保留，不自动重建或循环复用给新任务。

### 4.10 APP-ENV-MAINTAIN 进入维护与原工作收尾

#### 4.10.1 一致准入顺序

1. 管理先固定原操作／计划和环境互斥，调用独立受限控制通道，请求当前应用以expected_control_revision进入维护。记录ENTERING；应用未应答前不宣称已经维护，也不停止进程。
2. 应用持有共享准入闸门，暂时阻止新受理及后台新派发进入；登记已取得准入票据的请求／事务、已受理长操作及其实际派发阶段，封存drain_manifest。先持久写control.admission=DRAINING并同步成功，再发布可核对回执；期间已取得票据的短事务可完成原提交，未获票据的写请求明确拒绝。
3. 所有HTTP、应用命令、工作器claim、实际模型／计数／Git／执行出口共用该闸门及原操作归属判断。维护入口与准入获取串行，不能仅在HTTP中先检查布尔值再放任后台异步派发。控制记录持久失败保持内存禁止新接单并报UNKNOWN；崩溃恢复从控制记录与封存原意图核对，不按管理端的期望猜结果。
4. 按下表推进原工作。已受理但原业务轮次尚未开始执行的意图保持原记录并禁止首次派发；如果没有原契约支持的安全挂起，列为阻塞，让用户选择等待／取消维护／明确取消原任务，不替用户把其改成失败或删除。已实际开始的原轮次，其必要内部步骤按冻结收尾集合及第4.14节准入；不能只凭早先取得票据或task_id相同，就把新的人工轮次／答复／检查列为收尾。
5. 原执行／线程／写事务全部结束，未决结果符合允许保留条件后，持久CLOSED并发布QUIESCENT；关闭只读HTTP连接、退休剩余租约、关闭工作器和实际应用。核对受管进程退出后，专用维护工具取得同一稳定锁，再标STOPPED。任何旧写入者未退出都不释放给新实例。

控制闸门只限定准入和派发，既有Database、Idempotency、ExecutionLease仍负责事务及提交；不要在进入DRAINING时立即retire全部租约，否则原工作无法正常落盘。现有GuideWorker.close的宽限和恢复属于进程关闭路径，主动维护先完成上述收尾再调用它。维护控制期间的systemd模板不得在超时后自动SIGKILL活动任务；SendSIGKILL=no，超时保持原操作待核实。OOM／机器掉电等被动故障按故障记录，不伪装成安全维护完成。

#### 4.10.2 允许动作必须对应真实调用

| 类别／现有调用位置 | DRAINING处理 | CLOSED／VERIFYING处理 |
| --- | --- | --- |
| 需求／文档／草稿／Revision人工写入 | 新受理全部拒绝；进入前已受理短事务完成原提交或原回滚 | 拒绝普通写入，保留本机输入 |
| 文档、任务、仓库已保存元数据、原command-receipts读取 | 仅登记为无持久／外部副作用的handler允许；沿权限及原scope | 应用还在线且持有正确锁时允许必要读取；停机后只提供独立管理元数据 |
| guide.api创建、continue、retry、评论修订及卡片新答复 | 拒绝。源码中的continue_guide_run创建新GuideRun，不是原运行的收尾，不能因名称“继续”放行 | 拒绝 |
| GuideWorker／orchestrator已有运行的响应接收和持久化 | 只允许drain集合中已开始运行、原冻结输入及授权／预算内的必要步骤；不得新建人工轮次或扩权限 | 仅无新增外部请求的恢复落盘，计入核验 |
| testing.planning_worker.claim_draft／_send | 未发送NOT_SENT不开始；已SENDING的原返回沿finish_draft落盘，未知按recover_drafts保留，不能再排队 | 不启派发循环；仅已登记恢复 |
| 仓库登记／刷新、Git读取命令、快照／内容包、检查和交付 | 若会创建操作、运行进程或写私有记录，不能因GET放行；只读已保存投影与实际执行分开 | 禁止新执行；需要外部核对的动作仍按专用原操作入口 |
| GuideRun cancel、Coding terminate、Testing原停止及其收尾 | 用户明确对drain集合中原任务取消才准入，沿原键／版本／权限；只允许停止／撤权／核对，不创建新工作 | 若仍需要这些动作说明未安静，退回阻塞，不在备份时偷偷并行推进 |
| 原结果核对及迟到计费 | 原执行身份、固定目标与无新工作许可下可收取原结果；核对所需写入重新计入安静检查 | 切换前关闭其写入者；可保留只待观察／费用的记录，前提是执行权已封闭、资源已停且新版本兼容 |
| Coding／Testing等待用户输入、角色继续、复测／修复／交付继续 | 第4.14节明确拒绝新问题答复与全部权限决策，原已发送答复只核对；角色继续／复测等不得新派发 | 不自动续跑 |

源码静态核对已覆盖service.py、guide/worker.py／commands.py、testing/planning_worker.py、code_tasks/task_stop_api.py／command_api.py／repository_reads.py／repository_snapshot_reads.py及维护工具。完整执行适配仍须将所有实际命令和后台入口登记为PURE_READ、NEW_INTENT、DRAIN_ORIGINAL、CANCEL_ORIGINAL或RECOVERY_ONLY；未登记默认拒绝。纯读取仓库投影不能替代真正运行Git的接口。此表是准入规则及首批定位，不宣称已审阅全部内部控制调用或已有Linux执行证据。

#### 4.10.3 安静、阻塞与取消

不要求所有任务变成COMPLETED。已保存的人工草稿、无活动的等待任务可以保留；必须分别证明没有在途写事务／线程、无可继续派发的未决意图、模型通道已封闭、执行／检查子进程已停及Git等外部写入结果已核对。只有迟到费用／观察未结且满足上述条件可列为可保留待核对项；未知模型结果的业务处置、未知交付或未停子进程不能因此被放过。

管理页列安全的阻塞类型、原任务／操作ID、最后证据和允许动作，不取得改业务状态权。用户明确取消原任务应通过原业务权限入口；管理身份不自动充当业务用户，也不代交用户问题答案。无法正常访问原业务时仅提供已准入的受限恢复入口；尚未实现该入口则保持阻塞，不能直接改库。

切换前取消维护，先核对原部署／数据、控制revision、已完成副作用和未决活动，撤销本次切换意图；只有原实例可安全继续时持久开放并返回CANCELLED。已停机可按原取消计划启动原部署核验，不能未核对就写OPEN。切换开始、数据变动或结果未知后，CANCEL只停止尚未派发步骤并保留维护，须先核对和明确恢复；页面关闭、超时、管理重启均不解除。原操作仍UNKNOWN时不允许新恢复操作抢占；已查明的失败可在同一环境互斥内将维护归属转交给明确引用原操作的修复计划。

### 4.11 APP-ENV-RELEASE 固定候选、配置与程序回退

固定候选先在管理维护之外构建、准入和验证；构建不进入正在服务目录。候选验证绑定目标平台的准确应用／前端／运行包摘要和检查证据；ARM64证据不自动覆盖云x86_64。生产使用该已验证包，不重新构建前端注入生产参数。受控运行时公开配置、私有配置和密钥引用分别准备；任何影响实际代码或固定资源的修改都产生新候选。

| 步骤 | 原操作输入与完成依据 |
| --- | --- |
| 计划／确认 | 从已登记候选和目标选择；列源部署、配置差异、能力、数据兼容、必要停机及恢复方式。确认固定计划摘要，不授权任意后续候选 |
| 目标预检 | 安装到独立不可变目录，核对实际目标宿主、文件权限、固定运行绑定、协议和恢复资产准备；目录存在／包hash相同不代替本机信任准入 |
| 维护收尾 | 按第4.10节进入并停止原实例；取得稳定环境锁。普通STOP到此完成并保持NORMAL_STOP，不隐含备份或构建 |
| 停写后准备 | 对实际源完成一致恢复点；有源相关转换则在隔离副本演练并核对实际适用性。与原计划不符时保持维护并REPLAN |
| 切换 | 在CLOSED下记录切换前／后完整元组，再原子更换control.v1.json的部署选择；数据工具有自己的原ID／提交标记，不能把两个提交伪称同一事务 |
| 新实例核验 | 新程序读取CLOSED及新元组、取得环境锁，以RECOVERY_ONLY启动；核对Schema、数据归属、实际包／配置、协议和要求能力，只做必要数据库恢复，不重发外部工作 |
| 重新开放 | 实际核验回执匹配目标及控制revision后，按已确认计划持久记录OPEN与开放回执，再开放普通准入；最后管理补记成功。回执丢失先核对实际OPEN，不再切一次 |

离线工具在CLOSED下提交并核对新部署选择后关闭自身SQLite连接、释放稳定环境锁，再启动严格匹配新元组的应用；新应用必须重新取得同一锁。交接空档旧程序因元组不匹配不能进入，不能同时持锁等待新程序就绪。核验失败保持关闭，并记录实际仍占锁的进程。

在受信入口完成认证／静态资源／公开配置切换后，必须核对所指程序和当前配置一致；部分切换时客户端应阻断，不能自动选择返回值“修正”预期。保留旧固定静态资源供已打开标签完成只读处理，旧协议不兼容时先保全输入再提示重新进入；不得在生产核验中创建测试文档、发模型或跑用户任务来证明健康。

RECONFIGURE沿同一流程选择已准备的私有配置引用，默认保持环境ID、用途、data_generation及数据根。涉及换数据根／数据集使用RESTORE，不能伪装成改配置；改变生产用途不能改标签直接完成。模型许可配置不由本动作自动授予，降低能力导致原任务无法核对时阻断。配置改变即使不改Schema，也必须核对原操作、访问保护、运行时绑定和恢复策略，不热改全局环境变量。

ROLLBACK_CODE是有确认的新修复意图，仅在固定旧程序明确兼容当前数据／资源、当前实际源已核实时切回旧包及匹配配置，保留当前数据及代次。不能因为新实例未对外开放就假设数据未写：启动恢复可能已经落盘。若需要恢复旧数据，改走RESTORE及第4.12节条件，不以“回滚版本”按钮暗中覆盖。

已记录或无法排除新部署曾OPEN时，禁止用发布前快照直接覆盖当前数据；先保护现状，再制定不丢新内容的恢复／修复方案。只改程序且验证兼容当前数据的回退仍可按上段实施。没有适用兼容性／恢复工具的目标明确BLOCKED，不临时调用151→200重建，不删除库新建。

普通START必须检查closed_reason：NORMAL_STOP且无未决可按本次启动授权核验后开放；MAINTENANCE／RECOVERY_REQUIRED只能接续原维护或其明确修复操作，不能借普通START解除。自动重启同样先读持久控制记录。完整／生产START、STOP只有维护契约及对应执行停止证据实际准入后才开放；P1仍只提供其普通范围。

### 4.12 APP-ENV-RECOVERY 恢复点、数据恢复与管理恢复

#### 4.12.1 形成一致恢复点

首期BACKUP采用可接受维护窗口的停止后备份，复用第4.10节，不宣称在线复制所有资产一致。取得稳定环境锁并核对所有写入者停止后，以SQLite Backup API生成新目标；独立重开核对完整性、Schema、环境绑定及引用，所有连接关闭后再计算文件摘要／同步。不能只复制可能依赖WAL的主文件，也不通过手工删除WAL促使“备份干净”。[SQLite Backup API](https://www.sqlite.org/backup.html)、[WAL文件与一致性约束](https://www.sqlite.org/wal.html)。

恢复资产覆盖实际数据库、计数／调用审计、正文及任务引用的库外内容、固定资源关联、实际程序／配置版本和原操作回执依据。每种库外引用须有明确capture／verify／restore规则：固定不可变包可保存可取回引用，可变内容必须封存副本；内部任务工作区、Git未交付内容、检查结果不能笼统归为可丢临时文件。不能备份活进程或把已消失的执行器凭据当作可恢复会话。未完成资产覆盖或存在不兼容未决执行，标BACKUP_ASSET_UNSUPPORTED并阻止需要该恢复点的发布。

凭据不进入公开清单／浏览器／普通备份正文。配置中保存秘密引用；实际秘密及Restic仓库密钥由独立受保护恢复材料管理，准备可用性纳入演练。部署到新宿主后重新绑定路径、文件身份、账号与可信组件；内容hash相同不证明权限正确。备份保存在独立恢复根，禁止工作区／环境清理联动删除；保留／销毁备份另有明确策略及授权，不能将其当测试产物清理。

采用“SQLite一致快照＋项目资产清单＋Restic保存封存包”的分工，复用现有备份／资产核验逻辑及成熟存储工具，不自研加密、去重或远端存储协议。Restic仅读取已经封存的包，固定snapshot ID关联backup_id与manifest摘要，不能用latest作为恢复身份；恢复到全新暂存根后按项目清单核验再采用。官方资料以0.19.1接口核对，实际二进制版本／摘要及后端在部署时锁定；本轮未安装或创建远端仓库。[Restic存储与密钥](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html)、[固定快照恢复](https://restic.readthedocs.io/en/stable/050_restore.html)。

恢复点状态为CREATING／LOCAL_VERIFIED／OFFHOST_VERIFIED／UNVERIFIED。LOCAL_VERIFIED仅表示本机完整封存并做过隔离恢复核验；不防宿主损坏。OFFHOST_VERIFIED还须在异机存储形成固定快照并实际取回本包核验，单次上传成功或默认restic check不等于内容全部可恢复。[Restic检查范围](https://restic.readthedocs.io/en/stable/045_working_with_repos.html)。正式云生产需异机副本、独立密钥恢复材料、固定备份策略及恢复目标；首期候选与频率／保留／成本约束见架构评审第3.2—3.4节，实际区域、费用、Restic／COS兼容及演练时长仍待核验。Mac休眠不能成为云生产唯一备份依赖。

独立BACKUP计划声明完成后的状态为恢复原运行或保持停止；原来停止的环境不因备份被启动。发布内的备份是原RELEASE的子步骤，继续保持维护。可在本机封存并核验后恢复业务，再上传不可变包以缩短停机；若计划要求异机验证才能继续切换，则原发布等待该条件，不能悄悄降低恢复要求。上传失败保留LOCAL_VERIFIED及失败原因，不重做数据库快照混淆cutoff_at。

#### 4.12.2 恢复数据不覆盖原库

RESTORE只选择属于同一environment_id的已核验恢复点；恢复Windows旧历史到新云环境不在范围内。隔离演练使用专用验证身份／禁止外发配置，不把备份中的原生产身份或许可直接当成可运行环境。正式故障恢复到新宿主需第4.12.3节宿主恢复门槛，不能直接复制目录启动。

1. 固定恢复计划、原数据代次／当前部署、所选backup_id、恢复后的程序／配置、资产范围及可接受数据处理方式。常规发布失败回退仅在能证明切换后未开放新业务且适用恢复点时采用；已开放后存在新内容，拒绝直接覆盖，先保全当前源并制定单独修复方案。灾难丢失时不承诺找回备份截止之后的数据，实际损失范围需明确确认。
2. 在CLOSED、原执行已停止和稳定环境锁下，封存当前可读取数据及原结果索引；即使现库损坏也保留原文件和已知事实，不先删源。新目标根由原操作预留，以新UUID data_generation准备副本，依次恢复数据库和全部声明资产。恢复过程及重试都绑定同一新代次，不能每次重试再换代。
3. 由专用工具在新副本的单事务中核对源environment_binding并更新data_generation；environment_id保持，initialized_at保留原首次初始化事实，restore时间记在外部回执。该授权只适用于未开放的新恢复副本，普通API不能修改绑定。业务结构／来源元数据继续按适用Schema核验，不冒充一次空库初始化或重跑DDL。
4. 在外部control记录保持CLOSED并预置outbound_hold=true，准备完整新部署元组；确认新库绑定、资产、配置和回执后，原子切换控制元组。库内提交与外层记录无法同事务完成：中断后只核对原副本、代次和元组，不拿其中一个已成功就开放。
5. 以RECOVERY_ONLY启动新副本，核对旧外发／交付结果及不兼容待执行记录。旧授权、旧预算余额或NOT_SENT队列不自动恢复执行资格；所有实际外发与后台恢复都受outbound_hold。需要真实调用的新代次授权，须先核对已发生用量及未知结果，再明确任务／预算／重试边界。未能满足required_capabilities时继续维护，不能自动降级完整环境来放行。
6. 满足已确认恢复计划及开放条件后记录OPEN，业务页面因新代次重新绑定。旧数据根、备份和原代次回执留作受控只读依据，另行清理；恢复成功不等于原未知调用已经确认或费用撤回。

实施先准入无外发的普通恢复；不提供随意清除outbound_hold的Web接口。完整环境核对、许可与恢复提交已由第3.9—3.10、4.16—4.18、6.8及7.12节定义；实际资源、逐路径接入和可信历史补证仍待交付。历史缺失按第4.22节处理，不能把普通恢复或只读资料核验通过当作完整任务恢复。

原代次结果查询来自恢复前封存的只读回执索引／保留原数据及原控制证据，不向新库查同名ID推断旧结果。索引按原环境、代次、动作与原键定位，只投影状态、结果摘要和证据来源；缺失为UNVERIFIABLE，不能转成NOT_EXECUTED。管理查看这些元数据仍需相应原操作读取许可，不授予业务正文读取。受损或已丢失的原事实无法重建时如实保留未知。

#### 4.12.3 管理登记与宿主故障恢复

管理库恢复使用独立固定离线工具，不提供让正在被替换的管理服务自我恢复的普通HTTP按钮。先暂停管理派发并取得宿主固定控制锁，核对旧辅助进程与所有已登记环境；正常业务可维持原运行，但既有维护不得解除。恢复工具只使用受信安装锚点／已登记根核对，不扫描端口后自动认领资源。

恢复管理SQLite一致快照、必要计划／回执／资源目录后，保持原manager_id、显式生成新的registry_generation；安装锚点与管理库都核对新代次后才恢复控制。应用control.v1.json不被旧管理备份覆盖；旧管理记录与实际部署／维护不一致时，以各自原身份核对并保留差异，不能用旧“成功／空闲”释放当前占用。旧代次管理请求和浏览器原键保留只读，不能向新登记库重放。

宿主整体损坏时，在恢复管理或业务数据前，受信安装入口先建立宿主recovery_hold，启动器拒绝所有普通自启。只有逐环境恢复control事实、重新准入运行包／权限、封闭旧执行凭据并核对原操作后，才能为已证明安全的目标开放；恢复的旧OPEN记录不能跳过此门槛。安装锚点、宿主hold和稳定锁不从任意业务备份反向覆盖。宿主恢复状态由受信安装锚点固定，初次安装也须显式建立；新备份中的启动配置不得自报hold=false。逐环境放行绑定实际恢复核验的部署及数据代次，不按等待时长自动解除。第4.2节启动前与最终开放均核对；故障恢复模式可运行固定离线核验工具，但不开放普通业务。此宿主启动限制不等于已停止仍存活的进程，存活目标仍须按原操作完成维护与停止核实。

同宿主仅恢复管理库不改变业务data_generation；业务数据另行恢复才换其代次。管理库单独恢复不声称已恢复云服务；若最近登记／外发事实已丢失，则相关环境保持UNKNOWN／CLOSED，由实际证据与明确处置方案收口。离线恢复工具的命令格式、固定发布及故障演练属于后续资源交付，不能用当前Windows工具冒充已具备。

### 4.13 APP-EXEC-LINUX 固定执行底座与启动

Docker＋固定runsc／gVisor systrap仍是项目代码隔离候选，OpenCode保持1.19.5；整套执行部署须先通过第4.15节来源门槛及替代候选评估，本节不直接放行“OpenCode与项目脚本同容器”。业务应用无Docker socket／docker组权限；独立受信执行控制适配负责固定动作，不作为通用远程命令服务。环境管理只申请容量和观察执行结论，不能通过“环境管理”身份任意创建任务容器。Docker控制权限本身具有宿主级影响，必须限定受信安装与控制程序。[Docker权限依据](https://docs.docker.com/engine/security/)。

#### 4.13.1 固定运行配置与文件

- 准入清单固定OS／架构、Docker Engine及API兼容范围、runsc二进制摘要／参数、镜像具体平台manifest及config摘要、OpenCode与工具链、内核／cgroup要求。ARM与x86分别检查；不以tag、镜像多平台索引或容器内自报版本代替实际产物核验。
- 必须使用受信登记的runsc systrap配置；不满足就UNAVAILABLE，不回退runc、host network、privileged或关闭浏览器沙箱。普通容器只能承担已定义的可信应用，不冒充完整任务隔离。
- 任务采用非root身份、只读程序根、明确可写工作区／临时目录、有限CPU／内存／进程数／磁盘增长与输出；禁用宿主PID／IPC共享、设备透传、额外能力、提权和任意挂载。实际参数及可用性在P2固化，不靠文档说“受限”即放行。
- 不挂载业务库、control_root、管理库、运行时接口、供应方密钥、其他环境目录或共享仓库可写公共元数据。任务取得自己的工作副本，Git控制写入由原受信交付路径完成；宿主root控制代码和业务源码均不来自任务可写目录。
- 挂载前后核对受保护根及实际文件身份，拒绝符号链接、越界、可替换祖先和不受信挂载点。读取产物时同样按句柄／目录边界核验，不能在任务目录中以宿主权限执行打包脚本；压缩包路径、链接及文件类型必须检查。
- 项目依赖预取与执行分开：固定工具依赖随包交付，项目锁定依赖在受限准备环境取得；安装脚本也属于不可信代码。缺依赖显示明确阻塞，不能临时开放全网、借宿主缓存秘密或在宿主运行仓库脚本。

[runsc接入](https://gvisor.dev/docs/user_guide/quick_start/docker/)和[平台选择](https://gvisor.dev/docs/user_guide/platforms/)支持该候选路线，但不证明本项目固定执行器、文件机制或源进程核验已兼容。容器内dmesg自报不作为可信准入。

#### 4.13.2 原操作启动顺序

1. 业务按原START／RUN_TEST契约固定任务依据、范围、预算、控制代次及操作。原操作受当前环境绑定、维护／恢复限制及任务授权共同约束；无可用执行能力时在副作用前拒绝。
2. 从管理已授予的环境额度中取得本次执行资源；控制适配持久记录原范围与输入摘要，再准备工作区、网络及关闭状态的模型窗口。首期全宿主一个完整重任务，通过第3.5／4.8节同一resource_claims事务取得绑定环境和原业务操作的宿主执行名额，不靠各环境自己的计数。环境已预留的内存份额不再重复扣除。容量不足只等待，不能启动后再抢额度；管理不可用时不发新名额，已获准运行及原停止不依赖管理持续在线。
3. 创建尚未运行的项目沙箱容器，固定完整ID和实际配置回执；回执持久成功后才允许原START。固定OpenCode由7.11.8—7.11.10的独立宿主unit启动，不是本容器内的后台进程；原unit／启动描述及关闭状态的窗口须先绑定原操作。Docker create与Windows CREATE_SUSPENDED不是同一种OS机制，业务共同前提是“身份已落盘、策略已安装、工作负载尚未运行”。
4. 再核对控制任期、原操作、停止标记、维护归属、全部挂载／策略与准入；先持久START_DISPATCHED再一次启动。容器运行不代表OpenCode就绪；原启动器凭据交付、固定exec、实际身份及原生接口的实例／会话／工作区核验分别完成后，才推进原消息与模型窗口。
5. 创建或启动结果未知时，只观察原资源、原回执及实际配置；不得另起容器、重发初始消息、按名字认领外来实例。不存在资源但无法证明旧执行未发生，仍是UNKNOWN；已退出容器不能重新start来重做原工作。
6. 同一应用重启也不自动续跑旧沙箱；先封闭旧窗口，再按原恢复观察核对。仅后端重启的有限接管按4.23.3，接管成功本身不恢复模型或工具派发。任务资源restart policy固定no，不由Compose／systemd另设自动重启任务；应用恢复与任务重新授权分开。[Docker重启语义](https://docs.docker.com/engine/containers/start-containers-automatically/)。

控制适配要覆盖守护进程重启而容器仍活着、控制回执丢失和创建后未启动三类情况。不能假定Docker故障会自动结束任务，也不能自动删除容器来掩盖未知。普通健康检查只读可信元数据，不执行容器内脚本或发模型。

### 4.14 APP-EXEC-STOP 原任务停止、维护与异常恢复

沿task_runtime_stop.py的原步骤：封闭新派发／模型窗口 → 原生abort → 所属运行资源停止 → 核对外部写入 → 保全结果并按范围释放。Linux替换平台证据，不改变“停止请求、实际停止、结果核清、资源释放”是不同事实。

| 场景 | 处理与完成条件 |
| --- | --- |
| 用户明确终止任务 | 原任务版本／代次下受理；先撤销模型入口，再发送原abort。按已确认执行策略的温和／强制停止阶段处理原资源；强制阶段属于此终止授权，不能扩为杀同名进程 |
| 仅进入维护或更新超时 | 不自动形成任务终止授权；等待原工作，或用户明确取消任务／取消维护。不能直接调用Docker默认stop并把超时强杀当正常收尾 |
| 停止中又有启动／原生请求 | 持久stop fence先于新派发核验；已接受未执行的启动永久禁止，重复原停止只核对和完成剩余关闭 |
| 应用／控制适配崩溃 | 旧模型入口失效，剩余任务保持被隔离；恢复先观察，不续跑／不重发。无法确认控制者或收回权限时保持UNKNOWN并占用资源 |
| 宿主重启／OOM | 记录故障原因；boot变化使旧运行身份不能直接沿用。核对持久启动意图、运行时残留、外发与Git结果后才能释放，不能伪称用户取消成功 |
| 仅费用迟到 | 已撤销执行权、全部资源停止且业务结果已处置后，可保留原费用待核对；费用未明不等于进程仍活跃，也不等于允许新模型请求 |

Docker默认stop会在宽限后强制结束，维护通道必须使用不隐含强杀的控制方式并有界返回观察；真正执行强制阶段只来自原任务终止／已明确资源策略。[Docker停止行为](https://docs.docker.com/reference/cli/docker/container/stop/)。

停止证据须由控制侧核对原完整资源集：容器／runsc状态、cgroup剩余成员、所属辅助进程、模型／控制连接和受管写入；取不到任何一项即未知。容器内ps、主PID退出、端口消失或业务TERMINATED均不够。资源被删除不能单独证明停止；须有可信停止回执，或能证明原资源和子资源全部消失的恢复证据。控制程序不通过任务可修改的PID文件决定kill对象。

维护中的Coding问题答复与权限决策本批明确拒绝新受理，包括DENY：当前两者都生成独立CodeOperation并向原生发送控制，拒绝权限也可能使模型继续执行，不能按文案推定无副作用。原已发送答复允许核对回执，原已受理未发送仍按第4.10节阻塞／取消；取消原任务保持可达。追加预算、角色继续、修复、独立复测和交付继续均不属于收尾。

已运行原生轮次在冻结输入／权限／预算内的必要工具和模型步骤可以收尾，但不能新开人工轮次、发起未登记的压缩调用／自动重试或新增独立检查。准入绑定具体原消息／轮次及原步骤链，不只绑定整个任务；例如原轮次工具结果后的下一模型步骤可在原预算内继续，而维护前仅受理、尚未发出的新ANSWER_QUESTION操作不能借相同任务ID首次发送。已有未派发意图不得删除后换键重建来取得收尾资格。每个真实外发仍须原窗口及预算准入；无法证明属于冻结轮次时关闭窗口并显示等待。任务停机后只保留恢复观察，不以“继续原操作”重新发未知消息。

### 4.15 APP-EXEC-MODEL 网络出口与请求来源

执行网络在沙箱之外执行默认拒绝；第4.15.2—4.15.6分离候选中，仅固定控制器可访问模型专用Unix入口，项目工具沙箱没有该入口／凭据，只允许明确准入的工具目标。其他部署只有独立通过来源验证后才能授予模型入口；不接入业务／管理默认网络，不发布任务端口到宿主公网，不开放任意CONNECT／HTTP转发。IPv4／IPv6、宿主桥接地址、其他任务、云元数据和DNS路径都在核验范围。只用域名白名单不足以防重定向／解析变化；模型出口由受信配置固定供应方端点并在传输前核验，不采用任务body／URL。

gVisor提供隔离边界，但网络策略及资源限制仍需宿主控制；netstack不是业务访问授权。首期不采用实验性网络代理作为已验证依赖，也不使用network=host取得兼容。[gVisor网络](https://gvisor.dev/docs/user_guide/networking/)、[安全模型](https://gvisor.dev/docs/architecture_guide/security/)。

**关键未闭合项：主进程请求来源核验。** 当前Guard以原根进程身份与实际已接受连接核验来源，TaskModelIngress在发送前后重查窗口／凭据；原规格要求项目脚本不能借实例凭据调用模型。Linux的容器ID、IP、短期token和会话头只能证明部分归属，不能证明请求由OpenCode根进程产生；gVisor内进程也不能直接套宿主PID／socket归属算法。不得在平台迁移时降为“整个容器都可调用”。

P2最先验证的最小实验为：固定OpenCode建立真实模型格式的本地离线连接，控制端核验根进程来源；同沙箱子进程尝试复用token／会话头必须被拒绝；连接重用、继承socket、子进程exec、源端口重用、并发、控制重启及观察丢失均不得错误归属。实验使用本地假供应方，不产生付费请求。[运行监测](https://gvisor.dev/docs/user_guide/runtimemonitor/)仅保留辅助诊断用途；第4.15.1节源码审查已排除stock remote事件流作为唯一同步鉴权。事件缺失／证据不完整必须拒绝，不靠事后告警弥补已经外发。

当前优先按第4.15.2—4.15.6评估固定OpenCode与工具分离、Unix传输及内核凭据；没有实证前不新增自制复杂内核监控，也不自动改用普通容器或宣称独立VM天然解决同机进程冒用。本项未通过时INTERNAL_EXECUTION保持UNAVAILABLE／RUNTIME_NOT_ADMITTED；不影响P1人工业务设计。

来源通过后，继续复用原模型网关、LLMUse、code_task_reservations与价格规则：CODE／COMPACTION均占原任务次数和额度；先持久预留，发送前再验，HTTP重试为0；UNKNOWN／DISPUTED保持原占用；迟到用量只结算一次、不重开窗口。不能为Linux复制第二套费用账，tokenization与Guide／Testing后端调用也必须接入环境许可／恢复限制，不能只拦OpenCode入口。

#### 4.15.1 开源源码核查与淘汰条件

2026-11-16只读核查后，**不采用gVisor现成remote监测事件流作为模型外发的唯一同步鉴权依据**。其[监测说明](https://github.com/google/gvisor/blob/master/pkg/sentry/seccheck/README.md)、[remote协议](https://github.com/google/gvisor/blob/master/pkg/sentry/seccheck/sinks/remote/README.md)及[实现](https://github.com/google/gvisor/blob/master/pkg/sentry/seccheck/sinks/remote/remote.go)表明：事件异步发送，拥塞／错误可导致丢弃；握手后监测端主要接收事件，并没有逐次请求的允许／拒绝协议。启动时安装监测不能消除运行中丢失；发现丢失后再关闭窗口也不能撤回此前已发请求。上述为当日master源码评审，不是已选runsc发布物的验证，也不推断gVisor所有扩展方式均不可行。该通道可作辅助诊断，不承担本项目所需的发送前证明。

固定OpenCode 1.19.5继续对照现有来源提交810c0eba1a7348036f8bdf61e6632d0c36c6876c，不借最新版本推断兼容：

| 源码事实 | 对方案的约束 |
| --- | --- |
| [MCP接入](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/mcp/index.ts)支持远程HTTP／SSE工具 | 可以评估使用现成工具协议，不等于本地工具已禁用、网络重试符合原操作规则 |
| [工具注册](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/tool/registry.ts)包含内建工具与动态加载；[原生shell入口](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/prompt.ts)另有执行路径 | 只换一个shell工具不足以隔离项目代码；插件、自定义工具、原生shell、命令、LSP／formatter及本地MCP均需纳入 |
| [配置目录](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/config/paths.ts)的禁项目配置开关仍保留全局／home等来源 | 控制器必须使用受保护的专用配置和home，不能把任务仓库或用户可写配置当可信启动输入 |
| [会话工具](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/tools.ts)内部有session／call标识，但[MCP转换](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/mcp/catalog.ts)显式发送的是工具名和参数 | 尚不能证明远端获得不可伪造的原业务操作身份；JSON-RPC请求ID、模型填写的operation_id均不能替代持久原操作 |

#### 4.15.2 执行器与项目工具分离的候选

下一离线原型优先评估“固定OpenCode控制器＋gVisor项目工具”的边界；这是**待验证替代候选，不是已获准替换第4.13节部署**。OpenCode负责原生会话及模型通信；项目读写、命令、依赖脚本、被测应用等放在独立工具沙箱。沙箱无模型／业务／管理凭据及控制目录，不能直达模型入口；固定工具桥只接收已绑定原任务的受限动作，不能提供任意宿主命令。

控制器候选在专用非特权Linux身份下运行，与任务UID／目录／网络隔离，不挂载项目仓库为本地可执行配置；必要数据通过受限工具取得。宿主可见的进程身份有助于验证根来源，但[pidfd](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)只固定进程引用，[proc文件描述符](https://www.kernel.org/doc/html/v6.15/filesystems/proc.html)只提供部分归属信息；二者都不是“该HTTP请求必由此进程发出”的现成证明。仍须核验已接受连接、实际根身份、继承／传递连接与并发竞态，不能把native运行或专用UID写成已通过。

先验证以下小范围，不先重写执行器或全部工具：

1. 固定版本能否关闭全部本地不可信执行与配置加载，并限制原生控制API只对受信业务可达；任务返回内容只能作为数据，不能加载成插件／配置。应用内权限配置不能替代OS隔离。
2. 原生模型请求能否由可信连接证据绑定根进程；工具沙箱、控制器辅助进程及复用凭据／连接的请求均不得取得同权。监听器、源身份或观察失效时不外发。
3. 远程工具调用能否绑定原session／消息／tool call、业务operation、控制代次与输入摘要；需要桥接时只接受受信侧提供的标识。当前源码没有证明这些标识已随MCP送达，不能仅凭插件hook存在宣称闭合。
4. 文件修改／命令已受理而响应丢失时，先查原结果；不能因MCP重连、模型重发同参数或换JSON-RPC ID自动重做。取消／未知须同时约束OpenCode、工具桥及全部子资源。
5. 原问题／权限、增量输出、取消、工作区与候选形成、工具名／Schema／上下文预算均需兼容验证；不能将新工具集冒充原ExecutionProfile。所有进程与沙箱合计占同一个完整重任务名额。

若固定版本必须长期fork、建设通用远程执行平台或无法封闭本地执行，淘汰该候选并回到架构评审；不并行建设两套执行后端，不默认降级runc／host network，也不把“不可信工具”和“可信控制器”的名称当安全证据。以上原型仅本地假供应方，无真实模型／计数；本轮未执行。

#### 4.15.3 固定工具扩展的最小适配路径

候选优先采用OpenCode已有的自定义工具／插件机制，不重写执行器，也不把远程MCP当作原操作协议。以下依据固定1.19.5源码提交810c0eba1a7348036f8bdf61e6632d0c36c6876c；版本、启动配置、插件与工具Schema必须一起固定，源码事实不代表当前产品已完成接入。

| 固定源码事实 | 对本项目的约束 |
| --- | --- |
| [会话工具执行](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/tools.ts)构造sessionID、messageID、callID并调用before hook；[插件工具注册](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/tool/registry.ts)运行时展开该上下文 | 可评估受信工具适配器向沙箱转交原身份；这些值必须来自控制器执行上下文，不能由模型参数提交 |
| [公开ToolContext类型](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/plugin/src/tool.ts)未声明callID；[公开before hook](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/plugin/src/index.ts)声明callID但不含完整消息上下文 | 不是直接依赖稳定公开类型即可交付。允许评估一个针对固定版本的运行时字段校验器；缺字段／身份不符即拒绝，不用any、全局“最后一次调用ID”或按相同参数猜测配对 |
| [插件加载](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/plugin/index.ts)存在记录错误后继续的路径；pure模式排除外部插件 | 进程启动成功不证明必需适配器已加载；不能同时依赖pure禁插件和自定义插件工具。须核验实际启动组合、固定适配器就绪回执及实际工具清单，再开放模型窗口 |
| [原生提示处理](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/prompt.ts)含file附件直调内置read、原生命令／shell及subtask路径 | 单靠隐藏内置工具、before hook或permission配置不能封闭所有入口；控制API与附件输入也必须限界，直接执行路径逐一核对 |

最小闭环限定为“受信自定义工具→原操作登记→固定沙箱工具桥→原结果”：

1. 控制器只从固定受信目录加载该适配器；使用独立工具名，不靠同名覆盖内置工具。项目无权写控制器HOME、配置、插件、可执行文件或依赖缓存；禁止运行时从项目安装插件。配置搜索还包含全局／HOME目录，关闭项目配置不等于全部加载源已封闭。
2. 每次调用绑定environment_id、data_generation、control_generation、原task／session、native messageID、callID、工具名及规范输入摘要。callID可能来自模型协议，本身不是授权凭据；须与可信控制器来源、当前原生轮次和业务授权一起校验。适配器为并发调用分别保存上下文，不跨调用共享可变“当前ID”。
3. 受信控制侧在派发前持久映射到原operation／步骤；工具桥只接受该绑定和已登记沙箱，不能接受任意宿主路径／命令。相同原键及输入查询原结果；同键异输入拒绝。新callID即使参数相同也不是已证明的重试；旧文件／命令效果未知时阻止相关后续变更，不能让模型换ID绕过。
4. 控制API按固定版本列出实际必需入口；原生shell／command、指向项目或宿主的file附件及其他本地执行入口默认不准入。项目内容通过受限工具作为数据返回，不由控制器本地read、LSP、formatter或stdio子进程解释执行。原生subtask、问题与权限流程须分别证明兼容；不支持时对应执行配置不可用，不能暗中删除现有业务能力后宣布兼容。
5. 就绪证明须由受信启动装配核验固定文件、实际工具集合和适配器握手，再绑定当前控制代次；仅有插件自报字符串不够。缺失、加载失败、版本不符或重启失配时停止新派发并保留原结果核对；不得回退到内置本地工具。取消／崩溃按原资源集处理控制器、桥与沙箱，不只停止一个进程。

本适配器只解决工具转交及原操作关联；不能证明模型HTTP连接必属根进程，也不能替代第4.15.2节的OS隔离。先以本地假供应方验证SRC全组及EX-09，再决定是否接受该ExecutionProfile；新的工具名／Schema／上下文输入须独立固定资源，不沿用旧配置冒充兼容。若必须改OpenCode内核、广泛替换原生协议或无法封闭隐式入口，该候选退出评审，不追加长期fork。当前未编写或运行适配器。

#### 4.15.4 Linux同机模型传输与逐段来源候选

本节将根来源门槛收敛为一个优先离线原型：**固定OpenCode进程内的模型fetch适配→受保护AF_UNIX／SOCK_STREAM→原业务模型网关**。不经通用本地HTTP代理转发，否则网关只能看见代理身份。此候选不沿用Windows的TCP端口／进程归属格式，不要求先建设eBPF监控；尚未准入，不能把下面的设计判断写成已通过来源证明。

官方／固定源码依据：

| 依据 | 可确认的事实与本方案判断 |
| --- | --- |
| 固定OpenCode [provider实现](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/provider/provider.ts)及[公开AuthHook](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/plugin/src/index.ts) | auth.loader可提供provider options；该固定版本timeoutFetch包装自定义fetch，openai-compatible路径保留此选项。loader依赖已存在的原provider认证记录，后续配置还会合并；不能只写一个baseURL就假定适配生效 |
| [Bun Unix fetch](https://bun.sh/guides/http/fetch-unix) | 可将HTTP请求直接送入指定Unix套接字。文档证明能力存在；OpenCode固定二进制内嵌的Bun、SDK请求／SSE／取消是否兼容仍须逐项验证，不能用另一份最新Bun替代 |
| [Linux Unix凭据](https://www.man7.org/linux/man-pages/man7/unix.7.html) | SO_PEERCRED反映连接建立时身份；SO_PASSCRED可使接收侧取得随数据而来的SCM_CREDENTIALS。只查连接一次不足以处理继承／转交后的发送者变化 |
| Linux v6.8 [Unix流接收](https://github.com/torvalds/linux/blob/v6.8/net/unix/af_unix.c)及[凭据校验](https://github.com/torvalds/linux/blob/v6.8/net/core/scm.c) | 源码为发送缓冲附当前线程组身份，接收时区分不同凭据；显式声明其他身份受能力检查。此为选定上游源码依据，不等于Mac VM或云内核已固定并验收 |
| [Python3.13 socket](https://docs.python.org/3.13/library/socket.html)与[pidfd](https://www.man7.org/linux/man-pages/man2/pidfd_open.2.html) | 可通过recvmsg取得数据及辅助信息、保留原进程引用。普通recv不会把凭据交给上层；pidfd本身也不证明该进程没有exec换成另一程序 |

传输与进程边界按以下完整组合验证，缺一项就不开放模型窗口：

1. 固定插件在OpenCode进程内为唯一WALL-E provider安装受限fetch，使用原实例网关凭据；内存auth装配只含该内部provider的原凭据，不放真实方舟密钥，也不要求用户登录Codex或外部账号。逻辑baseURL固定为http://walle-model.invalid/internal/code-model/<原32位小写十六进制实例路由>/v1，Host严格为walle-model.invalid；该URL仅供SDK组织请求，实际传输必走Unix，不做DNS／TCP连接。只接受POST、原chat/completions route和已允许模型用途；Unix路径来自受信实例装配，不来自消息／项目参数。关闭自动跳转、代理和传输自动重试；任何连接失败不得改走TCP或供应方直连。HTTP正文、原生会话头、AbortSignal和SSE保留原语义，不在适配器内重写预算或构造另一请求。
2. 采用短的受保护pathname套接字，父目录不可由控制器／项目替换；长度按目标sockaddr_un实际限制核验，不直接拼接冗长项目路径。监听身份、socket实例、原运行和控制任期绑定。工具沙箱不挂载它；原生控制API、受信工具桥、管理入口和模型入口各自独立。控制器没有外网直连能力，缺适配器只会失败；原生控制API仍按固定受信入口访问，不因此开放普通业务网络。
3. 受信启动方在固定程序启动时取得原pidfd并核验受保护二进制、运行身份与隔离配置；接收侧和该进程使用可正确对照的PID命名空间。收取任何请求字节之前启用并核验SO_PASSCRED，SO_PEERCRED仅作初始交叉核对；首包在accept前到达的情况也必须覆盖。每次读取都用recvmsg并验证唯一、完整的SCM_CREDENTIALS，匹配原根线程组及预期UID／GID；缺失、MSG_CTRUNC、额外／异常辅助数据立即拒绝。意外收到SCM_RIGHTS时关闭收到的描述符并拒绝，不能泄漏句柄或借其更换通道。
4. 所有HTTP头、首次读取携带的正文前缀和后续正文均经过同一个凭据接收器，不能先用recv／makefile／HTTP框架读走一部分再验剩余内容。对每段验证后累计规范来源摘要与完整请求摘要；只有有界完整正文全部来自原根才进入原业务准入。根发送头而子进程发送体、分片／并包、已连接FD转交和同UID其他进程均要拒绝；同一根的正常工作线程按内核线程组身份处理，不能误拒绝为陌生子进程。
5. 首期保持现有单连接单请求、Content-Length和HTTP/1.1限制；拒绝chunked／Upgrade／CONNECT／管线复用，响应沿原SSE后关闭。不新增通用HTTP代理或第二套模型路由。读取大小、连接上限、超时与输出限制复用原配置；并发连接不共享凭据累积器。多出的请求不作为第二次调用，连接池、SDK失败重试及压缩路径必须在固定版本验收，不能以“客户端一般不会重试”代替。
6. 在原发送提交点再次核对pidfd仍指向活的原进程、当前运行／控制代次、来源回执、原窗口／许可和正文摘要。进程退出、接收器／控制端重启、策略更换或身份无法核清时立即失效，不按同名PID／socket路径认领新进程。已可能外发仍按原UNKNOWN和费用规则；来源失败不表示免费，也不自动重发。

同PID exec不会改变PID，所以逐段凭据必须与控制器执行封闭配套。首期优先评估固定[AppArmor强制策略](https://manpages.ubuntu.com/manpages/noble/man5/apparmor.d.5.html)：从受信启动方进入固定控制器profile，服务阶段拒绝exec／execveat、其他profile切换及不可信代码／插件加载；同时无可伪造凭据的能力、无提权／调试注入、不可修改控制策略或宿主命名空间。实际加载策略、enforce状态和固定资源须核验，策略文件存在或complain模式不算生效。不使用允许失败后继承／不受限执行的fallback；Bun正常线程／JIT与固定依赖要实际兼容，不能笼统禁用可执行内存后宣称可运行。若OpenCode必需启动／原生功能不能满足该边界，先定位并退出或修订候选，不临时允许任意本地命令。

逐段凭据只能支持“谁发送了这些请求字节”的判断，不保证响应FD从未泄漏，也不证明进程内逻辑未被破坏；后两项仍依赖固定程序、无不可信本地执行、目录／身份隔离和完整停止。受信控制、宿主内核或管理员被攻破不在此机制的独立保护范围；任务脚本复用内部凭据则是必须覆盖的威胁。

模型fetch、工具扩展可以封装在同一个固定插件资源中，但两个能力分别就绪和验收；仅工具握手成功不证明模型传输已生效。插件／socket／凭据装配变化按原生命周期重新准备，禁止热替换fetch后继续复用旧SDK缓存。原型仅本地假供应方；应先证明传输和拒绝行为，再验证完整工具／问题／权限／角色交接／压缩及候选流程。当前未改运行包、接收器或启动策略。

#### 4.15.5 冷启动与原生能力兼容边界

本节明确第4.15.4候选怎样在禁止控制器执行本地命令的条件下运行。依据仍是固定1.19.5源码；下表给出可实现方向及必须保留的业务行为，不把源码中存在分支等同于实际二进制已通过。

| 已核对的路径 | 固定候选的处理 |
| --- | --- |
| [配置加载](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/config/config.ts)对搜索目录准备.gitignore并异步执行Npm.install；安装错误会被记录后消化。[Npm.install](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/core/src/npm.ts)在目录不可写时直接返回；可写目录主要检查node_modules及锁文件声明，并不完整校验依赖版本／字节 | 在安装阶段离线准备完整依赖与配置，运行身份不可修改；就绪前由受信装配核对全部成员及摘要。waitForDependencies完成既不证明安装成功，也不证明版本正确。不能依靠只读目录让缺依赖被静默跳过后报就绪 |
| [配置目录](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/config/paths.ts)还搜索全局、HOME/.opencode及显式目录；配置可来自认证记录的wellknown入口 | 固定专用HOME／XDG路径、唯一受信配置源及其完整搜索集合；其他搜索位置为空且不可被项目或控制器新增配置。认证只含内部WALL-E provider，不导入用户账号、远程配置或环境覆盖。禁止运行时下载、修复依赖或发现新插件 |
| [Git发现](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/core/src/git.ts)在找到祖先.git后才执行git命令；[项目解析](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/core/src/project.ts)的无仓库结果以文件系统根作directory | 控制器元数据目录及祖先不能含.git，不把项目挂到该目录；安装方核对真实路径／挂载及祖先。根目录值不是业务读写权限。代码仓库、依赖命令及Git交付仍走已登记沙箱／可信交付路径 |
| [bootstrap](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/project/bootstrap.ts)先初始化配置／插件，再并行初始化LSP、format、VCS、snapshot、project，并记录而不传播其中的初始化错误 | 有进程、HTTP响应或bootstrap结束都不是完整就绪；核对实际生效配置、必需适配器及相关原生服务。被明确关闭的可选功能与必需功能失败分别处理，不能把所有启动告警一律忽略 |
| [snapshot](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/snapshot/index.ts)由VCS及snapshot配置决定是否启用；[SessionSummary](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/summary.ts)计算文件差异，snapshot=false时停止该差异路径 | 固定snapshot=false、lsp=false、formatter=false，不依赖控制器本地Git快照。SessionSummary此路径没有模型调用；其空差异不能用作“项目未修改”或正式候选依据。WALL-E原候选、独立检查和Git交付保持第4.19—4.21节职责 |
| [标题生成](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/prompt.ts)可能另发small模型请求；[Agent装配](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/agent/agent.ts)支持disable，并会给原生截断目录补external_directory许可 | 使用受信生成的非默认会话标题，并固定禁用title／summary及未使用的原生子Agent。权限不能只配置通配deny：显式拒绝实际截断目录模式，核对最终合并规则。不能把原生默认白名单视为任务授权 |
| [Question工具](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/tool/question.ts)通过原session／message／callID发起问题；[压缩处理](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/compaction.ts)另经processor调用模型，并可能继续原会话 | 保留原问题／权限事件及业务答复，不需要为提问开放shell。compaction agent显式绑定walle/walle-compaction、无项目工具；CODE／COMPACTION继续共用原窗口、次数、预算和维护收尾规则，不能误用默认CODE别名或增加免费后台调用 |

新Linux配置明确不启用OPENCODE_PURE，否则必需插件可能被排除；同时保持关闭项目配置、默认插件、外部技能、Claude配置、LSP下载、模型目录下载及自动更新，实验性并行／后台子Agent／code-mode／工作区能力不默认开启。由固定版本确认实际生效开关，不能照抄Windows变量后只检查字符串。mcp为空、share禁用；唯一插件及其可加载依赖按第7.11节固定。

原生内置项目read／edit／write／bash／task／skill及联网工具不开放；采用第4.15.3节的独立受信工具名。原生shell／command／subtask、配置／认证变更和Agent生成等控制入口不在业务转发白名单，消息继续采用现有native_message_input的严格文本输入，不引入file附件。保留已核对的question及原权限事件；其确认只能在原授权边界内推进，不能通过“始终允许”扩大沙箱动作。WALL-E前后端角色交接沿原业务会话与控制代次完成，不借OpenCode原生task创建未经登记的子会话；不能把禁用原生task解释为取消业务角色交接。

就绪顺序固定为：受信安装方校验完整静态包与目录边界 → 模型窗口关闭状态下启动受限控制器 → 只读核对实际配置／模型别名／Agent规则／有效工具集合 → 核对模型与工具两个适配能力及原运行绑定 → 依原业务授权开放窗口。此处就绪核对不发真实或探测模型调用、不执行项目命令、不运行安装修复；协议兼容用隔离假供应方验收后的固定证据。缺依赖、配置漂移、隐式加载、必需服务失败或无法证明实际组合时保持不可用，已启动资源沿原停止流程收尾，不能报“未启动”后释放占用。

会话数据库、消息、权限等待及原生日志仍需要独立可写数据／state／temp目录，受任务资源上限约束；只读约束针对程序、依赖及所有配置加载根，不是把整个HOME或全部状态锁成只读。可写目录不得成为插件／配置／项目发现入口，任务沙箱不可访问。源代码审查暂未证明必须开放本地exec；固定二进制若仍依赖不可关闭的辅助执行，先判定该候选不满足或修订可核对的边界，不开临时任意命令白名单。当前没有启动或安装此组合。

#### 4.15.6 工具动作、授权对象与取消的对应

本节固定候选的最小工具面，不新增一套任务授权。每次实际动作同时满足原EFFECTIVE AuthorizationGrant、所绑定ExecutionProfileVersion、当前会话／控制代次、环境维护规则及本次工具绑定；OpenCode权限决定只是其中的一步。现行task_native_policy仅编译Windows受管read／edit范围，并明确拒绝含命令或网络的scope，不能将其通过结果当作Linux完整工具准入。

固定源码有三处必须显式适配：

- [session/tools](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/tools.ts)把abort和ask交给工具，再调用execute；自定义工具不会因此自动执行具体对象授权检查。[工具注册](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/tool/registry.ts)包装结果，[模型请求准备](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/llm/request.ts)另按合并权限筛除工具。须核对最终实际发送的工具集合；“看不见工具”与“调用动作有权限”不能互相替代。
- [Permission](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/permission/index.ts)按最后匹配规则判断，once只释放对应等待；always会写入实例内批准规则，reject会影响同会话其他待批请求。候选只使用once／reject，禁止always、配置通配扩大及沿旧实例保留批准；不靠调整显示名称缩小实际拒绝范围。
- [公开工具上下文](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/plugin/src/tool.ts)有AbortSignal及ask，但不提供“外部命令已经停止”的证明。HTTP请求取消、Promise结束或原生工具报错均不能替代原任务资源停止与效果核对。

**工具与业务动作。** 工具Schema、描述和下表映射随固定包发布；模型参数只提供动作数据，原身份与scope均由受信上下文解析。已授权范围内沿原策略自动处理，不为每次读写增加人工批准；仅固定生效策略本来要求ask时等待单次确认。范围外、不能识别对象或不支持的动作直接拒绝，不能通过再问一次获得权限。

| 工具／输入边界 | 对应原授权及效果 |
| --- | --- |
| walle_read：scope_ref、规范相对path及有界读取范围 | READ；scope_ref必须属于原read_roots并绑定真实TASK_WORKSPACE或TASK_BASIS。原文件完整摘要与返回片段摘要分开，原文件摘要不能由局部片段代替；文件超原大小上限则拒绝。结果按7.11.2续读，不是宿主路径读取器 |
| walle_search：scope_ref、目录前缀、LIST／TEXT及有界字面查询 | READ；范围同上，先校验根再列举／搜索。目录根用独立空前缀表示，不把.或..加入原内容路径规则；不接收Shell、正则程序或任意rg参数，不通过链接走出根 |
| walle_write：operation=CREATE／REPLACE／DELETE、path、content及expected_sha256 | WRITE；仅本任务workspace。CREATE要求目标不存在且expected_sha256=null；REPLACE／DELETE要求匹配原内容摘要。CREATE／REPLACE的content为有界UTF-8文本，DELETE必须content=null且不接受目录递归。依据、其他任务、宿主配置及受保护元数据不可写 |
| walle_patch：单文件path、原内容摘要及有界文本补丁 | WRITE；同一工作区规则。补丁声明的目标必须与path一致，不支持多文件、改名、二进制、链接、模式变更或可执行脚本。先在内存完成并校验整个新内容，再原子替换；不调用项目提供的patch程序 |
| walle_command：command_id | EXECUTE；必须是原配置及allowed_command_ids中的同一完整COMMAND定义，purpose=EXECUTION，实际程序与参数模板已准入。模型不能另填argv、工作目录、环境变量、Shell文本、超时或网络 |
| walle_result_read：原result_ref与cursor | READ；按7.11.2核对原任务及不可变结果，不借引用读取任意文件，不重跑原工具 |

读写继续用CONTENT20-STORE-1的规范相对路径、普通文件和名称冲突规则；字符串规范化不替代Linux句柄／真实根／链接／类型核验。捕获的include／exclude是成果选择规则，不是新增读写授权。新建父目录、目标不存在、删除与替换分别固定前提；创建不覆盖，替换保留模式／字节约束，按4.23.1在已核验的同一文件系统内准备完整文件并原子落位，删除保存可核对的原身份与效果。等待期间内容或父目录身份变化时拒绝旧动作，不用同名文件替代。补丁分文件调用可能部分成功，不承诺跨文件事务，不自行回滚其他已确认写入。

**命令与网络。** execution_profile_content只对argument_template做一般结构校验；真正准入还须沿execution_profile_resources核对完整注册资源。首期Linux命令模板仅接受固定字符串argv和受信装配值，不接收模型替换槽；不支持的模板使对应配置不可执行，不能把命令删除后仍报全配置就绪。命令的network_scope_ref非null时必须同时属于原network_targets，且实际出口只开放该命令的固定范围；null即无网络出口。范围来自原资源，不能由命令文本、重定向或DNS结果扩大。

首期EXECUTION要求TASK_WORKSPACE在原read_roots中，固定依据仅在另有原读取范围时只读挂载。每条项目命令在独立短时工具沙箱内执行，只挂载本次必要的任务根及固定非产品临时目录；其网络不临时加到控制器、文件工具或下一命令上。全部子资源纳入同一原任务名额，不新增宿主重任务槽；命令结束或取消后核清全部后代／写入者，再允许下一项目动作。项目脚本可以执行，但始终是不可信负载，不能进入控制器或宿主受信程序。CHECK／SERVICE仍由原检查计划及其授权启动，不能通过walle_command绕过独立检查；项目命令退出0只形成CommandExecution事实，不直接产生合格Verification、Testing报告或交付资格。依赖预取沿4.13.1的受限准备流程，不在缺包时临时放开外网。

**单次调用顺序。** 复用4.15.3原工具操作关联，增加OC201-TOOL-AUTH-1绑定：

1. 受信侧严格解码工具数据，核对实际控制器及当前业务scope，解析真实对象／命令并形成规范输入与摘要；原tool_operation_id由控制侧生成（operation_ref引用同一规范UUID），关联原task／run／session／message／callID／业务operation、授权及配置摘要。模型填写的身份字段或native metadata自报不产生此绑定。
2. 在原工具操作内保存被确认对象、输入、所用资源与必要文件前提；然后调用工具上下文ask，permission为固定工具名，patterns仅含原操作引用，always=[]，metadata仅含协议、引用及绑定摘要。固定allow规则可直接返回；ask规则才产生原NativePermission。独立业务校验无论ask返回方式均执行，不能把Promise返回当作权限来源。
3. 命令确认另绑定工作区最近已核清写入的高水位；只有全部写入者均受管且已静止时才能形成，等待期间发生新的工具写入／命令效果即失效。该高水位不能替代真实写入者停止证据，也不把可变工作区伪装成已封存候选。待批时不占住数据库事务或文件写锁。原权限通过第6.7.1节与原操作精确关联；ALLOW_ONCE只对应该输入及对象，不是下一条相同工具／命令的许可。内容、参数、配置、授权或会话变化使旧确认不可用于新动作；普通问题答案不能转成权限决定。
4. 真正派发前，受信控制侧在原任务动作闸门内重核当前生效授权、配置、控制代次、维护资格、停止／取消、对象前提、原确认和效果状态，持久写入一次派发事实。与取消、授权替换和捕获停写按同一控制顺序决定先后；旧callID同输入查原结果，异输入拒绝，新callID不解除旧效果未知。
5. 写入／项目命令互斥；文件读取只在可保证一致的无写入阶段进行。权限等待不阻塞问题答复、原结果读取或停止，不能把等待确认变成持锁死锁。工具原效果／结果分别保存，失败及未知经7.11.2有界返回，不以抛出错误表示副作用必未发生。

**拒绝与取消。** DENY仍为“拒绝本会话待批权限”，不等于任务终止。投递前暂停该会话新的适配器ask进入，核清已进入的登记，再固定当前原生待批集合；不能稳定该集合时不首次投递reject。固定策略关闭其他未准入的原生权限产生路径（含doom_loop自动ask），意外请求按未识别保留而不放行。发送后逐项消费对应permission.replied证据；列表消失、404或只收到所选一项回执都不能批量记已拒绝。证据不全时保留原决定UNKNOWN及等待；未派发的可释放登记屏障，已可能派发的只核对／停止，不重投reject到新会话。

AbortSignal监听须在可能等待／外发之前建立，并转为原工具操作的取消标记。先于派发提交点的取消保证不开始；晚于提交点则关闭后续派发、停止已登记资源并核对效果。迟到ask成功、迟到HTTP响应或插件Promise继续执行都必须再检查该标记；不能在取消后偷偷写文件。原生permission pending只在内存，重启后消失不代表批准／拒绝，不恢复旧许可。任务终止与捕获停写继续覆盖控制器、工具桥、命令沙箱及全部写入者；未核清时保留资源占用和原效果，不把工具错误等同整项任务已停止。

### 4.16 APP-EXEC-RESTORE 恢复数据后的执行与额度

普通同代次应用重启与恢复旧快照分开：前者读取当前完整账与原控制证据，沿原恢复机制；后者第4.12节已换data_generation，旧EFFECTIVE授权、APPROVED_UNBOUND授权、待发队列、实例token和原生会话一律不产生新代次执行权。旧数据可读取／核对；不改写历史授权内容来冒充新批准。

恢复必须形成同一原RESTORE操作下的审阅结果：

| 结论 | 所需事实与禁止替代 |
| --- | --- |
| 旧执行已封闭 | 原任务窗口、控制资格及运行资源均撤销／停止；无法取得旧宿主时，供应方／远端写凭据也需可验证撤销。备份时“未运行”不能证明备份之后无活动 |
| 历史调用覆盖完整 | 对照恢复点、恢复前保全库、独立原外发证据及必要供应方原账单，确定恢复点之后的调用范围；不能仅查恢复后的llm_uses |
| 已核算与未决分别保存 | 原LLMUse／CodeTaskReservation仍是账务依据；可靠usage或PROVIDER_BILL才结算。缺结果、缺用量、冲突与范围缺失分别保留，不以0元／失败／用户勾选代替 |
| 原外部写入已处置 | Git交付、问题答复、权限变更和检查目标的原结果核对；核清费用不能证明这些操作没发生 |
| 新代次允许范围 | 新环境许可绑定当前environment_id／data_generation／配置与供应方范围；新的业务授权仍按原任务／配置／预算契约。恢复确认本身不授予模型额度 |

恢复点之后的原外发事实不能仅保存在同一会被回退的业务库：在control_root外发证据子目录保留只追加的原准备／发送意图／结果索引，记录原代次、原调用／计数审计身份、操作、请求摘要、证据引用及提交顺序。该目录不被RESTORE覆盖、不由任务修改；仅是恢复证据，不计算独立余额或向模型发请求。真实内容沿LLMUse及CountingJournal保存；首次外发前须有业务准备与外层发送意图，任一持久失败不发。已外发后的结果保存失败保留未知；缺记录不反推未发送。

外层与业务数据库不存在跨文件事务：重启按原身份对照，外层发送意图未取得确定未发送证据时保守为未知，不能由旧库NOT_SENT释放。当前coding_model_ledger.recover_interrupted_calls只适用于确认未回退、实际发送者已失效且持久步骤完整的同代次恢复；不能原样应用于旧快照。CountingJournal.PREPARED也不证明已发送或免费。

现存完整费用证据能够关联原owner时，专用恢复步骤以原代次＋原身份去重核对，不新建第二笔调用、不覆盖新代次同名ID。不能恢复完整关联时，原代次保留只读待核对，禁止恢复任务自动继续、沿用旧余额或把不明费用改为已结算。重新创建任务必须重新形成范围与预算授权，并向用户分开展示旧未决费用；不把“另开新任务”当成解除全环境恢复限制的旁路。

本批固定解除outbound_hold的必要条件与核对顺序，但不提供布尔开关：先完成上述恢复审阅，再由具备业务付费授权资格的当前用户确认具体新许可；持久保存许可／审阅依据后，原恢复操作以预期control_revision解除该代次hold。中断时先查原结果，任何当前配置、数据代次或审阅依据变化使原确认失效；普通START、管理MANAGER身份或额度追加不能清除hold。

环境许可、逐次准入与恢复提交按第3.9—3.10、4.17—4.18、6.8、7.12节；许可及恢复证据置于不回退的control_root，不新增费用账。缺失原历史证据的补齐仍须各业务原审计契约，当前不提供人工改账或通用导入接口；无法取得可信完整证据时保持受阻。本节不承诺用量永久缺失时自动恢复，也不把预留上界标成实际支出。


### 4.17 APP-ENV-MODEL-AUTH 许可签发、撤销与逐次准入

入口认证、环境能力、环境许可、原业务授权／预算、来源证明五项分别检查，不用一个“已授权”标记相互代替。当前环境模型授权由第6.8节业务身份完成；环境管理员、程序服务UID、只读／DEVELOP身份均不自然拥有该权。

1. 签发前显示当前环境、数据代次、具体用途／模型、到期时间与“不会自动启动任务”。用户提交原命令；后端重读当前部署、策略、身份、控制版本及安静边界。许可只可选既定策略子集，不能提交端点、价格或密钥。
2. 正常签发先封存许可／效果准备记录，再在同一应用准入闸门下CAS更新model_access及control_revision，最后落原结果；任何持久失败不外发。普通签发遇outbound_hold拒绝，恢复签发用第4.18节原操作。
3. 撤销先在同一闸门下持久将active_permit_ref置null并推进许可版本，再返回完成。已越过发送提交点的调用仍可能发生费用；撤销不伪称能撤回网络数据。尚未越过提交点的调用不可发送，旧许可不能因程序重启重新指回。
4. 每次计数／Chat／压缩在持久准备前和真正发送提交点各校验当前控制、许可、用途、原业务范围及额度。应用内所有外发适配共用此准入闸门，与许可撤销、维护、恢复切换串行决定先后；后台worker不能在启动时验一次后永久放行。原发送提交点已落但结果未知按可能已发送处理，不重发。
5. 准入是当前许可与原业务批准范围的交集；绑定许可ID／摘要、环境／代次、原操作、原调用／计数审计身份、用途、模型与资源引用进入第7.12节外层证据。不得根据模型返回、任务环境变量或浏览器body声明身份。窗口仍需TaskModelIngress的可信根来源证明。
6. 维护收尾仍按第4.10／4.14节冻结原轮次；新许可不能扩大冻结范围，到期或撤销后的原轮次也不再新增外发。许可被替换后，旧待发授权不自动换绑；只能以新的明确业务动作重新取得范围。

各路径绑定既有业务事实，不统一伪装成Coding：

| 路径 | 原依据与调用边界 |
| --- | --- |
| Guide讨论／出稿／修订 | 原GuideRun及用户明确操作、固定上下文与资源；每run最多一次Chat，计数按当前资源的有界候选批次，本地重算不冒充免费远端计数。具体批次上限随固定资源核验，不由许可增加 |
| Token计数 | CountingJournal的原批次身份、所属Guide／Testing／Coding原操作与用途；每个实际HTTP批次均单独准入。没有所属操作的自动“连通性检查”不得外发；计数与Chat分别列次，不能把8段文本计成8次HTTP或把多批计成1次 |
| Coding模型／压缩 | 原有效AuthorizationGrant、ExecutionProfile、任务预算、ModelWindow和原生轮次；CODE／COMPACTION继续共享原次数／额度和未决限制 |
| Testing计划 | 原Testing操作、固定计划输入／模型／价格与该操作预算；不能借已有Coding授权开启新计划 |
| 独立检查／命令 | 取得执行权不等于取得模型权；无模型用途默认无权，若需要计划模型则仍走明确TEST_PLAN_CHAT操作 |

Guide现行Token预算与Coding金额预留不是同一种度量。本单元不凭Token限制宣称提供统一人民币硬上限；如需环境总金额或Guide新增金额封顶，必须另定义费用批准与并发预留，不能在环境许可表中加一个无人扣减的max_cost。首次真实验证的次数／预算／重试仍按当前用户明确范围，不能用本设计或历史许可代替本轮授权。

### 4.18 APP-ENV-MODEL-RECOVER 恢复放行原操作

恢复数据先完成第4.12节部署／只读核验；outbound_hold仍为true。业务应用可以在明确恢复模式提供第6.8节只读审阅和受限许可命令；admission=CLOSED时仅允许这些控制元数据动作及第4.22节已核验PURE_READ，不开放普通业务写入、AI、计数、队列重放或任务继续。应用不满足启动／固定资源核验时须先修复，不能靠恢复授权绕过启动。

1. 有资格的业务用户请求生成审阅；程序只读当前完整证据，形成第3.10节快照。四项非全PASS就返回阻塞，不展示可确认计划。审阅期间旧执行须保持封闭；出现新外发证据、控制代次或配置变化即使原审阅失效。
2. 用户确认具体新许可范围和到期时间，连同review_id／sha256及预期版本提交ACTIVATE_AFTER_RESTORE。该操作同时形成新代次许可和解除外发限制的意图，不把“确认恢复”解释为批准任意任务或余额。
3. 在同一控制闸门下再验当前可信业务主体、未过期审阅、原RESTORE归属／目标、部署与证据高水位、四项事实和安静边界。新许可、不可变效果准备及原命令均可靠落盘后，单次control CAS更新active_permit_ref、model_access.revision并清除对应outbound_hold／cause_operation_id；其余admission及部署字段原值保持。
4. 该CAS是许可／hold共同生效点，不存在“先解除hold，稍后再写许可”。它不开放仍为CLOSED的环境、不启动旧任务、不重发旧请求。原管理恢复操作观察该效果，业务授权不通过管理身份转发；管理服务不在线也不能代为确认。
5. CAS前崩溃只有准备文件，不生效；CAS后回执丢失按原命令及control中的last_effect_ref核对，可补原回执，不能再次签发。效果未核清前不推进下一许可变更；未知保持阻断，不用新请求键猜测重做。
6. 原审阅过期／事实变化在生效前返回PRECONDITION_FAILED并需新审阅；原命令已生效后查询仍返回原结果及当前许可是否有效，过期不抹去历史成功。恢复到另一代次后，旧结果仅历史，不重新解除限制。

旧费用及外部写入无法核清时保持hold；不能用新任务、换许可、管理页面或直接改配置绕过。其他数据代次的原LLMUse／CountingJournal证据按完整来源身份访问，不以新库同数值ID覆盖。此恢复API只消费既有可信核对结果，不提供任意金额修正、SQL导入或将缺失事实手工勾成PASS的接口。

### 4.19 APP-ENV-CONTENT 固定候选与只读检查副本

复用原捕获、seal、包发布、候选指针CAS和恢复流程；Linux替换Windows文件句柄／路径保护，不改变“检查及交付只能消费明确固定内容”。

1. 在原任务／控制代次下封闭新模型、工具、命令和受管文件写入入口，取得完整写入者资源集。首期优先采用明确阶段边界下**结束项目写入者并撤销其工作区访问**，再捕获；工具分离候选可保留无项目本地写权的可信OpenCode控制器。若实际布局无法做到且又需要保留原生会话，来源／捕获能力保持不可用，不能临时杀掉控制器后静默重建会话。
2. 控制端核对原工具进程、被测服务、子进程及文件代理，确认无未核清写入；维持栅栏到封存结束。chmod只读、flock、打开fd、一次摘要、OpenCode idle或仅暂停主PID均不足。cgroup.freeze只是暂停机制，[内核文档](https://docs.kernel.org/admin-guide/cgroup-v2.html)仍允许进程迁移，不能单独作为已停止或文件写入已全部结束的证明；本版不依赖freeze后直接拷贝活目录。
3. 从已核实根按架构6.3的openat2／类型／链接／祖先边界读取，并执行原内容选择、秘密扫描、总量和时间限制；与原清单及结束时全量核对一致后封存。失败不从部分文件生成候选，不把原文件临时改只读作为永久业务改动。
4. 原CONTENT20-STORE-1普通文件路径、字节和模式规则继续，Linux不静默放开符号链接／gitlink／LFS／大小写别名、改换行或凭chmod推断新执行位。原Windows兼容路径限制首期保留；修改内容策略须另发版本，不能因ext4可存就默认支持。
5. 新包在同一受管文件系统按不覆盖方式发布并同步文件／目录；Linux不可把os.replace用于“最终包不得存在”的发布，因为它允许替换目标。原目录已存在只核对seal／原操作；对应文件系统必须支持经验证的不覆盖发布方式。
6. 检查副本由封存包或固定Git对象重新物化，产品输入及其受信父目录只读，无共享硬链接或任务可写宿主别名。依赖与构建输出只能落入预声明的非产品位置；挂载输出不能遮蔽任何候选条目，也不能让产品根有可写上层。Docker只读挂载还需核对[子挂载和传播规则](https://docs.docker.com/engine/storage/bind-mounts/)，不是看到ro就放行。

构建需要缓存／临时数据库时用本轮假数据目录和固定配置传入，不写正常业务库、不在源码里临时生成配置后仍称原候选。需生成产品源码时回编码并重新捕获；拒绝“测试改完又改回”通过。若运行的是构建产物，先固定原候选、依赖、命令及实际输出摘要，结束构建写入者后只读交给被测服务；报告说明实际测试源码服务还是构建产物。测试副本绝不回写为新候选。

### 4.20 APP-ENV-CHECK Linux独立执行、报告与停止

复用[V2.0后端](../../../design/v2.0/WALL-E.后端设计文档_V_2.0.md)APP-TEST-RUN及7.6的计划／包、阶段、断言、资格和原结果规则；本节只定义Linux运行边界。

#### 4.20.1 原执行准备与能力

RUN_TEST仍固定唯一Verification、完整Item／case、测试计划及资源闭包，先取得同一宿主完整重任务名额。Coding交接给Testing是原资源收尾后释放，再由Testing原操作取得名额；不同时保留一个Coding重任务并要求Testing抢第二个名额。候选和会话历史可以保留，未核实停止的进程不能当空闲。检查里的前端、后端、浏览器和driver合计同一个资源组，不能各自再申请名额造成自锁。

首期按CONTENT_INTEGRITY→CLI／项目命令→HTTP→BROWSER逐能力取得离线实证；缺浏览器时如实UNAVAILABLE，不能删掉必检项使报告合格。INDEPENDENT_CHECK就绪还受实际配置所需能力／资源约束，不能由一个CLI通过推断完整支持。检查不需要模型费用许可，仍需要原Testing执行授权；新计划模型是独立TEST_PLAN_CHAT操作。所有检查网络默认无模型／计数及真实外部服务出口。

#### 4.20.2 可信检查与浏览器

CLI／HTTP受控比较优先复用check_case_values／check_case_evidence及固定CasePack；项目stdout只作待比较数据。Linux受信driver用独立非特权身份、固定程序与隔离的HOME／加载路径，不在业务HTTP进程内import候选或项目依赖。案例是有界数据，不接受任意脚本、eval、page.evaluate或候选提供的断言实现。

浏览器优先复用Playwright及原数据命令／结果协议；现有check_driver_pipe_worker.cjs／pipe_sdk中的Windows可执行路径、LPAC、私有桌面和进程broker不得仅改后缀后视为兼容。先验证独立driver、固定SDK及受控浏览器启动／通信的Linux组合。浏览器／页面／项目进程不能继承权威结果写端、读取私有预期或连接业务控制套接字；不能把Docker logs或容器stdout直接当可信断言流。

固定清单必须绑定Python／Node／Playwright版本、其匹配浏览器修订、OS／CPU及完整文件／宿主库闭包，不使用运行时npx下载或个人全局浏览器。按[Playwright官方说明](https://playwright.dev/docs/docker)，镜像不包含Playwright依赖包，root运行还会关闭Chromium沙箱；因此不能直接采用示例的root、host IPC或额外SYS_ADMIN权限。项目要求非root、chromiumSandbox=true、私有且有界共享内存；不兼容时保持UNAVAILABLE，不加--no-sandbox或关闭web安全。镜像文档不是本项目gVisor／浏览器组合已验证的证据。

浏览器每项新profile，禁扩展、下载和service worker；WS／重定向／子资源按固定允许集合处理，不转发任意CONNECT。只测试本轮受管前后端和登记离线替身，INTEGRATION／ACCEPTANCE所需真实候选前后端不能被替身替换。网络由沙箱外规则约束，Playwright route拦截只是应用层补充；缺请求／端点归属证明时不发送业务字节。

#### 4.20.3 结果可信度与故障

权威结果继续BEGIN／CASE_RESULT／END、连续seq和完整case／assertion集合；Linux控制侧验证原driver根身份、固定包、受保护通道和原nonce。管道／UDS名称、可复用token或容器ID均不足，必须证明项目／浏览器子进程不能冒写。浏览器原控制请求和HTTP步骤已有派发意图后响应丢失，只核对原记录，不重做点击／提交／CLI；不以Playwright重连或期望等待为理由引入业务重试。

每项结束先撤销新请求，结束本项应用／driver／浏览器及全部关联子资源，核对实际停止、输入与临时数据收尾，再计算eligible。cgroup populated=0可作为原资源组停止的组成证据，必须同时核验真实资源归属、启动已封闭及组外辅助资源；容器删除、主PID退出、退出0或到达超时均不单独证明完整停止。

结果沿原规则：可信失败为FAILED，资源／隔离不可用为UNAVAILABLE，过程／帧不明为UNKNOWN；停止未知继续占用，全部活动已核清但结果缺失可形成不合格UNKNOWN报告。取消保留已完成事实，不自动复测。报告result、eligible、delivery_eligible和TestingTask.COMPLETED分别展示；每次采用报告重新核对当前候选、原设计、资源／计划包未撤销及完整收尾。换OS／CPU／依赖、候选或检查标准不改旧报告，也不沿用旧通过。

### 4.21 APP-ENV-GIT Linux本地交付及恢复

#### 4.21.1 登记与预览

服务器侧仓库由负责人明确准备，受信入口登记；应用没有自动clone／fetch／push／PR能力。REGISTER_BASE按第3.12节原代次命名空间create-only保留所选commit，读取不补对象、不从当前工作树取未提交内容。实际git_common_dir的长期环境归属与本次Git动作互斥分别核对；环境交接、数据恢复不能释放未核清Git占用。

PrepareDelivery继续取得固定候选、适用独立报告及目标直接分支，封存目标完整tree并逐路径比较增删改／模式；目标独有文件的删除明确展示。AcceptCode绑定原Plan、candidate、report及expected_target_commit；人工范围确认不替代AUTO必检或未覆盖门槛。目标分支在任何worktree被检出均拒绝，不自动切换用户分支。

#### 4.21.2 固定Git与单次写入

LinuxGit为另行准入的固定包，不能使用Windows MinGit摘要、随PATH的git或apt最新版本作证明；保留files引用后端、完整本地历史及受支持配置范围，不新增网络协议或用户hook／签名能力。git_ref_protocol、固定对象／提交构造、原回执和交付状态机优先复用；只替换进程／文件／持久性适配。

CONTROL_GIT为独立受信非特权写入者，只对已登记本环境仓库及原私有包取得必要权限，无模型权、root身份或任意shell入口。程序／库／HOME／配置由受信清单固定，清除Git注入、个人代理、askpass、加载器及启动钩子；实际config有界私有副本解析、拒绝include等危险配置、只允许原白名单，命令行强制空hooks和无网络仍只是第二道边界。

保持原hash-object／mktree的字节级对象写入，不checkout、不碰用户索引。新GIT201-LOCAL-1提交尾注为WALL-E-Delivery: <origin_environment_id>/<origin_data_generation>/<delivery_id>，origin取原效果准备记录，纳入原payload／摘要／planned_oid。重启只读原字节，恢复历史核对按原协议版本，不重新渲染时间或尾注。

引用更新继续start→update(expected,new)→prepare→持锁复核→一次commit；prepare输入绝不预含commit。持锁后核对直接ref、真实repo／config／锁身份和全worktree集合，原交付合作窗口仍有效才可派发；[Git事务文档](https://git-scm.com/docs/git-update-ref)提供引用锁与旧值保护，不等于冻结所有外部Git操作。仓库所有者在至多300秒原窗口暂停其他Git写入，控制重启／排队到期失效；只能在确证未发时按原RESUME重新确认，未知先RECONCILE。

Linux固定命令增加明确持久性设置core.fsync=objects,reference及core.fsyncMethod=fsync，不改用户config；固定Git必须实际支持。官方[配置语义](https://git-scm.com/docs/git-config#Documentation/git-config.txt-corefsync)说明平台默认可能不强化松散对象，引用原子替换也不是数据库与Git的原子提交。目标ext4／云盘的对象、ref、目录写回及宿主异常恢复须分别验证，不能把成功ACK写成绝对掉电保证。

#### 4.21.3 外部写入与恢复边界

沿原写状态及postcheck，不新增“Linux成功”状态。提交可能派发前先将原范围、repo身份、完整expected／planned、payload摘要、许可／窗口与步骤绑定保存在control_root的Git效果依据（第7.13节），再持久原MAY_HAVE_BEEN_SENT并经停止／代次栅栏单次发送。外层与业务SQLite不是同一事务；任一可能派发事实存在就只核对，恢复旧库的PENDING／NOT_DISPATCHED不能覆盖更晚依据。

| 实际证据 | 处理 |
| --- | --- |
| 原可靠ACK，或当前ref为planned／可证后代且原对象字节一致 | 补原Git成功；当前分支／worktree冲突另记postcheck，不能覆盖外部新提交 |
| 可能已发但ref回到expected，或历史重写／对象丢失 | UNKNOWN并保留原互斥，不重复commit，不因旧值出现判断从未写入 |
| 原写确定未发但目标已变化 | 阻塞，重新预览／接收；不把旧Acceptance套新父提交 |
| 用户停止与Git已提交并发 | 如实保留已交付事实，停止资源并核对；不自动回滚或撤销分支 |
| 进程停止但.lock残留 | 明确阻塞，维护另处理；不按PID／年龄自动删锁或repair |
| 数据恢复使旧Delivery行不存在 | 以原环境／代次和外层依据保留孤立未决写入，阻断该仓库新写；不能以当前库查无ID释放 |

交付成功不等于任务完成：还需postcheck=VERIFIED、原执行完整STOP／CLEANUP及没有优先停止；报告仍适用。成果保存在服务器登记分支及固定候选包，清理任务不得删除它们或原基线保留引用。页面仅说明“已交付到服务器本地分支”；GitHub、Windows工作树或生产服务是否更新属于另一次明确操作，不作成功推断。


### 4.22 APP-ENV-RECOVERY-EVIDENCE 历史缺失、只读保全与再核验

#### 4.22.1 缺失不是零，也不是未执行

同一个恢复点可能具备完整正文，却缺少其截止之后的外发记录。按现有四项审阅逐项判断，不新增一个笼统“恢复成功”字段覆盖差异：

| 已知事实 | 必须保留的判断 | 允许的下一步 |
| --- | --- | --- |
| 旧执行或凭据是否仍可作用不明 | OLD_EXECUTION_CLOSED为UNKNOWN／BLOCKED；不能假定关掉页面或旧主机失联即停止 | 核对原执行、撤销范围和隔离事实；未证明新只读根不受影响时也不提供业务读取 |
| 原调用范围完整，但某调用最终用量／结算未知 | CALL_RANGE_COMPLETE可PASS，USAGE_RECONCILED仍UNKNOWN | 保留原调用、预留和hold，查可信原证据；不得填0、释放余额或发新请求“试一下” |
| 截止之后是否还存在调用不明，或原归属索引缺失 | CALL_RANGE_COMPLETE为UNKNOWN；已知调用金额不证明集合完整 | 保全源、补齐可信范围证据；未决总数不能显示为0或只用恢复库COUNT宣称完整 |
| 原Git／其他写入可能发生，当前结果不足以判定 | EXTERNAL_WRITES_RECONCILED为UNKNOWN；保留原仓库／资源占用 | 沿原效果和原目标核对；当前引用碰巧等于预期、重跑成功都不是旧动作未执行证明 |
| 源库／正文／引用资产不完整或不匹配 | 对应读取验证不通过，与费用缺失分开 | 只展示可见诊断；不把残缺正文当空数据、不自动创建替代资产 |
| 多个可信来源冲突或来源身份无法绑定 | 相应检查BLOCKED，保留全部来源及冲突 | 定位原身份／来源，生成新审阅；不能挑选较便宜金额或较新时间覆盖旧事实 |

缺失原因和检查结论由受信核验器产生；页面确认、管理人员备注和等待时长都不能改成PASS。恢复库里NOT_SENT只说明该快照的旧状态，不证明备份后没有发送；不能直接套当前中断恢复函数释放这类预留。原账与外层证据先按原环境／数据代次／owner／operation／调用绑定核对，新代次同号记录不能继承旧结算。

#### 4.22.2 资料可读与恢复完成分开

在第4.12节既有恢复顺序内，允许保持RECOVERY_ONLY、admission=CLOSED、outbound_hold=true提供已核验资料的只读访问。必须已经确认稳定锁、当前部署／数据绑定、Schema及读取所需资产；旧写入者不能作用于新恢复根，启动过程不派发业务恢复工作器或外部动作。读取能力须有对应当前部署的可信验证回执，不能因管理记录写着“已切换”就假定页面可用。若完整能力不满足，仍处维护，不把required_capabilities改成普通环境来通过。

复用第4.10节已分类的PURE_READ及当前身份／scope校验：需求、正文、历史和已有报告仅在各自资产验证通过时可读；浏览器可下载已经读取的核验内容及导出本机未提交草稿。不得为导出创建新业务记录、补写缓存资产、运行项目、访问Git远端或调用模型／计数；有副作用的现有GET不因方法名称而获得例外。资产缺失的区域显示具体错误，其余已核验范围仍按许可读取，不能用空态遮盖丢失。

有可靠只读回执时，维护阶段仍为BLOCKED并保留最后阶段VERIFYING和实际阻塞项，原RESTORE不写SUCCEEDED；原管理操作按已知步骤保持受理／运行，外部结果未知才按原规则记UNKNOWN，不能把BLOCKED另造为operation终态。保留维护占用，禁止普通写入、AI、检查执行、Git交付、队列恢复及普通START绕过；只读开放不清hold、不产生新许可、不自动结束恢复。不能以单纯数据可读满足原完整恢复计划。

每次读取继续核对当前scope、部署／控制版本和对应验证回执；版本变更、原根不可读、权限撤销或回执失配立即撤销相应读取资格。客户端保留本机输入，并按新观察刷新，不把上次AVAILABLE缓存当当前许可。受控只读应用不能安全启动时，只保留管理诊断与受信离线工具核验，管理入口不因故障获得正文读取权。

原环境未换代且admission仍OPEN、只是某笔费用未知时，普通人工业务沿现有能力／占用规则判断；这不是RESTORE重新开放的快捷方式。恢复新代次只能在原计划、required_capabilities、四项审阅和适用新许可条件均满足后按第4.18节及OPEN_ADMISSION开放。用户已允许首次云新建不保留旧Windows历史，不授予后续清库或通过新建同用途环境绕过未知费用的权限。

#### 4.22.3 可信补证及不能恢复的情况

现行coding_model_read等模块接受PROVIDER_BILL结算来源枚举，不等于已有供应方账单获取、归属匹配及回写能力。本版复用原LLMUse／CountingJournal、预留及结算规则；外部补证须由专用、版本固定的适配器提供并纳入原证据索引，不设计任意文件上传／金额编辑／直接改SQL入口。

适配器至少证明原供应方／账号范围、原请求标识、模型／计量项目、时间范围及其完整性、最终用量／金额／币种与结算状态，以及与原调用绑定一致。供应方没有逐请求账单或完整性依据时如实记不支持；总余额、某日合计、人工截图或按价目表估算不能替代精确原调用结算。可信原响应包含所需最终用量且满足原结算规则时可以复用，不强制所有调用都再获取账单；记录差异时不可覆盖另一份原证据。

补证本身若需访问供应方或轮换凭据，另按实际动作授权；读取／刷新审阅不得发起外部请求。适配器按原来源身份及内容摘要去重，冲突阻断，追加事实而不改旧审阅。新证据到达后原review不原地变绿，须生成新review并按版本／证据高水位重新确认；历史ACTIVATE结果也不能因新资料而重放。真正的原账补记只能通过原业务结算事务及原幂等边界，离线工具不得先把审阅改成PASS再补账。

若可信原范围、最终用量或外部写入永久无法取得，相应完整恢复可以长期受阻；仍按第4.22.2节保全可读资料，明确没有自动解除日期。这是当前单机与定期备份方案的限制，不冒充实现缺陷已被“人工确认”解决。供应方适配器和缺失区间的完整性证明仍是实际交付门槛；没有证据时本版不保证完整执行恢复时限。

#### 4.22.4 火山方舟补证能力与原请求身份

本版先对现用火山方舟北京、固定文本模型Profile评估专用适配，其他供应方／多模态／计数接口不自动获得同等能力。2026-11-16官方资料核对得到以下范围；未登录供应方账号、创建导出任务或取得真实用量证据。

| 官方能力 | 可利用范围及限制 |
| --- | --- |
| [GetInferenceRequestUsage](https://docs.volcengine.com/docs/ark/get-inference-request-usage-api?lang=zh) | 按原同步推理响应body的id与QueryHour查询，小时使用Asia/Shanghai；Records可能一请求多行。使用AK鉴权，模型API Key不能直接替代；查询结果不直接提供人民币最终账单 |
| [CreateRecordExportTask](https://docs.volcengine.com/docs/ark/create-record-export-task-api?lang=zh) | 依原时间／过滤条件创建用量导出，单次时间跨度至多3小时、起始不早于2026-05-01 UTC；账号并行至多3个、滚动24小时至多100次。导出不能无限拆分或重试 |
| [GetRecordExportTask](https://docs.volcengine.com/docs/ark/get-record-export-task-api?lang=zh) | 沿原Task.Id查Pending／Running／Succeeded／Failed；ExportCount上限10万，TotalCount大于ExportCount表示截断。下载有效期12小时；轮询采用官方建议至少5秒间隔、总观察不超过5分钟，超时只停止观察，不等于取消原任务 |
| [用量CSV字段及charge_value_list](https://docs.volcengine.com/docs/ark/usage-csv-charge-value-list-best-practice?lang=zh) | req_id关联请求，uuid标识计量行；同请求多行不按req_id直接去重。charge_value_list的value／scale是对应项目的计量数量，不是元；当前CSV覆盖正常后付费计量记录，不能据此证明失败、在途或所有其他计费状态的调用集合完整 |

现行代码存在必须纠正的接入假设：coding_model_gateway从HTTP x-request-id写入llm_uses.provider_request_id；普通model_gateway读取响应body id；coding_model_sse另校验流中body id一致并由原审计保存payload。这些字段目前不能统一视为方舟查询所需RequestID。适配时从可信原响应／流审计明确取得inference_response_id，单独保留transport_trace_id；查询响应ResponseMetadata.RequestId又只是此次查询的编号。不得改写旧provider_request_id的历史含义，不能猜测两种ID相等、用日志时间接近认领原调用或把查询编号当原推理编号。完整原审计丢失且只有HTTP头时，单请求查询路径保持不可用。

首期补证作为受信维护适配器能力，不新增前端通用账单抓取／上传入口，也不在GET审阅中自动联网。一次明确补证计划固定原环境／代次、供应方绑定、账号／地域、允许的查询集合或时间范围、适配器／格式版本、查询与导出次数及观察上限；AK以受限查询权限单独保管在受信维护侧，不进入任务、模型入口、浏览器或原始证据。若供应方实际权限粒度不能满足，记录差异并在启用前解决，不能宣称已经最小授权。真实执行需相应当前授权，本轮不执行。

补证流程沿既有原操作与证据索引，不建设第二套费用数据库：

1. 先核对原绑定和可用ID，再选单请求查询；范围补证确需导出时按明确窗口创建并先保存原意图。创建响应丢失按原创建未知处理；官方参数没有提供本方案可依赖的业务幂等键，不能自动重新创建。已知Task.Id只续查原任务，不因页面刷新另建。
2. 核验返回账号／模型／端点及原身份；导出按QueryParams确认实际查询窗口和过滤条件，Task.StartTime／EndTime是任务执行时间，不能代替业务查询范围。查询边界的包含规则与计量延迟尚需实际契约验证；必要重叠窗口按uuid去重，不推断无遗漏。
3. 下载只接受固定适配器从原成功任务取得的供应方地址，限制域名、大小、类型和跳转，不接受用户URL。临时文件处理后清理；仅保留原审计所需的核验事实、摘要和证据引用，签名链接不进入页面或普通日志。识别固定CSV版本／列及单位，未知格式停止；不猜测旧列等价。
4. 同请求多行仅在计量项目、单位及原归属均可证明时合并；不同uuid可能是不同项目，冲突不得选较小值。CSV的input_tokens已包含缓存输入，不再叠加；缺少原价格／用量维度或最终性依据时仍未决。查询Token可按原固定价格及既有结算规则核算，但仅查到数量不自动标为PROVIDER_BILL。
5. 将匹配、未匹配、冲突、截断及尚不支持的范围分别追加到第7.12节原证据；只通过原业务结算事务幂等补记。新审阅重新核对全部四项，不改旧review；没有原owner／operation绑定时不得新造调用归属。

**导出成功且未截断，也只证明该查询条件下的可导出行取得完整。** 空CSV、正常后付费总数相符或全部已知请求查到用量，都不单独满足CALL_RANGE_COMPLETE。其余计费状态、查询可见延迟／保留时限／最终性、流式调用与计数路径支持范围仍须逐项准入；不能靠等待固定天数自动PASS。供应方用量也不恢复原工具结果、项目文件或Git写入。本轮确认“存在可用的补证接口”，未确认“宿主灾难后一定能恢复全部调用和费用”；原绑定／外发范围保护仍是必需前提。

### 4.23 APP-EXEC-TOOL-RECOVER 原工具操作登记与恢复

本节落实4.15.3／4.15.6的派发与恢复；采用3.8.1的私有执行子记录，复用CommandExecution、原OPERATION_RESULT等待及RECONCILE／RESUME／TERMINATE入口。以下为新Linux适配要求，当前Windows实现未具备该完整路径。

**登记与首次派发。**

1. 在原任务控制资格下核对受信来源、原键、业务关联和规范输入。原键已存在时，同输入只查询原记录或等待同一次调用，异输入拒绝；新callID不解除同任务的未知写入。恢复记录缺失／损坏时先阻断，不能重新生成UUID覆盖。
2. 先封存有界输入及不可变绑定，再将该绑定加入受保护任务清单；未完成登记不请求原生权限、不登记命令或执行项目动作。因中断留下的未入清单文件只能核对／封闭，不能扫描到后直接补发。授权等待按4.15.6处理，不占住写入锁。
3. walle_command先按7.11.4将唯一命令ID与原调用持久关联，再提交原code_commands的PENDING记录；task／实际session／parent_operation、command_ref、配置及EXECUTION用途全部匹配，verification_item_id=null。记录尚不存在、记录不符或事务结果未知时不启动命令；没有命令的文件动作仍需自己的原意图。
4. 派发前在同一原任务闸门重核授权、对象前提、取消、维护及旧效果，固定单次派发意图；再进入文件提交或命令资源创建。意图可能已保存但动作未发生，也按MAY_HAVE_DISPATCHED核对，不重发。文件变更和项目命令互斥，命令结束须核清完整后代后才能让出写入权；原任务登记清单同时覆盖启动尚无回执的资源。
5. 先持久保存可信效果／停止事实和有界结果，再补记业务命令及安全观察，最后返回模型。DB补记失败不得重做实际动作；返回失败也不得把派发标记清零。CommandExecution.started_at／ended_at／exit_code按真实证据填写；未知不提前置FAILED／CANCELLED。命令终态不表示工作区无修改，收到取消前已可靠完成的命令保留真实完成结果。

**中断位置与恢复。**

| 中断时已保存的事实 | 允许的恢复及禁止事项 |
| --- | --- |
| 绑定尚未入完整清单 | 核对孤立文件和原登记资格；证明未进入派发后封闭该尝试。不得把找到文件当作恢复执行许可 |
| 登记／待批已保存，无派发意图且记录完整 | 重启后封闭原尝试为NOT_STARTED，旧ask／once不恢复；不替用户重新申请确认。仍在同一有效进程内的重复请求可等待原调用 |
| 命令ID或PENDING行已保存，尚无动作提交意图 | 核对原映射与完整日志，按未派发事实关闭原命令；ID不借给别的工具，不创造第二行“重试” |
| 派发意图已保存，文件／创建／启动回执缺失 | effect_state=UNKNOWN；先封闭新派发并查原资源／文件提交证据。不能据PID消失、容器名字相同、文件摘要相等或目标不存在直接宣告成功／未执行 |
| 可信文件提交或命令效果已保存，DB尚未补记 | 同代次、原输入与原关联均相符时仅补原事实；按固定ID比较已有行，禁止新建另一命令／改写终态 |
| 效果与DB事实已保存，输出返回丢失 | 返回原封存结果或结果不可读说明，不重做；效果已核清且资源已停止时，输出缺失本身不无限占用重任务槽，但仍保留诊断和审计 |
| 原控制者重启／被替换，旧回执迟到 | 旧身份无新执行权；回执只在原范围补充证据，不能转给当前同数值ID任务或重新开放模型窗口 |
| 业务恢复到旧备份、新数据代次或原任务已缺失 | 原证据保留在恢复审阅范围，不能向新代次补造旧命令／任务；先按4.16／4.22核对原外部效果，禁止用新任务绕过未决资源 |
| 清单、日志或原输入损坏／缺失 | 不认定零动作，不自动清目录重建；阻止相关执行与写入，保留可读资料及原取消／恢复诊断，进入证据恢复 |

**文件提交与证据。** CREATE必须不覆盖已有目标；REPLACE／PATCH先形成完整临时文件并核对原目标／父目录，成功落位后核实结果身份；DELETE只处理已绑定的单个普通文件。首次动作意图还包括准备创建的父目录、临时对象及其归属，不能只登记最终文件而漏掉目录副作用。取消时只清理本次已证明归属的临时对象；保留已完成修改，不回滚其他动作或删除后来形成的内容。

文件内容持久、目录项持久和控制回执持久是三个观察点。[Linux fsync](https://man7.org/linux/man-pages/man2/fsync.2.html)明确文件同步不自动保证目录项同步，[rename](https://man7.org/linux/man-pages/man2/rename.2.html)的原子替换也不使另一个回执文件成为同一事务。因此固定文件适配须覆盖每个断点并校验实际文件系统；不能用“原子保存”直接宣称崩溃恢复闭合。原提交回执可靠时补记真实效果；仅有当前文件状态而无连续归属／原提交证据时维持UNKNOWN，不伪造历史成功。第4.23.1给出有限的恢复观察候选及反例；只有固定平台包通过实际故障验收后，才可据此核清当前效果，不以人工勾选替代证据。

**重启、停止与继续。** 服务启动先恢复原控制清单并封闭旧派发资格，再核对任务全部历史会话及工具子资源；只查active_session_id或code_commands不足以覆盖文件桥及创建中资源。TERMINATE的RECONCILE_WRITES与自然交付收尾均加入该集合；当前task_runtime_stop的受限原生Job路径不能直接宣称已覆盖Linux所有工具。核对事实不调用模型、执行命令或写项目文件；需要停止活动资源时只能沿已授权的原停止／限额策略，不能把只读RECONCILE变成隐含强杀。

工具效果未明时复用OPERATION_RESULT，source_kind=OPERATION、source_id=parent_operation_id，原任务进入WAITING并阻断相关新派发。一次父操作下多个未决工具由完整清单分别核对，共用该来源等待而不漏项；原生权限、模型费用和其他等待独立保留。原操作已SUCCEEDED不自动解除此等待。核对全部工具／写入者后，记录6.7.2快照；核对动作完成与原任务可继续分开。恢复中不重开旧模型窗口、不重放原提示；明确RESUME仍须重新检查原费用、其他等待、当前授权及会话。旧会话无法安全延续时按4.23.2分别处理；原替换／修复有自己的候选与活实例前提，不能许诺所有崩溃都能原地继续。

#### 4.23.1 文件效果的有限恢复证明

首期只评估OC201-FILE-EFFECT-1，服务于固定walle_write／walle_patch的单文件动作；不是通用文件事务、项目命令回滚或自动重试系统。原回执丢失后，目标是核清“截至本次观察，原动作对应的文件状态及写入者”，不追认原系统调用返回成功。任意Shell命令的网络／多文件效果不能套用本协议。

**证明前提。** 原任务须有完整登记、不可变输入、原目标／父链身份和同一个持久写入闸门。进入准备前，全部项目命令及其后代已停止；直到效果证据和必要清理落盘前，不允许项目写入、文件读取、候选捕获、角色交接或另一个同任务文件工具进入。权限等待不持有该闸门；重启时先封闭派发，再核对原文件工作器与全部可能迟到的资源，不能仅靠文件锁自动释放判断安全。

固定文件工作器只运行受信程序，不加载项目代码；在一个已核验的同文件系统挂载内访问workspace和本任务受保护的file_effect_area。后者在workspace之外，模型不能命名或读取，项目命令沙箱不挂载它；control_root中的意图／证据也不挂载给文件工作器。两次独立bind mount即使底层设备相同也不能假定可跨挂载rename。此布局须与原受管根／权限清单一起准入，不把整台宿主或其他任务目录挂进去。

准备阶段封存新文件内容／模式，并给需保留的原普通文件、新普通文件建立仅此操作持有的硬链接锚点，固定实际对象身份、字节摘要及精确链接集合。锚点用于防止原对象被释放后复用身份，不是备份或只读副本；任何别名写入都会影响同一内容。临时多链接仅对本协议已登记对象例外，任意项目硬链接仍拒绝；原对象身份与可变元数据分开，登记操作造成的nlink／ctime变化不能误当对象替换，未登记变化仍拒绝。使用原受管所有权，不关闭protected_hardlinks等内核保护；固定工具不为此获得宿主特权，也不使用需要额外能力的按空路径link方式。Linux硬链接共享对象且不允许普通目录硬链接的依据见[link](https://man7.org/linux/man-pages/man2/link.2.html)。

第4.23节原工具派发意图仍须在文件工作器／资源创建前保存；本节另设file_commit_intent，在准备完成及原控制清单持久登记后保存，才执行下表的一次命名空间动作。两者不能混为一个提交点；工作器准备已可能发生时不能因为尚无文件提交意图就抹去原派发。准备不完整时不动目标；已登记准备材料可以按原归属封闭，但不能当作一次新的工具调用。

| 动作 | 原绑定及唯一提交 | 原回执缺失时的两种完整可判定布局 |
| --- | --- | --- |
| CREATE，父目录已存在 | 私有install为准备的新普通文件，原目标缺失；以RENAME_NOREPLACE发布到原目标 | 未应用：原目标仍缺失、install及新锚点仍为原对象。已应用：原目标为该新对象、install缺失、新锚点完整；父链及内容／模式均相符 |
| REPLACE／PATCH | 原目标为已确认旧对象；install为完整新对象，旧／新锚点均已保存；以RENAME_EXCHANGE交换install与原目标 | 未应用：原目标=旧对象且install=新对象。已应用：原目标=新对象且install=旧对象；两者及原锚点的身份、内容／模式都相符 |
| DELETE | 原目标为已确认旧普通文件，旧锚点已保存；以RENAME_NOREPLACE移至私有quarantine | 未应用：原目标=旧对象且quarantine缺失。已应用：原目标缺失且quarantine=旧对象，旧锚点及内容／模式相符；目标不存在本身不够 |
| CREATE，缺少父目录 | 在私有区完整准备“第一个缺失目录及其剩余子路径＋唯一目标文件”，固定各目录身份和叶文件锚点；从已核验的现存祖先处一次不覆盖发布该分支根 | 未应用：缺失位置仍不存在且整个准备分支完整。已应用：该位置是原分支根，全部预期后代／叶文件与清单相同且原install分支缺失；不逐层创建后再猜测哪些目录归本动作 |

“已应用／未应用”只表示本次可靠观察到的最终布局；未应用不能降回NOT_DISPATCHED或NOT_STARTED，也不授予重复原动作的资格。固定方案保留最小缺失分支的整体发布，使新建目录不变成未登记的部分副作用；目录不能创建锚点，须另核对原目录身份、完整受控分支和无外来改动事实。任一混合布局、额外链接、父链替换、材料缺失、内容／模式变化或未知写入者均保持UNKNOWN。不会把“两个对象恰有相同内容”判为同一对象；也不通过恢复旧文件、改名回来或重做删除消除矛盾。

**持久性及收尾。** 原文件和准备内容、锚点及私有目录在提交前同步；提交后同步涉及的源／目标目录，缺失目录分支按由内到外的顺序覆盖。恢复观察只能在原写入者已停止且闸门仍封闭时核验实际底层状态；必要的文件／目录同步及私有材料收尾由原受信控制流程按已登记对象执行，不能更改项目目标命名空间。只读RECONCILE只读取该流程保存的证据，不在GET或核对请求中暗中启动文件修复。原控制流程尚未完成时仍显示待核对／待收尾。

先持久保存完整恢复观察，才能按原记录逐项回收私有install／quarantine／锚点；收尾中断只核对已登记的私有名字和精确对象，不递归清理workspace或重放提交。清理前后事实分开追加，私有目录及受影响文件元数据按固定同步规则落盘；文件链接数恢复到原准入要求、工作器及相关资源确已停止后才SETTLED并释放闸门。最后一个锚点删除后的中断依赖此前已持久的观察与清理意图；该证据缺失／冲突时仍UNKNOWN，不能再次从路径猜测。异常停止可完成必要私有收尾，但不自动撤销已经确认的项目修改。

effect_basis=RECOVERED_STATE时另存APPLIED／NOT_APPLIED、观察时刻、原证据及收尾引用；dispatch_state仍为MAY_HAVE_DISPATCHED，原outcome保持UNKNOWN，不能填成SUCCEEDED／FAILED。原响应、模型工具part及业务历史不伪造成功；另追加有界恢复说明及安全观察。收到后来可核验的原回执时追加并比较，矛盾进入恢复冲突，不覆盖已存事实。该结果可满足文件效果门槛，但不自动解除原等待、回调旧工具请求或重开旧模型窗口。合法的原生工具收尾也必须受当前关闭窗口约束，不能因收到核对说明就外发下一轮模型；无法安全收尾时保持接续不可用。原生会话是否允许继续仍按4.23.2独立判断。

本候选依赖固定运行时、挂载模式、实际ext4及完整写入者控制。宿主重启后必须核验原数据卷／根归属与持久材料；设备号、inode或sandbox内数值不能跨重建直接当成相同对象，不能把sandbox合成身份与宿主身份混用。发生控制域回滚、数据卷替换、无法证明原目录连续归属时退出该证明路径，按4.22保全可读资料。任何关键前提无法实现，都保持完整文件工具未准入，不退化为只比摘要或开启宿主任意写入。

#### 4.23.2 原生轮次结束后的明确继续

“继续”沿原RESUME操作登记一条新的模型消息，不恢复旧callID，不再次发送原提示，也不把已CLOSED窗口改记HELD。原task_resume_runtime目前主要承接HELD窗口；原task_instance_driver还要求活的网关／原控制对象。以下是Linux适配的目标规则，不是现代码已经支持的恢复能力。

| 原事实 | 可执行的接续 |
| --- | --- |
| 原控制器／实例／session仍存活，旧窗口HELD | 原消息及费用已核清、旧turn确已结束、全部工具和原问题／权限处理完毕后，按原RESUME发送新消息 |
| 同一原实例／session可核验，旧窗口CLOSED且本轮接续资格有效 | 增加受限CLOSED来源分支：封存旧窗口与结束证明，形成新RESUME意图及新message_id／QUEUED窗口；旧窗口保持关闭，不能仅凭status=idle进入 |
| 只有业务后端重启，原执行实例仍在 | 按4.23.3在原执行控制进程连续存活的前提下建立新attachment，原记录不改owner；先观察和收尾，只有受支持的稳定业务来源才能明确RESUME。接管未准入时禁用继续 |
| 原OpenCode进程退出、宿主重启、原会话资料丢失或不能核实 | 不提供通用“新建会话代替原会话”的自动接续；保全已核清成果及原效果，按实际资格进入原修复或终止。首期不承诺透明恢复进度 |
| 文件效果已核清，但原生tool part／消息未结束、问题或权限未决 | 仍不可发下一消息；不能修改OpenCode数据库／伪造工具回执使其终态。原问题、权限或已授权停止流程分别收尾，再重新核验 |
| 新RESUME已经保存发送意图，但响应丢失 | 只查该原session中的精确新message_id及冻结输入；原attachment仍有效才可按原完成事务继续，跨后端重启按4.23.3保全／停止，不能打开旧窗口或以新幂等键绕过未知投递 |

旧turn结束证明须覆盖原触发消息及其关联assistant消息／工具part的终态、全部原生会话无活动及待批项已核清；原生终态仍不能替代实际工具效果／后代停止证明。原session必须属于当前允许的业务角色和控制范围，不能跨角色套用。现行session replacement属于REPAIR的固定候选恢复路径，还要求原实例可控、候选来源与已还原工作区等前提；Windows的NTFS／Job计数证明须换成实际Linux证据。不得把该路径描述成处理任何实例消失的现成办法。

RESUME受理时固定原操作、waiting_item_ids、旧窗口、当前角色、原控制及最新工具快照，保持这些等待OPEN，由这一个活动RESUME占有接续资格。重核模型许可、费用／额度、维护和其他等待后，先持久保存新的发送意图、冻结payload摘要与新message_id，再单次投递。输入仍由原上下文构造器生成，恢复摘要只包含安全事实及原结果引用，计入本次实际输入与预算；不能用模型补写恢复结论，也不能把固定“后端阶段”文本用于前端／集成角色。

只有原session中精确新消息的接收事实及原网关／attachment绑定均已核验，且原工具快照／控制代次仍相符时，才在原完成事务内同时开放新窗口、完成RESUME、转RUNNING并关闭其固定的等待集合。新等待、停止／维护抢占或来源失效须按原规则重新判断，不能顺便解除其他等待。投递前失败保持等待；投递后未知继续查询原消息，窗口不先开放、等待不先关闭。消息已收到而业务补记失败只补该事务，不再次投递。

已核清文件但无法继续的任务可以保全资料；已经业务终止的任务不会因为原轮次后来结束而转回RUNNING。资料是否可成为候选、通过检查或交付，仍沿原捕获／验证／用户确认规则，不新增“把当前目录当作成功成果”的捷径。后端／控制器／宿主三类中断的恢复能力必须分别验收并显示，不能用普通SSH重连或一次进程重启概括全部恢复。

#### 4.23.3 仅业务后端重启时的有限接管

接管是固定执行控制适配对原实例的受限重新绑定，不是业务RESUME。当前Windows的RuntimeTaskRecovery仅接受OBSERVE／STOP／RELEASE，TaskInstanceDriver._owners、控制凭据及TaskModelRoute在内存中；现有实现不能从原日志重建活网关。本节为Linux新增适配目标，不扩大Windows恢复协议。

**旧资格封闭。** 原启动时，执行控制侧就核验并连续持有原后端进程引用、原OpenCode根pidfd、启动策略及原资源集合。原后端退出或原控制资格已确认失效时，先在原动作闸门关闭新工具／新资源派发并保存fence；不能等新后端上线才处理。控制通道暂断先关闭该通道的新派发，原资格是否撤销另有持久事实；仅心跳超时／连接断开不证明原后端已经退出，也不允许另一个后端抢占；原进程还活着时新接管拒绝，沿原身份处理故障或明确停止。

首期原执行包固定控制丢失策略：关闭全部新派发；对已派发文件动作只允许完成已进入的原提交／必要私有收尾，对项目命令沿启动时明确的有界停止策略核清后代；不重发意图、不继续旧命令链。该策略须在START的固定配置中可审查，不能事后把恢复观察改成强杀许可。仍存活的受限OpenCode可暂时保留用于原消息核对；其模型入口关闭，工具桥拒绝旧资格。进程空闲不释放整个重任务名额，原限时／内存策略仍生效，接管不能重置额度或延长期限。

**接受新后端的顺序。**

1. 新后端按原启动顺序获得同环境ProcessLock，核对环境／数据代次、原运行包及完整未决集合；所有旧窗口先受持久fence限制，不能按库中OPEN恢复外发。接管仅为控制恢复，不授予新的业务动作或费用。
2. 通过受保护控制通道核验当前后端真实peer、受信程序、当前run_id／owner_epoch、单实例资格及目标原绑定。执行控制进程必须仍是原control_runtime_id，原后端pidfd须证明原进程已退出；没有原连续引用、只有PID／锁文件／服务名称则拒绝。当前单实例锁与原进程退出是两项独立条件。
3. 在原实例唯一控制闸门中重核旧资格已封闭、当前attachment未被另一个活后端占有，再将新attachment及前序撤销证据持久保存。写盘失败不交付能力；响应丢失只查同请求／同输入，不重新分配绑定。执行控制侧不写业务库。
4. 只向该实际新后端交付原OpenCode pidfd的副本及原范围所需的临时控制／内部模型凭据；原件仍由执行控制侧持有。核验新接收者及当前attachment后才能交付，不能把句柄、原凭据、socket路径或任意PID通过浏览器／JSON请求指定。凭据缺失不临时改密码／改fetch配置继续。
5. 新后端校验原执行包、实际profile／网络、工作区／依据、原生session／配置及完整工具／文件／费用记录；重建的是当前受控观察对象，不能反序列化Windows_Owner或伪造旧gateway。先追加接管观察及原等待投影：仅对原BACKEND／FRONTEND／INTEGRATION活动任务，在原版本事务中保持或转为WAITING，保留原phase；以原ModelWindow父操作为source_kind=OPERATION／source_id，复用或建立精确OPERATION_RESULT等待。已有其他等待不删除，已终止／完成任务不重新激活。数据库补记失败只补原事实，不重新接管／启动实例。
6. 新绑定就绪后仍保持模型窗口关闭。工具与原生轮次、原费用、业务等待全部核清后，只有4.23.2允许的来源才能提供明确RESUME；发送意图、新来源证明及每次工具派发都绑定当前attachment。接管期间再次失联或原控制进程退出，立即撤销本次资格并保留已发生效果。

新的应用可以自动完成上述身份核对和观察准备；不会自动发送问题答复、权限决定、初始提示或继续消息。私有收尾和停止仍各自受原策略／用户授权约束，普通GET不驱动接管。控制适配的当前绑定与业务投影中断时以真实控制记录核对并补记，不能因业务库里还写旧owner就允许旧请求重新进入。

**模型通道重新建立。** 首期不保留跨后端生命周期的模型连接／SSE／待发缓冲。新接收器使用新listener_instance_id，重建原受保护pathname的监听前须证明旧后端已退出并核对该路径的受信归属；不能按名字直接unlink仍被未知进程使用的socket。OpenCode固定fetch可保持原已核验的路径／内部route，原内部凭据也只证明原实例，不代表新窗口许可；每次请求仍校验实际根来源、当前attachment及精确新ModelWindow。旧连接、旧原消息头、旧source proof或旧SDK重试均不得被新监听接续。连接错误不会自动换路径、重新发送或借原额度再次外发。

原业务后端的模型HTTP连接即使消失，供应方仍可能已经受理；接管不能据此把调用记成未发送或归零。原LLMUse／预留／CountingJournal及用量恢复继续按原外发事实处理，费用未知与文件效果未知分别保留。执行控制适配不接管供应方密钥、不为后端代发模型，也不重放尚未交给新后端的工具响应。

**继续接管的业务范围。** 首期仅支持同一原实例／当前角色的稳定来源：原触发父操作已SUCCEEDED且原业务作用域允许接续，无旧任期的START、RESUME、REPAIR、HANDOFF_ROLE、配置应用或权限／问题投递仍在PENDING／RUNNING／UNKNOWN；原生轮次可证明结束、无待批项，原工具／外发效果已经核清。原工具核对等待可以保留给新的明确RESUME。此限制是本版设计选择，防止把大量在途业务动作一并改造成跨进程发送系统。

尤其旧RESUME的消息可能已被接收、但旧完成事务尚未完成时：接管只补存精确接收事实，不调用旧_finish打开窗口，不因新attachment存在把原等待关闭，也不生成另一个RESUME绕过未知操作。此类任务保全资料并沿原TERMINATE收尾；不能以FAILED宣称消息从未发送，不能改写已经完成的业务操作。其他未完成角色／修复／权限动作同样保留原核对与终止边界。后续若确需覆盖这些中断，须分别补全对应业务协议及验收，不隐含在本次接管之中。

如果只有连接暂断而原业务后端还活着，同owner／同epoch可以在原资格未撤销时重新认证原控制连接；一旦该资格被持久封闭，就不能借相同进程身份恢复旧派发。首期不提供跨活后端抢占、租约超时自动接管或远端节点选主。完整执行资源仍须核清后释放；接管成功、页面可读与任务能够继续是三个不同结论。

## 5. 前端协作边界

页面、不可变客户端、浏览器分区、旧记录保留及恢复详见[前端迭代0.4](WALL-E.环境分离前端迭代设计_V_2.01.md)。先完成入口配置与握手核对，再创建业务客户端、路由和恢复owner；只读状态不触发任务重发。普通环境清楚显示用途及不可用能力，并按握手access展示当前只读／可编辑权限。

持久作用域为协议、origin、环境与数据代次，run_id不进入草稿或幂等键。正常重启保留原键；数据更换阻止旧作用域写入。原请求已发而结果未知时，新的能力关闭、认证失败或新代次NOT_FOUND均不能证明旧动作未执行。前端旧存储不自动迁移或删除，具体格式及所有现有接入点以该稿第7章为准；定义完成不等于实现或验收。

## 6. HTTP与其他入口

### 6.1 BND-ENV-BINDING 公开配置与握手

#### 6.1.1 公开配置

GET /.well-known/walle-environment.json返回一个严格JSON对象，不使用业务信封：

| 字段 | 类型与校验 |
| --- | --- |
| format_version、binding_protocol | 均为整数1 |
| environment_id、data_generation | 规范小写UUID v4，来自受控环境描述 |
| display_name | 1—80个Unicode码点，非全空白，无控制字符；只作显示，不是环境身份 |
| purpose | 第3.2节枚举；P1仍只准入DEVELOPMENT／INTEGRATION |
| public_origin | 与window.location.origin精确相等的规范HTTPS origin；规则见第6.3节 |
| api_base | 固定/api/v1，不允许绝对URL、其他前缀或URL参数改写 |
| configuration_sha256 | 当前应生效的私有环境描述文件摘要；与后端实际运行配置核对 |
| management_url | null或受控登记的HTTPS管理页面绝对URL；不得含userinfo／查询／片段。P1没有管理服务时为null，不给出失效按钮 |

公开配置由受信准备入口从环境描述及已登记站点配置生成，单独保存；display_name、public_origin和management_url由站点登记提供，不从业务响应推导。不包含密钥、宿主目录或任意程序。目标摘要为私有描述的摘要，公开配置自身不参与该摘要，避免循环。入口控制方拥有文件，普通前端构建／热更新不覆盖它。客户端拒绝未知字段、重复JSON键、无效UTF-8和大于16KiB的响应；应用实现用统一严格解析，不用JSON.parse默默接受重复键。

公开配置在认证后按明确路由读取；不从业务库当前值反射生成，也不让错误API自报的环境成为预期身份。配置来自入口、实际绑定来自应用，二者相同才接入；该交叉核对防误配，不声称能防已经控制入口与应用的宿主管理员。

配置响应为application/json、Cache-Control: no-store，无跳转。index.html采用no-store保证重开取得当前入口；带内容摘要的固定资源可缓存，但不能包含环境或秘密。配置变更与业务实例切换存在短暂不一致时客户端阻止接入，不能选择其中一个作为默认。

#### 6.1.2 后端握手

GET /api/v1/environment使用既有success／data／error／meta结构。成功data仅包含environment_id、data_generation、purpose、run_id、phase、observed_at、configuration_sha256、binding_protocol（整数1）、access、第6.6节maintenance和capabilities（第3.3节全部六项，按表中顺序，无重复）。access为当前已认证身份按固定策略得出的{client_kind, permission}，枚举见第6.3节，不返回密码或原生用户信息；它是本次请求的访问投影，不是环境的全局权限。每个能力项为code、state、reason_code；observed_at为实际核对时间，不能每次响应重写成“刚刚正常”。

握手执行认证及第6.3节来源检查，携带X-WALL-E-Client；它不要求三个业务绑定头，供客户端取得实际值与预期比较。只读当前已核对内存状态及认证上下文，不初始化、恢复、建目录或访问供应方；进程启动失败无HTTP时仍使用第6.4节诊断，不伪造握手。

握手和配置均no-store。两者的环境、代次、用途、协议和配置摘要必须匹配；phase=READY且要求能力就绪后，仍按第6.6节maintenance准入开放；维护期间仅允许已登记纯读取／原收尾，不能只凭READY开放写入。run_id只说明本次运行，不用于数据或草稿身份。前端兼容协议由产物明确声明，不能接受任何返回数字。

#### 6.1.3 业务请求与响应

所有业务请求携带唯一的X-WALL-E-Environment-ID、X-WALL-E-Data-Generation和X-WALL-E-Binding-Protocol（值1），以及第6.3节客户端形态头。重复头、非法值、缺失、协议不兼容或不匹配，在调用业务函数／读取正文前拒绝；原URL、请求体和Idempotency-Key保持。

业务响应回传X-WALL-E-Environment-ID、X-WALL-E-Data-Generation及X-WALL-E-Run-ID；均为实际处理实例身份，不回显未经校验的请求值。前端先核对原请求作用域再解码业务数据，正常重启只改变run_id，不改变幂等作用域。

若收到严格匹配第6.2节的环境／代次／协议不匹配错误，data=null，即使实际身份头不同也可呈现“连接目标不一致”的安全拒绝原因；不能读取该环境正文、自动绑定它或把旧命令记作确定未执行。除此以外，身份头缺失／不匹配的成功或业务错误均不能作为可信业务结果，写请求保留未知。

同一代次不同run_id的正常响应不是串库；前端按原请求及页面生命周期核对，触发一次合并的状态重新核对，不清草稿、不重发请求。前端详设见[环境分离前端迭代设计](WALL-E.环境分离前端迭代设计_V_2.01.md)。

### 6.2 共同错误及判定顺序

继续使用现有错误信封。下列公共错误在文档／Coding／Testing两类严格解码之前统一识别，details固定为null，不把新错误默认为INTERNAL_ERROR。请求ID仍为每次交换新生成的UUID。

| HTTP／code | 固定文案 | 含义 |
| --- | --- | --- |
| 403 ENVIRONMENT_ACCESS_DENIED | 当前访问身份无权执行此操作 | 已认证身份不匹配策略或权限不足，不替代业务权限 |
| 403 REQUEST_SOURCE_REJECTED | 请求来源不符合当前环境要求 | 客户端类型、浏览器来源或必需来源头不符合第6.3节 |
| 400 ENVIRONMENT_BINDING_INVALID | 环境绑定信息缺失或不合法 | 当前交换未进入业务函数 |
| 409 ENVIRONMENT_MISMATCH | 当前入口与请求所属环境不一致 | 未在错误环境执行；不能将旧请求转送至新环境 |
| 409 DATA_GENERATION_MISMATCH | 数据已更换，请先核对原操作和草稿 | 当前交换未执行；旧代次结果仍可能未知 |
| 409 BINDING_PROTOCOL_MISMATCH | 客户端与服务的环境协议不兼容 | 升级匹配客户端，不默认忽略 |
| 403 ENVIRONMENT_CAPABILITY_DISABLED | 此环境未启用该操作所需能力 | 配置关闭，不是任务失败或调用额度自动清零 |
| 503 ENVIRONMENT_CAPABILITY_UNAVAILABLE | 此环境所需能力尚未就绪 | 未派发新意图；查看能力状态取得具体原因 |
| 503 ENVIRONMENT_NOT_READY | 环境尚未就绪，请稍后查看状态 | 启动或收尾中，当前请求未受理 |

认证／可信入口与来源检查 → 绑定格式／协议／身份 → 生命周期与动作分类 → 原请求身份及幂等核对 → 新动作能力／业务权限与版本检查 → 实际事务／派发。原操作只在原作用域查；恢复查询也不能绕过身份及权限。

入口Basic认证失败使用标准401及WWW-Authenticate，可能没有业务JSON或环境头；前端只将其作为认证状态，不能套入业务拒绝回执。后端上述错误沿用现有严格信封，认证策略及来源错误也不返回来路秘密。

只有可信后端明确给出的拒绝可以判定本次交换未执行。网络断开、代理非JSON页、超时、客户端解码失败、提交未知仍按原未知结果处理；即使当前拒绝明确，也不推断同键此前的交换没有执行。

### 6.3 BND-ENV-ACCESS 单人入口、认证与来源保护

#### 6.3.1 地址和接入拓扑

首批采用每环境一个独立HTTPS来源，P1本地格式为`https://e-<environment_id>.walle-dev.test:9443`。这是部署命名规则，不是已经存在的域名／证书。Windows将本轮明确登记的主机名解析到127.0.0.1，经SSH将Windows回环9443转发至Linux回环9443；TLS、Host及SNI中的登记主机名保持不变，不通过修改HTTP Host伪装目标。不直接转发后端或Vite端口。端口占用时报错，不漂移；修改外部来源视为访问配置变化。

Linux Caddy监听回环9443并按明确站点配置分流；不使用通配任意站点、动态URL上游或自动认领未知环境。开发／集成使用上述开发站点；未来管理与生产使用各自独立的站点范围及凭据，不能放在开发页面的路径下或复用父域会话。云端沿同一协议选定受控HTTPS来源，实际域名、网络入口及证书准备在部署时填写，不把本地.test地址写入交付包。

本地证书采用Caddy内部CA，Windows需显式安装并核对对应根证书，私钥只留在受保护入口配置中。证书错误时修复信任和名称，不跳过TLS验证。浏览器中的SSH转发不代替这一步；本轮只定义方案，未修改hosts、证书信任或转发。[Caddy本地HTTPS要求](https://caddyserver.com/docs/automatic-https)。

#### 6.3.2 复用认证与最小权限

复用Caddy内置Basic认证，不新增账户数据库或自制登录页。每个环境独立用户名／密码、独立realm为`walle-env:<environment_id>`；管理凭据不用于业务环境。Caddy配置只存密码哈希，浏览器原生提示承担输入。自动化工具另配本环境专用身份，不读取或复制浏览器凭据。[Caddy认证能力](https://caddyserver.com/docs/caddyfile/directives/basic_auth)。

access_policy_ref解析为受保护、按摘要固定的策略对象：

| 字段 | 精确规则 |
| --- | --- |
| format_version | 整数1 |
| environment_id | 与应用环境一致的规范UUID |
| public_origin | 登记的HTTPS origin，规范序列化、无路径／查询／片段／userinfo |
| principals | 非空数组；每项为principal_id、client_kind、permission；同策略principal_id唯一 |
| principal_id | 1—64字符，匹配[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}；与本环境实际认证用户名精确匹配 |
| client_kind | WEB或AUTOMATION |
| permission | READ_ONLY或DEVELOP；P1仅普通业务权限，不包含环境管理、付费授权或系统控制 |
| upstream_socket | 本环境runtime_root内明确Unix套接字路径；不是由HTTP提供 |

上述是P1的有限角色映射，不扩成多用户权限平台。READ_ONLY只能读取登记的无副作用结果；DEVELOP增加本批人工业务写入。环境能力、任务权限及预算检查继续独立生效；其他原路由未列入P1开放范围时均拒绝。全站页面、资源、公开配置与API都先经过认证；浏览器不能直接访问未认证的开发模块。

认证失效后由入口拒绝后续请求。Basic认证没有本项目可保证的可靠“退出当前账号”按钮；关闭标签不算凭据撤销，使用凭据轮换撤销旧访问。未保存输入仍保留原页面；可以另开同源入口完成原生认证后回到原页重新核对连接，不强制刷新编辑页。

#### 6.3.3 可信代理与路由

| 路径 | 唯一处理方与限制 |
| --- | --- |
| /.well-known/walle-environment.json | 入口侧固定公开配置；从受保护配置根读取，与前端构建目录和业务API独立 |
| /api/* | 直接代理到本环境后端Unix套接字，不经Vite二次代理；未知API返回API错误，不回退index.html |
| 开发页面／模块 | 仅DEVELOPMENT／INTEGRATION可路由到本任务Vite；其他用途服务已固定构建产物 |
| /__walle_hmr | 仅开发入口转发对应Vite WebSocket；认证与Origin核对在升级前完成，生产不注册 |
| 其他 | 只按既有页面／静态资源路由处理，不提供通用文件读取、目录列表或任意上游代理 |

Linux后端用一个Uvicorn进程监听已登记Unix套接字，父目录不可由任务写入；连接权限仅授予该环境后端和受信入口，其他环境／任务不能连接。套接字身份及旧进程归属在创建／清理前核对，不按路径盲删。独立测试使用明确私有测试通道，不为测试给正常应用增加公开TCP旁路。[Caddy Unix上游与头部处理](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)、[Uvicorn官方套接字配置](https://raw.githubusercontent.com/encode/uvicorn/master/docs/settings.md)。

Caddy在认证成功后删除来路Authorization、Proxy-Authorization、Cookie、Forwarded及全部X-WALL-E-Auth-*头，再生成唯一X-WALL-E-Auth-Principal，其值为本入口实际认证用户名；后端从固定策略解析身份类型和权限，不能相信来路自报角色。业务绑定的X-WALL-E-Environment-ID等原请求头必须保留原值和重复性检查，不替换成后端身份来掩盖误连。重复或被合并为多值的绑定头均非法。

后端只在受保护通道接收该身份头；拒绝缺失、重复或策略未登记的身份。不以任意X-Forwarded-Host／Proto推断期望origin，public_origin来自固定策略；Uvicorn不配置“信任所有代理”。完整环境需要不同宿主身份保证套接字权限；普通同UID开发不冒充恶意进程隔离。

API响应的身份头由后端生成，入口不能覆盖。入口不记录密码、原Authorization或正文；只记录必要请求关联及状态。固定单上游、不启用代理自动重试、缓存或写请求重定向；超时／502等不能改成业务未执行或成功。Caddy配置验证和实际重复派发测试是接入条件。

#### 6.3.4 来源与CSRF保护

所有/api/*请求必须携带唯一X-WALL-E-Client；它是请求形态标识，不是秘密或授权凭据。浏览器为web-v1，自动化为automation-v1，必须匹配已认证principal的client_kind，不能由一个请求头将WEB身份变成AUTOMATION。

| 请求类型 | 放行条件 |
| --- | --- |
| WEB握手及业务GET | X-WALL-E-Client=web-v1；Sec-Fetch-Site必须为same-origin；Origin如有则必须与固定public_origin精确一致，null／重复／多值拒绝 |
| WEB的POST／PUT／PATCH／DELETE | 上述条件，加上必须存在且匹配的Origin；原JSON／空请求体约束不变 |
| 有副作用的GET | 同样执行WEB来源限制，另按真实动作检查能力、权限及原意图；不因方法为GET就当纯读取 |
| AUTOMATION | 专用认证身份＋automation-v1＋业务绑定；不允许Origin或Sec-Fetch-*浏览器上下文头。仍按限定环境和权限执行，不能扩大到管理或其他环境 |
| 其他形态 | API导航、跨来源／same-site请求、表单、缺少必需头或浏览器不支持所需来源元数据，均拒绝 |

不开放跨来源API CORS许可；OPTIONS不授予跨源读取或带凭据调用权。此设计采用自定义非简单请求头、严格来源／Fetch Metadata及禁止跨源授权的组合，不另建CSRF令牌或会话服务。即使攻击站点知道环境UUID，也不能因此满足浏览器来源要求；身份字段公开与鉴权无关。XSS及同源恶意脚本不由CSRF规则解决，开发代码不在生产来源执行。[MDN CSRF防护依据](https://developer.mozilla.org/en-US/docs/Web/Security/Attacks/CSRF)、[Sec-Fetch-Site语义](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Sec-Fetch-Site)。

公开配置和静态资源的顶层导航不套API的Sec-Fetch-Site=same-origin规则，否则新开页面无法加载；仍必须认证、限定Host／SNI且不提供跨源读取许可。HTML及入口配置设置Referrer-Policy: no-referrer、X-Content-Type-Options: nosniff；HTML的Content-Security-Policy至少包含frame-ancestors 'none'。HMR握手必须精确Origin；不将其路由复用于产品控制。

#### 6.3.5 开发服务和首次验证

现有frontend/vite.config.ts仅有/api代理，需改为受信入口分别路由API与Vite；移除能绕开统一绑定／来源校验的开发API旁路。Vite仅回环监听，端口固定、strictPort=true、allowedHosts列出本环境精确主机名。按锁定Vite8.3.2的server.ws配置wss、登记主机及外部clientPort=9443、path=/__walle_hmr；不将新版网络文档当作任意升级许可。仓库现有Vite类型声明已静态核对server.ws入口。

代理需支持WebSocket；连接失败时不得让浏览器成功直连未认证Vite。只有入口端口经SSH转发，配合明确来源／连接地址限制，并实际检查无直连旁路。HMR失败显示开发连接异常，不自动切换API地址或更换环境。[Vite代理、Host与WebSocket说明](https://vite.dev/config/server-options)。

首次入口验收须覆盖：未登录页面／模块不可读、错误凭据、TLS／Host不匹配、伪造身份头、直连后端拒绝、跨来源写入、同站不同来源写入、重复绑定头、HMR认证及凭据不传入Vite。完整生产仍另验固定产物、外网限制、容量及密钥管理；这里不将本地验证结果推广为云上线。

### 6.4 启动、初始化与诊断入口

扩展现有tools/python-v20.py、__main__及显式数据维护入口，参数统一解析第3.2节配置。Linux不得导入Windows SID／句柄实现后再捕获错误降级。入口适配应提取实际共用业务，平台文件只处理各自系统机制；不为未来平台预建通用插件框架。

初始化使用第4.1节结果与原CLI安全错误投影。诊断入口仅返回配置／平台准入、根检查、Schema、绑定、锁占用、恢复阻塞阶段及reason_code；不回传密钥、正文或原生异常字符串，不为诊断实例化create_app或工作器。普通启动失败时可通过此入口核对；它不自动获得停止、修复或恢复权限。

### 6.5 BND-MGT-API 独立管理入口

#### 6.5.1 入口、身份与权限

管理页使用独立固定前端产物及API，业务导航仅新标签跳转。首期本地来源约定为https://manage.walle-control.test:9444，经独立SSH转发到宿主回环入口；这仍是待实施命名，不是现有可访问地址。沿第6.3节TLS／Caddy Basic／受保护Unix套接字／来源检查，管理realm为walle-manager:<manager_id>，凭据与任何开发站点分开。禁止从开发Vite提供管理页；同源脚本有控制权限，管理产物只能由受信安装流程更新。云部署另登记自己的HTTPS来源，协议不写死.test。

认证后的GET /.well-known/walle-management.json为严格对象：format_version=1、management_protocol=1、manager_id、registry_generation、host_id、display_name、public_origin、api_base=/management/api/v1。UUID、名称、origin、JSON上限16KiB、no-store和未知字段处理沿第6.1节。该入口配置来自受保护安装登记，不从管理API返回反向自认身份；不含文件路径、账号或密钥。

GET /management/api/v1/identity沿success／data／error／meta信封，data返回同一组身份、manager_run_id、phase（RECOVERING／READY／BLOCKED）、observed_at、access及available_actions。access为principal_id、client_kind、role与可见环境集合；观察时间不因响应自动变新。握手只需认证、来源及X-WALL-E-Client，核对完成后其他API要求唯一X-WALL-E-Manager-ID、X-WALL-E-Registry-Generation、X-WALL-E-Management-Protocol=1。响应回传实际Manager-ID、Registry-Generation、Manager-Run-ID三个头。业务的Environment-ID／Data-Generation头不能替代管理绑定。

固定安装策略只登记principal_id、WEB／AUTOMATION及角色；分配关系从当前管理记录取得。WEB沿web-v1与精确Origin／same-origin检查，AUTOMATION沿专用身份automation-v1且无浏览器来源头；无跨源CORS、任意转发和写请求代理重试。角色是本管理域权限，不继承业务DEVELOP：

| 角色 | 允许范围 |
| --- | --- |
| VIEWER | 只读其获准环境／操作／脱敏观察，不能预览含私有文件详情的清理或产生控制操作 |
| DEVELOPER | 已分配普通环境的读取、START／STOP／REGISTER_DELIVERY、允许的原操作继续／取消／核对；交接撤权后无继续执行权 |
| MANAGER | 管理本宿主登记范围内的CREATE／ATTACH／HANDOFF／ARCHIVE／CLEANUP及普通启停；仍受用途、维护、版本和实际动作准入限制 |

非MANAGER不能看到无关任务的私有路径或所有人操作。交接后原请求者的原结果只读权限单独保留在该操作上；账号被整体撤销则不再可读。available_actions和各环境allowed_actions返回{action, enabled, reason_code}，只用于显示；每次请求重新鉴权，前端启用按钮不授予权限。

#### 6.5.2 路由与原请求契约

下表路径均相对/management/api/v1。ID为规范UUID，分页使用opaque cursor及limit（默认20，最大100），无任意SQL筛选。所有JSON请求严格解码且不接受额外字段；单请求上限64KiB，文本工作包单字段至多2000码点。操作输入只含登记引用及人类说明，不含密钥、完整文件内容或脚本。

| 路由 | 输入／返回及副作用 |
| --- | --- |
| GET /catalog | 已准入的仓库／固定commit、规格／能力、已安装资源、可登记候选及允许负责人；仅受信来源投影，不扫描认领 |
| GET /capacity | 总配置额度、已预留、实际余量、观察时间、等待原因；没有数据时标未知，不返回虚构0占用 |
| GET /environments | purpose、registration_state、task_id可选过滤；返回第3.4节公开摘要及next_cursor |
| GET /environments/{id} | 期望配置／实际观察、工作包、资源摘要、当前动作、限制；按权限投影路径，绝不返回秘密 |
| POST /plans | kind=HANDOFF／CLEANUP、environment_id、expected_record_version、expected_assignment_generation；HANDOFF附new_owner_principal，CLEANUP附selected_resource_ids。只读外部事实，保存计划及摘要／有效期 |
| POST /operations | Idempotency-Key=原request_key；动作联合类型按下表；202返回operation及原目标，重复已终态返回200。同键异输入409 |
| GET /operations | 按environment_id／status过滤；只返回可见范围内原操作 |
| GET /operations/by-key/{request_key} | 在固定管理作用域及权限内查询，响应丢失且尚无operation_id时使用；不产生新动作 |
| GET /operations/{id} | 原输入安全摘要、revision、状态／cancel_requested、步骤、遗留资源及可继续原因；失败不直接暴露子进程输出 |
| GET /operations/{id}/commands/{control_key} | 查询该原操作内特定控制回执；超时恢复使用，不因回执暂未查到自动产生新control_key |
| POST /operations/{id}/commands | Idempotency-Key=独立control_key；body={command: CONTINUE／CANCEL／RECONCILE, expected_revision}。登记唯一控制回执并引用原operation；返回control_receipt和原operation，不创建新的业务动作意图 |

CONTINUE只对原动作已知未执行部分重新准入；CANCEL登记请求并按安全边界收尾；RECONCILE仅观察核对原资源，不代替CONTINUE重发。控制回执与修改原操作状态在同一管理事务，control_key的重复／冲突规则与原键一致。控制响应丢失后按原operation_id和control_key查询特定控制回执；页面不能重复生成CONTINUE来掩盖未知。原操作及控制回执均带独立revision；同键查回执先于新expected_revision校验，避免成功响应丢失后被新版本误挡。

| action | 首次受理的精确动作参数 |
| --- | --- |
| CREATE | purpose仅DEVELOPMENT／INTEGRATION、display_name、profile_ref、repository_ref、baseline_commit、工作包goal／scope／checks／owner_principal；task_id与environment_id首次受理生成；无客户端自定路径／端口 |
| ATTACH | candidate_ref、expected_candidate_sha256；若为原归档环境再登记，须附原environment_id及expected_record_version；与其他活动登记碰撞拒绝 |
| START／STOP／ARCHIVE | environment_id、expected_record_version、expected_assignment_generation；START附expected_configuration_sha256；STOP附target={kind:RUN, run_id}或{kind:START_OPERATION, operation_id}，二选一；ARCHIVE不删除资源 |
| REGISTER_DELIVERY | environment_id、两个expected版本、commit、resource_refs、check_refs、manual_notes、not_covered；集成附source_environment_ids／source_commits，均按已登记范围读取 |
| HANDOFF | environment_id、两个expected版本、plan_id、plan_sha256、new_owner_principal、old_writer_stopped=true；目标和许可边界须与预览一致 |
| CLEANUP | environment_id、两个expected版本、plan_id、plan_sha256、selected_resource_ids、external_writers_stopped=true；选择集必须与确认计划完全一致 |

第3.5节与第4章是以上方法的事务及结果语义。配置更新、候选／生产发布和备份恢复按第6.6节扩展及实际准入开放，不能把CREATE／ATTACH当作更新入口。操作详情不得返回可一键执行的原始任意shell。

#### 6.5.3 错误与未知结果

共同错误的data=null、details=null；必要安全原因来自已授权原操作／计划，不把任意异常串进HTTP。认证401及来源403沿第6.3节。新增code如下：

| HTTP／code | 含义与页面行为 |
| --- | --- |
| 400 MANAGEMENT_INPUT_INVALID | 绑定／输入格式错误；修正输入，不发送新副作用 |
| 403 MANAGEMENT_ACCESS_DENIED | 当前身份或分配无权；保留原本地记录，不能自动换负责人 |
| 409 MANAGEMENT_SCOPE_MISMATCH | 管理ID／登记代次／协议不符；停止新写，旧原键不能去新登记库查后清除 |
| 409 MANAGEMENT_KEY_CONFLICT | 原键绑定了另一输入；不随机换键重试 |
| 409 MANAGEMENT_VERSION_CONFLICT | 环境、归属或操作版本已变化；重新读取，不自动采纳旧确认 |
| 409 MANAGEMENT_OPERATION_CONFLICT | 同目标或跨环境资源已占用；查看具体获准可见的原操作 |
| 409 MANAGEMENT_PLAN_STALE | 预览过期／前提或目标已变化；未执行剩余步骤，需重新预览 |
| 409 MANAGEMENT_RESOURCE_UNVERIFIED | 外部身份、停止、交付或许可撤销未核实；只查原结果 |
| 409 ACTION_NOT_AVAILABLE | 用途／安装能力／当前阶段未开放动作；不能强制执行 |
| 503 MANAGEMENT_NOT_READY | 登记锁、恢复或宿主观察未就绪；读取仍按可用范围提供 |
| 404 MANAGEMENT_RECORD_NOT_FOUND | 当前原作用域无可返回记录；不能据此推断先前外部执行从未发生 |

容量暂不足但输入有效为202加WAITING_CAPACITY，不伪造执行失败。迟到成功、提交未知、代理HTML／超时和绑定不符响应沿原结果待核实处理；只有可信明确拒绝说明本次交换未受理，不能据此否定同键较早交换。管理服务重启只改变manager_run_id；换登记代次则冻结旧控制上下文。

### 6.6 BND-ENV-MAINTENANCE 维护观察、控制与发布入口

#### 6.6.1 业务握手与共同拒绝

第6.1节握手增加必填maintenance对象：{contract_version:1, admission, maintenance_id, stage, control_revision, reason_code, allowed_drain_actions, recovery_read}。无维护时maintenance_id／stage／reason_code为null，admission=OPEN；普通停止或恢复阻塞时按实际持久记录返回。allowed_drain_actions是当前身份允许的原任务／动作投影，标识原owner与operation，不包含任意新任务权。recovery_read按第6.6.2节同一观察投影，业务握手仅保留当前身份获权的安全内容；没有相应读取权限沿原鉴权返回。读取握手不推进维护或业务恢复。

phase继续描述进程状态；进程phase=READY可同时处于DRAINING，这时只读就绪不等于可写。能力READY说明组件可用，maintenance决定当下能否派发；不把维护伪装成永久CONFIG_DISABLED。首次页面可在绑定与纯读取能力核验后进入维护只读态，所有新写由后端拒绝。绑定错误优先于维护错误，原scope不可达时不伪造当前维护原因。

共同增加503 ENVIRONMENT_MAINTENANCE（当前环境维护中，此次新操作未受理）和503 ENVIRONMENT_CONTROL_UNVERIFIED（环境控制状态尚未核实）；沿success／data／error／meta信封，data=null、details=null。原已提交结果在鉴权及原scope核对后可返回，不受新写限制抹除；允许收尾的原动作仍按自己的错误契约返回。新的拒绝不证明同键较早交换未执行。

本稿协议1仍处首次实现前的DRAFT：维护字段、动作及严格解码应随首版共同实现，不假定按0.4草案子集实现的客户端能兼容。已发布旧产品缺少环境协议不能默认通过；生产准入核对具体客户端／服务维护契约版本1及共同Schema摘要，不仅核对软件名称。未来已发布协议再变更必须显式升级，不能沿“草稿可改”处理。

#### 6.6.2 管理扩展复用原操作

第6.5节management协议及原键语义保持。/catalog增加已准入release／configuration／backup引用及兼容范围，不接受外部任意包URL。新增GET /environments/{id}/maintenance及GET /environments/{id}/backups，分别返回安全维护观察／可见恢复资产及分页；详情将期望／实际部署、最近开放事实、data_generation和outbound_hold分开展示。

POST /plans增加RELEASE／RECONFIGURE／BACKUP／RESTORE／ROLLBACK_CODE以及完整／生产START／STOP的计划种类，均绑定目标与当前control_revision；旧HANDOFF／CLEANUP计划不自动获得发布权。下列动作复用POST /operations、原Idempotency-Key、环境／分配版本和plan_id／plan_sha256。五类新增动作及完整／生产控制仅MANAGER可发起，能力准入仍逐项检查；开发者原普通START／STOP不因此取得发布权。

| 动作参数 | 必需内容及范围 |
| --- | --- |
| RELEASE | release_ref、configuration_ref、compatibility_ref、recovery_policy_ref；引用全部来自已登记目录，计划里列出实际摘要 |
| RECONFIGURE | configuration_ref、recovery_policy_ref；数据／用途不得暗换，应用包保持当前已核验引用 |
| BACKUP | backup_policy_ref、after_completion=RESUME_PREVIOUS／KEEP_STOPPED；策略包含资产覆盖及本机／异机要求，不由HTTP自由指定存储URL |
| RESTORE | backup_id、target_release_ref、target_configuration_ref、recovery_policy_ref、source_data_generation；新代次由首次受理固定；不得传任意源文件路径 |
| ROLLBACK_CODE | retained_release_ref、configuration_ref、compatibility_ref、repair_of_operation_id可空；不含恢复数据库选项 |
| 完整／生产START、STOP | 沿原目标参数并追加plan_id／plan_sha256；普通START不能替代维护继续，STOP不默认取消任务 |

POST /operations/{id}/commands增加REPLAN：{command:REPLAN, expected_revision, plan_id, plan_sha256}，使用独立control_key，返回原operation及控制回执；只有已核实安全阶段可将新计划追加到原操作历史。输入摘要和旧计划不覆盖，未知步骤先RECONCILE；REPLAN后的CONTINUE仍按新计划与原步骤事实准入。一般CONTINUE不隐含同意新候选或数据损失。

GET /environments/{id}/prior-command-results使用明确source_data_generation、原动作及request_key，只在相应原读取许可内返回KNOWN／UNVERIFIABLE、安全结果摘要及来源；不返回正文、不触发原业务进程，不读取新代次同名行代替。索引不完备时不编造不存在。管理登记换代后的自身原结果通过离线归档核对入口读取，不给新代次普通控制API提供重放开关。

共同增加409 RELEASE_PLAN_CHANGED、409 RELEASE_COMPATIBILITY_UNVERIFIED、409 RESTORE_NEW_WRITES_PRESENT、409 BACKUP_ASSET_UNSUPPORTED、409 MAINTENANCE_DRAIN_BLOCKED，分别表示需重新确认、兼容证据不足、不能直接回到旧快照、资产覆盖不足和原活动未收尾。采用既有错误信封／null details；具体安全阻塞项通过获权维护详情读取。流程已受理后的阻塞记在原operation中，不把后续HTTP409伪造为整次从未执行。

维护详情增加必填recovery_read投影：{status, observed_at, deployment_id, data_generation, control_revision, verification_ref, verified_scopes, blockers}。status为NOT_APPLICABLE／BLOCKED／AVAILABLE；非恢复维护时NOT_APPLICABLE且verification_ref=null、verified_scopes=[]，恢复中无可信读取回执时BLOCKED；AVAILABLE必须引用当前部署下的只读核验回执并列至少一个核验范围。AVAILABLE时身份／版本／verification_ref均非null；其余状态中未知值为null，不能编造部署标识。verified_scopes只允许DOCUMENT_CONTENT／DOCUMENT_HISTORY／EXISTING_REPORTS中实际核验的项目；业务握手进一步按当前读取权限过滤，过滤后无可读范围沿原403鉴权拒绝，不返回空范围AVAILABLE。其中DOCUMENT_CONTENT包含关联需求元数据和已核验正文，不代表全部资产完整。管理身份投影仅包含范围与状态元数据，不取得正文访问。观察不可达或过期时不能生成AVAILABLE；GET观察不启动应用或重新做恢复演练。

blockers沿第3.10节程序生成安全code／说明及可信引用；本节固定读取阻塞code为SOURCE_UNVERIFIED、BINDING_UNVERIFIED、ASSET_UNVERIFIED、EXECUTION_NOT_FENCED、OBSERVATION_UNAVAILABLE。未知费用／调用／外部写入仍使用四项review的结论分别展示，不借读取blockers混成一个错误。读取资格按第4.22节实时核对；该投影用于解释现状，不是浏览器持有的通行证。

备份列表／维护详情同时投影已登记backup_policy_ref、最新尝试及状态、本机与异机各自最新有效backup_id／cutoff_at／verified_at，以及as_of、目标RPO秒数和rpo_status=MET／MISSED／UNVERIFIED。没有可靠异机点或目标未登记为UNVERIFIED，不显示0小时丢失；MET仅当as_of减异机cutoff_at不超过已登记目标。异机verified_at较新不能抹去旧cutoff；时钟异常／观察失效为UNVERIFIED。最近失败不覆盖较早成功点；目标4小时是策略目标，只有具体演练才有实际耗时，不把目标值当SLA或实绩。策略候选见架构评审第3.4节。

#### 6.6.3 私有应用控制通道

管理至应用的控制通道是control_root内独立受保护Unix套接字，不通过公开业务API／Vite代理，不由管理浏览器直接访问。固定消息只允许ENTER_MAINTENANCE、OBSERVE_MAINTENANCE、PREPARE_STOP、VERIFY_DEPLOYMENT、OPEN_ADMISSION；调用者绑定本环境受信管理身份及原operation／maintenance_id、目标部署、expected_control_revision、plan_sha256。无任意shell／SQL／文件路径／正文参数，重复原消息返回原控制事实。

应用拥有业务锁时负责自己的闸门与control记录；应用停止后专用工具在同一锁下负责离线阶段。套接字权限不等于业务取消授权，管理只能要求维护／观察，具体取消任务仍走第4.10节。只读观察不得实例化create_app；应用不可达时由独立工具核对文件／受管进程，不擅自写“已停止”。

不使用锁TTL或浏览器心跳开放业务。OPEN_ADMISSION仅接受与当前核验回执完全匹配的原计划及部署元组，并先持久化开放事实；未知回执按原revision核对。普通开发同UID环境仍不承诺恶意进程防护，完整／生产必须使用分离宿主身份和受信安装权限。

### 6.7 BND-EXEC-LINUX 受限控制与业务投影

Linux执行控制只经受保护Unix套接字接收固定协议：peer凭据、安装锚点、已登记应用身份／环境、当前owner_epoch及原范围全部核对。普通业务代理身份不直达该通道。原动作最小集合为PREPARE、CREATE、START、OBSERVE、STOP、RELEASE及固定来源核验；另按4.23.3／7.11.6增加只作用于原实例控制绑定的ATTACH，不表示重启或业务RESUME；普通动作输入仅资源引用／原摘要／预期代次，不能传任意命令、镜像、mount、SQL或容器ID作为控制目标；7.11.10仅为已认证CREATE准备增加一次严格的内部模型秘密子消息，不接受任意环境变量，不向HTTP调用者开放。原生接口另按7.11.9的OC201-NATIVE-CONTROL-1接入原业务操作：仅固定native_method与严格输入，不接受任意HTTP目标；它不是新的业务任务或通用RPC。

每个变更先有原意图，再有ACKNOWLEDGED或UNKNOWN回执；重复同原键／同输入查询原结果，异输入冲突。OBSERVE不会触发创建／启动／原生消息，STOP在创建未完成时也先关闭原范围的启动许可；RELEASE需已有停止证据及资产保全结果。运行时适配可变化，但不得将Linux动作伪造成Windows命名管道回执。

业务继续使用原Coding／Testing任务、停止、原操作及用量API，增加只读execution_observation投影：environment_id、data_generation、control_generation、operation_id、phase、evidence_state、observed_at、stop_verified、cleanup_verified、source_admission和reason_codes。枚举与第3.8节对应，source_admission为VERIFIED／UNVERIFIED／UNAVAILABLE，描述当前来源核验能力，不等于模型窗口已开放；stop_verified／cleanup_verified为true／false／null，分别表示已证实完成、已证实未完成、尚无可靠结论，不缺省为false。字段来自受信回执，业务状态单独保留，不暴露宿主PID／路径／socket／token。无运行绑定时为null，不渲染为已停止。完整资源明细仅限受信诊断。

当前身份归属须适配authorizations.py的current_operator_sid：Linux使用可信入口验证的实际业务principal及固定授权策略，不以服务进程UID冒充操作用户，也不相信body中的actor_ref。第6.3.2节P1的DEVELOP不自动获得付费授权；业务模型使用、许可签发及恢复审阅动作按第6.8节精确定义，未定义的动作拒绝。管理MANAGER不继承此权。

原码和原错误保持，共同能力缺失沿ENVIRONMENT_CAPABILITY_UNAVAILABLE；来源未准入使用能力reason_code=RUNTIME_NOT_ADMITTED，恢复限制使用RECOVERY_REQUIRED。具体SOURCE_PROOF_UNVERIFIED、RUNTIME_STOP_UNVERIFIED、OUTBOUND_HISTORY_INCOMPLETE等诊断放reason_codes，不把它们作为新的全局phase或允许重试信号。Unix候选新增MODEL_TRANSPORT_NOT_ADMITTED（传输组合未准入）、MODEL_SOURCE_CREDENTIALS_INVALID（原请求来源无法核实）、CONTROLLER_CONFINEMENT_UNVERIFIED（控制器隔离未核实）三类安全诊断，同样只进入reason_codes；不暴露内核凭据或被拒绝的内部请求。冷启动和工具结果另使用CONTROLLER_DEPENDENCIES_UNVERIFIED（执行组件不完整或未经核验）、CONTROLLER_CONFIGURATION_MISMATCH（实际配置不符）、TOOL_RESULT_UNAVAILABLE（原工具结果不能完整读取）；仅为诊断，不另造任务终态。部署与原生控制传输按7.11.8—7.11.10映射EXECUTION_DEPLOYMENT_NOT_ADMITTED／NATIVE_CONTROL_TRANSPORT_NOT_ADMITTED，实际连接中断或端点身份失效沿NATIVE_CONTROL_UNVERIFIED；环境锁的真实竞争、归属未核实和持有资格失效按7.11.7映射ENVIRONMENT_LOCK_CONFLICT／ENVIRONMENT_LOCK_UNVERIFIED／ENVIRONMENT_LOCK_LOST，只改变安全诊断和实际准入，不增加业务终态。恢复审阅提交沿第6.8节限定入口；实际实现与验收前保持禁用，不提供绕过证据的“启用”按钮。


#### 6.7.1 原生工具权限的绑定与投影

继续使用原权限列表及POST /api/v1/code-tasks/{task_id}/permissions/{permission_id}/responses，输入仍为expected_state_version、session_id、decision=ALLOW_ONCE／DENY及原幂等键；不新增浏览器工具执行API，不接受客户端修改对象、工具输入、授权范围或native metadata。

现有task_native_issues仅识别内置permission名称，native_permission_objects／permission_granted／task_issue_reads及前端code-task-issues只接受受管workspace对象。Linux适配必须同时更新观察、真实对象核验、当前授权判断、结果投影与严格解码；仅把新工具名加入字符串映射不能放行。

新原权限的私有metadata严格为{protocol_version,operation_ref,binding_sha256}，protocol_version=OC201-TOOL-AUTH-1；patterns为单个tool-operation:<规范UUID>，always=[]。原生事件session／tool.messageID／callID、固定permission工具名和metadata须与受信控制侧已保存的原绑定完全相符，才能形成动作投影。绑定摘要核对真实保存内容，不能把传入摘要当证明；缺失／伪造／过期对象保留UNKNOWN动作或明确不可用，ALLOW_ONCE禁用。

权限列表每项新增必有tool_binding：无已核验绑定时为null；否则为{protocol_version,operation_ref,tool_name,action,input_sha256}。action仅READ／LIST／SEARCH／CREATE／REPLACE／DELETE／PATCH／EXECUTE／READ_RESULT，按4.15.6精确对应工具；tool_name为固定工具ID，原权限行tool_name仍保存原permission名称。operation_ref为受信生成的规范UUID，input_sha256为64位小写十六进制；此投影是关联说明，不是执行凭据。原requested_action继续READ／WRITE／EXECUTE／NETWORK／UNKNOWN，按该精确动作映射；首期没有通用NETWORK工具。

object_refs扩为下列严格联合，每个新绑定动作恰有一个对象；不识别时为[]且不能允许一次：

| kind | 完整字段与用途 |
| --- | --- |
| WORKSPACE_PATH | {kind,path}；本任务workspace的规范文件路径，供CREATE／REPLACE／DELETE／PATCH或文件读取 |
| READ_SCOPE_PATH | {kind,scope_ref,path}；已绑定read_roots中的路径；仅LIST／SEARCH允许path为空表示该根，其他情况为规范内容路径 |
| COMMAND_REF | {kind,command_id,definition_sha256}；原配置的完整已登记EXECUTION命令，摘要匹配实际不可变定义 |
| TOOL_RESULT_REF | {kind,result_ref,content_sha256}；7.11.2原任务的封存工具结果，不是文件地址 |

tool_binding与object_refs由原私有观察和受信工具记录投影，不新增业务表或另建权限数据库；协议／绑定／效果日志随执行控制资源保留。原code_permissions、code_waiting_items及DECIDE_PERMISSION操作仍承载待批、答复与回执，73表／301对象设计预期不因本节增加。旧未绑定记录可按原规则只读显示，不为它补造新的当前执行权。新字段属于本版未发布契约，前后端同批严格接入；旧客户端不通过握手后偷偷忽略它。

available_actions仍由服务器决定。允许一次须当前已生效范围及真实对象均可核验；超范围沿PERMISSION_NOT_GRANTED，未准入组合沿CONFIG_NOT_READY／环境能力拒绝，旧会话沿SESSION_NOT_CURRENT。原execution_observation.reason_codes可细分TOOL_SCOPE_UNVERIFIED（对象或范围未核实）、TOOL_INPUT_CHANGED（原确认内容已变化）、TOOL_EFFECT_UNKNOWN（原工具效果待核对）；不新增任务phase，不用这些码自动重试。原permission=RESOLVED只证明权限决定得到确认，不证明对应文件已写入、命令成功或独立检查通过。

#### 6.7.2 工具恢复的查询、核对与继续

继续复用原任务、操作列表／详情及POST /api/v1/code-tasks/{task_id}/reconcile，不增加浏览器命令重放或文件修复接口。GET只读已保存的控制证据及业务投影，不向原生Agent／容器发请求，不因页面轮询执行恢复动作。

原OperationView新增必有tool_recovery，作用于操作列表及详情的统一投影；不适用固定Linux工具的原操作为null。START／RESUME／REPAIR／HANDOFF_ROLE已形成该工具控制范围后须返回对象，即使记录不可用也不能用null冒充无工具：

| 字段 | 类型与规则 |
| --- | --- |
| protocol_version | 固定OC201-TOOL-RECOVERY-1 |
| parent_operation_id | 正整数，等于当前原操作id；RECONCILE的result_ref中则等于其固定输入operation_id |
| snapshot_ref、observed_at | 同为null或同为已保存观察快照的opaque引用／UTC时刻；不是实时运行保证，不是内部文件地址 |
| inventory_state | VERIFIED／UNVERIFIED；仅VERIFIED证明本次观察已覆盖该原操作全部工具登记及可能迟到的派发 |
| counts | null或{total,not_dispatched,active,settled,unknown}，均为非负安全整数，后四项相加等于total。UNVERIFIED必须为null；VERIFIED须有快照，逐工具恰归一类，不把未知数量填0 |
| resources_state | NONE／ACTIVE／STOPPED／UNKNOWN，针对快照覆盖的工具资源，不能替代整个任务的STOP／CLEANUP事实 |
| reason_codes | 去重安全诊断数组；TOOL_EFFECT_UNKNOWN表示效果未明，TOOL_JOURNAL_UNAVAILABLE表示原记录不完整／不可核验，TOOL_RESULT_UNAVAILABLE表示输出不可读，TOOL_EFFECT_OBSERVED表示至少一项文件效果依据可信恢复观察而非原回执核清；不作新全局状态 |

summary由同一个受信清单及效果版本形成，不能拼接不同观察时点的计数。counts=0只有完整清单证明确无调用时成立；active来自原资源观察，输出成功文字不增加settled。旧可信快照可作历史显示，但不能用于当前继续准入；服务端动作资格必须再比较当前清单、控制代次、授权和快照覆盖范围。日志／安全摘要仍走原records API，无权的宿主路径／PID／凭据不进入投影。

**核对入口。** 请求体仍是{expected_state_version,operation_id}及原幂等键，operation_id是原业务父操作，不能填写tool_operation_id或猜测命令ID。受理时核对原任务WAITING、该原父操作的OPEN OPERATION_RESULT及受信工具范围；固定本次观察集合，保持一个原RECONCILE操作及QUERY／COMPARE／RECORD三步骤。原父操作可以已经SUCCEEDED，不能只从active_operations中的UNKNOWN行查找。原有角色／修复／交付分支保留各自判据，同一来源同时有原消息和工具未知时必须一起覆盖，不以新增分支遮蔽原消息问题。

已完成控制接管但原任务仍需明确继续时，也使用同一原父操作及OPEN等待核对当前attachment、原生轮次和工具清单；完整零工具可返回counts=0，但不能省略控制／外发核验。运行记录不能核验时保持原诊断，不以接管回执代替工具恢复快照。

工具核对结果采用严格result_ref变体{operation_id,original_status,tool_recovery}，其中tool_recovery为此次不可变观察；原变体仍为{operation_id,original_status}，不得容忍任意额外字段。工具变体的original_status沿原业务状态完整枚举，但该值不是工具结论；三个步骤在本次观察完成时保存同一结果。RECONCILE.SUCCEEDED仅表示此次核对已完成，tool_recovery仍可能UNVERIFIED或unknown>0。存储事务／观察无法可靠完成时保留原请求恢复，不制造一份“全零成功”快照。

**继续与终止。** 核对不自动关闭OPERATION_RESULT或开启模型窗口。全部相关工具效果已核清、无活动／未知资源且原原生投递也已核清时，服务器才可按现有规则提供RESUME；该动作仍提交原operation_id、waiting_item_ids、任务版本及新业务动作幂等键。受理事务重核快照、清单、其他等待及费用条件，固定原等待集合并保持OPEN；只有按4.23.2核实新消息接收及原绑定后，才在完成事务中关闭这些等待。投递或完成事务未知时保持原请求可恢复，不提前消费等待，不重发消息。原task_resume的model_waits_cleared仅处理预算／模型等待，必须增加精确工具等待分支，不能泛化为“所有OPERATION_RESULT都可继续”。

接续资格按4.23.2逐项核验；原execution_observation.reason_codes增加NATIVE_TURN_UNSETTLED（原轮次尚未核清）、NATIVE_CONTROL_UNVERIFIED（原实例控制／网关尚未核实）、NATIVE_CONTINUATION_UNAVAILABLE（原会话无法按本版规则接续）。这些是安全诊断，不新增任务状态或独立接续API。接管另外映射NATIVE_CONTROL_REATTACHED（已建立原实例的新观察绑定，任务仍需核对）、NATIVE_CONTROL_OWNER_ACTIVE（原后端尚活，不能抢占）、NATIVE_CONTROL_RUNTIME_CHANGED（执行控制进程已更换，连续能力不可沿用）；仅反映已保存的当前观察，不在GET中重新接管。若旧会话不能安全延续，RESUME禁用并明确原因，原修复／终止入口仍分别核对实际资格；恢复观察不自动使原ask／once有效。TERMINATE沿原唯一终止请求核对整个任务集合；停止已受理时不另发RECONCILE争夺所有权，由原停止过程补齐观察。维护与新数据代次恢复仍遵守4.10／4.16／4.22，不因本接口是“核对”而绕过环境资格。前端只用available_actions的实际资格，不从settled计数自行启用按钮。

接入需同时覆盖task_operation_reads及各严格操作投影、task_role_reconciliation、task_read_api、coding_model_wait、task_resume、task_runtime_stop和前端操作解码／恢复控件；现有接口名字可复用，不代表这些分支已实现。73表／301对象的设计预期不因本节改变，实际协议资源与代码仍待实施。

### 6.8 BND-ENV-MODEL-AUTH 业务许可与恢复入口

本接口属于已认证的**业务origin**，不在环境管理origin提供代理签发。P2采用access-policy.v2：沿第6.3.2节字段，每个principal增加model_actions无重复数组，值仅MODEL_USE／MODEL_AUTHORIZE／MODEL_RECOVERY_REVIEW；v1没有此字段，默认空。新增权限不从DEVELOP、MANAGER、Linux UID或Windows SID自动映射。READ_ONLY不得配置模型动作；AUTOMATION只可显式取得MODEL_USE，不能配置签发／恢复审阅。WEB可以按固定策略获得三项；这不是新增多用户账户系统。

MODEL_USE允许提交会产生模型外发的原业务操作，仍须环境能力和原任务范围；MODEL_AUTHORIZE允许签发／撤销许可及原Coding业务授权，仍受其原业务契约约束；MODEL_RECOVERY_REVIEW允许准备恢复审阅。ACTIVATE_AFTER_RESTORE要求后两项同时具备。后台只继承原操作固定的已验证主体与批准范围，不假设服务身份天然有权；发送前还须确认该主体未被当前策略撤销。认证代理先移除外来身份头再注入可信主体，原actor_ref改为含环境／principal／access-policy摘要的明确跨平台格式，不把用户名伪造成SID。

| 方法／路径 | 输入、权限及结果 |
| --- | --- |
| GET /api/environment/model-access | 本环境可读身份；返回当前许可状态、许可版本、允许用途的安全投影、到期时间、outbound_hold、恢复原因及当前用户allowed_actions；不含凭据、宿主路径及原始证据 |
| POST /api/environment/model-access/operations | 下列固定action；需要规范小写UUID v4 Idempotency-Key、当前环境／代次头及精确期望版本；受理202返回原operation_id与state，已存在原键返回原结果 |
| GET /api/environment/model-access/operations/{operation_id} | 仅当前环境／代次内有权查询的原命令；返回PREPARED／APPLIED／REJECTED／UNKNOWN、实际effect_ref与安全阻塞；不触发续作 |
| GET /api/environment/model-access/by-request/{request_id} | UUID原键，按当前环境／代次及可信principal查原命令；丢202时使用，不以404推断外部调用未发生 |
| GET /api/environment/model-access/reviews/{review_id} | 有MODEL_RECOVERY_REVIEW的当前主体；返回审阅四项事实、证据摘要／高水位、安全阻塞与过期时间，不读取供应方远端 |

POST公共body严格为action、expected_control_revision、expected_model_access_revision、payload；最大64KiB，未知字段／浮点版本拒绝。payload精确按action解码：

- AUTHORIZE：policy_sha256、allowed_use_refs（策略条目的完整固定引用）、expires_at；须MODEL_AUTHORIZE，当前无hold、OPEN且外发安静，产生一份许可并替换原指针。
- REVOKE：permit_id；须MODEL_AUTHORIZE，必须是期望版本指向的原许可；即使正在维护／恢复也可撤销，不顺带清hold。
- PREPARE_REVIEW：restore_operation_ref；须MODEL_RECOVERY_REVIEW且当前hold正由该RESTORE产生；只封存事实快照，返回review_id／sha256及可否确认。
- ACTIVATE_AFTER_RESTORE：review_id、review_sha256、policy_sha256、allowed_use_refs、expires_at；须两项授权资格，按第4.18节提交；不接受布尔force／skip_checks。

语法／身份／环境检查后，先核对同scope原键与规范输入：相同则返回原事实，异输入409 IDEMPOTENCY_CONFLICT；原键绑定主体，不由换用户续写。新命令再核对期望版本、当前权限、状态及前置条件。失去权限后可按只读策略查看安全原结果，不能借“同原键”继续未完成变更；重新具备资格也须在当前事实下重新核验后才续原命令。未受理的错误不消耗原键，已持久受理不能换键重建。

格式错误400 INVALID_INPUT；权限403 FORBIDDEN；环境／代次错误沿第6.2节；过期期望、策略不符、审阅变化409 PRECONDITION_FAILED；非安静替换409 ENVIRONMENT_BUSY；恢复条件不满足409 RECOVERY_REQUIRED；控制／文件无法核对503 ENVIRONMENT_CONTROL_UNAVAILABLE。这些是本入口错误，原业务路由仍沿能力拒绝；details只含reason_codes、当前安全版本和原命令引用。没有凭据／网关或来源证明时，签发许可也不会使执行能力变READY。

普通关闭且非恢复模式的应用不提供写入入口；停机工具不能借本接口伪造WEB主体。恢复模式中PREPARE_REVIEW、ACTIVATE_AFTER_RESTORE及REVOKE只更新第7.12节控制元数据，是CLOSED的明确例外；不允许AUTHORIZE或普通业务写入。所有GET无模型、计数、供应方账单或执行探测副作用。

### 6.9 BND-ENV-CHECK-DELIVERY 原业务入口与Linux投影

继续使用原VERIFY_CANDIDATE、RUN_TEST、报告查询／采用、PrepareDelivery、AcceptCode、RECONCILE、RESUME和停止接口；不新增“运行任意Linux命令”“上传检查通过”“强制交付”或“按路径删除”的公开API。原body、任务版本、幂等及错误枚举沿V2.0，统一携带本稿环境绑定；收到相同数值ID也必须确认同环境／数据代次／owner。

Snapshot公共读取保留原字段集合，content_policy_version固定为GIT201-BASELINE-1；两项origin保存在服务端原操作及Snapshot，不新增客户端可写字段。repository_snapshot_reads.py与frontend/src/api/code-snapshots.ts须同步新策略枚举，旧Windows GIT20-BASELINE-1响应不能在本版入口假装已准入；候选CONTENT20-STORE-1不变。

无模型的原检查／Git动作按DEVELOP、已生效业务授权、能力、原控制状态和实际操作范围判定，不要求为了执行测试另签模型调用许可。任何计划生成、Coding模型步骤仍必须第6.8节MODEL_USE及环境许可；管理角色不代用户接收候选或批准交付。

| 投影 | 新增安全字段及来源 |
| --- | --- |
| 原Verification详情的platform_observation | 无实际绑定时null；否则{format_version:1, environment_id, data_generation, verification_id, execution_platform_ref, target_kind, target_id, input_verified, result_channel_verified, endpoint_verified, stop_verified, cleanup_verified, observed_at, reason_codes} |
| 原Delivery详情的location_observation | 无可靠登记事实时null；否则{format_version:1, environment_id, data_generation, repository_id, location_kind:SERVER_LOCAL, repository_claim_verified, original_result_verified, observed_at, reason_codes} |

上述verified字段均为true／false／null，表示已证明符合／已证明不符／未知；CLI无端点时endpoint_verified=null并附ENDPOINT_NOT_APPLICABLE，不能默认true。target_id分别是candidate_id或snapshot_id，仍须原owner核对；execution_platform_ref为固定平台资源版本引用，无宿主路径／UID／私有端口／token。observed_at为真实证据时间，不能随GET刷新。location投影不新增Git成功枚举；git_write_status、postcheck_status、Delivery及Task状态沿原字段。投影中的environment_id／data_generation来自原证据，不因恢复改写；HTTP响应绑定头仍是当前请求的服务环境。后端可按原记录安全返回较早代次的已完成证据，必须验证其完整原关联，不将它重新认作当前运行。历史证据能否适用当前候选由原业务资格核对决定，不能只比较编号或强制把全部历史结果清空。

新诊断reason_codes用于具体说明INPUT_PROTECTION_UNVERIFIED、CHECK_DRIVER_NOT_ADMITTED、CHECK_ENDPOINT_UNVERIFIED、RESULT_CHANNEL_UNVERIFIED、REPOSITORY_CLAIM_CONFLICT、GIT_DURABILITY_UNVERIFIED、ORIGINAL_GIT_EFFECT_UNRESOLVED；不替代已有状态／HTTP错误，也不能提示客户端自动重跑。INPUT_CHANGED等原业务错误保留。平台字段未实现时严格识别为能力未就绪，不默认信任旧Windows观察。

原Check／Git控制调用扩展第6.7节固定协议的资源引用及用途，控制端完整验证binding与原操作，不接受HTTP指定任意可执行文件、Git argv、ref、mount或网络目标。CONTROL_GIT／CHECK_DRIVER均不可取得模型源身份。原始回执保存在受信目录，浏览器只读安全投影，提交报告备注不产生可信PASS。


## 7. 数据存储与实现定位

### 7.1 归属与发布

新增environment_binding单行表，字段按第3.1节；同一最终新Schema包含第7.14节CodeSnapshot原来源及保留引用约束。绑定表由新Schema发布DDL定义STRICT、主键固定1、非空及身份格式约束，程序严格校验规范UUID。首次插入与schema_migrations、code_schema_state在同一初始化事务提交。普通业务不提供更新／删除接口；未来恢复工具只有在明确维护中才能改变data_generation，且必须与外层恢复记录核对后开放。

逻辑结构因此不同于db20-r50。既有72表／299对象专项仅是复用基础，不能当作新增结构已经验证。新发布须固定新DDL、对象清单、实际构造源码与本稿来源；Schema200版本号不能单独证明兼容。原V2.0清单、SQL及正式设计字节不改写，不将本稿伪装成已合入原设计。

P1只准备全新库；原151→200升级实现保留其原范围，但不因发布新Linux资源就宣称旧库可升级。之后V2.01生产更新与恢复另有实际方案，不能用“不迁旧历史”省略。

### 7.2 数据目录及锁

#### 7.2.1 固定命名空间与准备

根目录与祖先权限、openat2定位、实际对象类型、链接数和挂载依架构6.3实施。受信宿主准备操作先登记environment_id→lock_root／control_root的唯一映射，在lock_root预建普通文件environment.lock并固定实际身份；初始化、应用及专用维护入口均使用它。锁根及祖先由安装身份控制，应用／维护身份仅有目录遍历和锁文件读写权限，执行控制身份仅有遍历与只读查询权限，内部Agent无访问权限；ACL、补充组及可写别名一并核验。锁文件不能属于可自行chmod的应用身份；锁根不能经可改名祖先被整体移走。权限针对实际对象验证，不把固定chmod数字当充分条件。

control_root仍允许获权写入者原子更新控制数据，不能因此同时让它替换锁对象。本稿将锁的物理位置固定为独立lock_root/environment.lock，替代同目录保存控制数据和锁的早期安排；不提供两处锁的兼容查找。锁内容不是授权记录，无需写PID、口令或心跳。普通启动不带O_CREAT、不mkdir、不truncate，也不删除“陈旧锁”。缺失、符号链接、多硬链接、身份／归属改变一律停止准入；更换数据路径、恢复业务代次或发布新程序仍竞争同一锁。

锁根是宿主安装状态，不属于业务备份。新宿主须经受信准备生成新的宿主绑定和锁对象，再恢复业务；旧宿主仍可写时不得用同一环境身份同时启用新宿主。普通重启不重建锁，不根据备份中的inode重建授权；新宿主恢复也不支持旧实例直接ATTACH。

数据库活动期间不使用通用文件Guard额外打开／关闭主库，不哈希活动DB、不改名、不替换；内容核对使用既有SQLite连接，备份走Backup API。目录保护覆盖主库、WAL、SHM及锁；对象／根身份变化时停止新派发并保留核对状态。环境锁与SQLite事务锁各有职责，不能互相代替。

#### 7.2.2 OC201-ENV-LOCK-1 Linux持有协议

首批本地ext4候选统一采用进程关联的POSIX记录锁：F_SETLK、F_WRLCK、SEEK_SET、start=0、len=0，非阻塞取得整文件及将来增长区间。安装绑定固定protocol_version=OC201-ENV-LOCK-1；全部初始化、应用、恢复和维护入口必须遵守同一协议。原process_lock.py的Linux flock分支是待替换位置，不保留双锁回退；Windows实现保持原范围。未声明或不同锁协议的包不能访问本环境数据。

选择进程锁是为了由独立执行控制进程查询实际持有者；不是将锁当强制权限系统。F_GETLK可返回冲突记录锁的持有PID，但只是瞬时观察；同进程关闭该文件的任意描述符会释放其全部记录锁，fork不继承、exec有另外的继承语义。[记录锁定义](https://man7.org/linux/man-pages/man2/fcntl_locking.2.html)。flock与本地Linux记录锁不互斥，且其共享打开对象可被dup／fork延长持有，不能用F_GETLK查询或用传递锁FD证明应用本人持有。[flock定义](https://man7.org/linux/man-pages/man2/flock.2.html)。

实现约束固定如下：

- 每个应用进程只允许ProcessLock拥有一个本环境锁描述符，使用非继承／CLOEXEC打开；不dup、不通过SCM_RIGHTS传递、不让日志／通用文件Guard再次打开关闭它，不fork继承业务写入者或用exec替换已准入后端。必要元数据检查使用原fd的fstat及受保护根定位。线程内单例和释放同步复用原所有权机制。
- assert_owned仍可检查本地生命周期，但不能独自作为外部持锁证明；调用F_SETLK“确认”会重新加锁，禁止用于掩盖已经失锁。F_GETLK由另一个已准入控制进程以自己的只读fd查询同一固定对象，不能由持有进程查询自己再宣称没有冲突就是有效。
- 查询固定整文件写锁，要求返回F_WRLCK及完整范围，l_pid是当前已认证后端在查询方PID命名空间中的实际线程组。F_UNLCK、局部锁、读锁、l_pid=-1的OFD锁、其他PID／命名空间均不能成为该后端的所有权证明。锁文件自报PID、文件存在和一次抢锁失败都不算证明。
- struct flock、off_t、pid_t和选项常量使用固定目标平台头文件构建的小型绑定；禁止把某台ARM的字节布局复制成x86通用struct.pack字符串。该绑定进入运行包摘要和实际ABI验证，不新增锁服务。控制端的只读查询不获取第二把锁，也不承接原锁的生命周期。
- 只有F_SETLK阶段的真实冲突映射“环境已有占用”。打开文件被拒、ENOLCK、EIO、ABI／能力不支持及异常结果分别保留为不可用原因，不能像当前acquire那样把所有OSError都归为ProcessAlreadyRunning。失败不打开业务库、不启动后台任务，也不自动重试或改权限。
- 正常释放顺序为关闭新准入、退休既有执行／数据库租约、确认原写线程与连接收尾、撤销控制资格，最后解锁并关闭fd。execution_lease.py只负责进程内事务与退休顺序，不能替代内核锁或跨进程证明。释放失败保留故障事实；非预期失锁／身份改变永久封闭本owner_epoch，不在本进程重新加锁后继续原业务。

P1普通业务需要此互斥及退出顺序，但不为P1单独启动执行控制服务。完整执行在ATTACH及每次受限控制动作准入／实际派发前，联合7.11.7查询持有者、当前活后端及原控制资格；不能把一个历史查询结果缓存为永久许可。锁查询、控制记录和业务提交之间没有内核级联合事务，正确性还依赖已准入程序的单一fd和退出约束，不能宣称防御已攻陷的受信后端。完整执行中发现锁丢失时，即使另一后端已拿锁，只要原后端仍活也不能接管原实例；继续按原终止／保全路径核对。检查不到异常不代表内核为应用提供持续失锁通知，因此单一fd规则和退出顺序必须先通过源码调用点核查及故障验证；检查线程的周期探测不能替代这些约束。

以上为待准入选择；若固定程序不能避免额外close、不能在实际部署命名空间对照持有者或无法证明退出顺序，停止该候选的准入，不引入调试权限、自动清锁或双协议来掩盖失败。

### 7.3 首批修改位置

| 现有位置 | 复用／修改职责 |
| --- | --- |
| infrastructure/sqlite_runtime.py；tools/python-v20.py | 平台运行包激活和实际加载核验，保留require_active |
| schema_v20_release.py、schema_v20_state.py及发布工具 | 平台清单绑定、新环境元数据、显式初始化与重开验证；生成新资源，不覆盖旧发布 |
| infrastructure/database.py、process_lock.py、execution_lease.py | 受保护路径输入、稳定锁、连接生命周期及旧线程退休；不复制事务引擎 |
| schema_v20_cli.py、schema_v20_upgrade.py | 将共用初始化／核对与Windows文件机制分开，Linux不直接复用LocalPathGuard文件句柄 |
| __main__.py、service.py、code_tasks/local_deployment.py | 启动配置、平台装配、最终开放顺序与部分失败收尾 |
| guide/worker.py、guide/orchestrator.py、testing/planning_worker.py | 保留数据库恢复；补齐能力准入，关闭时不启动新派发 |
| shared/http_boundary.py、http_errors.py及代码错误投影 | 可信代理身份／权限、来源、环境绑定与共同错误，不使原请求恢复丢失 |
| 前端公开配置与受信Caddy部署输入 | 每环境独立HTTPS、认证、固定路由、头部清洗及Vite HMR；不写入业务库或前端构建产物 |
| documents、requirements、revisions及现有仓储 | 复用原业务；只接入共同上下文，不另建Linux业务实现 |

上述是待修改位置，不是已完成映射。新文件的具体拆分可由实施者决定；新增源文件必须进入相关发布源码清单，不能因旧清单未列到就漏掉完整性保护。

#### 7.3.1 普通业务装配的最小依赖与最终开放

本节落实4.2—4.5的普通能力边界，不新增“轻量版WALL-E”、另一套数据库或第二个业务工作器。A／B／C及P2是交付批次，不是客户端可选择的运行模式；真正允许的行为仍由3.2的明确能力配置、当前持久准入和原业务权限决定。

**先处理导入和构造边界。** 当前__main__.main在调用create_app前进入Windows local_deployment；service.py在模块级导入RegistrationInstallation／RepositoryRegistrationWorker，生命周期中调用production_options，随后默认创建Testing计划与停止循环。GuideWorker.start又会在后续恢复完成前设置accepting并启动monitor。这些是源码中已有的装配关系，不是Linux已运行的结果。production_options当前仅构造TokenizationGateway，函数明确不在构造时读凭据／联网；本稿不得将“构造了依赖”误报成“已经发出付费调用”。

| 调用位置 | 普通业务必须保留 | 必须按能力分开的部分 |
| --- | --- | --- |
| __main__／私有启动入口 | 固定解释器／SQLite准入、受信描述、原启动身份、应用根及最终关闭 | 先由已核验平台与能力选定实际装配；不先导入Windows部署再捕获错误，不为P1要求SID、Guard或完整RegistrationInstallation |
| service.create_app | 同一个应用工厂、原文档路由、Database／ResourceCatalog／HttpRuntime及幂等契约 | 路由声明／严格解码与Windows原生构造分开；未启用能力仍有规定的拒绝行为，不用卸载整个路由或返回404掩盖关闭 |
| GuideWorker | 原唯一ProcessLock、原Idempotency、纯数据库恢复、HTTP租约与关闭责任 | started与accepting分开；P1不启动AI派发／模型监测循环，不给dispatch／after_commit绕过配置的入口 |
| Testing／Coding恢复 | 复用recover_drafts、recover_workspace_starts等实际规则中适用的数据库部分及原未知语义 | 纯恢复函数不能因同模块的执行类导入而强制装配Windows／Docker／OpenCode；需要活控制证明的分支保持BLOCKED，不伪造已停止 |
| 原生运行和模型装配 | 启用相应能力时才实例化已准入的真实实现 | P1不构造production_options、模型／计数传输、注册工作器、原生监听或执行队列；不读取供应方配置或尝试安装缺失依赖 |

选择发生在可信组合入口，业务函数不得到处检查平台名称或环境变量；不增加插件注册框架。可复用的类型、纯解码／恢复规则从实际平台构造中分离；平台实现仅在对应能力经过准入后导入和实例化。固定Schema sources继续校验登记的Windows源文件字节，“不执行”不能变成“删除来源保护”。完整CodeTask／Testing表、命令身份和原约束仍进入P1最终Schema，缺执行器不影响生成这些纯数据结构，也不表示相关动作被开放。

不通过测试替身worker_factory、worker=None、静默吞异常或固定成功结果运行真实P1。HttpRuntime.commands及handle_http提交后的worker一致性要求保留；普通人工提交仍走原回执和投影，after_commit只处理已获准的真实后续动作。能力拒绝覆盖路由、应用命令、提交后派发及传输边界；即使数据库误出现待派发项，也不能由后台扫描触发外发。

**最终接单只由统一启动完成点开放。** 私有配置先验证required_capabilities是enabled_capabilities的子集；P1两者仅包含DOCUMENT_READ／DOCUMENT_WRITE且均为必需。错误配置在业务库打开前拒绝，不用“可选能力不可用”掩盖声明矛盾。锁内先检查是否存在需要外部控制证明的未决事实，再执行适用的纯数据库恢复；不能先用恢复函数改写未知事实，再据状态已变化判普通模式安全。

GuideWorker取得锁后可以成为已启动owner，但保持accepting=false；先完成所有本批恢复、能力装配、HttpRuntime及租约绑定，再由同一最终完成点检查原启动许可、control revision、宿主hold和要求能力，最后开放业务。普通模块不得自行把accepting改回true；完整能力失败时按required集合决定阻断，不自动降级为普通模式。原只读诊断不依赖create_app构造成功，也不为“探测可用”启动工作器。

每项资源取得后立即登记到唯一清理责任，再进行下一项可能失败的操作；不能将清理try/finally放在worker.start之后而遗漏这段窗口。故障覆盖取得锁后、创建HTTP租约前后、恢复中、装配中及最终开放前后；按4.5先封闭接单／派发、退休租约、等实际本地工作结束，再关闭连接和释放锁／根保护。已提交内容与原未知回执保留，未完成清理不得允许新实例接管。此处是现有生命周期的修订要求，未修改源码。

**没有管理服务时仍走同一控制契约。** A单元的离线准备入口复用3.6的LOCAL_TOOL及原control文件／初始化意图；先建立受信安装归属、宿主hold的明确状态、稳定锁根、分离控制根及CLOSED／NORMAL_STOP记录，再显式初始化。没有管理服务不等于缺失control可以视为OPEN，也不要求先建设管理数据库和页面。

本地工具在锁内封存原START依据后释放锁，应用随后取得同一锁；原私有启动调用绑定control中的operation_source／operation_id、预期control_revision及完整部署元组，不能只读取“当前为CLOSED”就自授开放权。不让工具持锁等待应用ready，也不通过继承锁FD实现交接。当前应用owner在恢复完成、原启动依据仍有效且未被STOP／维护／后续操作替代后，沿同一控制函数写OPEN并发布就绪。未知START只观察原run／回执，不另起进程；缺记录、旧控制revision或结果不明不生成新许可。后续M接入使用同一函数与MANAGER身份，不能复制第二套初始化／启停规则。

### 7.4 PKG-ENV-RUNTIME 平台运行包格式与启动准入

#### 7.4.1 清单关系与序列化

运行包、数据库结构和应用代码分开标识：运行包负责解释器／SQLite／依赖，Schema发布负责实际DDL与对象契约，program_source负责实际应用输入。三者按摘要关联，不能用一个“版本2.01”代替。首批只交付Linux ARM64普通业务包；x86_64使用同格式另产出、另验证。

以下JSON资源统一使用现有canonical_bytes的UTF-8、sort_keys=true、紧凑分隔符和末尾一个LF；拒绝BOM、重复键、未知字段、浮点数／NaN／Infinity、孤立代理字符和非规范整数。整数不接受bool冒充；布尔字段明确允许bool。加载先限制单文件4MiB、核对实际字节摘要，再严格解析并校验重编码与原字节一致。此规则用于本节发布／维护资源，不追改既有业务JSON与前端快照。

Artifact统一为{path, sha256, bytes}：path是指定资源根内的精确POSIX相对路径，禁止空值、绝对路径、反斜线、NUL、空段、.、..和大小写猜测；sha256为64位小写十六进制；bytes为正安全整数。记录中明确允许空文件时bytes可为0。来源URL只作构建溯源，不成为运行期下载指令。私有安装绝对位置只出现在明确的安装字段，不能藏在Artifact.path中。

依赖关系固定为：受信安装入口固定runtime-manifest.v1.json与Schema manifest.v2.json摘要 → 运行清单固定文件索引／wheel清单 → Schema清单引用已固定运行清单。运行清单不引用Schema；文件索引不包含自身及运行清单；生成的Schema准入pin不进入它所钉住的sources。禁止自摘要循环或通过读取同目录未受信“最新pin”自我授权。

#### 7.4.2 runtime-manifest.v1.json

顶层仅有下列字段；表中对象的字段集合亦严格固定。

| 字段 | 内容 |
| --- | --- |
| format_version | 整数1 |
| runtime_id | 匹配[a-z0-9][a-z0-9-]{0,95}的发布名；名称不是信任依据 |
| platform | {os, architecture, distribution_id, distribution_version}；首批linux、aarch64、ubuntu、24.04，目标架构由安装入口核对 |
| installation_prefix | 本发布实际准入的绝对安装根；与受信安装记录一致，不由请求或PATH选择 |
| python | {implementation, version, cache_tag, soabi, executable_ref, sqlite_extension_ref, site_packages_ref}；implementation固定cpython，首批version为3.13.18；其余值从构建产物实测，三个ref均相对安装根 |
| sqlite | {version, source_id, library_ref, compile_options, required_features, required_limits}；version为3.54.1，source_id须匹配原已固定源码身份；library_ref为包内普通文件 |
| files_ref | 固定runtime-files.v1.json的Artifact |
| dependencies_ref | 固定metadata/python-wheels.v1.json的Artifact，规则见第7.5节 |
| host_libraries | 按absolute_path排序的无重复数组；每项{absolute_path, sha256, bytes, package_name, package_version}，记录该包全部原生模块依赖的宿主动态库闭包（真实目标文件路径，既核对ELF依赖也核对实际加载）；不得将私有SQLite列作可替代宿主库 |
| build_ref | 固定metadata/build-inputs.v1.json的Artifact |
| launch_flags | 精确数组["-I","-B","-S"]；不接受环境配置扩大为任意解释器选项 |

runtime-files.v1.json为{format_version:1, files:[...]}。每项{path, sha256, bytes, mode}，mode为四位八进制权限字符串，仅允许0400／0440／0444／0500／0550／0555，不含写权限及setuid／setgid；按path排序、无重复，记录包括CPython标准库、扩展、应用依赖及发布启动脚本在内的完整安装内容。不接受未登记普通文件、符号链接、多硬链接或设备对象；目录为清单路径前缀及固定元数据目录，不能夹带额外可导入目录。只有根下runtime-manifest.v1.json和runtime-files.v1.json不进入该索引，分别由外层摘要和files_ref核对；其余元数据同普通文件一样进入索引，不留未核对的清单例外。写时缓存、日志与临时文件均在安装根外。

包内入口ref必须命中文件索引；site_packages_ref必须为登记文件的目录前缀。构建时可从受信来源解引用必要安装链接并生成普通文件，但最终必须重新验证实际加载，不在运行时放宽链接保护。已打开写句柄、可写父目录和相同UID的修改能力仍按架构权限边界处理；字节清单不能代替撤销写入权。

compile_options为实际PRAGMA compile_options的完整字符串集合，去重后按字典序排序，必须与当前产物逐项一致。required_features精确为FOREIGN_KEYS、STRICT、JSON、WAL、FULL_SYNCHRONOUS五项；required_limits精确为{trigger_depth:100}，与现有约束触发器深度对齐。THREADSAFE必须非零且Python绑定的线程能力符合原使用方式；不自动抄入Windows独有扩展。功能探测在新内存库／本轮可清理临时库执行，不能使用业务库当探针。

build-inputs.v1.json为{format_version:1, sources, toolchain, configure_argv, cflags, ldflags, expected_prefix}。sources为按name排序的{name, source_url, member_path, sha256, bytes}数组，至少固定Python源码归档、SQLite源码归档及sqlite3.c；归档本身的member_path为null，解包成员使用精确归档内相对路径，摘要明确对应该成员，不能混淆下载文件与解包文件；toolchain为{name, version}数组，记录编译器、链接器、基础发行版和安装器实际版本；argv及flags为有序字符串数组，不允许启动端执行其内容。expected_prefix须等于installation_prefix。完整编译命令的引用材料是构建输入，不是运行期任意shell入口。

当前候选使用绝对RUNPATH，因此P1采用“安装位置固定”的运行包。迁到另一路径、另一宿主基线或x86_64时重新构建／准入，不直接复制旧目录假装可重定位。当前runtime_root是套接字／锁等运行状态根，与installation_prefix不是同一目录。宿主动态库更新后重新核对并发布准入记录，不用取消摘要检查来继续运行；也不宣称此包已经脱离宿主ABI。

#### 7.4.3 两段启动与实际加载

安装方的受信宿主入口先核对安装位置、权限、清单和包内字节，再启动被核验的解释器。它可以使用宿主受维护的系统Python以-I -B -S执行固定安装脚本，做文件／JSON检查，但不得导入产品包、sqlite3或打开业务库；这不是业务运行时，也不改变系统Python。此入口随安装流程部署，不是第三个后台服务或通用插件执行器。

原工具先导入工作区sqlite_runtime再验证的顺序需要调整：目标解释器以-I -B -S启动受信小入口，先显式加入已经核验的site_packages路径，再验证_sqlite3及实际私有库，最后才加入本任务应用源码根并导入产品。-I不会关闭系统site处理，故本方案显式使用-S，不能只依靠忽略PYTHONPATH；不调用site.main或执行.pth／sitecustomize／usercustomize；准入前已出现sqlite3或_sqlite3模块即拒绝，实际映射中也不能混入另一份SQLite。若某个依赖确实依赖这些启动钩子，列为准入失败，不能默默重新启用。[CPython启动选项](https://docs.python.org/3.13/using/cmdline.html)。

父进程在创建目标进程前构造最小环境：不继承PYTHON*、LD_PRELOAD、LD_LIBRARY_PATH、LD_AUDIT、PIP_*和用户代理变量；语言、时区、HOME／TMPDIR及业务配置仅按允许值提供，HOME／TMPDIR指向本环境受控位置。PATH只为后续已登记工具提供确定值，不能选择解释器。普通SSH开发沿同一显式入口；不能声称在已经受污染的进程里删除变量就修复了加载风险。

准入结果保持为当前进程私有的不可变上下文，包含运行清单摘要、实际解释器／_sqlite3／库身份及能力；require_active只接受此上下文并复核关键绑定，不能重新选择另一份库或仅判断sys.modules。运行时不额外open／close活动数据库做文件摘要；加载对象检查针对代码和库，数据库保护按第7.2节。

### 7.5 PKG-ENV-DEPENDENCIES Linux依赖产物锁

本节的input_lock、install_lock及bootstrap_wheel均为安装根内元数据文件：分别保存原锁的逐字节副本、本平台带hash锁和固定安装器wheel，全部进入运行文件索引；31个业务wheel归档保存在构建输入仓库，不作为业务启动时的下载／安装来源。

原backend/requirements.lock固定31个版本，含Windows来源说明，但没有wheel哈希；它继续作为本批版本集合输入，不修改为Linux全局锁，也不在本轮顺便升级／删减pytest等已有依赖。Linux ARM64和x86_64分别产出自己的`requirements-linux-<architecture>-cp313.lock`及python-wheels.v1.json。

python-wheels.v1.json字段为format_version=1、platform（与运行清单一致）、python_version、input_lock（原锁的Artifact）、install_lock（本平台锁的Artifact）、installer、wheels。installer为{name:"pip", version, bootstrap_wheel}，bootstrap_wheel为已固定pip wheel的Artifact；工具版本不能取“最新”。wheels按规范包名排序，每项仅{name, version, filename, sha256, bytes, tags, source_url}：name按PEP503规范化，version与原锁对应，filename为单个.whl文件名，tags为该wheel声明的完整兼容tag集合（排序无重复），不得伪造当前架构标签。名称和标签解析复用锁定packaging能力，依据[包名规范](https://packaging.python.org/en/latest/specifications/name-normalization/)及[兼容标签规范](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/)，不自制字符串猜测。

首次收集在受控构建阶段完成，核对官方发行资产及目标解释器的兼容标签；必要纯Python py3-none-any和兼容abi3可被接受，不能机械只接受文件名cp313。最终平台锁每个包只允许本批实际选定的一个wheel摘要；31个包完整覆盖且无额外依赖，新增传递依赖也先作为版本输入变化评审。没有目标wheel时中止该包准入；不回退sdist、临时编译或安装其他版本。

锁行固定为`规范包名==精确版本 --hash=sha256:<实际wheel摘要>`，按名称排序、UTF-8及LF，不带URL、环境marker、extra-index、可编辑安装或未固定VCS来源。只在已准备的私有wheel目录离线安装，使用--no-index、--find-links、--require-hashes、--only-binary=:all:、--no-cache-dir及--no-compile；安装器仍检查依赖闭包，不能通过--no-deps掩盖遗漏。父入口隔离pip配置，不让用户pip.ini／pip.conf补入额外源。pip的完整哈希模式要求依赖也固定，复用其能力，不自研包解析／安装器。[pip安全安装规则](https://pip.pypa.io/en/stable/topics/secure-installs/)。

安装后执行pip check、精确distribution集合／版本核对，以及FastAPI、Pydantic原生扩展、SQLite等必要导入；最终运行采用第7.4.3节同一启动方式，防止只在普通venv成功却在-S入口失败。安装工具分布与31个业务输入分开登记，不能将pip等工具误报成未知业务依赖。所有已安装内容进入运行文件索引；wheel摘要只能证明下载输入，不能单独证明安装目录没有额外文件。

包构建、临时venv和探针均有明确临时目录及清理；通过后的锁、来源清单和正式运行包属于发布输入，不能当测试JSON清除。实际wheel哈希和新运行包摘要必须来自准备后的字节，本稿不编造。本轮未下载、构建或发布这些资源。

### 7.6 DB-ENV-BINDING 精确增量DDL与初始化校验

本节定义environment_binding表；完整新Schema还必须包含第7.14节的code_snapshots来源字段／约束及触发器变更，P1即使用该最终结构。应用绑定是元数据，不与内部任务EnvironmentRecord共用。完整fresh.v1.sql由受信构造器生成上述明确增量，不接受CLI提供任意SQL。

```sql
CREATE TABLE environment_binding (
    singleton_id INTEGER NOT NULL PRIMARY KEY CHECK (singleton_id = 1),
    environment_id TEXT NOT NULL CHECK (
        length(environment_id) = 36
        AND length(CAST(environment_id AS BLOB)) = 36
        AND substr(environment_id, 9, 1) = '-'
        AND substr(environment_id, 14, 1) = '-'
        AND substr(environment_id, 19, 1) = '-'
        AND substr(environment_id, 24, 1) = '-'
        AND length(replace(environment_id, '-', '')) = 32
        AND replace(environment_id, '-', '') NOT GLOB '*[^0-9a-f]*'
        AND substr(environment_id, 15, 1) = '4'
        AND substr(environment_id, 20, 1) IN ('8', '9', 'a', 'b')
    ),
    data_generation TEXT NOT NULL CHECK (
        length(data_generation) = 36
        AND length(CAST(data_generation AS BLOB)) = 36
        AND substr(data_generation, 9, 1) = '-'
        AND substr(data_generation, 14, 1) = '-'
        AND substr(data_generation, 19, 1) = '-'
        AND substr(data_generation, 24, 1) = '-'
        AND length(replace(data_generation, '-', '')) = 32
        AND replace(data_generation, '-', '') NOT GLOB '*[^0-9a-f]*'
        AND substr(data_generation, 15, 1) = '4'
        AND substr(data_generation, 20, 1) IN ('8', '9', 'a', 'b')
    ),
    initialized_at TEXT NOT NULL CHECK (
        length(initialized_at) = 24
        AND initialized_at GLOB
            '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'
    )
) STRICT, WITHOUT ROWID;
```

WITHOUT ROWID避免INTEGER PRIMARY KEY的自动rowid分配；程序插入仍固定singleton_id=1，不能省略或接受调用方输入。日期SQL检查只约束表示形式，程序须解析实际日历时间并按现有utc_milliseconds往返校验；UUID也再次严格验证。STRICT不意味着任意业务约束天然成立。[SQLite严格表语义](https://www.sqlite.org/stricttables.html)、[WITHOUT ROWID规则](https://www.sqlite.org/withoutrowid.html)。

同一BEGIN IMMEDIATE内依次执行完整DDL、写schema_migrations的(200, fresh_checksum)、写code_schema_state和environment_binding，再校验结构／来源／身份及完整性。两项元数据共用本次初始化生成的UTC毫秒时间；事务回滚后重试可生成新时间，已提交结果的时间不改写。

保留code_schema_state.origin='FRESH_V20'及schema_version=200，表示Schema200系列的新建来源；软件目标版本为2.01，不把来源枚举字符串当软件版本。新库只有一条200迁移记录、一个原来源标记及一个本绑定。普通Database每次原有事务校验同时核对期望环境／代次；不能仅首次启动核对后，后续连接从同名替换文件继续读写。

合并第7.14节增量后，设计预期从72表／299对象变为73表／301对象：原297对象不变、2项指定对象修改、2项新增。必须用现有inspect_schema从实际新库生成objects.v1.json，核对全部列／约束／触发器及strict／without_rowid结构；此为待验证计数，不以手写清单或旧299对象专项证明新DDL已执行通过。

旧db20-r50、新表缺失、绑定为空、非法UUID／时间、错环境／代次、错误来源或不同DDL摘要一律拒绝，不自动补表／认领。相同DDL及对象契约、仅平台或程序发布改变时不要求重建业务数据；前提仍是新发布明确接受当前fresh_checksum及完整结构。任何逻辑结构变化另走明确维护设计，不在启动中更新checksum骗过检查。

### 7.7 PKG-ENV-SCHEMA 新Schema发布格式与不覆盖发布

#### 7.7.1 manifest.v2.json

继续使用schema_v20_release／publish、canonical_bytes、inspect_schema、verify_schema及verify_integrity，扩展为显式的新发布格式；不另建Linux简化数据库发布器。新目录不覆盖db20-r50，新格式与旧格式必须按受信pin明确选择，失败不能回退旧格式或旧迁移路径。

| 字段 | 精确规则 |
| --- | --- |
| format_version、target_version、schema_version | 分别为2、字符串2.01、整数200 |
| release_id | 原有[a-z0-9][a-z0-9-]{0,63}规则；平台各自独立发布名 |
| initialization_mode | 固定FRESH_ONLY；不承诺151或旧200数据升级 |
| runtime_manifest_sha256 | 对应平台已固定运行清单摘要，与私有启动输入一致 |
| schema_contract_sha256 | 实际objects.v1.json字节SHA256；同逻辑结构的跨架构发布须独立验证后得到相同值 |
| expected_objects_ref、fresh_sql_ref、upgrade_sql_ref | 固定objects.v1.json、fresh.v1.sql、null |
| resources | 精确两个键objects.v1.json及fresh.v1.sql；每项{sha256, bytes}，按实际字节核对 |
| sources | 项目相对路径→SHA256映射；精确匹配受信构造源码注册表，不能由清单自行缩小集合 |
| design_sources | 固定两项{path, sha256}：原V2.0后端设计与本V2.01后端迭代；使用实际构建输入字节，记录各自职责 |
| base_release | {release_id:"db20-r50", manifest_sha256}，摘要沿现有固定pin；仅用于业务结构承接核对，不代表其Windows运行包被加载 |

现有39项SOURCE_NAMES是本批基线：全部保留校验，包括尚未被Linux执行的Windows原生源文件，不把“未执行”误解为可悄悄减少来源保护。新增平台启动、文件保护、依赖准入和环境绑定模块必须加入同一注册表；实施前固定新增文件清单，构建前后校验全部实际字节。生成pin及新manifest自身不得入sources，避免循环。后续若删除已无调用的旧模块，须按实际调用及发布引用同步收敛，不能维持不存在的来源项或假文件。

design_sources的两份来源是构建溯源，不将独立迭代伪装成已经合入正式设计；构建输入快照必须保留这些实际字节及完整sources集合。不能只记录Git HEAD而丢失当时未提交输入。正式资源产生时记录确定摘要，本稿不提供假摘要或空值放行。

SchemaRelease表达“无升级脚本”为明确的null；访问upgrade_checksum或升级命令须返回SCHEMA_UPGRADE_NOT_ADMITTED，不填空字符串、拼出151脚本或沿用旧包。FRESH_ONLY构建执行真实全新建库、结构对照与初始化／重开证据，不为凑旧构造器的fresh／upgrade相等检查而虚构升级路径。旧151升级资源保留原范围，本批不宣称它可通往新绑定结构。

#### 7.7.2 构建、发布与准入顺序

1. 固定源码／设计输入和目标运行包；确认无并发写入者，再构建DDL、临时新库及实际对象清单。原db20-r50资源按原摘要读取作结构基线，不通过Windows运行库激活它。检查仅含第7.6及7.14节定义的增量，其他297项原对象不变。
2. 在同一受信文件系统的新临时目录写完全部资源与清单，分别flush／fsync并关闭；核对每个文件、目录、权限和来源前后摘要。目录同步与资源完整校验完成前不发布。
3. Linux用renameat2(RENAME_NOREPLACE)发布到全新目录，随后fsync父目录；目标已存在即失败，不合并、不覆盖，不用普通os.rename或跨盘复制回退。底层能力不支持则明确拒绝。[Linux不覆盖重命名](https://man7.org/linux/man-pages/man2/rename.2.html)。
4. 从最终路径重开核对全部资源，最后才原子更新受信准入pin。pin比较开始时的旧字节，并受专用发布互斥保护；仅“比较后replace”没有跨进程CAS保证，不能省略锁。更新文件后同步父目录；文件fsync本身不保证目录项已落盘，见[Linux同步语义](https://man7.org/linux/man-pages/man2/fsync.2.html)。
5. 新目录已发布但pin未更新时保留为未采用产物，旧pin保持；不删除可能被另一操作引用的目录。pin更新／父目录同步结果未知时核对原发布ID及新旧摘要后报告，不自动再次发布或切换。
6. 只清理本轮拥有且未发布的临时目录，检查最终绝对位置、归属、无链接及无其他使用者；保留输入、正常运行包、发布资源和维护回执。

固定prefix的运行包采用不同的准备方式：维护方排他创建全新最终安装目录，准备期间仅维护身份可访问，按最终prefix构建、安装并完成实际加载／能力检查，再形成清单、同步全部文件并封存；最后核对权限并发布外层准入引用。目录名提前存在不代表可用，启动入口必须有匹配的已准入摘要。失败保留为未采用安装目标，不能在旧活动包上继续构建；另次构建使用新runtime_id和目录。这样不要求带绝对RUNPATH的包先在错误临时路径运行，也不把普通目录改名当作可重定位证明。Schema资源仍按上面的不覆盖原子重命名发布，两者共用的是“旧产物不覆盖、准入引用最后更新”的原则。

准入pin是程序／安装发布输入，普通网页、任务代码和服务启动不能修改。普通开发工作区的源码变化若涉及注册来源，需准备新的可核对Schema候选；仅源字节变化而DDL／对象完全相同时可沿用该数据库。不能一边保留“源码已固定”声明，一边允许启动忽略差异。

### 7.8 APP-ENV-INIT-RECOVER 原初始化操作及崩溃边界

沿用既有显式维护入口的--package、原操作绑定、短错误投影及进程独占规则，扩展初始化专用意图；不把新数据初始化假装成151升级计划。维护包必须在数据根之外、由安装方登记，普通应用和内部Agent不能写入。开始新操作创建新包；继续／查询必须给原包、operation_id和intent_sha256，不重新创建一份同名包。

intent.v1.json为不可覆盖的规范JSON，字段固定为format_version=1、operation_id、environment_id、data_generation、configuration_sha256、runtime_manifest_sha256、schema_manifest_sha256、data_root、database_relative_path、lock_path及prepared_at。operation_id与环境／代次均为规范UUID；路径来自已核验配置和安装登记，prepared_at为UTC毫秒。该文件的SHA256由原准备结果返回并在后续命令明确提供；不把它写入自己。

progress.v1.json为受锁保护的可更新记录，字段固定为format_version=1、operation_id、intent_sha256、revision、phase、data_root_identity、database_identity、initialized_at、reason_code、observed_at。revision为从1开始的正安全整数；phase为INTENT_RECORDED、TARGET_BOUND、DATABASE_VERIFIED、COMPLETE或UNVERIFIED。身份值在尚未取得时为null，否则为{device, inode}规范无符号十进制字符串；它们只是与原操作一起核对的文件事实，不是可独立授予权限的令牌。initialized_at在读回已提交绑定前为null。reason_code只在未核实时填安全码，其余为null。

在创建数据库前先持有稳定应用锁，并将原意图和目录身份持久保存；排他创建新普通文件后保存并同步TARGET_BOUND身份，之后才允许SQLite建立连接及事务。不能先调用现有_initialize里的source.open('xb')，再等MaintenanceSession取得锁。跨进程重入统一争该稳定锁，不额外套第二个数据库锁owner。

| 中断位置／现场事实 | 接续动作与结果 |
| --- | --- |
| 原意图已固定，数据库仍不存在 | 原ID、摘要及根身份核对后，可继续该原操作；不另生成环境／代次 |
| 文件存在但TARGET_BOUND尚未持久保存 | 保留文件并返回TARGET_OWNERSHIP_UNVERIFIED；不能凭空文件／同名文件自动认领。这一窄窗口需另行核对处理；若选择另建隔离目录，使用新操作并保留原目标，不修改原意图中的路径。不声称所有失败都可自动恢复 |
| TARGET_BOUND已持久，原对象仍在，逻辑库尚为空 | 在原锁和身份核对下读取SQLite实际状态；确认无业务对象／序列数据后继续同一初始化。不能按字节大小推断空库，也不删除WAL或SHM |
| 提交抛错或进程在提交前后退出 | 关闭旧连接，在原锁下新连接核对结构、来源及绑定；符合完整已提交事实则补记DATABASE_VERIFIED，无完整事实则保持未核实或按原已证实空库规则处理 |
| 数据库已验证，进度／最终回执缺失或同步失败 | 重开核对原数据库并补原记录；不得新建库，客户端结果为待核实直至回执已持久 |
| COMPLETE后重复同一原请求 | 核对原意图和数据库实际结构／归属后返回ALREADY_INITIALIZED，不因业务后来有数据而重跑建库 |
| 根／文件被替换、错发布、未知对象、另一操作输入 | BLOCKED，保留原文件和记录；不自动修权限、改绑定或清理重建 |

最终成功必须同时具备已提交并重开的数据库事实和已持久维护回执。普通启动校验受信配置及库内完整已提交事实，不导入维护包或把其回执作为每次业务读取依赖；初始化结果未核实的工具流程不得自动接着启动服务。准备工具不靠库内单个UUID替代原意图／目标身份。当查询原操作时，只核对和补充原观察／回执，不执行DDL；用户明确继续原准备才可执行已证实未完成的初始化步骤。

沿用CLI退出0成功、2明确拒绝、3结果待核实；PENDING_RECONCILIATION不显示为初始化失败可重来。新增安全原因固定为RUNTIME_MANIFEST_MISMATCH、RUNTIME_FILES_MISMATCH、HOST_DEPENDENCY_MISMATCH、DEPENDENCY_LOCK_MISMATCH、RUNTIME_FEATURE_UNAVAILABLE、SCHEMA_RELEASE_MISMATCH、SCHEMA_UPGRADE_NOT_ADMITTED、ENVIRONMENT_BINDING_MISMATCH、INITIALIZATION_INTENT_MISMATCH、TARGET_OWNERSHIP_UNVERIFIED、PUBLICATION_UNVERIFIED。仅说明原因，不回传密码／正文／原生异常。第3.3节的公开能力状态仍使用其原有短码，不把私有安装诊断全部暴露为前端能力枚举。

### 7.9 DB-MGT-REGISTRY 管理登记的持久与宿主边界

管理库选用独立SQLite文件，复用本项目固定Python／SQLite产物及纯校验／序列化组件，避免用多份JSON自行实现跨环境占用事务。它不使用业务Database对象，不装配业务工作器；独立schema_version=1，不是业务Schema200的一部分。不能修改业务库的任务、预算、原幂等结果或environment_binding。管理安装、完整性检查和显式升级各有入口，普通启动不建空登记库或自动升级。

| 逻辑存储 | 必需持久约束 |
| --- | --- |
| manager_state | 单行安装／管理身份、registry_generation、schema_version；受保护安装锚点指向唯一登记库，不能另传空路径逃过固定锁 |
| managed_environments | environment_id主键，record_version及assignment_generation单调CAS；私有配置引用、期望事实、当前任务分配；环境ID不复用 |
| management_operations | operation_id主键；(registry_generation, request_key)唯一；原规范输入、请求者及原结果读权、状态／revision／cancel_requested |
| management_controls | control_key在当前登记代次唯一，指向原operation、command及固定输入摘要、控制回执；控制更新与原operation修改同事务 |
| management_steps | (operation_id, ordinal)唯一；固定类型、派发前身份、已知／未知结果、逐项清理事实；不得删除后重排已执行步骤 |
| resource_claims | 资源身份／范围、所有者、原操作、额度及释放事实；包含排他目录／端口／分支与聚合额度。路径祖先冲突由事务内统一规范化检查，不能只做字符串UNIQUE |
| management_plans | plan_id主键、请求者、目标版本、规范预览摘要、有效期及实际消费原操作；同plan只可被一个执行操作消费 |
| environment_observations | 环境与来源的最新投影和必要故障证据引用，CAS观察序号；旧run记录不能覆盖当前投影。日常采样允许压缩，未决依据和操作回执不可压缩掉 |

控制库采用foreign_keys=ON、journal_mode=WAL、synchronous=FULL及短事务，外部工作不跨持有写事务；底层存储耐久性仍须实际验证。固定宿主锁覆盖管理写入者生命周期，资源预留／操作受理／plan消费使用同一写事务。数据库提交返回不明时只查回执；不以重新执行外部动作“试一下”。新锁实现须满足第7.2节稳定根保护，不能直接把现有ProcessLock能打开文件等同安全接管。

管理辅助进程与应用进程使用明确服务组；普通原生Linux适配优先采用受信systemd服务模板，单位身份包含环境／原操作，记录启动实例身份和boot_id，配置KillMode=control-group并核对全部受管进程。具体退出是否强制由动作的停止策略规定，超时不能自行清未知；不得仅凭服务名称或活动状态判断业务成功。[systemd进程组停止语义](https://www.freedesktop.org/software/systemd/man/latest/systemd.kill.html)。首期应用与完整执行控制统一采用7.11.8的宿主服务部署，不同时实现另一套Compose应用启停适配；Docker仅管理已登记工具／检查资源，不使用全局down／prune清任务资源。

额度登记只是准入；实际受管进程的MemoryMax、CPUQuota、TasksMax等限制由安装模板设置并验证。不能让HTTP传入任意systemd属性、Docker挂载／特权参数或宿主shell，也不能把Docker socket交给开发Agent。[systemd资源限制依据](https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html)。共享运行包只读，构建／依赖安装在相应任务受限身份和独立可写根完成，不执行为root。关闭管理服务不联动关闭所有业务服务；安装更新也不能默认重启业务。

Git使用结构化worktree列表核对真实归属及主／关联工作区；删除用其正规接口并遵守未提交和锁保护。安装固定版本后仍须验证项目实际仓库特征，不把最新版文档当作现场版本已支持的证据。[Git worktree生命周期与限制](https://git-scm.com/docs/git-worktree)。

受信安装需提供管理程序／前端／Schema版本及摘要、固定根／UID权限、有限命令模板和无业务实例时的独立启动方式。管理库备份必须取得一致快照，不能在WAL活动时只复制主文件；本批不开放恢复按钮。登记恢复／重建须暂停管理派发、换registry_generation、核对宿主全部已登记资源和原操作后开放，具体顺序见第4.12.3节，离线工具仍待实现及故障演练；管理库丢失不授权清理孤立资源。

实现定位：新增独立环境管理模块和入口；从现有基础设施提取确有复用的规范化、固定资源读取、错误投影和安全锁部件；不从tools/ai-service.py启动，因为它沿业务配置／模型装配路径。现有code_tasks/operation_protocol.py、infrastructure/command_receipts.py仅作为原意图和事务约束的复用依据，不直接扩其业务动作注册。上述逻辑存储、API及状态为本批设计；确切DDL／索引、受信manifest、服务模板及逐步故障注入在管理实施单元按契约生成，尚无管理程序可供运行。

### 7.10 PKG-ENV-DEPLOYMENT 原子控制、候选与恢复清单

control.v1.json按第7.4.1节严格canonical_bytes规则及字段Schema生成；在稳定环境锁和应用准入闸门下CAS，写同目录临时文件、fsync、关闭、复核原revision／身份、原子替换并同步父目录。调用返回成功前必须核对落盘事实；同步／回执结果未知不能重写为OPEN。原子替换的是控制数据文件，稳定environment.lock本身绝不替换。目标操作系统／文件系统不支持所需保证时阻止该能力，不退回清空再写。

应用启动描述增加control_root并核对其安装身份；control记录中的program_ref／data_root_ref仅引用受信安装目录，解析结果须与本次启动完整描述一致。原型阶段直接指定另一个库路径不能绕过该环境锁与元组核对。控制选择和公开配置分别落盘，切换不一致窗口保持CLOSED；新版只读核验后才开放，不声称多文件原子提交。已有私有配置、前端静态摘要目录、候选及恢复包都是新对象发布，不就地覆盖在用文件。

发布清单release-manifest.v1.json最少精确包含format_version=1、release_id、source_commit、target_os、target_arch、application_index_ref、frontend_index_ref、runtime_manifest_sha256、schema_manifest_sha256、resource_refs、binding_protocol、management_protocol、maintenance_contract=1、compatibility_refs和verification_refs。索引沿Artifact约束完整列文件及摘要；不得包含自身摘要循环，外层受信登记固定manifest摘要。源码提交、实际构建文件、固定包及验证证据分别关联；没有可信验证来源的人工说明不能填verification_refs。

恢复清单backup-manifest.v1.json包含format_version=1、backup_id、source_environment_id、source_data_generation、source_deployment_id、source_control_revision、cutoff_at、database_artifact、asset_index_ref、program_and_configuration_refs、original_result_index_ref、restore_verification_ref。秘密只用独立引用；数据文件／资产索引／验证证据与清单按不可变包发布，manifest最后落盘并核验后才登记LOCAL_VERIFIED。状态和异机snapshot／验证事实是后续外层回执，不修改已封存清单。实际内容不完整或fsync失败的目录保持UNVERIFIED。

封存包采用新目录排他取得，不覆盖已有包；按第7.7节不覆盖发布机制完成。Restic上传或恢复的结果先绑定固定snapshot、原backup_id及manifest摘要，网络超时不能推断未保存；先查原匹配快照，多个重复候选也只在核验同一包后归并，不依据标签单独认领。不得由普通清理执行restic forget／prune；仓库密钥及存储账号不暴露给业务／开发Agent。异机取回到独立暂存目录并核对全部受支持资产，实际生产采用前另验环境身份与权限。

数据恢复新根先生成并验证完整副本，control元组只在CLOSED下切换。修改副本的environment_binding使用专用维护事务，其提交标记与外部原操作绑定；工具恢复时能区分尚未改代、已改为原计划新代次和身份不明三种情况。原库及控制锁不被备份复制覆盖，新副本不继承活动WAL／SHM／进程锁文件；Backup API目标产生的SQLite状态经正常关闭和独立核验处理，不能直接拼接另一时期的侧文件。

源码复用以schema_v20_plan.py的独立Backup连接、完整性重开、plan最后封存，schema_v20_assets.py的审计资产，schema_v20_maintenance.py的原计划核对及外部回执分离为起点。其当前Windows LocalPathGuard、NTFS身份、151→200数据保留投影和rebuild_locked不直接用于Linux全量恢复；新增适用资源与Linux目录／锁保护，保持旧发布字节。当前Database.backup_to只覆盖单库，不能作为全部资产备份完成依据。

验证引用避免摘要循环：候选检查绑定实际应用／前端内容索引及固定资源摘要；恢复演练绑定database_artifact、asset_index及程序／配置摘要，不引用尚包含自身验证引用的最终manifest摘要。最终封存清单再由外层登记固定；两层均需核验，不能只验证自报hash。

首期管理库仍使用第7.9节已有逻辑记录：候选来自受信安装目录，备份作为本环境持久资源登记并由原操作结果关联；不因增加发布流程再造业务模型库。具体维护文件Schema／资源索引、Linux复制与恢复工具、兼容矩阵及故障注入尚待实现生成；本稿不把上述清单名当作已存在的正式资源。任何实际不兼容数据转换必须先独立形成源→目标规格和恢复实证，不能由执行者临时补一个通用SQL入口。

### 7.11 PKG-EXEC-LINUX 适配边界与资源交付

| 现有位置 | Linux适配与保持的不变量 |
| --- | --- |
| task_runtime_launch／recovery、guard_task_execution／launch_protocol | 分开业务原操作和平台实例证据；新控制协议绑定同一原范围，未知不重复启动 |
| task_runtime_stop、testing/run_stop／run_ownership | 保留先撤权、原abort、完整停止、写入核对和清理顺序；Linux证据严格解码，不伪造Windows字段 |
| task_model_ingress、coding_model_listener、guard_task_model_source | 将Windows连接／根身份核验收敛为平台证据入口；先证明等价强度，再接已有ModelWindow；不能只删type断言 |
| coding_model_ledger／admission、usage、Testing planning_worker | 保留预留、费用精度、冻结价格、调用序号、无自动重试；恢复前区分同代次当前库与旧快照 |
| authorizations.py、task_start_authorization、task_question／permission_response | 授权者改为可信业务principal；原任务／会话／版本检查不减弱，维护拒绝新原生控制 |
| CountingJournal、ProcessLock及原审计目录 | 适配稳定control_root环境锁与数据身份；原CountingJournal._guard仍按数据库锁路径校验，不能仅改变锁文件后绕过检查 |
| 既有原生检查／Git控制执行 | 后续分别生成Linux固定资源与证据；不允许任务自身替代独立检查，未完成不得声明INTERNAL_EXECUTION整体READY |

Linux执行发布至少生成：固定runtime／镜像索引、受限服务及网络模板、平台控制与观察Schema、目录权限／挂载规则、完整停止与原操作恢复证据、恢复外发索引格式及备份处理器。选择实际版本、ABI／架构、文件摘要和资源上限时记录现场证据，不在设计中编造产物hash。

外发恢复索引采用原操作文件协议的排他创建、完整写入／fsync与父目录同步，按原环境／代次／调用身份唯一；内容不含密钥或完整提示词。索引只引用不可变审计证据并被恢复点资产清单收录；普通日志保留期和CountingJournal原始数组清理不能删除尚未核清的最低恢复依据。宿主灾难导致最新外层索引也丢失时仍为覆盖不明，不能把备份中的旧索引当作完整高水位。

本轮不改实际Schema资源或旧db20-r50字节；V2.01最终新Schema依第7.6、7.14节，73表／301对象仍仅为设计预期。环境许可与外层恢复关联的物理文件格式见第7.12节；不借此修改原费用字段或临时向旧库补列。实际调用源证明、网络执行细节、Linux独立检查／Git交付及完整许可恢复实证尚有门槛，详见第8.3节。


#### 7.11.1 同机执行候选的固定交付单元

第4.15.4候选使用独立平台协议标识OC201-MODEL-UNIX-1；原OC20-CONFIG-1／OC20-MODEL-1及Windows固定资源保持原字节。现行opencode_runtime_bundle要求plugin=[]，task_initial_prompt核对原TCP baseURL及配置；不能只删除这些检查来“兼容插件”。新平台装配须明确允许的唯一插件及传输格式，同时保留provider／模型集合、原会话、配置和凭据核验。

| 随Linux执行包交付 | 固定与检查内容 |
| --- | --- |
| OpenCode及插件闭包 | OpenCode1.19.5实际平台二进制、内嵌Bun观察、插件源码／编译产物／依赖摘要、公开扩展与固定源码契约、唯一工具集合及Schema；运行期不下载npm／插件 |
| 控制器启动策略 | 受信启动入口、AppArmor策略及ABI／内核能力、实际profile／enforce核验、UID／GID／命名空间、只读程序与可写数据目录、外部网络拒绝、完整资源归属 |
| 模型传输 | OC201-MODEL-UNIX-1、受保护socket装配／清理、逻辑HTTP authority、凭据接收器、原source proof严格Schema及原业务入口映射；不包含方舟密钥 |
| 工具沙箱 | 固定runsc／平台镜像／工具闭包、原工具操作协议、OC201-TOOL-RESULT-1结果封装／续读与限额、网络／目录；控制器包和工具包的发布引用互相匹配 |
| 准入证据 | 同一产物组合通过SRC／EX边界与业务兼容；ARM64、云x86_64分别绑定内核／策略／摘要和实际结果，不能互相代替 |

Linux source proof增加平台判别值及原host／boot、environment／data_generation、原launch_run_id／原owner_epoch、control_generation、原根身份／可执行资源／策略引用、listener_instance_id、connection_id、完整request_sha256、受信接收证据摘要及原ModelWindow引用；当前业务控制身份、attachment及control_runtime_id按7.11.6另行绑定，不覆盖原启动身份。进程号、pidfd文件描述符和socket路径只供当前受信执行核验，持久记录不能在重启后重新产生权限；proof不从HTTP头或客户端JSON反序列化成可信对象。connection_sha256按新协议的真实连接绑定计算，不填伪造127.0.0.1或沿用旧Windowswire。原费用账只保存原证据引用，不增加业务费用表。

固定OpenCode的[项目装配](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/project/project.ts)在无VCS的global项目路径可能把worktree设为/；不能把该值直接映射成任务可读根。控制器使用独立元数据目录，工具桥的项目根只从原业务登记解析；插件上下文directory／worktree仅作受信关联输入，不赋予宿主目录权限。启动时项目发现／依赖准备及运行时原生后台行为都纳入固定组合检查，不能只测一次fetch就宣布完全封闭。

实际接入顺序：先将coding_model_listener的字节接收与有界HTTP解析分开，保留原解析／响应／队列规则；Linux接收器在每段字节进入解析器前核验凭据。再将guard_task_model_source／RuntimeTaskLaunch的来源核验及TaskModelIngress的连接描述改为明确平台契约，原窗口、凭据、许可、预算、调用序号与冻结价格仍使用原调用链。最后按真实传输更新opencode运行包／准备、model credential、task_initial_prompt及ExecutionProfile资源绑定。不能把TCP转接进旧listener来取得代理PID后返回“根来源通过”，也不能创建第二套Coding网关或结算器。

分两次原型收口：先用最小受信发送程序与攻击夹具验证Linux逐段身份／停止条件，再用实际固定OpenCode二进制及插件验证provider loader、SDK、SSE、压缩和原业务兼容。前者通过只证明内核接收路径，不足以准入产品；后者缺项时整套候选仍不可用。任一固定文件、内核／策略或必要配置变化都重核受影响证据，不用版本名称沿用结论。本轮未生成清单、hash、策略、Schema或原型代码。

#### 7.11.2 工具结果大小与续读契约

固定[自定义工具注册](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/tool/registry.ts)在插件返回后仍调用Truncate.output；[截断实现](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/tool/truncate.ts)默认限2000行／50KiB，超限会在控制器本地写完整输出，再提示模型用Read／Grep或Task读取。只限制沙箱命令、却原样返回大字符串，会触发这条旁路或使模型反复调用被禁工具。因此固定工具适配按OC201-TOOL-RESULT-1返回有限预览及原结果引用，不提高原生上限来掩盖问题，也不开放控制器目录读取。

1. 固定Linux配置显式设置tool_output.max_lines=2000、max_bytes=51200；适配器最终output（含状态、说明及续读提示）按UTF-8最多32KiB、512行，必须同时满足。title最多256码点，适配器metadata规范JSON最多8KiB；所有字段严格白名单，不转发项目提供的原生metadata／attachments／outputPath。长单行、多字节文本、空输出和错误输出同样计入；任一返回路径都经过统一封装。
2. 工具控制侧在原操作结果存储中封存输出，沿第4.15.3节身份关联，不新建通用文件服务。每份记录固定format_version=1、opaque result_ref、原环境／数据代次／task／run／operation、native session／message／callID、工具与输入摘要、结果状态、内容摘要、字节数、编码、完整性和原效果证据引用。文件位置只由受信存储解析，result_ref不是路径、URL或授权凭据；沙箱不能覆盖封存结果。输出文本即使写“成功”也不能替代可信退出／效果证据。
3. 优先流式、有界采集；设计初值为单原结果最多8MiB、一个原业务任务累计64MiB（角色交接或控制器重启不清零），并纳入原磁盘占用与执行包固定配置。实际值须经容量验证后固定，不能留空或运行时由模型修改。到限停止该原命令并核清子资源，保留已采集前缀与OUTPUT_LIMIT事实；有可靠效果／停止证据如实记录，核不清才UNKNOWN。不能把部分输出说成完整，也不能把已发生的文件写入改记“未执行”。文件本身的大小限制仍按原工作区／候选规则，不被此输出限额代替。
4. 预览返回result_ref、内容摘要、是否完整及可用的opaque cursor；固定walle_result_read工具按引用与cursor只读后续页，每页仍满足第1项封装上限。调用身份仍来自当前受信上下文，服务端核对原任务、当前控制及读取范围，cursor绑定同一不可变结果／摘要／位置；新callID只登记一次只读观察，不重新执行原命令。跨任务／代次、伪造游标、旧控制身份及路径参数拒绝。正常角色交接只能读取原业务允许的已封存结果，不因知道引用取得其他角色或环境权限。
5. UTF-8文本按完整字符分页，明确下一游标与结束；无法解码或二进制仅返回类型／长度／摘要和受限说明，不把任意字节替换后伪称完整正文。输出引用仍作为不可信工具数据进入模型。缺失、损坏、收集不完整及保留期内不可读分别返回明确原因，不能输出空串冒充没有内容。续读失败先核对原结果，不重做有副作用工具；原结果保留与任务审计／未决操作共同清理，不依赖OpenCode截断文件的默认7天清理。
6. 下游运行时若仍出现原生truncated=true、outputPath或本地读取提示，按封装失配阻止该结果进入下一模型步骤，保留原工具效果并关闭该轮后续派发；不得仅删掉路径后继续。须验证固定版本在after hook、异常和事件投影后的实际结果。原始错误不直出到UI／模型，适配器也不能靠抛出任意大异常绕过大小控制。控制器会保存正常会话中的有限预览，这不等于把完整项目输出落到其可读文件目录。

本协议只服务已登记工具结果；不接受任意宿主文件、远程URL或用户上传证据，不改变正式候选、检查报告或Git交付身份。程序就绪、来源隔离与结果封装分别验收；输出缺失不解除费用／效果未知，也不把模型自述转成业务完成。协议Schema、结果收集／续读和固定资源均待实现。

#### 7.11.3 工具策略与既有调用链接入

OC201-TOOL-AUTH-1随唯一固定运行包交付，清单收录6个工具的ID／参数Schema／描述摘要、动作与对象映射、allow／ask规则、结果协议、输入／输出上限及支持的COMMAND模板版本。它是原executor／runtime_bundle引用的程序资源，不成为浏览器可编辑授权；实际作用范围仍只来自原ExecutionProfileVersion和EFFECTIVE授权。所有正文、补丁、查询和数组均有明确上限，总输入沿原HTTP_REQUEST_BYTES再取资源更小值；缺少限制或资源闭包时不准入。本节不编造实际文件摘要或已发布资源。

| 既有位置 | Linux适配的具体责任 |
| --- | --- |
| execution_profile_content／execution_profile_resources、authorization_scope、managed_read_scopes | 保留不可变完整资源相等、scope子集及任务绑定；按新Linux固定政策准入工具包、EXECUTION模板、根与网络，不能去掉旧校验来接受任意配置 |
| task_native_policy、task_initial_prompt、运行包／配置应用 | 按固定工具名生成最终权限；保留CP20上下文与两个模型用途。核对插件tool.definition和请求准备之后的真实工具Schema／集合，不只读配置JSON；旧Windows read／edit策略不是新执行证据 |
| task_native_issues、native_permission_objects、task_permission_response／task_issue_reads、原生控制driver | 实现6.7.1关联、具体对象／命令校验及一次决定；保留原请求、拒绝集合、未知结果及当前会话检查 |
| 原执行控制、资源记录及Linux文件／停止适配 | 同一派发闸门固定授权／对象前提与取消先后；命令独立短时沙箱、按条网络及完整子资源停止，结果沿7.11.2保存 |
| coding_check_plan、CommandExecution与原Verification／Git交付 | 命令记录与可信检查结论分开；CHECK／SERVICE只由已准入检查路径使用，不能因Agent自检退出0越过候选／交付条件 |

原型仍用本地假供应方：固定模型请求中必须只有预期工具，模拟工具调用、权限答复、取消及异常并观察真实效果；无需真模型来证明这些程序规则。实际插件／接收器／Schema／工具及命令资源尚未实现；若只能通过开放宿主任意执行或长期修改OpenCode内核才能兼容，则退出候选。

#### 7.11.4 工具证据落盘与业务补记

固定包新增OC201-TOOL-OP-1及OC201-TOOL-RECOVERY-1资源，复用第3.8节原控制证据目录与单写入者／任期机制。runtime_launch_journal和project_check_journal已有“派发前记意图、原范围核对、回执不重放”的模式；它们当前依赖Windows私有目录及Guard类型，Linux需提供同等严格的文件／权限实现，不能仅改路径后宣称复用完成。不开第二套业务SQLite、队列或调度服务。

**记录布局及顺序。** 每任务保存受保护登记清单，每原工具保存不可变绑定、有界输入引用、可选命令关联、派发意图、取消标记、效果／结果及追加观察；记录均含协议、原范围、规范输入摘要及前序证据引用。查找键由3.8.1完整原键确定，核对原字段而非只信哈希；UUID与原键关系只生成一次。清单固定登记序号、记录摘要及已核清写入高水位，权限等待中的新写入使旧确认失效。它是原任务控制记录的索引，不承担业务状态、授权决定或费用结算。

输入与绑定先完整写入受保护临时文件并同步，再以同文件系统不覆盖发布并同步目录；清单在原控制锁内按原版本原子更新。未登记的孤立文件不得派发，更新失败保留原事实。动作意图在真正外发之前持久发布；同一意图文件已存在则只核对。效果、取消和恢复观察追加保存，不能覆盖旧回执来抹去UNKNOWN；当前指针只指向完整且已验证的记录。不以数据库事务包住文件操作来声称跨存储原子。

**命令与观察ID。** 在绑定已登记、尚无派发意图时，由业务层使用原EntityKind.COMMAND_EXECUTION序列预留一个ID，先完成该序列事务，再将该ID持久写入原工具的唯一命令关联，最后插入相同ID的PENDING命令。预留之后、关联之前中断只产生未使用ID间隙；它从未授权创建命令或启动项目。关联之后中断只比较／补原命令行，不能重新分配ID；事务结果未知先查固定ID与完整不可变字段。原关联不可读时阻断，不能凭数据库没有行判断尚未预留。

CommandExecution使用原父操作ID、实际执行session、原配置及登记command_ref；不把COMMAND定义ID与CommandExecution.id混用，不把核对操作或权限决定换成其父操作。创建回执／真实启动／结束／停止分别补记原process_identity及Linux runtime_binding，未知字段保持null；既有终态和已固定事实不覆写。后续发现矛盾作为恢复冲突保留，不反向改旧成功为失败来掩盖问题。

ExecutionRecord仍是追加安全观察。工具核对摘要关联原OPERATION，命令输出关联原COMMAND；使用既有kind及真实来源，native_event_id=null，不伪造上游prt_事件。需要恢复补记时以“原工具＋观察版本＋输出类别”固定一次记录ID，并采用同样的预留／持久关联／插入核对顺序，重复补记只比较原行。task_records目前的record_project_output只覆盖CHECK，不能直接套给EXECUTION；须增加受信原命令关联验证，保留原脱敏／大小限制。不将原生工具日志的自报成功当作这份可信效果证据。

**有界保存与保留。** 固定包初值为每原任务至多10000份工具绑定、元数据／回执合计64MiB、保留输入合计64MiB；结果另沿7.11.2的64MiB总额。再为停止／核对／最终补记保留8MiB受保护应急空间；这些值均为待容量验证的包资源值，计入宿主磁盘准入，角色交接、控制重启不重置。接受前预留本动作的最坏记录空间；额度不足拒绝新工具，不能删除旧证据为新调用让路。出现系统写入错误仍可按既有授权停止原资源，但无可靠回执时保持UNKNOWN；预留空间不保证物理磁盘永不故障。

未决记录、取消标记、调用去重索引及关联原结果不得按普通日志轮转删除。只有原任务全部执行范围已核清、原审计保留及资产清理条件满足后，才能由原清理流程回收已登记内容；先保留原身份与清理事实，迟到请求只能被拒绝或查询原结论，不能复活已清理动作。普通业务备份不覆盖更晚的控制证据；控制域丢失或整体回滚按4.22的证据缺失处理，不从业务库反推完整外发集合。

**准入范围。** 先用本地假供应方和固定工具夹具验证登记、ID间隙、每个外发／落盘断点、停止／取消、补记、跨代次恢复及UI投影。当前未生成Schema／运行包或执行故障注入；第4.23.1候选未通过实际文件故障及收尾证据时保持该执行候选未准入，不能以允许人工强制成功补过。

#### 7.11.5 文件恢复与原轮次接续的固定资源

本单元只增加原执行包内的固定协议／适配规则，不新建业务表、恢复服务、通用事务系统或任意文件接口。OC201-FILE-EFFECT-1的每次操作关联原OC201-TOOL-OP-1，至少封存：原工具UUID与全范围绑定、输入／授权／配置摘要、volume／真实根及父链、目标相对路径、动作、准备材料精确清单与身份／内容／模式／链接集合、file_commit_intent、原回执或恢复观察、私有清理意图及完成事实。opaque引用由原控制域解析，模型不能传入路径或替换证据。每个准备对象／目录在创建前登记精确名字、用途与原操作，创建后保存实际身份；中断时仅有名字而不能核验归属的对象保持未决，不能直接删除或重建。提交前须完整核对所有准备回执。

恢复观察固定observation_basis=RECOVERED_STATE、observed_layout=APPLIED／NOT_APPLIED、原意图摘要、观察范围／时刻、写入者停止及同步证据引用；条件不齐只记录未核清原因，不制造上述有效观察。effect_receipt_ref可引用可靠原回执或这份观察，由effect_basis区分。同步、清理和最终SETTLED各有追加事实，不能用最后一个JSON文件存在代替前序完整性。后续正常写入使旧布局失效，但不改写已保存的历史观察；新准入使用当前高水位及完整清单。

实际文件身份统一由固定Linux适配解释。宿主只在文件工作器已停止／卸载且没有旧缓存写回者后核对底层文件，并在原闸门内完成必要同步和私有收尾；新工具使用新挂载观察，不能同时从多个不一致的缓存视图判定身份。主机只读观察与受限私有清理不是允许宿主任意运行项目代码。固定受信清理仅接受原对象引用，缺失或归属冲突即停止，不通过目录通配推断所有权。

空间准入除7.11.4的记录／输入／输出额度外，须在原任务磁盘预算中预留本动作新内容、被保留旧内容、缺失目录分支及清理余量；锚点共享数据块不按每个名字重复计费，但旧对象保留确会阻止空间释放。以最坏保留量准入，不借8MiB停止／核对应急空间存项目内容。原任务结束与异常清理均覆盖该材料，未核清时不得随容器退出一起删除唯一证据。

原生继续资源沿已有RESUME发送意图扩展source_window_state=HELD／CLOSED及原结束／工具快照引用，明确原scope／角色、源触发消息、新消息、冻结输入与发送事实；前者为来源证据，不能改写新ModelWindow状态语义。实际接收及完成事务仍用原操作和固定步骤。原上下文生成器按实际BACKEND／FRONTEND／INTEGRATION角色生成继续内容；新增恢复摘要必须有限、可脱敏、计入既有计数，原依据与费用不删除。不存在“为了恢复先调用一次模型”的旁路。

实施接入同时覆盖task_resume的model_resume_window／model_waits_cleared、task_resume_runtime的原意图解码／新窗口／完成事务、task_instance_driver的continuation_payload／dispatch_continuation／observe_continuation，以及task_model_ingress的原消息／用途绑定。当前driver依赖活owner.gateway，不能从SQLite重建出发送许可；Linux接管能力必须另有原型证明。task_session_replacement／task_repair_runtime继续保留原候选与实际实例前提；不得仅放宽一个窗口枚举就宣称后端重启、会话重建已完成。

**平台可行性来源及边界。** 2026-11-17读取[gVisor固定源码中的gofer RenameAt](https://github.com/gvisor/gvisor/blob/bf5df9a1c9211afe4dbd7267c4423e9ae575f7fa/pkg/sentry/fsimpl/gofer/filesystem.go#L1445)及[宿主转发](https://github.com/gvisor/gvisor/blob/bf5df9a1c9211afe4dbd7267c4423e9ae575f7fa/runsc/gofer/fs/lisafs.go#L1188)：该源码处理EXCHANGE／NOREPLACE，但shared互操作模式明确拒绝NOREPLACE。系统调用兼容表的“支持”不能单独证明本方案所需的挂载组合可用。[Linux rename语义](https://man7.org/linux/man-pages/man2/rename.2.html)和[fsync语义](https://man7.org/linux/man-pages/man2/fsync.2.html)也不能替代runsc、gofer及底层文件系统的联合证据。

因此固定包须选定并验证实际runsc构建／摘要、允许的互操作模式、单挂载布局、目录同步和工作器退出后的可见性；上面的源码提交只是本轮可行性依据，不是已选运行二进制。不能为绕过EINVAL／EXDEV改成先删除再复制、取消不覆盖保护、开放宿主执行或降级为普通容器。首轮故障原型以全部文件动作及原消息投递断点为最小集合；若不满足这些有限机制，退出候选并重新评估执行底座，不继续堆叠私有文件系统。

#### 7.11.6 接管关联、原能力交付及失效

固定资源OC201-CONTROL-ATTACH-1复用原控制域的原子发布／单写入者及3.8.2身份；不增加业务表，也不新建可从HTTP操作的“接管任务”。ATTACH输入为规范request_id、原实例绑定引用、预期attachment_revision、当前环境／数据代次及实际新后端绑定；不能携带任意PID、FD编号、口令、Unix路径或程序。服务端重新取得peer事实并与输入比较。单实例资格按7.2的OC201-ENV-LOCK-1，由固定Linux锁适配核验lock_root中原稳定environment.lock身份、当前实际持有者及有效受信启动绑定；锁文件里的PID／JSON、自报成功或仅一次尝试加锁失败均不构成持有证据。实际记录锁绑定、查询权限及命名空间组合须作为固定包准入项，取不到可信持有事实时拒绝接管，不降级为字符串比较。

每份持久接管记录固定protocol_version、request_id、原执行绑定摘要、control_runtime_id、原后端退出／撤销证据引用、前一attachment_id／revision、新attachment_id／revision、新run_id／controller_id／owner_epoch、程序／配置摘要、阶段及安全原因。阶段限PREPARED／ATTACHED／FENCED；未知响应是调用方观察，不通过重写记录抹去已生效绑定。接管序号用CAS推进，同键同输入只返回原事实，异输入拒绝；新的后端不能继承上一个后端的request_id与活能力。

| 中断点 | 固定处理 |
| --- | --- |
| 原后端仍活／只有控制连接暂断 | 不改变当前接收者；同一尚有效owner可重新认证原连接，另一个owner不能用超时夺取资格 |
| 已封闭旧资格，尚未提交新绑定 | 原模型和新工具仍关闭，只观察／原策略收尾；新请求须重核完整前提 |
| 新绑定已持久，能力／应答丢失 | 同一实际新后端按原request_id查询，可重新取得同一原pidfd的副本；接收器关闭重复副本，不生成新attachment或新实例 |
| 新后端拿到能力，业务投影未补记 | 只补固定接管事实及原等待，模型仍关闭；不因为业务库缺项撤销保护或重启任务 |
| 接管期间新后端又退出 | 原执行控制侧封闭该attachment，下一后端从新前序revision重新核对；禁止让迟到应答授权已退出／另一接收者 |
| 原执行控制进程重启或原能力丢失 | 新control_runtime_id不继承旧活能力；拒绝继续接管，只按原恢复路径观察／停止／保全，必要条件不明仍UNKNOWN |
| socket重建、原新消息或模型外发已未知 | 不重播字节／SSE／请求；各自查原记录，不借新监听或新attachment恢复旧窗口 |

**活进程引用。** 在宿主受保护控制连接上，本候选要求用SO_PEERPIDFD取得实际peer引用，再结合每个控制帧的SCM_CREDENTIALS、已准入程序／UID／命名空间和当前单实例资格认证；pidfd不验证程序本身。该路径需要固定内核和封装支持，不能只读SO_PEERCRED的数字PID再无条件pidfd_open当成同一个连接来源。[Linux v6.8实现](https://github.com/torvalds/linux/blob/v6.8/net/core/sock.c#L1671)从socket保存的peer进程引用取得pidfd；[pidfd说明](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)给出进程退出观察能力。这些是候选机制依据，实际Ubuntu／云内核仍须验证。

仅在已认证的控制通道允许固定ATTACH响应携带一个原OpenCode pidfd副本；完整帧同时绑定原实例、当前attachment及control_runtime_id，接收端核验实际FD类型、引用归属、未退出状态及当前控制资格，异常／截断／多余FD全部关闭后拒绝，成功副本也在失效时关闭。[SCM_RIGHTS语义](https://man7.org/linux/man-pages/man7/unix.7.html)传递打开对象的引用，接收FD数值可能不同，不能把数字写日志再复用。模型入口仍按4.15.4拒绝全部SCM_RIGHTS，工具／浏览器接口也不因此获得句柄传递功能。

原生控制口令由control按原实例生成，内部模型能力由业务按7.11.10使用独立材料签发；两者在原执行控制进程的受保护活对象中保留，以支持已定义的有限接管。按7.11.9，原生Basic凭据仅由原控制适配使用，不交付业务后端；接管只向已核验新后端交付原模型网关所需的内部能力，原生控制使用新的attachment访问同一控制进程。日志／持久接管记录只存不可逆摘要与引用。不得从OpenCode用户目录、进程环境扫描或普通备份“找回”凭据，不新增供应方密钥托管。原控制程序失去活对象就不支持继续接管；不会为可恢复性新增通用秘密持久服务、调试权限或通过pidfd_getfd抽取别的进程FD。原控制程序／内部实例配置的既定秘密防护仍需准入，不承诺语言运行时对象释放等于物理内存擦除。

新的model source proof明确同时绑定原执行范围与current_run_id／current_owner_epoch、attachment_id／revision、control_runtime_id及新listener_instance_id；原launch_run_id／原owner另保留，不用新身份改写历史。已撤销proof永不重用；每次原发送提交点检查这些活绑定、原根pidfd和业务窗口，控制进程死亡／策略变化即停止新准入。提交点之前失效拒绝，已可能外发的原请求按实际结果与费用核对，不能以事后撤销倒记未发送。

业务与控制记录无法做跨存储事务，因此顺序固定为“持久封闭旧资格→持久接管绑定→活能力交付→原业务等待／观察补记→用户明确新RESUME”。每一步允许只补原事实；接管或源核验失败不影响原终止／只读保全的权限，但不能跳过其停止证明。当前原TaskModelRoute.queue_continuation需要旧活_window，Linux须增加只接受已核验旧结束证据及当前attachment的新窗口准备分支，不能先构造一个伪造的旧OPEN route来绕过检查。

实施须联合覆盖process_lock／guard_controller_binding的Linux实际身份、RuntimeTaskRecovery平台门面、task_instance_driver的owner重建、coding_model_listener的路由／监听生命周期、task_model_ingress的来源与窗口、task_resume_runtime跨任期拒绝、原停止／等待投影及严格解码。Windows原恢复动作保持其范围；普通P1不依赖接管能力。固定包准入还要验证保留期限、断连／死亡区分及资源占用；若需要常驻代理续转模型、持久克隆会话或远程选主才可工作，退出本候选，不扩大到分布式恢复系统。

#### 7.11.7 控制报文与最小离线准入矩阵

本节细化原6.7控制通道与7.11.6接管；不增加调度器、第二套持锁服务或通用RPC。固定OC201-CONTROL-FRAME-1使用pathname AF_UNIX／SOCK_SEQPACKET；模型入口仍为4.15.4的SOCK_STREAM，两者不共用接收器。一次sendmsg对应一条完整控制报文，UTF-8严格JSON载荷至多64KiB，未知字段／重复键拒绝；大工具输出沿原结果引用读取，不在此拆片或传大文件。原生HTTP请求／响应的有界分帧单独使用7.11.9的固定协议和独立pathname端点；不能把其DATA帧塞入普通控制动作。

原动作、请求键、环境／数据代次、实例／当前attachment与control_runtime_id及输入摘要沿原控制契约；首次建立绑定使用该动作的明确空值分支，不信任客户端自报当前runtime。响应关联原request_id、action及同一绑定，不接受跨连接迟到响应冒充当前成功；未知结果仍查原请求，不靠通道序号替代原幂等键。任何实现扩展字段必须先进入对应动作的固定Schema，不能接受任意dict透传。

接收前在listener与已接收socket启用并核验SO_PASSCRED；每次recvmsg必须得到一份完整SCM_CREDENTIALS，匹配该方向已经验证的peer与实际PID视图。缺失／零PID／身份变化／MSG_TRUNC／MSG_CTRUNC／未知辅助数据均拒绝；关闭该报文收到的全部FD。MSG_CMSG_CLOEXEC为接收FD设置close-on-exec，持有者仍负责显式关闭及禁止fork泄漏。[recvmsg标志](https://man7.org/linux/man-pages/man2/recvmsg.2.html)。请求及普通响应不允许SCM_RIGHTS；只有已授权ATTACH成功响应可携带恰好一个原OpenCode pidfd，同一辅助消息内有多个FD同样拒绝。重复成功应答只交付同一原对象的引用，关闭多余副本，不能创建新attachment。

连接建立、每条报文及实际派发检查的是联合条件：受保护socket目录及实际端点、SO_PEERPIDFD持有的原peer、逐报文凭据、受信安装程序与实际隔离策略、7.2的当前环境锁所有者、原任期和任务范围；新接管还必须证明原后端退出。锁文件内身份、UID相同、pidfd未退出或程序路径字符串任何一项单独成立都不足。程序执行替换可能保持PID／pidfd，仍须实际受保护程序和禁止非准入exec的策略；不给CAP_SYS_PTRACE／CAP_SYS_ADMIN等权限来补检测。锁、peer和原root只传私有证据引用，浏览器只收到安全原因。

首期完整候选按7.11.8将业务后端、执行控制及固定OpenCode放在同一Linux宿主PID／user命名空间，业务、项目工具与各执行实例分离非root身份；同一实例的control／OpenCode按7.11.9共用专属UID但使用不同强制profile、挂载和独立服务资源组，不能以UID代替角色认证；项目工具仍在gVisor内。不会将容器内PID与宿主PID混比，也不把不可见返回当作同一进程。不能为了让数字相等而默认启用host PID、特权容器或挂载宿主/proc；未来若改成容器部署，须另行证明双向身份、文件视图和生命周期，不能沿用当前宿主服务证据。当前已选择参考拓扑，实际服务包／权限／内核组合仍待准入。

[Unix套接字规则](https://man7.org/linux/man-pages/man7/unix.7.html)提供报文边界、凭据及FD传递基础；上述报文大小、严格字段、联合资格和拒绝策略是本项目选择，不是内核自动提供的业务授权。数据提前到达、共享连接、异常辅助数据和两侧命名空间都须实测。

以下是7.11.1既有两阶段来源原型的前置输入及检查矩阵，均未执行；不另开一轮真实模型测试：

| 阶段／输入 | 最小观察、故障及通过边界 |
| --- | --- |
| L0 固定现场清单 | OS／CPU、内核包／配置、libc／绑定摘要、实际本地文件系统、安装根与ACL／组、各进程PID／user／mount命名空间和策略摘要。任一未知标未准入；ARM与云x86分别记录，不猜宿主能力 |
| L1 锁对象与互斥 | 新隔离环境准备同一锁、两套不同data_root及竞争应用／维护进程；固定根不能unlink／rename，缺失不补建，F_SETLK冲突／异常分类。外部F_GETLK正确观察原owner；额外close、fork、exec、dup／传FD作为失败对照，仅限一次性夹具。对应PKG-09—10、SRC-43—44 |
| L2 控制连接与凭据 | 先用固定无业务夹具核对peer pidfd、每报文凭据、早到数据、共享fd后的其他发送者、截断／超限／额外FD、重复响应及fd清理；错误程序／同UID不同进程／命名空间不匹配均拒绝。夹具成功只证明原语，不能准入实际OpenCode。对应SRC-45—46、48 |
| L3 活资格与有界失效 | 仅原后端退出、仅连接断开、持锁丢失但原后端仍活、执行控制死亡及接管中再次退出；验证原lease退休、旧任期永不复活、已可能派发结果保留、无隐式新消息／外发、资源占用不提前释放。对应SRC-37—42、47 |
| L4 实际候选联合准入 | 固定应用／执行控制／OpenCode及工具包、原生端点、7.11.8宿主服务拓扑、最小权限、原root引用和模拟供应方联合通过；接入既有六工具／来源与恢复矩阵。更换包、内核、架构、挂载或权限组合须评估并重验受影响项，不能只拿L1／L2结果开放产品 |

每次故障场景仅使用测试方拥有的新目录、固定虚拟任务及子进程；事先固定每场景时限、资源上限、进程归属和finally清理，超时终止本测试资源并如实记录未通过。证据只留项目允许的Markdown摘要，记录输入摘要、实际观察、失败与未覆盖，不保留秘密／原始报文／测试数据库。不得触碰当前业务锁／数据库或运行中的用户服务；网络不得触达真实供应方，模型／计数／付费补证为零。当前仅设计，实际原型需后续任务明确授权。

ENVIRONMENT_LOCK_CONFLICT只表示真实锁竞争；ENVIRONMENT_LOCK_UNVERIFIED表示锁对象／权限／程序或所有者证据未核实；ENVIRONMENT_LOCK_LOST表示当前任期持有条件已失效。作为启动诊断或原reason_codes使用，沿原HTTP错误和available_actions，不增业务状态。观察失效不自动清锁、重启或解除等待；未有本环境业务服务时由管理启动操作展示失败，不能伪造一个正常业务响应。

#### 7.11.8 OC201-HOST-SERVICE-1 首期部署与程序身份

首期参考部署选用Ubuntu宿主systemd管理业务后端与受信控制进程，项目代码仍由Docker／固定runsc沙箱执行；不要求把业务后端、控制程序和OpenCode都装进应用容器。此为当前候选的明确选择，替代前期“应用默认Compose、控制留在宿主”的笼统安排，不同时维护两条完整部署链。Mac上的宿主指Ubuntu虚拟机内部，不是macOS；云端指独立Linux VM。两地使用同一职责划分，各自固定ARM64／x86_64产物和证据。

| 组件 | 进程／文件系统位置 | 身份、网络及启动边界 |
| --- | --- | --- |
| 业务后端及原工作器 | 每环境一个systemd业务unit，Python／SQLite及应用包只读；本环境业务库由该进程独占 | 专用环境UID；宿主PID／user命名空间；只开放原受控业务入口和获准供应方出口，无Docker socket或通用systemd写权限 |
| 宿主执行控制 | 每原OpenCode实例一个固定unit及独占控制证据子域，绑定单一环境／任务／实例 | 按7.11.9与该OpenCode共用专属非root UID及私有网络，使用独立强制profile／挂载；不挂载业务数据库，不成为第二个业务写服务 |
| 固定OpenCode控制器 | 每原实例一个单独受管unit／cgroup，固定二进制及插件；可写会话元数据仅限该实例，项目源码不在此执行 | 与本实例control共用专属非root UID，其他实例及业务身份分离；仍在宿主PID／user视图中，私有挂载视图；与本实例control共用仅loopback的私有网络及明确挂入的pathname Unix端点，原生TCP控制按7.11.9 |
| 项目命令／文件工具及被测应用 | 已登记Docker／runsc资源，分别挂入限定任务副本；不与OpenCode共用服务组 | 独立隔离身份与PID／网络；无业务库、管理总线、控制秘密、宿主/proc或Docker接口；原操作和完整停止规则保持 |
| 入口及管理 | Caddy与既有管理程序各自为宿主服务；前端固定产物按原入口提供，开发Vite按任务单独运行 | 只承担原入口／部署职责；不把systemd管理接口暴露给浏览器，管理退出不停止全部业务 |

上述固定包／完整来源证明用于完整候选与生产；P1普通开发仍可按3.2使用明确工作区来源，且不启动执行控制或取得完整执行资格。执行身份不得与业务、管理或外部开发共用；旧实例的全部资源未核清退出前，不复用其身份或可写元数据位置给另一实例。

同一PID命名空间只统一内核观察坐标，不自动授予共享目录或任意信号／调试权限。同实例control／OpenCode的专属UID例外、单向只读观察与强制隔离按7.11.9执行，其他角色和实例仍分UID。PID命名空间子层不能看到祖先中的进程，跨层Unix凭据也会转换到接收者视图；不能用一个自报NSpid列表补齐认证。[Linux命名空间语义](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html)。本候选不新建PID／user命名空间来包住这些受信控制进程；它们仍须通过实际UID／组、AppArmor及权限约束，项目沙箱保持自己的隔离边界。

**固定服务与安装权限。** OC201-HOST-SERVICE-1归入运行包与安装清单，固定systemd／内核适用范围、unit模板及全部drop-in、启动入口／argv、程序与依赖闭包、身份／组、挂载与可写根、网络与LSM策略、资源上限、停止／重启策略和允许的管理动作。unit名称由受信安装或原实例ID派生，HTTP不能提交unit名、ExecStart、User、环境变量、任意systemd属性或路径。应用、Agent、开发身份不能编辑unit或取得org.freedesktop.systemd1.manage-units等通用写权限。

需要特权的身份／命名空间／cgroup准备由systemd及原Linux受限启动适配完成；适配只接受已登记模板、环境／实例和固定发布引用，核对原操作后展开参数，不把StartTransientUnit或systemd-run任意参数透传给非特权调用方。每实例挂载可由该受限入口生成严格模板实例；它属于既定执行适配，不新增常驻调度服务。只限定unit名前缀不足以放行任意属性。真实特权最小集合与模板展开代码仍须安装准入，不能让业务／Agent整体以root运行来省略该边界。

unit使用Type=exec、固定前台主进程、NotifyAccess=none；不使用PIDFile猜主进程、forking服务或包装shell后台化。若必须有固定启动器，它只完成原准备后exec目标并退出启动阶段；业务及Agent的来源证明只接受目标运行阶段，不能把启动器的pidfd存活当目标已就绪。Type=exec只证明执行入口已成功，依赖／插件／配置、真实监听、原会话和业务握手仍分别核验。参考[systemd v255服务定义](https://github.com/systemd/systemd/blob/v255/man/systemd.service.xml)，实际Ubuntu修订需固定检查，不假设版本号相似就支持全部选项。

**实际进程到受信程序的证明链。** 不扫描其他身份的/proc环境或引入调试权限。候选优先复用系统服务管理器已有的只读身份接口：

1. 从真实受保护Unix连接取得SO_PEERPIDFD，保留原引用并检查仍活；逐报文凭据与之匹配。连接不能来自任意自报PID或从历史记录重新打开的数字。
2. 通过受信系统总线调用GetUnitByPIDFD，取得该原进程所属unit及InvocationID；再核对当前MainPID确为该peer线程组，不能接受同unit的任意子进程、ControlPID或历史ExecMainPID。固定unit映射到预期角色、环境和原实例，不能只匹配名称前缀。取得事实前后核对manager服务持有者／boot、unit代次和原pidfd仍一致，失败保持未核实。
3. 核对安装清单与systemd实际加载的有效属性，包括全部drop-in、入口、非秘密配置引用、运行身份、挂载及限制。仅检查磁盘unit文件或MainPID不够；程序源码、解释器、依赖和动态库必须是同一受保护闭包，不能把“都是Python”当同一个后端程序。开发工作区的可变源码不获得完整执行资格。
4. 以实际内核LSM观察核对预期运行profile及强制状态；策略限制进入目标程序的执行转换、可加载文件、后续exec和权限改变。若存在启动器，采用明确目标转换且禁止失败回退到继承／不受限模式；进入运行profile后禁止任意再执行及切换profile。SO_PEERSEC只作为连接关联标签，不能独自证明持续程序身份；同PID仍可能exec，故实际禁止规则与固定启动链缺一不可。
5. 最后联合7.2真实持锁者、当前owner_epoch、原control_runtime_id／attachment、操作范围和业务授权。unit及安装证明不代替任务权限，也不自动开放模型窗口。系统总线或必要观察失败时不缓存上次通过继续新派发；已可能执行的原动作按原事实核对。

固定[v255管理接口](https://github.com/systemd/systemd/blob/v255/man/org.freedesktop.systemd1.xml)及[实现](https://github.com/systemd/systemd/blob/v255/src/core/dbus-manager.c)提供GetUnitByPIDFD，并在返回前重核进程引用；它只返回所属unit／调用代次，完整程序准入是上述项目组合，不是systemd替我们验证了所有文件。实际目标缺该接口或受限权限不可用时，本候选不退回PID字符串。只读查询权限不授予服务启动、停止、属性变更或守护程序重载。向systemd传pidfd只用于这条受信系统总线查询，不放宽7.11.7的控制通道FD规则；不将其转发给模型或浏览器。有效属性按固定非秘密白名单逐项读取，不抓取完整Environment／凭据或整份D-Bus属性转储。

私有证明记录绑定format_version=1、host／boot、受信manager代次引用、unit_id、原InvocationID、unit_manifest_sha256、effective_unit_sha256、program_manifest_sha256、运行角色／原范围和策略引用。InvocationID按systemd原16字节标识以32位小写十六进制保存，不强改成项目UUID v4；PID／pidfd只作为活对象，不落盘后重新授权。原OpenCode unit代次不因后端接管改变；新后端使用自己的新unit代次，控制进程仍必须保持原连续存活。秘密不得进入unit参数、D-Bus属性快照、通用Environment配置或journal；沿原私有启动通道交付，观察只保存安全引用和摘要。

**文件与策略必须真的生效。** 私有挂载视图中按明确安装映射开放本实例所需路径；与宿主指向同一锁／socket对象，而不是在两个同名目录各造一个。只挂pathname端点的受控父目录并禁止接收方改写，以便后端重启时原路径指向新监听对象；不固定bind-mount单个旧socket inode，也不暴露整个control_root。进入新模型监听仍须重新核验listener_instance_id及来源，旧连接不得复用。Agent看不到业务库、lock_root或供应方密钥；启动器只在7.11.10规定的bootstrap阶段访问受信系统总线，关闭全部相关FD后进入运行阶段，运行Agent无权连接总线。只隐藏路径不能撤销已经打开的FD。

AppArmorProfile设置在AppArmor禁用时可能不生效；PrivateNetwork及其他防护也有实际平台条件，不能仅检查unit文本。[systemd v255执行环境](https://github.com/systemd/systemd/blob/v255/man/systemd.exec.xml)。准入应实证profile处于预期enforce且无宽泛default_allow／执行回退，检查实际目录／网络拒绝、动态库／JIT兼容和后续exec拒绝；不为Bun能启动直接套用禁止所有可执行内存的选项，也不悄悄移除必要边界。[AppArmor策略](https://manpages.ubuntu.com/manpages/noble/man5/apparmor.d.5.html)与[Linux v6.8连接标签实现](https://github.com/torvalds/linux/blob/v6.8/security/apparmor/lsm.c)只是机制依据，具体内核与打包策略仍待验证。策略／unit变更须经原维护并使旧准入证据失效，不能热改限制后继续沿用旧通过；本协议不宣称可防御受信宿主管理员主动改写内核或安装状态。

**生命周期分开，业务停止保持原流程。** app、control和各OpenCode／工具资源使用独立服务或运行时组；不能把Agent作为业务unit中一个普通后台子进程，再指望业务重启后它必然存活。不配置让业务重启自动传播到control／Agent的PartOf、BindsTo或等价依赖；仅建立必要启动顺序，实际可用性仍由准入检查。首批相关业务／控制／Agent unit均Restart=no，只有原管理或业务动作启动；不通过守护程序自动重启来绕过恢复。

每unit使用完整进程组跟踪，不能以KillMode=process或none掩盖残留；正常维护先完成原业务收尾，再请求已登记unit停止。SendSIGKILL=no与有界停止超时配合，超时记录未知及保留占用；若原明确停止策略另允许强制结束，只按该策略和原范围执行，不由部署默认值额外授权。系统关机、OOM和管理员强制操作仍可能杀进程，按故障处理而非安全停止成功。[systemd停止语义](https://github.com/systemd/systemd/blob/v255/man/systemd.kill.xml)。控制进程故障／重启不使原活能力恢复，后端只重启的有限ATTACH仍需原control与Agent的unit代次及活引用未变；全部关联资源与候选收尾核清后才释放任务占用。

**原生OpenCode控制入口仍是独立门槛。** 固定源码810c0eba1a7348036f8bdf61e6632d0c36c6876c的[Server.listen](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/server/server.ts)按hostname／port创建TCP监听并要求TcpAddress；不能把Bun底层可用Unix套接字，写成该固定CLI已支持Unix原生控制入口。[插件client装配](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/plugin/index.ts)在已有serverUrl时走该地址，仅无serverUrl分支使用进程内fetch；正常serve模式不能假定插件client自动绕过网络。

因此模型Unix入口、宿主SEQPACKET控制及OpenCode原生HTTP控制是三条不同通道。7.11.9选择由原执行控制适配在同实例私有网络中接入原生TCP，业务后端只访问受保护Unix操作入口；不向普通宿主端口发布。原生通道仍须独立准入，不能用模型fetch成功、HTTP可达或服务active代替。就绪诊断EXECUTION_DEPLOYMENT_NOT_ADMITTED及NATIVE_CONTROL_TRANSPORT_NOT_ADMITTED沿原reason_codes，不新增业务状态或绕过开关。

#### 7.11.9 OC201-NATIVE-CONTROL-1 原生连接与有限转送

**选择与范围。** 复用现有opencode_control／opencode_instance_control的固定动作和校验，将实际HTTP连接、Basic凭据及SSE接收放入原宿主执行控制适配。业务授权、原操作／步骤、消息内容、费用及模型窗口仍由业务后端决定；控制侧只执行已核验的原生动作，不生成消息、不自行决定权限或恢复任务。这里是有限协议适配，不实现任意HTTP代理，不fork OpenCode核心，不新增独立网络转发守护进程。

已比较现成[systemd-socket-proxyd](https://man7.org/linux/man-pages/man8/systemd-socket-proxyd.8.html)：它可以跨私有网络转送字节，但不会传递原对端的Unix凭据／pidfd，不能独自完成本项目的原实例与原请求核验；本候选不采用它作为认证控制通道。复用systemd的网络／生命周期能力和现有原生方法，把必须自写的部分限于平台连接证明、严格本机传输及原回执关联。该取舍不等于现成代理功能有缺陷，也不改变模型通道禁止代发的规则。

首期将执行控制由可跨环境共用的一份进程，收敛为每原OpenCode实例一份固定control unit；它只管理该原范围及其工具资源。控制证据使用既有control_root下独占的原实例子域，无跨实例可写索引，不把多个写入者放到同一原子指针。control_runtime_id继续指这一真实进程的连续生命周期。成本是每活实例多占一份轻量控制进程；沿原单宿主一个重任务额度测内存／进程／FD峰值，不据此提高并发或宣称预算足够。

**网络和身份。** 固定启动顺序为control建立私有网络 → 原受限启动入口启动对应OpenCode → 核验原实例 → 原生只读就绪核对。两unit均PrivateNetwork=yes，OpenCode的JoinsNamespaceOf只指定对应control，并固定启动顺序；安装方核验实际为同一网络对象，只有lo，无veth／默认路由或对外端口。systemd负责进入命名空间，业务／control不取得CAP_SYS_ADMIN或自行setns能力；控制所需模型／工具／受限启动及只读系统总线仍经明确的pathname Unix挂载。PrivateTmp不由这条关联意外共享；模板固定其选择和实际挂载。依据为[systemd v255命名空间关联](https://github.com/systemd/systemd/blob/v255/man/systemd.unit.xml)及[执行环境](https://github.com/systemd/systemd/blob/v255/man/systemd.exec.xml)，配置存在不代替实际观察。

为避免新增CAP_SYS_PTRACE，首期control与它唯一管理的OpenCode共用一个安装方分配的专属非root UID／必要组，其他实例、业务后端、开发者及项目沙箱均不共享。两者必须使用不同的受保护程序、AppArmor强制profile和挂载视图；同UID只是满足受限proc只读访问的条件之一，不构成身份或隔离证明。这一选择替代“control和Agent必定各自不同UID”的早期细节。

control仅获准读取已绑定原根的fd符号链接及网络命名空间身份，配合该私有网络中的只读socket诊断；不读取进程环境、内存、任意fd内容，不调用ptrace、process_vm_readv／writev或pidfd_getfd，不获CAP_SYS_PTRACE／NET_ADMIN。proc访问须同时满足内核PTRACE_MODE_READ_FSCREDS所检查的真实凭据／dumpable条件及AppArmor单向read／readby限制；不能为了通过而开放trace／tracedby或任意peer。control自身设置不可dump，Agent到control的proc读取、信号、profile转换和控制域文件访问均拒绝；项目沙箱无这两个身份／端点。挂载遮蔽与LSM必须同时证明同UID下不能修改对方配置／日志／回执、取得秘密或转交连接，不能只靠chmod或“代码不会这样做”。任一平台无法以该最小权限读取所需事实或维持上述隔离，就判本候选未准入，不回退到全局调试权限。

**先证明实际TCP对端，再发送凭据。** 每实例固定127.0.0.1与一个非零端口（初值4096，包含在包清单）；各实例网络独立，因此不需要宿主端口分配。关闭mDNS、端口0回退、代理、跳转、连接池自动重连及客户端自动重试。原进程由受信启动绑定建立并保留pidfd；若启动阶段从systemd MainPID打开pidfd，必须立即用GetUnitByPIDFD、当前MainPID／InvocationID、boot／manager及有效程序证明前后重核，不能仅把数字PID重新打开视为原进程。此只适用于受信启动定位，Unix peer仍按7.11.8直接取SO_PEERPIDFD。

每条原生HTTP连接按以下顺序执行，失败关闭连接并沿原操作记未派发或待核对：

1. 重核当前业务peer／持锁／attachment、原control与OpenCode代次及活pidfd、固定程序／profile和真实网络对象；在同一私有网络核对固定监听。
2. 建立到该精确端点的TCP连接，但不发送HTTP头、Basic或正文。保存实际本地／远端地址和端口；禁止HTTP库失败后偷偷另建连接。
3. 通过NETLINK_SOCK_DIAG核对内核回复来源、序列、完整性及精确反向四元组，取得服务端ESTABLISHED socket的inode／cookie和UID；再将该inode与原OpenCode根进程的/proc/<原TGID>/fd只读符号链接对应。同时核对匹配该固定端点的完整LISTEN集合均属于同一原根，拒绝通配／其他进程的竞争监听，不只比较UID、端口或一条监听行。接受端尚未完成accept而无法对应时，只能在原截止时间内等待观察，期间零HTTP字节；不能先发送密码“促使连接成功”。
4. 重核连接仍为同一活socket、cookie／原根持有关系及前述活绑定，再进入原发送提交点。对有副作用的调用先持久记录MAY_HAVE_DISPATCHED，随后仅在该已核验连接发送一次完整固定请求。HTTP库auto_open关闭；不接受3xx换目标、Upgrade或任意Host／头部覆盖。
5. 响应／事件读取前后重核原根、代次与实际连接归属；结果完整且原输入对应才记录原回执。任何身份不明、短读、超限或超时不伪造成功，也不能因服务已退出就把已可能发送改成未发送。

[socket诊断](https://man7.org/linux/man-pages/man7/sock_diag.7.html)给出内核socket信息，不直接给出原进程所有权；[/proc进程fd](https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html)提供socket inode关联和受限访问语义。本方案组合仍须固定内核实测，不能用另一网络空间的/proc/net/tcp、ss输出字符串或SO_PEERCRED检查TCP来替代。cookie不是PID／授权凭据；上述观察不是原子租约，必须与禁止不可信代码／exec、受限FD传递、原pidfd和每次提交资格联合。已连接TCP不会因同端口新监听而改连新进程；原进程失效后禁止重连继承资格。检测前已发生的原动作仍可能有副作用，按原未知结果核对。

**冷启动不依赖插件先就绪。** 固定[serve入口](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/cli/cmd/serve.ts)以instance=false启动服务，实例按请求目录装配。control用上述TCP证明后访问原health／Basic挑战，再发绑定目录的原configuration读取，触发固定实例初始化；不先要求尚未加载的插件提供Unix控制入口。目录来自受信元数据装配，不能由业务正文或Agent传入。只有4.15.5的有效配置／依赖及模型、工具适配全部核实，才由业务授权开放模型窗口。原生口令由control按7.11.10的固定启动器握手交给原Agent，不进入unit属性、命令行或持久接管记录；不能从明文环境文件恢复它。Linux的内部模型能力另用独立材料签发，不向业务返还Basic来维持Windows原构造关系。读配置可能触发初始化，必须属于原启动／恢复步骤，不在浏览器GET轮询中隐式执行；测试只用假供应方。

**固定原生动作。** native_method是下表已有方法的固定标识，安装清单固定到具体HTTP方法／路径构造器及严格输入／输出Schema；业务不能提交URL、HTTP方法、头、directory或任意JSON。值和原任务／会话／message／permission／question对象从原业务步骤绑定，control按原输入摘要及范围复核：

| 固定方法集合 | 允许边界 |
| --- | --- |
| probe_health、verify_basic_challenge、configuration、verify_workspace_paths | 原启动／恢复核验；绑定唯一目录；不把配置读取扩成配置／认证写接口 |
| session、find_session、execution_status、message、pending、settled_turn、capture_turn_completion、original_turn_idle | 原会话／消息及有限清单观察；原分页／完整性判据保持，非业务GET自动触发 |
| create_session、update_session_permission、send_message | 仅原启动、继续、修复、角色交接及配置应用步骤中的确切输入；文本消息及稳定messageID，未知不得新建会话或重新发送 |
| reply_permission、reply_question、abort_session | 原决定／答复／停止步骤；范围、答复与原对象绑定；连接中断本身不授权abort或第二次答复 |
| reply_events | 原有限事件等待；先确认server.connected，事件属于原session／request才交给现有业务解码；不承诺历史事件重放 |

复用native_request_bytes、native_session_input、native_message_input等纯校验，拆除其平台类型耦合后接入；不能复制一套宽松Linux输入。权限变更仍不得扩大已准入范围；原shell／command／配置写入／任意工具和原生子任务路由全部排除。复合只读方法可以在同一原截止时间内执行固定读取序列；副作用方法只有一次固定HTTP派发，不能把“查不到”自动变成再发。原查证verify_message继续比对原稳定消息与完整输入，不借模型文本回显证明执行成功。

**有界分帧与原请求恢复。** 原生通道使用另一个受保护pathname SOCK_SEQPACKET端点，由同一control主进程创建；端点由受信实例装配派生并登记，业务只持原实例引用，不能提交任意路径；复用7.11.7逐报文凭据／peer程序／持锁／attachment核验。所有帧仍≤64KiB严格JSON，全部拒绝SCM_RIGHTS；普通控制ATTACH的单pidfd例外保持，不传TCP连接FD给业务后端。此通道与模型／工具结果端点不混用。

OC201-NATIVE-CONTROL-1帧种类固定BEGIN、DATA、COMMIT、STATUS、CANCEL、RESULT、EVENT及END，按方向和当前阶段严格解码。每帧绑定protocol、request_id、原实例／当前attachment、control_runtime_id和每连接每方向从0递增的seq；旧记录另保留origin_attachment，新attachment的STATUS只查旧记录，不重绑派发；BEGIN另含native_method、原业务operation／step、规范输入摘要／字节数、timeout_ms（1—30000，不能超过原步骤剩余时间；control从首帧起按自身单调时钟计时）。DATA用规范base64传至多32KiB解码字节，按连续seq重组；严格JSON输入总计至多4MiB，沿现有_MAX_NATIVE_JSON。禁止重复／缺片／换输入／跨request拼接，COMMIT仅在完整重算摘要、严格业务输入和当前授权均通过后才可接受，收片不派发HTTP。组装超时／取消／断开清理本请求临时数据；未COMMIT的该request_id封闭，不在原连接上重传分片。

STATUS只返回该原请求的已存派发／回执事实，不发原生HTTP；RESULT／END回传固定状态、完整性、原响应摘要及有界分片，不含Authorization／认证头。JSON响应仍受原方法上限约束，最大4MiB，不因分帧提高原限额；同键同输入在重连后只能STATUS取原结果，异输入冲突，不能重新COMMIT。取消在提交点前证明未派发；提交点后只关闭读取并保留MAY_HAVE_DISPATCHED／实际回执，不能撤销原生副作用、自动abort或伪造已取消成功。新的明确动作须沿原业务恢复规则判断，不能通过换request_id重做未知请求。

HTTP与事件等待保留当前最长30秒的单次截止时间（包括组装／校验／连接／读取），业务原步骤可更短；序号／超时不代替原幂等键。SSE保持原OpenCodeEvents的MAX_EVENT_BYTES=4MiB+16KiB、MAX_STREAM_BYTES=2×MAX_EVENT_BYTES及MAX_EVENTS=256限制；逐事件严格解码，再经EVENT有界分帧返回，END标明是否完整；不得无界缓存或漏掉事件后报空列表。每实例初值至多一个变更调用、一个只读调用和一个事件等待；STOP／取消保留独立受限控制入口及优先额度，不被慢事件消费堵住。慢接收、队列／事件过限或断开关闭该等待，原结果待核对；不无限扩容、不自动重放SSE或副作用HTTP。帧Schema实物、固定方法路由表及资源参数随固定包交付；错误沿原ORIGINAL_TASK_CONTROL／EVENT及ORIGINAL_OPENCODE诊断归类，再投影原NATIVE_CONTROL_UNVERIFIED／等待，不造可自动重试的成功回执。不能只有逻辑名就开放能力。

持久native记录归原实例控制证据域，键为原业务operation／step、固定native_method及调用序号，request_id只是该确定键的规范引用；输入摘要、原attachment、派发状态、响应摘要／完整性及安全原因不可变追加，原秘密不落盘。读写请求都先绑定原业务依据；新attachment查询旧原记录只用于核对，不把旧键换绑为新派发权。副作用请求先记录可能派发，再写HTTP；崩溃窗口即使实际尚未发送也保持待核对，不能以“尽量恰好一次”冒充OpenCode原生幂等保证。结果内容缺失只保留可证事实，沿原方法只读核对，不为了补输出再运行。

**断线与接管。** business Unix断线立即封闭该连接新派发，停止未提交组装，关闭该连接所开的HTTP／SSE；原native记录保留。已经受理的OpenCode动作可能继续，模型／工具窗口另按原lease／失效规则处理。仅断线不能证明原后端死亡；同owner重连先认证并STATUS，不自动继续旧消息。后端确实退出后，7.11.6有限ATTACH仍要求原control／OpenCode连续存活；先保全所有旧native调用，重新证明原端点，只开原只读核对，再按4.23.2决定是否可提供新的RESUME。旧有副作用调用未核清仍阻止继续；新attachment不重建旧SSE，也不使原Basic凭据变成业务层通用访问令牌。

control退出／重启不自动带起新control并绑定旧Agent，即使systemd因命名空间关联仍能找到同一网络也不成立；原进程、同名unit、原会话磁盘或相同端口均不能恢复丢失活能力。完整停止覆盖原control／OpenCode、原生连接、工具及受管写入；仅停止控制连接不能释放任务。7.11.8的Restart=no、独立资源组及原停止授权保持。

**未准入及实施顺序。** 本节将连接方法从未选定推进到明确候选；尚无Linux代码或运行证据。先在7.11.7的L2／L4证明“原根已accept但尚无HTTP字节时可核验”“无CAP条件下proc观察与强制策略可共存”“同UID反向读取／信号／写回执被拒绝”，再验证固定OpenCode启动、完整方法集合、分帧与断线矩阵。任一前置失败，不扩大宿主权限、不发布端口、不长期fork原生API，重新评审该候选。部署／传输未准入仍用原诊断；已运行通道失效用NATIVE_CONTROL_UNVERIFIED并保留原未知等待，不新增自动重试码。模型来源仍按4.15.4由OpenCode直接发Unix请求，control不转送模型字节。

#### 7.11.10 OC201-STARTUP-1 安装、启动阶段与秘密交付

本节收敛7.11.8—7.11.9的安装候选，不新增常驻凭据服务、通用进程调试或业务状态。systemd负责身份、命名空间和生命周期，AppArmor负责强制边界；项目只补固定启动器、原范围握手和现有校验的Linux装配。实际unit、策略、启动器和故障矩阵仍未生成／执行，不能把下列配置意图当作已安装证据。

**安装清单及单向观察。** 每实例control／Agent使用同一专属UID和主GID；各自real／effective／saved／filesystem身份一致，补充组限定且不带管理权限，能力集合为空，无setuid／setgid／文件capability入口。control读取原Agent的fd链接仍必须同时满足PTRACE_MODE_READ_FSCREDS、实际dumpable及LSM，而非只比较UID；同一user命名空间下的能力比较也不能遗漏。只允许原绑定peer间的ptrace read／readby，两个方向的策略均须匹配；不得省略access列表而授予全部ptrace权限。Agent到control的read／trace／信号及控制文件访问拒绝，control本身保持不可dump；不通过CAP_SYS_PTRACE、pidfd_getfd、process_vm或降低宿主ptrace_scope补通。[proc访问](https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html)与[ptrace访问判定](https://man7.org/linux/man-pages/man2/ptrace.2.html)支持这些条件；Yama针对ATTACH的限制不等同只读fd检查，不能将两者混为一项开关。

安装清单除原unit／程序闭包外，固定bootstrap和运行阶段的完整LSM标签集合、策略源／编译结果及内核特性、proc挂载与hidepid／ProtectProc实际效果、每实例网络对象、秘密入口挂载、core／swap限制和输出去向。SystemCallArchitectures=native；需要socket／netlink／线程的具体调用按固定包验证，不套用会破坏Bun线程或JIT的通用禁令。control只能读取原TGID的fd链接、必要网络身份及原准入事实，不开放mem／environ／任意进程读取；实际策略不能只写“对所有同UID进程可读”。若AppArmor的peer标签不能单独区分实例，还必须以专属UID、挂载、实际pidfd和原范围共同收窄，不把标签名当任务身份。

**启动阶段只收紧权限。** 固定启动器是原OpenCode unit的前台主进程，完成握手后在原PID中exec唯一固定二进制；无shell、用户插件、任意argv或先fork再认领子进程。启动阶段允许受保护bootstrap端点、必要只读systemd查询及这一条执行转换；运行阶段禁止bootstrap、系统总线、任意再exec及策略切换，仍允许已定义的模型／工具Unix通道。全部辅助FD在exec前关闭或CLOEXEC，0／1／2按固定null输出配置，禁止把bootstrap连接、总线连接或秘密文件FD留给Agent。

NoNewPrivileges=yes从启动器开始保持。候选采用保留bootstrap约束并叠加运行profile的执行转换，完整运行标签是两个约束的交集；运行profile拒绝后续exec，bootstrap中的执行许可不能绕过它。不采用从一个受限profile直接换成另一个不相关profile、再声称“新规则更严所以NNP必然允许”的方式。NNP检查与叠加语义见[Linux v6.8 AppArmor执行转换](https://github.com/torvalds/linux/blob/v6.8/security/apparmor/domain.c)，具体策略语法和编译产物须随目标AppArmor包验证；没有成功的完整标签证据就不准入，不关闭NNP或回退unconfined／inherit模式。

受保护入口无凭据／能力提升，启动器与目标的UID／GID保持一致。使用安全环境处理的明确转换，不通过放宽执行模式维持环境；固定环境白名单中的OpenCode认证字段必须实际保留。安全执行标记、dumpable和NNP不是同一属性：不能仅凭Px名称断言进程必然不可dump，或凭启动前dumpable值推断exec后仍可读。固定[v6.8 exec](https://github.com/torvalds/linux/blob/v6.8/fs/exec.c)及[凭据提交](https://github.com/torvalds/linux/blob/v6.8/kernel/cred.c)分别处理这些条件；准入必须在真实exec之后、发出首个HTTP字节之前验证原根fd可读、完整运行标签和凭据／能力未变。后续变化按通道失效处理，不临时调回权限。

**秘密的来源与交付。** 固定OpenCode认证字段从环境读取，见固定提交的[Flag实现](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/core/src/flag/flag.ts)。启动器仅在内存形成严格exec环境：既有非秘密运行值，加OPENCODE_SERVER_USERNAME／PASSWORD及WALLE_CODE_MODEL_BASE_URL／BEARER；不得直接继承调用者环境、代理、加载器变量或任意配置。启动参数、unit Environment／EnvironmentFile、D-Bus属性、可持久恢复的临时文件均不承载这些秘密。systemd的[LoadCredential](https://github.com/systemd/systemd/blob/v255/man/systemd.exec.xml)是可复用的成熟文件／Unix凭据交付机制，但不会自动替本项目绑定原业务操作／活进程，也不能让此固定CLI直接读取凭据文件。本候选选用既有control的私有握手，不同时维护第二条秘密分发链；不否定LoadCredential本身的适用性。

原生Basic由原control生成并仅存活内存；业务后端不持有它。内部模型能力仍由原业务网关签发／保留，control仅向原启动器转交一次，不因此取得模型窗口或代发权；真实供应方密钥始终留在业务网关。现Windows实现从原生口令种子派生模型能力的装配不能直接照搬：Linux装配为两类秘密使用独立随机材料，保留既有范围／路由／窗口校验和安全引用，禁止把Basic送回业务来复用旧构造器。模型能力经已认证的原业务控制连接交给control，绑定原operation／step／实例／attachment；该初始秘密消息作为CREATE准备的严格子消息，最大16KiB、全部拒绝FD，不扩大其他动作的输入；只持久化非秘密引用，不将秘密并入普通幂等规范输入、查询响应或通用请求日志。原ATTACH对已经运行实例只续接原活能力，不重发启动秘密。

启动器与control在单独受保护pathname SOCK_SEQPACKET端点握手，全部报文≤16KiB、严格固定字段、拒绝任何SCM_RIGHTS；不共用native分帧入口。control用真实SO_PEERPIDFD、逐报文凭据、GetUnitByPIDFD／当前MainPID／InvocationID、预期bootstrap标签和固定程序闭包核验原启动器；启动器经同样的受信manager／安装锚点核验原control角色、范围及连续代次，无需读取control的内存或环境。端点、unit引用及范围均来自受保护启动描述，不能用消息自报PID／unit决定接受对象；未完成双向核验前不发送秘密。

握手固定HELLO → GRANT → RECEIVED：HELLO绑定协议、原任务／操作／实例、原control_runtime_id／attachment、启动清单摘要及原unit代次；GRANT仅携带该原范围的两类秘密和非秘密配置引用；RECEIVED只回安全引用，不回显秘密或其明文派生。control先将该启动交付绑定到原活pidfd并记录安全的“可能已交付”事实，再在原连接发送一次；丢回执不换连接补发、不改密码重试、不启动第二个Agent。启动器收到完整有效GRANT后关闭bootstrap及总线FD，再exec；RECEIVED与systemd active都不等于目标已执行或就绪。整次握手初值≤10秒且不超过原START剩余期限，超时／取消只沿原停止核对。磁盘事实只存原范围、清单／输入摘要、阶段和安全原因，不保存秘密帧；整个秘密载荷也不作为通用请求日志输入。

启动后重新核对同一活pidfd／unit代次、完整运行标签、固定程序和原端点，再按7.11.9完成先证TCP再认证、配置初始化及插件／模型／工具就绪。原模型窗口在全部条件满足前保持关闭；启动器的凭据握手不会触发模型。停止与交付并发时，control先封闭新的GRANT／原生派发并登记原停止；已可能交付或已经exec按原资源核对，不把“还没ready”当作未启动。exec失败、交付未知、control故障和原Agent退出均不自动重新启动；已持活引用可核对原资源，丢失活能力仍按原恢复／保全边界处理。全部关联资源核清后才释放UID／私有元数据与名额。

**凭据过滤与故障输出。** 现task_instance_driver在答案、问题／权限和原轮次读取等路径调用_check_credentials；迁移Basic持有者时必须同步迁移校验。control在COMMIT派发前检查完整请求输入，并对完整严格解码后的RESULT／EVENT，在任何持久化或向业务分帧之前检查Basic口令、完整Basic头编码及其持有的内部模型秘密；至少保持现有原值／URL编码／base64变体和递归字符串键值检查，业务仍独立检查自己的模型秘密及范围。不能逐片检查后边检查边放行，不能因为“业务没有密码”就删除原保护，也不承诺识别任意变换后的秘密。

命中时原始内容不进入控制证据、日志、业务库、SSE或浏览器；仅回安全失败原因及原派发／完整性事实，既有已可能执行或已核清效果保持。缺失输出不伪造成功、空事件或未执行，不重做动作补回内容。原生stdout／stderr不送journal；固定原生日志只放有界的实例临时区，不导出或纳入备份，临时日志也不允许包含上述秘密；准入检查原生错误路径和会话元数据，不以临时存储掩盖泄漏。安全诊断另由固定适配产生，不保存原始失败对象／环境转储；本规则不替代用户正文的正常持久化。

为维持只读fd观察，不能简单把Agent设成不可dump而声称仍可读取。首期专用Linux VM的安装候选同时要求业务／control／启动器／Agent的LimitCORE软硬上限为0、承载秘密的unit从启动前设置MemorySwapMax=0并核验实际cgroup限制，且宿主core_pattern为已登记的非管道模式；不使用默认管道转储后仅靠LimitCORE=0推断没有内存输出。[Linux v6.8 coredump实现](https://github.com/torvalds/linux/blob/v6.8/fs/coredump.c)的管道分支不按普通core大小限制处理。若宿主必须保留管道收集器，须另证在读取秘密内存前排除这些进程，否则当前候选不准入；不在用户Mac／Windows上擅自更改全局转储设置。该条件只针对选定的专用Linux VM，安装变更和ARM／x86证据分别固定。受信管理员主动取内存、虚拟机快照／休眠及主机级内存取证不在本应用权限隔离的防御承诺内，不能把“应用不落盘”扩大为所有宿主行为均无副本。

**交付与退出条件。** 安装输入是一套固定模板／策略、启动器闭包、秘密字段Schema、阶段转换表、输出规则及无真实秘密的正反夹具，仍归原7.11.1平台包，不另建运行时或第二套配置平台。以下顺序纳入L2／L4：先用无秘密夹具证明NNP下叠加exec及同UID单向观察，再用假凭据验证交付／失败输出，最后接固定OpenCode的冷启动与原生动作。任何一环需要全局调试权限、重新开放exec、将秘密放入unit属性、长期fork OpenCode或无法消除原生错误落盘泄密，就退出本候选并重新比较执行部署；不一边失败一边增加例外。

启动前权限／策略／转储或秘密装配不成立用EXECUTION_DEPLOYMENT_NOT_ADMITTED；目标启动后原生证明不成立用NATIVE_CONTROL_TRANSPORT_NOT_ADMITTED；已运行连接／输出核验失效沿NATIVE_CONTROL_UNVERIFIED并保留原结果未知及实际效果。内部bootstrap阶段不新增产品业务状态、浏览器凭据页或重试入口。

### 7.12 PKG-ENV-MODEL-AUTH 许可、审阅与外发索引落盘

环境许可属于不随业务快照回退的控制事实，采用control_root内受保护的不可变JSON对象和第3.6节control指针；**不为本单元新增业务费用表或向旧db20-r50补列**。业务授权／LLMUse／CodeTaskReservation／GuideRun仍保留原库结构职责；任何后续确需业务列变更须另发明确新Schema，不能借外层记录逃避原事务约束。

| 路径／对象 | 精确身份与用途 |
| --- | --- |
| model-access/operations/<request_uuid>/intent.json | 原scope={environment_id,data_generation,principal_id,request_id}、服务器operation_id、action、规范输入、input_sha256、created_at、accepted_control_revision及本命令预分配的permit_id／review_id（不适用为null）；UUID目录是服务生成映射，不是客户端路径 |
| 同目录effect-prepared.json、result.json | 准备事实含原operation／输入、预期control与许可revision、结果许可／审阅引用、预期完整控制变更及摘要；结果含state、effect_ref、实际版本和安全错误；PREPARE_REVIEW的control变更为null，仅封存预分配审阅ID及原结果，不推进许可版本。UNKNOWN不冒充APPLIED |
| model-access/permits/<permit_uuid>.json | 第3.9节不可变许可；活动权以control指针为准，旧许可文件保留供原证据核对 |
| model-access/reviews/<review_uuid>.json | 第3.10节不可变审阅，包含事实引用及高水位；重新审阅生成新ID，旧确认不被覆盖 |
| outbound-evidence/<source_generation>/<record_uuid>/ | binding.v1.json、send-intent.v1.json、send-committed.v1.json、result.v1.json分别固定绑定、发送意图、发送提交点及结果；不存完整提示词或密钥，不计算第二套余额 |

持久文件统一format_version=1、规范字节、独占新建／同目录完整临时写与fsync、原子落位及目录同步，读取严格Schema和大小限制。原请求目录由当前应用在稳定环境锁及进程内控制闸门下唯一建立；扫描索引可重建，不能以索引缺项认定原请求不存在。request UUID若被另一scope使用直接冲突，不覆盖。准备文件必须先于control CAS，control持有last_operation_id／last_effect_ref，后续变更前核清并补齐上一原结果；无法核清时冻结外发及许可变更。仅有intent不能自动重放命令；同原键再次提交仍需第6.8节当前准入。

权限文件仅受信应用／恢复工具可写，业务浏览器和任务不能传路径或修改。可信安装入口固定Schema与策略摘要；对象自报sha不成为信任根。环境许可不是秘密token；防修改来自目录／进程控制及原操作核验。恢复模式同样必须取得当前稳定锁；管理进程不并发写这些文件。

外发binding.v1固定source_environment_id、source_data_generation、record_id、original_identity、owner_ref、operation_ref、purpose、permit_ref、model_access_revision、configuration_sha256、provider_binding_ref、resource_set_ref、request_sha256、created_at。original_identity为受信原LLMUse身份或CountingJournal批次身份，含kind及原环境／代次；同身份唯一映射record_id。三个阶段文件均含format_version=1、record_id、binding_sha256、recorded_at及原阶段证据引用；提交点另固定admitted_control_revision／model_access_revision，结果另固定原结果与核对状态。阶段不可倒序，结果可以是UNKNOWN；不存在send-committed文件也不能在文件完整性不明时反推未发送。结果只引用原账／计数审计及可信结算证据，不在此记录可用余额。

供应方补证采用同一record_uuid下只追加的supplements/<evidence_uuid>.v1.json；不是覆盖result.v1或另建LLMUse。每份固定原binding摘要、适配器版本、补证原操作、来源类型、观察时间、规范事实摘要及原审计证据引用；供应方范围引用不可变provider_binding_ref及受信账号／地域／凭据版本引用，不保存秘密值。provider_identity分别保留inference_response_id、transport_trace_id和本次query_request_id及其来源；不可取得者为null并保留原因，禁止互相回填。

查询事实保存原QueryHour／时区、请求ID和安全返回身份；导出事实保存原Task.Id、QueryParams、状态、TotalCount／ExportCount、格式版本、内容摘要及参与核对的计量行uuid。匹配结论区分原调用归属、行覆盖、用量完整／最终性和冲突；不得用一个verified=true合并。无法匹配原binding的资料先进入受保护补证操作的未匹配清单，不制造record_id或污染原账；匹配后追加引用，原未匹配事实保留。大CSV不整份写入控制JSON，受限读取后沿原审计保存必要业务事实；临时下载与调试输出清理，不留原始测试报告。格式Schema／适配器及大小限制须随实际发布固定，本轮仅契约；缺少原审计存储接入时不得宣称补证已交付。

发送顺序：原业务准备／预留提交 → 外层binding及SEND_INTENT可靠落盘 → 闸门内最终核验并记录原发送提交点 → 一次网络派发 → 原业务结果／费用结算 → 外层结果索引。各文件／SQLite之间没有原子事务；任一发送可能性存在就不能将旧库NOT_SENT或缺结果当免费未发。撤销与发送提交点共用闸门；撤销不能承诺取消已经提交发送的请求，结果界面须保留该可能性。

CountingJournal继续负责每批请求和响应的原审计；模型用途／许可绑定通过外层索引精确关联，不另造“计数LLMUse”。当前idempotency.py限定APP-CODE／TEST等能力命名且绑定旧数据库锁；许可命令复用原操作持久化原则，但使用上述独立控制命令格式，不伪造Coding能力号，也不能直接绕过其锁断言。实现须统一稳定环境锁装配，保留原业务幂等事务。

备份包含这些对象的只读封存副本及高水位，实际恢复不覆盖当前control_root；宿主灾难必须将已核验旧证据导入新的历史命名空间，再重新核对完整范围，不能指回旧活动许可。原生效／撤销事实、未决费用最低证据及恢复审阅不按普通日志期限清除。Guide／计数／Testing／Coding的旧费用缺失补证仍使用各自原审计契约；本单元不提供通用人工改账／证据导入API，无法提供可信原记录即保持恢复阻塞。

以上定义物理文件与字段，不代表JSON Schema、写入器、适配器或新发布包已生成。平台发包必须固定新增文件Schema／程序源及完整准入检查，本单元控制JSON不增加业务表，最终新Schema的73表／301对象预期以第7.14节为准；control.v1.json是本稿尚未发布的格式，其Schema新增必填model_access并由固定发布摘要核验；不支持该Schema的程序拒绝启动。访问策略明确使用第6.8节v2，P1 v1不获得新权限；旧程序不得忽略新增许可字段后继续外发。

### 7.13 PKG-ENV-CHECK-GIT 平台资源、Git效果与复用映射

| 当前实际代码 | 本版适配与保留 |
| --- | --- |
| task_candidate_runtime／commit、candidate_materialization、content_package／publish | 保留原预留、seal、指针CAS及不重捕；替换Windows路径／私有包／拒绝写句柄，接原写入者停止与Linux不覆盖发布 |
| testing/run_ownership／run_stop、task_project_check_worker | 保留原owner、Verification／case完整集合、SERVICE子资源与停止核对；不以Linux返回空资源列表通过 |
| check_deployment_sources、check_driver_bootstrap／pipe_sdk／pipe_worker、check_driver_browser_process | 新Linux平台注册与固定启动／隔离；共享数据协议／断言，替换node.exe／Windows Chromium／LPAC／私有桌面，不能仅删除平台检查 |
| owned_check_http、check_case_evidence、project_check_dispatch／journal／result | 保留发送前端点证明、原步骤未知、不重放和有界比较；Linux需重新证明连接目标与结果通道 |
| git_bundle、git_repository_location／local_config／worktrees、guard_control_git_* | 固定LinuxGit包及真实文件／进程证据；原白名单、完整worktree、无hook／网络不变 |
| git_ref_protocol、git_baseline_ref_*、repository_baseline_input／validation／verify | 注册GIT201-BASELINE-1及完整origin，准备与commit分开；原Snapshot.retention_ref读取，不由当前代次拼接旧引用 |
| task_delivery_write／write_runtime／finalize、git_commit_input／receipts／receipt_store | 注册GIT201-LOCAL-1尾注与环境外层效果；保留停止栅栏、原payload、旧值／后代核对、postcheck和完成条件 |
| frontend/src/code-tasks/delivery-workspace／verification-history、testing/report/task-report、api对应解码 | 复用原页面和原命令，新增平台／服务器位置说明；不把环境管理登记交付REGISTER_DELIVERY当产品AcceptCode |

新增平台发布资源仍使用第7.4—7.8节清单／固定来源机制：Linux Runner、CasePack、测试fixture、SDK／浏览器闭包、Git及其库／协议能力、端点／结果通道／完整停止准入证据。案例包与工具包分开；模型或项目不能写受信发布目录。LinuxGit具体版本／发布来源／摘要与浏览器修订待实际产物准备时固定，不伪造hash、沿用Windows包或以版本名称代替验证。ARM和x86分别准入。

Git外部效果采用control_root/git-effects/<origin_data_generation>/<effect_uuid>/，不随业务RESTORE覆盖。首次写之前排他建立binding.v1.json，精确包含format_version=1、effect_id、origin_environment_id、origin_data_generation、owner_ref、operation_id、step_no、purpose（BASELINE_CREATE／DELIVERY_UPDATE）、repository_claim_ref、repository_identity_sha256、git_bundle_ref、protocol_version、full_ref、expected_oid（create-only时null）、planned_oid、payload_ref／sha256（BASELINE时null）、input_sha256、created_at。effect_id由受信首次意图固定；原env／代次／operation／step唯一映射，不能以文件名自报替代原操作。

prepare.v1、may-send.v1、ack.v1、observation.v1及closure.v1均引用原binding摘要及受信执行身份、真实时间和对应原GitReceipt；观察可按单调序号追加，不覆盖旧结论。业务操作先有原计划／对象依据，外层may-send可靠保存后才可进入原引用commit派发；任一外层／内层不一致按可能发生处理。正常模型外发索引与Git效果目录分开用途，共用原子记录／恢复原则，不建立新的业务调度或第二套Delivery。

恢复审阅的EXTERNAL_WRITES_RECONCILED必须覆盖此Git效果目录、恢复点后原库／回执及当前真实仓库；缺失较新索引不等于无写入。已知成功的原提交仍需对象可读和目标事实，冲突／缺失保持受阻；只有当前已知ref并不足以排除历史写入。结果补记仅原owner范围，旧代次记录不写进新同号Delivery。原效果与仍被引用的payload／候选包纳入备份资产，未决不清理；普通管理CLEANUP不能删Git锁、保留ref或效果证据。

当前原数据库中的仓库互斥仅覆盖同库repository_id，不能单独承担跨环境保护。实际git_common_dir的长期单环境归属沿管理resource登记；预览、基线登记和交付取得本环境仓库原操作互斥，未决保留。新跨环境申请在管理不可用／归属未知时拒绝；已合法绑定的原结果核对和停止沿持久回执，不依赖管理持续在线。跨宿主共享可写仓库／网络盘不在首期支持范围。

本节只定义新增资源和适配位置，未修改或发布实际包／协议；代码存在不等于Linux可用。完整浏览器端点／权威通道及Git持久性是实际准入门槛，缺项时对应能力不可用。资源清理按原范围保全正常CaseResult／报告／候选和交付事实，不保留临时trace／HAR／截图或原始测试JSON。


### 7.14 DB-ENV-BASELINE 跨代次Git基线约束

V2.01最终新库采用本节定义，P1即使用同一最终Schema并保持执行能力关闭；不先发布缺origin字段的P1库、再临时补列。本节是第7.6节普通绑定增量的必要修订：原code_snapshots表增加两个不可变来源字段，更新保留引用／策略约束及既有不可变触发器，新增原登记输入校验触发器。其他原业务表／对象不扩展；已有code_snapshots_owner_insert／update和外键继续保留。

下面为新发布的完整code_snapshots定义，替代新fresh生成器中的对应定义；不是对用户当前库执行的ALTER，也不覆盖原db20-r50：

```sql
CREATE TABLE "code_snapshots" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "repository_id" INTEGER NOT NULL CHECK("repository_id" BETWEEN 1 AND 9007199254740991),
  "registration_operation_id" INTEGER NOT NULL CHECK("registration_operation_id" BETWEEN 1 AND 9007199254740991),
  "content_profile_version_id" INTEGER NOT NULL CHECK("content_profile_version_id" BETWEEN 1 AND 9007199254740991),
  "commit_oid" TEXT NOT NULL CHECK(length("commit_oid") IN (40,64) AND "commit_oid" NOT GLOB '*[^0-9a-f]*'),
  "content_tree_oid" TEXT NOT NULL CHECK(length("content_tree_oid") IN (40,64) AND "content_tree_oid" NOT GLOB '*[^0-9a-f]*'),
  "origin_environment_id" TEXT NOT NULL CHECK (
    length("origin_environment_id")=36 AND length(CAST("origin_environment_id" AS BLOB))=36
    AND substr("origin_environment_id",9,1)='-' AND substr("origin_environment_id",14,1)='-'
    AND substr("origin_environment_id",19,1)='-' AND substr("origin_environment_id",24,1)='-'
    AND length(replace("origin_environment_id",'-',''))=32
    AND replace("origin_environment_id",'-','') NOT GLOB '*[^0-9a-f]*'
    AND substr("origin_environment_id",15,1)='4'
    AND substr("origin_environment_id",20,1) IN ('8','9','a','b')
  ),
  "origin_data_generation" TEXT NOT NULL CHECK (
    length("origin_data_generation")=36 AND length(CAST("origin_data_generation" AS BLOB))=36
    AND substr("origin_data_generation",9,1)='-' AND substr("origin_data_generation",14,1)='-'
    AND substr("origin_data_generation",19,1)='-' AND substr("origin_data_generation",24,1)='-'
    AND length(replace("origin_data_generation",'-',''))=32
    AND replace("origin_data_generation",'-','') NOT GLOB '*[^0-9a-f]*'
    AND substr("origin_data_generation",15,1)='4'
    AND substr("origin_data_generation",20,1) IN ('8','9','a','b')
  ),
  "retention_ref" TEXT NOT NULL CHECK(length("retention_ref")>0),
  "content_policy_version" TEXT NOT NULL CHECK("content_policy_version"='GIT201-BASELINE-1'),
  "registered_at" TEXT NOT NULL CHECK(length("registered_at")=24 AND "registered_at" GLOB '????-??-??T??:??:??.???Z'),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id"),
  UNIQUE(registration_operation_id),
  UNIQUE(repository_id,retention_ref),
  UNIQUE(id,repository_id),
  FOREIGN KEY("registration_operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("repository_id") REFERENCES "code_repositories"("id") DEFERRABLE INITIALLY DEFERRED,
  CHECK((retention_ref='refs/walle/baselines/'||origin_environment_id||'/'||origin_data_generation||'/'||id) IS TRUE),
  CHECK((created_at>=registered_at) IS TRUE)
) STRICT;
```

新Schema中code_snapshots_identity_fixed替换为以下完整定义，沿原字段不可变约束并增加origin；不是删除旧触发器后开放任意更新：

```sql
CREATE TRIGGER "code_snapshots_identity_fixed" BEFORE UPDATE ON "code_snapshots"
WHEN NEW."origin_environment_id" IS NOT OLD."origin_environment_id"
  OR NEW."origin_data_generation" IS NOT OLD."origin_data_generation"
  OR NEW."commit_oid" IS NOT OLD."commit_oid" OR NEW."content_policy_version" IS NOT OLD."content_policy_version" OR NEW."content_profile_version_id" IS NOT OLD."content_profile_version_id" OR NEW."content_tree_oid" IS NOT OLD."content_tree_oid" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."registered_at" IS NOT OLD."registered_at" OR NEW."registration_operation_id" IS NOT OLD."registration_operation_id" OR NEW."repository_id" IS NOT OLD."repository_id" OR NEW."retention_ref" IS NOT OLD."retention_ref"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER code_snapshots_origin_guard_insert
BEFORE INSERT ON code_snapshots
WHEN NOT EXISTS (
    SELECT 1 FROM code_operations o
    WHERE o.id=NEW.registration_operation_id
      AND o.resource_kind='REPOSITORY' AND o.resource_id=NEW.repository_id
      AND o.operation_type='REGISTER_BASE'
      AND json_extract(o.fixed_input,'$.snapshot_id')=NEW.id
      AND json_extract(o.fixed_input,'$.origin_environment_id')=NEW.origin_environment_id
      AND json_extract(o.fixed_input,'$.origin_data_generation')=NEW.origin_data_generation
      AND json_extract(o.fixed_input,'$.retention_ref')=NEW.retention_ref
      AND json_extract(o.fixed_input,'$.commit_oid')=NEW.commit_oid
      AND json_extract(o.fixed_input,'$.execution_profile_version_id')=NEW.content_profile_version_id
)
BEGIN
    SELECT RAISE(ABORT,'SNAPSHOT_ORIGIN_MISMATCH');
END;
```

REGISTER_BASE受理事务从当前environment_binding固定两项origin到原code_operations.fixed_input及各步input_ref；程序严格校验来源、完整字段／类型和同一原输入，不接受客户端提供origin。之后在事务外create-only原引用，完整核对后才沿repository_baseline_verify的原事务INSERT Snapshot并完成步骤；不提前把待登记行当有效基线。

插入触发器比对不可变原登记输入，**不要求其代次等于插入时的当前代次**。恢复后原REGISTER_BASE仍在库中且已有可靠外部成功时，允许在专用恢复范围核对并补记原事实，不能因此重发引用写入；若把trigger写成只认当前代次，会误挡这条恢复路径。旧操作行也缺失时仅保留外层孤立效果，不能新造同号操作／Snapshot冒认成功。

恢复采用完整库／资产到新根后只改当前binding，不逐行重插历史Snapshot；历史origin／retention_ref保持。历史读取不按当前代次重算引用，但须核对其原来源、保留引用和对象。普通应用不得直接写schema、关闭触发器或把历史引用改名。

相对原72表／299对象：新增environment_binding表和本节插入触发器，修改code_snapshots表及identity_fixed触发器，预期73表／301对象、其余297对象不变；这只是待生成／执行核对的设计计数。必须在新DDL／objects清单、来源构造器与pin中同步，不能沿用原299对象全部不变或上批73表／300对象预期。字段结构及约束变化要求新的Schema发布身份，即使schema_version仍按第7.6节为200也不代表与旧db20-r50兼容。

本轮仅从旧DDL读取并生成上述文档文本，未执行DDL、未改构造源码／资源或业务库。新建及本版同结构备份恢复是本次目标；旧2.0或曾按早期草案建立的库转换仍须独立维护方案，不自动认领／迁移。构造源注册、来源摘要、结构检视、反例与崩溃实证在A单元完成。


## 8. 验证、批次与未完成范围

### 8.1 P1验收要求

| 编号 | 场景与必须观察的结果 |
| --- | --- |
| TC201-P1-01 | 运行包／绑定错误在打开业务库前拒绝；系统SQLite不被替换；不能继承外部加载变量绕过 |
| TC201-P1-02 | 新初始化成功，原操作重复仅核对；非空库、另一环境库、错误发布、无原意图空文件均不覆盖；提交未知核对原结果 |
| TC201-P1-03 | 应用与维护进程争同一锁只允许一个获权；锁被替换／根变更时拒绝，关闭失败不提前释放保护 |
| TC201-P1-04 | 新Linux实例经实际HTTP完成需求、文档、草稿、CURRENT及Revision闭环，包含详情实际依赖的评论索引；关闭重启后值与版本一致；索引失败不伪造空值，也不靠停用详情核对让页面通过 |
| TC201-P1-05 | 保存草稿后重启、完成编辑响应丢失、版本冲突、事务失败均遵守原规则；未知不换键重发、不丢已有输入 |
| TC201-P1-06 | 直接HTTP、应用入口、后台派发分别尝试禁用能力，包括卡片答案触发模型、未开放人工分支和原结果回放；无新GuideRun／付费意图／执行分配，after_commit不因旧成功码重新派发；文档Chat／计数、Testing计划、OpenCode／检查出口均零调用 |
| TC201-P1-07 | 预置需原执行控制的未决事实时普通启动拒绝；不能跳过恢复、清未知或偷偷重发 |
| TC201-P1-08 | 错环境、错代次、旧协议、重复身份头均在业务读写前拒绝；响应和原请求作用域一致 |
| TC201-P1-09 | 页面使用真实Linux接口完成操作，含加载／空态／错误／能力禁用／恢复；浏览器存储隔离与入口认证联合验收 |
| TC201-P1-10 | 停止与启动失败覆盖部分资源取得、已受理事务和底层线程；旧实例不在新实例获锁后继续写入 |
| TC201-P1-11 | 固定正常入口在未安装Docker／runsc／OpenCode、无模型凭据及无管理服务时完成真实普通装配；不导入Windows原生构造、不调用模型／计数工厂、不起外发循环；恢复完成前无accepting，拒绝能力不退化成404或测试替身成功 |
| TC201-P1-12 | 有实际正文／草稿和原未知请求的普通环境完成同DDL／objects的来源刷新与受控重启，环境／代次及原键不变；变更DDL／来源不匹配／旧START被替代则拒绝，不改来源标记、不重新初始化、不复用旧就绪证据 |

01—08可先在隔离范围推进；09按本稿第6章及前端TC201-FE-01—13联合验收，包含实际HTTPS／认证／来源与浏览器存储，10—11要有实际正常入口／进程和失败清理证据，12结合PKG-04核对开发来源刷新与数据保全。真实模型效果、gVisor逃逸边界、Linux浏览器驱动及云x86_64均不包含在这些通过结论里。

#### 8.1.1 平台包与新建库专项要求

以下是本批新增的待执行检查，不增加真实模型调用。

| 编号 | 必须观察的结果 |
| --- | --- |
| TC201-PKG-01 | 实际宿主入口先核对字节再启动；错误解释器／ABI／SQLite／宿主库、额外可导入文件、启动钩子或加载变量均拒绝；未打开业务库 |
| TC201-PKG-02 | 31项固定依赖闭包、目标wheel、每项摘要和离线安装均核对；缺失／错误hash、其他架构、额外分布或-S实际导入失败不放行 |
| TC201-PKG-03 | 实际新DDL／objects核对：297原对象不变、2项指定修改、2项新增；新表strict／without_rowid、origin原输入／保留引用及NULL、非法UUID／时间反例符合各自责任 |
| TC201-PKG-04 | FRESH_ONLY明确拒绝旧151／db20-r50库与升级命令；不生成假升级SQL；相同DDL和对象契约的程序／平台新发布按原数据事实校验 |
| TC201-PKG-05 | 两个发布者、目标已存在、跨盘／不支持不覆盖重命名、目录同步失败、pin竞争及更新结果未知：不覆盖旧资源、不误报采用、不清理已发布目录 |
| TC201-PKG-06 | 初始化在原意图、文件排他创建、TARGET_BOUND同步前后中断；有原身份的空库可继续，无持久归属的同名空文件仍拒绝 |
| TC201-PKG-07 | DDL／三项元数据同事务；提交未知、新连接验证与回执丢失可核对原结果；正常写入后重复初始化不重置数据或时间 |
| TC201-PKG-08 | 普通启动不建库／升级／更改绑定；根／文件替换、锁竞争、错环境／代次及实际加载库变化拒绝；ARM结果不自动授权x86_64 |
| TC201-PKG-09 | 安装锁根与可变控制根分离；应用／维护不能改名锁及其祖先，错根／多链接／缺失拒绝；同环境换库仍互斥，新宿主显式准备而非还原旧锁身份 |
| TC201-PKG-10 | 固定记录锁ABI及全部入口同协议；竞争与权限／IO／资源错误分开，唯一fd、额外close对照和正常退出顺序验证；普通P1不为证明锁另起执行服务 |

#### 8.1.2 环境管理专项要求

以下均为待实施验收，不由P1业务通过自动覆盖：

| 编号 | 必须观察的结果 |
| --- | --- |
| TC201-MGT-01 | 业务全部停止时独立管理仍可读取；管理被停止时业务继续运行；登记库丢失／损坏不自动初始化或认领端口 |
| TC201-MGT-02 | 两个管理写入者、两个空闲量竞争请求、路径祖先／端口别名冲突只允许合法占用；未决资源不因超时释放 |
| TC201-MGT-03 | 创建响应丢失／初始化各断点后只核对原操作；创建成功应用仍停止；ATTACH零覆盖；入口缺失／共享配置竞争／采用未知正确阻断，Windows可达性另验 |
| TC201-MGT-04 | 同键同输入、同键异输入、原版本变化、控制回执丢失、多标签继续分别命中原结果／冲突，外部步骤至多按已核实状态派发 |
| TC201-MGT-05 | 管理退出而辅助进程仍运行、进程PID复用、旧运行迟到观察：不重派、不误停新run、不伪报STOPPED |
| TC201-MGT-06 | 等待容量、余量过期、磁盘写满、运行但未就绪保留必要占用；取消等待／取消进行中不把部分产物当作已回滚 |
| TC201-MGT-07 | 同任务交接保留脏文件和数据代次；旧权限被封闭；未知／撤权失败阻止新写权；交付登记不运行检查，伪证据／错commit拒绝，旧交付可查 |
| TC201-MGT-08 | 开发者／查看者、伪造owner及认证头、跨来源、直接套接字旁路、开发Vite管理页面替换均不可取得管理权 |
| TC201-MGT-09 | 清理预览不产生外部删除；过期、目标替换、内容变更、被忽略文件、外部写入未停或交付不可取回均阻断删除 |
| TC201-MGT-10 | 分项清理中断后只核对原项，部分结果保留；共享仓库／资源／证据不删除；归档不清文件，缺资源不能启动 |
| TC201-MGT-11 | 旧管理代次、损坏本地记录、超时／401／HTML、BFCache及迟到回调均不跨域重发；联合前端MFE验收 |
| TC201-MGT-12 | 原生服务组实际子进程停止、受限模板／额度和不受管进程边界；只选已登记commit／根／命令，仓库脚本不能取得管理权限 |

#### 8.1.3 维护、发布与恢复专项要求

| 编号 | 必须观察的结果 |
| --- | --- |
| TC201-REL-01 | 准入票据与维护并发时短事务归属明确；ENTERING不冒充DRAINING；持久失败／响应丢失按实际控制revision核对 |
| TC201-REL-02 | HTTP、命令、Guide派发、Testing claim／实际出口共同拒绝新工作；原continue实际新建GuideRun仍被拒绝 |
| TC201-REL-03 | 已开始原工作可按原范围落盘，未派发意图不丢／不偷偷发送；等待输入和无活动任务分别有正确处理 |
| TC201-REL-04 | 取消原任务／原核对可达，未知模型／Git／子进程阻断；仅迟到费用例外不能扩大；无需将全部任务改COMPLETED |
| TC201-REL-05 | QUIESCENT与STOPPED分别证明；线程／子进程未退、管理断连或systemd超时不强杀／误放锁，新库路径仍竞争同一锁 |
| TC201-REL-06 | ARM与x86候选、协议／配置差异、FRESH_ONLY与真实Schema兼容、错误旧升级工具均正确准入／阻断 |
| TC201-REL-07 | 收尾后实际有内容源重核，计划变更须REPLAN；原快照／旧检查不能代替新源与目标，重复确认不重复切换 |
| TC201-REL-08 | 控制选择、数据提交、公开配置、实际新启动与OPEN各断点故障，只有匹配完整元组可开放，原操作回执丢失只核对 |
| TC201-REL-09 | 切换前取消与切换后停止推进分别处理；普通START／自动重启不解除遗留维护 |
| TC201-REL-10 | Backup API加库外资产完整封存、独立重开／恢复核验；WAL、引用缺失、磁盘满、清单未完成均不能登记已验证 |
| TC201-REL-11 | Restic固定快照关联、上传未知／失败及实际异机取回；本机备份不冒充宿主灾备，密钥缺失明确阻断 |
| TC201-REL-12 | 新实例恢复写入或曾OPEN后程序回退／数据恢复分流；新业务内容不被旧快照覆盖，未知不能按无写入处理 |
| TC201-REL-13 | 数据恢复中新代次事务／外层元组任一中断保持关闭；旧许可／队列不复活，旧回执缺失保持UNVERIFIABLE |
| TC201-REL-14 | 管理库恢复换registry_generation但不改未恢复的业务代次；旧记录不接管资源；宿主恢复hold阻止旧OPEN自启 |
| TC201-REL-15 | 与前端联合验证维护读写、原结果恢复、草稿保全及确认失效；生产只读健康核验不创建测试业务或调用模型 |

上述均为待执行。普通环境先验证维护／兼容发布与无外发恢复；完整执行收尾依P2原控制证据和资产覆盖，不能用普通模式通过替代。真实供应方测试仍按单独明确次数／预算执行。

#### 8.1.4 Linux执行与外发恢复专项要求

| 编号 | 必须验证 |
| --- | --- |
| TC201-EX-01 | 实际runsc／平台／镜像摘要与声明一致；不支持时拒绝，不回退普通容器或host网络 |
| TC201-EX-02 | 业务／任务不能取得Docker接口；非法镜像／挂载／路径别名／其他环境引用在创建前拒绝 |
| TC201-EX-03 | 创建前后、回执保存及启动各断点中断，核对原完整资源，不重复创建／启动／初始消息 |
| TC201-EX-04 | 启动与停止并发，stop fence持久有效；旧代次或旧控制者不能重新启动资源 |
| TC201-EX-05 | 主进程退出仍有工具／检查子资源时不报停止；运行时失联、PID重用和资源删除均正确判未知 |
| TC201-EX-06 | 维护超时不隐含强杀；用户终止按原策略停止全部资源，原结果与迟到费用分别核对 |
| TC201-EX-07 | Docker／控制服务／应用分别重启，残留资源可核对，restart=no，不自动重开旧模型窗口 |
| TC201-EX-08 | 沙箱不能访问宿主控制、其他环境、元数据及任意外网；IPv6／DNS／重定向不绕过，依赖安装不在宿主执行 |
| TC201-EX-09 | 本地离线模型入口区分固定OpenCode根与冒用子进程；token／会话头／端口重用、继承连接、事件丢失均不误放行 |
| TC201-EX-10 | 复用原CODE／COMPACTION计费、请求数、预留及UNKNOWN占用；当前身份由可信principal生成 |
| TC201-EX-11 | 维护中问题答复、ALLOW／DENY和预算追加拒绝；原已发送答复只核对，原任务终止仍可达 |
| TC201-EX-12 | 外层发送意图／业务记录任一断点及旧快照恢复，不把缺记录／NOT_SENT当作确定未发 |
| TC201-EX-13 | 新代次旧授权与token无效，原用量去重且未知不记0元；任务同名ID不串用，未有新许可不能清hold |
| TC201-EX-14 | 恢复审阅／新授权／清hold之间崩溃，原操作可核对；管理身份、普通START及新任务不能绕过 |
| TC201-EX-15 | 恢复资产覆盖调用／计数最低证据；独立检查／Git能力缺失不能虚报完整执行可用 |

以上15项均为待执行；EX-09优先作为选型门槛，使用本地假供应方。真实国内供应方验证另行明确次数／预算及重试边界，不因本设计获得调用许可。


#### 8.1.5 开源适配与环境许可联合验收

| 编号 | 场景及必须观察的结果 |
| --- | --- |
| TC201-AUTH-01 | P1策略v1／model_permission_ref=null、DEVELOP／MANAGER／AUTOMATION权限各自核对，不能默认签发或发模型 |
| TC201-AUTH-02 | 策略／许可／配置摘要循环检查、未知字段、过期、跨环境／代次、同供应方不同模型／凭据版本被拒绝 |
| TC201-AUTH-03 | 签发不发请求，当前有效许可仍不能绕过任务授权／预算／来源证明；不存在环境总金额假扣减 |
| TC201-AUTH-04 | 同键双击、丢202、输入冲突、换主体及重启；只形成原许可效果，查询无副作用，不因404创建第二次外发 |
| TC201-AUTH-05 | 签发／撤销与发送提交点并发；未提交发送者被拒绝，已提交者保留可能费用，断电回执未知不误报撤回 |
| TC201-AUTH-06 | 有在途调用／待发预留时替换拒绝；到期、撤销、策略变化后旧worker不能新发，原取消／结果核对仍可达 |
| TC201-AUTH-07 | Guide的每批计数与一次Chat、Testing计划、Coding普通／压缩均绑定正确原身份；SDK重试为0，无额外连通性调用 |
| TC201-AUTH-08 | 审阅四项有缺失／UNKNOWN、审阅过期、高水位／部署／配置变化，确认拒绝且保持hold |
| TC201-AUTH-09 | 恢复确认仅原子变更许可＋hold，CLOSED保持CLOSED，无旧任务／消息重放；管理离线不获得代授权权 |
| TC201-AUTH-10 | 准备前后、control CAS前后、结果落盘前后故障；按原效果核对，不重复签发，不以文件存在当生效 |
| TC201-AUTH-11 | 恢复旧库NOT_SENT、计数PREPARED、缺外层索引和代次ID碰撞；未知不释放费用，不覆盖原证据 |
| TC201-AUTH-12 | 控制根／策略／审阅文件篡改、锁错配、历史主体权限撤销及恢复模式路由旁路均失败关闭 |

| 编号 | 候选原型门槛（均未执行） |
| --- | --- |
| TC201-SRC-01 | 模拟gVisor监测丢失／阻塞，证明本方案不依赖异步监测事件作唯一放行依据 |
| TC201-SRC-02 | 固定OpenCode关闭项目插件／配置、本地shell／命令、LSP／formatter／stdio等路径，项目代码只能进入工具沙箱；不得由提示词或工具隐藏假装隔离 |
| TC201-SRC-03 | 本地假供应方下根连接可核验，子进程／工具沙箱／继承与传递连接／端口复用／身份失效均不能冒用；沿EX-09完整边界 |
| TC201-SRC-04 | 工具原调用身份与输入绑定，MCP重连／超时／响应丢失不产生第二次文件或命令副作用，未知不会让模型自行换键重做 |
| TC201-SRC-05 | 原问题／权限／取消／输出／候选、整个资源集停止及单重任务容量兼容；失败不得以fork执行器或普通容器默默替换 |
| TC201-SRC-06 | 必需插件加载失败、pure配置冲突、工具集合或固定版本失配；进程虽运行也不开放模型窗口，不退回本地工具 |
| TC201-SRC-07 | 并发自定义工具取得各自完整原身份，缺callID／身份错配及同键异输入拒绝；不依赖公开SDK未声明字段而无运行时校验 |
| TC201-SRC-08 | file附件直调read、原生shell／command／subtask、HOME配置及插件安装路径逐一封闭或证明安全；仅隐藏工具不能通过 |
| TC201-SRC-09 | 工具已写入而回执丢失、控制器重启、模型换callID与取消同时发生；沿原效果查证，未知不重复副作用，完整资源停止 |
| TC201-SRC-10 | 固定OpenCode实际auth.loader与fetch生效，普通／压缩请求、SSE和取消保持；插件缺失／配置覆盖／SDK缓存失配时无TCP或供应方直连回退 |
| TC201-SRC-11 | 原根及其线程正常发送；同UID陌生进程、fork子进程、继承／SCM_RIGHTS转交FD后发送及显式伪造凭据拒绝，记录假供应方实际请求数 |
| TC201-SRC-12 | 首包早于accept、头／体分片、头携带正文前缀、不同进程混写、缺凭据／辅助数据截断及异常FD；所有字节必经核验，不泄漏描述符 |
| TC201-SRC-13 | 原根退出、PID复用、同PID exec／execveat、profile失效／complain、接收器重启、旧连接跨代次；旧proof不复活，缺策略不放行 |
| TC201-SRC-14 | socket路径／祖先替换、错误监听者、错误namespace／UID、管线请求、连接池重连和代理／重定向输入；原绑定不串线，不产生额外模型派发 |
| TC201-SRC-15 | 完整接收后到原发送提交点之间撤销／停止／控制换代；准入按原顺序决定，已可能外发保留未知，不以断连或来源错误自动退款 |
| TC201-SRC-16 | 固定二进制／内嵌Bun／插件／策略／工具包组合在ARM与云x86各自验收，真实问题／权限／角色交接／配置／压缩／候选及完整停止兼容；最小发送夹具通过不冒充产品通过 |
| TC201-SRC-17 | 冷启动断外网、只读依赖、缺／错锁定成员、HOME或祖先.git污染、pure冲突及bootstrap吞错；只有受信静态包与实际配置／服务均核验才就绪，不下载／修复／启动shell |
| TC201-SRC-18 | 显式标题与title禁用无额外请求；compaction走正确用途且计入原窗口预算；问题／权限／角色交接可用，原生子任务及本地附件不绕过；snapshot空差异不覆盖WALL-E真实候选 |
| TC201-SRC-19 | 大输出、中文长单行、超过行数、异常／metadata／attachments注入均被有界封装；原生截断路径不出现，真实结果在原task范围分页且不重复命令 |
| TC201-SRC-20 | 输出限额、失联、损坏、游标伪造、跨任务／代次、控制换代及清理并发；部分／未知明确，原效果不丢、不自动重试，取消后完整资源停止 |
| TC201-SRC-21 | 最终模型工具集合与固定策略一致；自定义工具未ask、ask直接返回、伪造metadata／对象／callID、会话规则后置覆盖均不能绕过独立业务动作检查 |
| TC201-SRC-22 | 工作区／依据根、链接／父目录替换、创建碰撞、旧摘要、单文件补丁／删除及内容选择混淆；确认等待后对象变化拒绝，未改目标字节，成功效果按原记录可查 |
| TC201-SRC-23 | EXECUTION完整定义、argv／cwd／env注入、命令／网络不在scope、null网络及相邻命令出口串用；独立短时沙箱与全部后代停止，CHECK／SERVICE不能由模型工具调用 |
| TC201-SRC-24 | ALLOW_ONCE只作用原输入；DENY期间新ask登记与原待批集合稳定，逐项事件／丢回执／旧会话／always旁路正确处理，不批量伪造已拒绝或任务终止 |
| TC201-SRC-25 | 取消发生在登记、等待、派发提交点前后及文件／命令效果之后；迟到ask／响应不再派发，原效果未知不重做，停写捕获与资源释放不越过未决操作 |
| TC201-SRC-26 | 原工具键与业务父操作：START／RESUME／REPAIR／HANDOFF_ROLE的真实目标会话、同键同输入／异输入、新callID、旧run／epoch和并发登记分别核对；不追加任意业务步骤，不重复派发 |
| TC201-SRC-27 | 命令与观察补记断点：ID预留前后、关联发布前后、DB提交未知、派发前后及效果后DB失败逐点中断；只补固定ID，允许序列间隙，不复制命令、不覆写终态、不伪造原生事件 |
| TC201-SRC-28 | 文件提交与回执断点：CREATE不覆盖、REPLACE／PATCH／DELETE、父目录及临时对象、副作用后取消、文件／目录同步失败与回执丢失；摘要相等／目标消失不能单独判成功，未知不重做 |
| TC201-SRC-29 | 完整资源恢复与停止：控制重启、创建中资源、历史会话、迟到启动／回执、权限等待、输出丢失及终止抢占；查全原集合，不按active_session或零命令行释放，已核清效果不因输出丢失重跑 |
| TC201-SRC-30 | 核对与继续契约：父操作已SUCCEEDED但工具未知、多个工具共用等待、原消息也未知、过期快照及其他费用等待；GET不探测外部，RECONCILE不执行，RESUME精确消费原等待，终止保持唯一 |
| TC201-SRC-31 | 控制证据保留与容量：清单／输入损坏、孤立文件、记录／输入／输出配额及磁盘故障、业务库恢复和控制域丢失、清理后迟到调用；不补造旧任务、不回滚控制事实、不删除未决证据腾空间 |
| TC201-SRC-32 | 文件布局证明：CREATE／REPLACE／PATCH／DELETE及缺失父目录分支逐点中断；原锚点和对象身份、内容／模式、链接集合及父链完整才形成APPLIED／NOT_APPLIED，不用摘要／缺失单独判定，不重放原提交 |
| TC201-SRC-33 | 平台与私有收尾：不同挂载、shared模式NOREPLACE拒绝、目录同步失败、额外别名写入、容量不足、清理断点和宿主重启分别核对；证据先持久后回收锚点，无旧缓存写入者才释放，实际ARM／x86产物分别验证 |
| TC201-SRC-34 | 效果／回执／原生状态分开：RECOVERED_STATE可核清当前文件效果，但原派发及outcome不改成功，迟到矛盾回执保留冲突；原生tool part未结束或费用未知时仍不得继续 |
| TC201-SRC-35 | 继续资格矩阵：HELD、同实例CLOSED、仅后端重启、原执行器退出、宿主重启及原问题未决；核验实际根来源／网关及旧turn，不以idle、SQLite或现有REPAIR代替完整证明 |
| TC201-SRC-36 | 新消息接续断点：受理、意图、新消息收到、业务完成事务前后故障及停止／维护抢占；等待保持OPEN直至接收确认，未知只查精确新消息，原角色／输入／费用完整，不重复投递或解除其他等待 |
| TC201-SRC-37 | 接管范围：仅后端退出、连接暂断但原进程仍活、原执行控制重启、宿主boot变化、包／数据代次变化分别核验；仅同原控制生命周期可继续接管，不用PID／锁文件／超时认领 |
| TC201-SRC-38 | 唯一当前绑定：旧资格封闭、新绑定持久、能力交付、业务补记各点中断及双后端竞争；同请求不重复绑定，新后端再次退出后旧应答失效，原执行／工具身份不改写 |
| TC201-SRC-39 | 活能力传递：实际peer、程序、单实例资格、SO_PEERPIDFD、原根pidfd与控制帧联合核验；错误类型／多余FD／截断／重复应答不泄漏，模型接口仍拒绝SCM_RIGHTS，不读取日志重建秘密 |
| TC201-SRC-40 | 网关换代：监听重建、旧socket／FD／消息头、旧source proof、并发控制死亡及SSE丢失均覆盖；新attachment不开放旧窗口，旧供应方请求只结算／核对一次 |
| TC201-SRC-41 | 接管与明确继续：稳定来源可在原效果核清后新RESUME；旧START／RESUME／REPAIR／HANDOFF_ROLE／权限投递未完时仅保全／原终止；精确消息已接收也不调用旧完成分支开放模型 |
| TC201-SRC-42 | 控制丢失与资源：固定原停止策略、文件提交中的断点、命令后代、保留Agent超时／内存及重任务占用；不重置限额、不以接管成功释放资源，取消／维护／终止资格保持一致 |
| TC201-SRC-43 | 独立查询方对同一对象F_GETLK、整文件写锁及实际peer线程组联合核验；自报PID、读／局部／OFD锁、无锁及错误命名空间均不构成持有证明 |
| TC201-SRC-44 | 锁fd不通过控制通道交付，fork／dup／exec和额外close夹具揭示真实语义；旧flock包被安装准入拒绝，不能与新协议并存访问同环境 |
| TC201-SRC-45 | SEQPACKET早到数据、其他进程借同连接发送、旧runtime／任期／请求应答；逐报文身份及实际端点核对，不因连接建立时凭据有效而持续放行 |
| TC201-SRC-46 | 64KiB边界、截断、缺失／异常凭据、多个／错误FD和重复ATTACH响应；全部异常资源关闭，无fd泄漏或继承；模型入口仍拒绝任何FD |
| TC201-SRC-47 | 后端仍活却失锁、控制断连／死亡、派发前后失效及lease退休；拒绝接管／新派发，保留可能已执行结果，不重新加锁复活原任期或提前释放占用 |
| TC201-SRC-48 | 实际包和目标部署双向PID视图、peer/root引用及程序／exec策略联合核验；夹具通过、同UID或pidfd存活不能代替准入，权限不足不增加调试或宿主管理能力 |
| TC201-SRC-49 | 宿主服务PID／user视图、环境／实例间UID隔离及同实例control／Agent的强制profile／挂载一致；项目沙箱仍隔离，不以host PID容器／特权模式替代参考部署；ARM与云各自准入 |
| TC201-SRC-50 | SO_PEERPIDFD→GetUnitByPIDFD→当前MainPID／InvocationID联合核对；同unit子进程、假unit名、旧代次、PID复用、manager观察变化或只读查询失败均不认证 |
| TC201-SRC-51 | 相同Python／可变源码、unit drop-in或有效属性变化、AppArmor未启用／complain／执行回退均拒绝；程序闭包与运行profile核验，秘密不进入D-Bus或通用日志 |
| TC201-SRC-52 | app单独重启不自动停止Agent／control；control或Agent换代不透明恢复，systemd启动不等业务就绪，停止超时／OOM及原残留保持原事实和占用 |
| TC201-SRC-53 | 私有挂载视图中的锁／socket实际为登记对象；只读父目录映射允许受控换监听，单socket旧inode／同名新目录拒绝，Agent不能访问业务库、管理总线或其他任务元数据 |
| TC201-SRC-54 | 固定原生TCP端点及凭据发送前归属核验未交付时阻止完整执行；模型Unix成功、localhost可达、插件client或服务active均不能代替，HTTP／SSE未知不重发 |
| TC201-SRC-55 | 每实例control／Agent使用同一私有网络但不同强制profile，实例间隔离；原主进程accept前不发HTTP／凭据，接受后精确反向四元组／cookie／原根fd及监听集合共同核验，竞争监听、其他进程持有或证据缺失均拒绝 |
| TC201-SRC-56 | 同UID最小proc观察在固定内核／dumpable／AppArmor组合下可用且无CAP_SYS_PTRACE；Agent反向读取／信号／修改控制证据、其他实例读取及profile切换均拒绝，不能只验证正常连接 |
| TC201-SRC-57 | serve无预加载插件时仍可先验TCP再进行原只读初始化；有效配置／工具／模型适配齐备前窗口关闭；固定方法拒绝任意URL、头、目录、file附件、shell／配置写及越权答复 |
| TC201-SRC-58 | 64KiB帧、32KiB分片、4MiB输入及原响应／事件限额；缺片／重复／异输入／跨绑定／超时／FD全部拒绝，完整COMMIT前零HTTP派发，慢消费者与事件占用不阻断STOP |
| TC201-SRC-59 | 覆盖组装前后、持久意图后未发、HTTP部分发送、执行后丢回执、响应部分读取、SSE断开；STATUS仅查原事实，取消不撤销已执行效果，同键／新attachment均不重发副作用请求 |
| TC201-SRC-60 | 后端重连及有限ATTACH先核对旧native记录、原端点和窗口；control重启不认领旧Agent，实际停止包含全部关联资源；模型始终由原OpenCode直达网关，native转送不形成模型代理或供应方直连 |
| TC201-SRC-61 | 固定unit／策略／身份和proc条件联合核验：缺read或readby、UID／GID／capability变化、不可dump、hidepid遮蔽均阻止发送HTTP；控制原根fd可读且Agent反向proc／信号／控制文件仍拒绝，不放宽ptrace_scope或增加CAP |
| TC201-SRC-62 | NNP从启动器持续有效；固定exec叠加后的完整标签、同一pidfd及unit代次重新核验；缺profile／转换失败／环境字段丢失不回退，运行Agent不能再exec、连bootstrap或使用遗留系统总线FD；Type=exec及RECEIVED不算ready |
| TC201-SRC-63 | 双向bootstrap认证覆盖假peer、同UID外来进程、错误主进程／unit代次、错误范围、超长／截断／额外字段及FD；核验前零秘密，GRANT仅发原连接一次，Basic与内部模型能力独立，供应方密钥不进入Agent |
| TC201-SRC-64 | GRANT前后停止、发送后丢回执、RECEIVED后exec失败、control退出、超时与重复HELLO均不补发／改密／重启／开放模型；核对原资源，未知保留占用，有限ATTACH不重新交付启动秘密 |
| TC201-SRC-65 | 假秘密出现在原生答案／问题／权限／结果／事件及编码变体、跨分片边界时，在保存与输出前拒绝；原效果不改写、不重做，安全诊断不包含秘密；业务保留独立模型秘密检查 |
| TC201-SRC-66 | exec后proc读取与拒绝方向实际通过；正反夹具覆盖core管道配置、软硬限制、swap、stdout／stderr及原生日志／会话元数据失败路径；无秘密进入持久证据／journal／备份，配置漂移拒绝完整执行，ARM结果不放行x86 |


以上为新增待执行要求；静态查到API或源码路径不算通过。原生工具隔离候选通过前，当前完整执行能力仍不可用。

#### 8.1.6 Linux内容、独立检查与Git交付验收

| 编号 | 场景及必须观察的结果 |
| --- | --- |
| TC201-CHECK-01 | 捕获前仍有工具／服务／文件代理写入、只改chmod、冻结主PID或原生idle，均不能封存；原写入口关闭至seal完成 |
| TC201-CHECK-02 | 恶意路径／链接／跨挂载／大小写别名／模式变化及容量超限拒绝；失败不形成部分候选，不改原内容策略 |
| TC201-CHECK-03 | 检查产品只读、构建输出不遮蔽候选、无可写别名；测试修改后恢复字节也不能绕过输入保护 |
| TC201-CHECK-04 | 固定候选与源码服务／构建产物、依赖／平台准确关联；ARM结果不能给x86目标放行 |
| TC201-CHECK-05 | Coding自检与Testing独立owner、plan／pack／scope和完整case固定；项目报告／退出0不能伪造CONTROLLED_CASES |
| TC201-CHECK-06 | 端口占用／复用、错误容器、重定向／WS／子资源／云元数据与正常业务地址均不越界；未证原连接不发送 |
| TC201-CHECK-07 | 项目／浏览器子进程冒写结果、缺END、乱序／重复case／断言、结果超限，均不形成合格报告 |
| TC201-CHECK-08 | 非root与Chromium沙箱、SDK／浏览器版本、私有共享内存及Linux隔离实测；不得用host IPC／SYS_ADMIN／no-sandbox补过 |
| TC201-CHECK-09 | 点击／HTTP写／CLI响应丢失只核对原操作，不因SDK重连自动重做；真实供应方调用为零 |
| TC201-CHECK-10 | 主进程退出但服务／浏览器／辅助资源残留，停止仍未知；完整停止后证据缺失形成不合格UNKNOWN，不假报产品失败 |
| TC201-CHECK-11 | 一重任务名额从Coding收尾到Testing重新取得，子资源不重复抢额度；取消／OOM／控制重启不释放不明占用 |
| TC201-CHECK-12 | 候选变化、计划／包撤销、人工范围与UNCOVERED、收尾缺失逐次影响eligible／delivery_eligible，不改旧报告事实 |

| 编号 | 场景及必须观察的结果 |
| --- | --- |
| TC201-GIT-01 | 同实际common_dir的不同路径／worktree／repository_id／环境登记被归属约束；未知交付不释放占用 |
| TC201-GIT-02 | 新Schema origin／原登记输入／保留ref约束、恢复历史origin不变及新旧同snapshot_id引用并存；旧操作已写未落库可只读核对补记，不以当前代次误拒；同名不同对象不覆盖 |
| TC201-GIT-03 | 固定LinuxGit／本地config白名单／无hooks、外部diff、签名和网络；Windows包或个人PATH不被准入 |
| TC201-GIT-04 | 完整候选对目标树的增删改／执行位一致，工作树与索引不变；任一worktree检出目标拒绝 |
| TC201-GIT-05 | prepare前后目标、symref、config、锁与worktree变化；停止／窗口到期先于commit时不发，窗口不能自动续期 |
| TC201-GIT-06 | 原payload／origin／planned_oid不变；commit丢ACK、目标后代、回旧值ABA、历史重写与对象缺失按原规则核对，不重复写 |
| TC201-GIT-07 | 对象／ref持久性设置、进程崩溃与宿主故障分别验证；ACK、数据库记录和实际持久性不可混为一谈 |
| TC201-GIT-08 | 恢复旧库缺原Delivery但外层已有may-send，或效果覆盖缺失，仓库写入保持受阻；不认领新同号任务 |
| TC201-GIT-09 | 写成功后postcheck冲突／停止请求／收尾不全，保留已交付事实但不误判COMPLETED，不自动回滚 |
| TC201-GIT-10 | 清理保留候选／保留ref／原效果及成果；交付成功只指服务器本地分支，未自动push／部署或改用户工作树 |

以上22项为待执行要求，另配前端CDF系列；源码／官方文档核查不替代固定Linux运行包、真实隔离、故障和交互验收。


#### 8.1.7 历史缺失、资料保全及备份时效验收

以下为待执行目标，未取得产品或云运行证据。

| 编号 | 场景与必须结果 |
| --- | --- |
| TC201-REC-01 | 恢复库NOT_SENT而外层存在已发送／未决证据；不自动释放预留或重发，按原身份核对 |
| TC201-REC-02 | 已知全部调用但一笔用量未知、以及调用集合缺失两种情况；分别阻断对应检查，缺失计数／金额不显示0 |
| TC201-REC-03 | 正文／绑定已核验而历史费用缺失；仅准入明确PURE_READ及浏览器下载，CLOSED／hold与原维护占用保持，RESTORE不成功 |
| TC201-REC-04 | 部分资产损坏、旧写入者未封闭、绑定失配、读取回执过期／部署变更；逐项撤销读取资格，不初始化缺失数据或启动后台动作 |
| TC201-REC-05 | 同代已OPEN环境的人工业务与新恢复代次CLOSED分别检查；前者沿原占用规则，后者不能借前者例外提交保存 |
| TC201-REC-06 | 可信原费用补证重复、归属不符、冲突、只有日汇总四种情况；原结算幂等保持，冲突／不完整不能PASS；无适配器时明确未支持 |
| TC201-REC-07 | 补证后旧review／旧确认仍保持原内容，新review绑定最新高水位；确认前事实变化拒绝，GET不触发供应方调用 |
| TC201-REC-08 | 旧Git效果未知且当前ref恰等于预期；保留占用／UNKNOWN，不靠重跑或新代次忽略 |
| TC201-REC-09 | 最近备份尝试失败、异机上传未取回、旧截止新验证、超过24小时、时钟异常分别显示；不得冒充RPO达标 |
| TC201-REC-10 | 有内容的固定快照异机取回及新宿主演练，包含Mac离线／独立密钥／容量不足；分记数据可读耗时与完整执行是否开放，不将只读RTO当AI恢复时限 |
| TC201-REC-11 | HTTP头ID、推理body ID、查询metadata ID不同；仅原body ID进入方舟单请求查询，缺失／错配保持受阻，不改变旧字段含义 |
| TC201-REC-12 | 一请求多计量行、跨窗口重复uuid、数量scale及缓存输入；不重复计量，不将计量数量当人民币或自动标PROVIDER_BILL |
| TC201-REC-13 | 导出创建响应丢失、原任务失败／运行超时、链接到期、截断、未知CSV列及配额耗尽；不自动重建／扩范围，原意图及未知保留 |
| TC201-REC-14 | 正常后付费CSV为空或完整，但其他状态／在途调用／原绑定缺失；CALL_RANGE_COMPLETE不因此PASS，错误QueryParams及身份冲突拒绝 |
| TC201-REC-15 | 可信补证重复、跨代次同号、未匹配后补齐、最终性不足及计数路径不支持；只通过原结算事务补原事实，新审阅才能使用新证据 |

### 8.2 实施依赖与交付判定

本节是实施前的依赖设计；启动实施后才建立本版本计划、需求实现映射和进度文件。已有记录、固定资源或历史测试不替代本轮交付。普通业务A→B→C与执行来源原型P2-a可以分别推进；需要特权策略的原型在独立验证VM中进行，Mac容量不足时串行使用，不能借“可并行设计”同时占用两个重任务名额。

#### 8.2.1 首批普通业务的具体交付

| 单元 | 必要输入与交付物 | 通过范围与失败处理 |
| --- | --- | --- |
| A1 固定运行包 | 固定目标平台／安装prefix、原31项依赖版本和源码；交付7.4—7.5的真实解释器／SQLite／wheel锁／文件及宿主库清单，按实际字节发布pin | PKG-01—02通过才准入该运行包；不依赖OpenCode、Docker、runsc或管理服务。失败不改系统SQLite、不借旧用户目录原型假放行 |
| A2 最终新Schema | A1及7.6／7.14的完整构造源码；交付FRESH_ONLY发布、最终DDL／对象清单、完整sources和平台关联 | PKG-03—05／08；保留预期73表／301对象的全部业务结构，实际数量须由构建核对。纯Schema构建不实例化执行器，不做P1专用删表版本；失败保留旧发布 |
| A3 首环境准备 | A1／A2及受信安装位置／身份；交付锁根与目录保护、宿主hold状态、LOCAL_TOOL控制／初始化原意图、准确启动描述及诊断入口 | PKG-06—10及P1-01—03；新库只初始化一次，初始CLOSED。不依赖M控制台，也不省略稳定锁与持久控制；结果未知保留原目录／操作 |
| B 普通应用装配 | A3及7.3.1的真实装配修改；交付平台导入边界、锁内恢复、能力拒绝、最终开放与失败清理 | P1-06—07／10—11；在没有执行运行包和模型凭据的隔离环境可启动普通业务，缺必需业务依赖仍拒绝。不能拿测试工厂注入成功代替正常入口 |
| C 真实前后端闭环 | A／B、固定公开配置／HTTPS与代理身份、绑定客户端和各存储owner；交付两套明确隔离的开发／集成scope及真实页面 | P1-04—05／08—09／12与FE-01—13；完成读写、重启、未知请求和跨scope反例后才算P1通过。前端可先做离线专项，但实际页面依赖B，不能用假API提前验收 |

A中用于验证的临时新库／目录与正式发布资源分开：前者清理，后者按项目来源与版本规则保留；不会因此保留测试JSON报告。每批检查绑定该批实际输入，失败从原操作和已取得资源接续，不能重跑上一批初始化或复制旧业务库“快速恢复”。A1仅证明运行时，A2仅证明结构资源，A3仅证明准备，B仅证明后端装配；都不自动意味着页面可用、Agent就绪或环境管理完成。

#### 8.2.2 执行候选与后续单元的最小门槛

| 单元 | 最小输入、验证次序与交付边界 | 依赖及明确退出条件 |
| --- | --- | --- |
| P2-a 系统机制夹具 | 在固定L0现场用受保护假角色／假凭据，按L1—L3验证锁、peer／pidfd、模型Unix逐段来源及FD拒绝、单向proc、NNP执行转换、一次秘密交付和失效清理；对应SRC-37—66中相应机制项 | 可在B／C未完成时推进，不使用业务库或真实供应方，不把夹具标签／回执放入产品pin。根观察、阶段收紧或同UID隔离无法成立即停止当前候选；不先造完整工具面再补安全原语 |
| P2-b 固定OpenCode组合 | 通过P2-a后，接7.11.1及7.11.8—7.11.10真实包，验证冷启动、原生TCP、进程内模型通道、固定工具、取消／断线／有限接管；只用隔离的假供应方 | 单机制通过不放行L4；业务组合依赖B及真实原操作／窗口，不以夹具代业务。固定包需要任意exec、全局调试、通用代理或长期fork才能工作，则退出并重评部署 |
| P2真实模型闭环 | 固定已准入的组合、原模型Profile、环境许可／原任务授权和预算；再验证真实国内供应方与原费用／恢复证据 | 额外真实调用须当时明确次数、预算及重试边界。无调用授权可交付离线结果，不能标记供应方或完整Coding任务通过 |
| P3检查与本地交付 | 按4.19—4.21及7.13—7.14先固定内容／CLI，再HTTP／浏览器，最后Git效果与故障核对；CHECK／GIT／CDF联合 | 纯算法及独立无模型检查可按实际依赖先做，不因缺模型许可一概阻断；任务候选／交付仍须真实原任务与对应执行证据，不构造演示任务冒充完成 |
| M环境管理 | 独立Schema／受信安装、真实观察，再接CREATE／START／STOP／HANDOFF／CLEANUP及管理前端；MGT／MFE联合 | 真实控制依赖A／B，页面不可用假观察开按钮。P1不等待M，M也不重新实现LOCAL_TOOL已采用的控制规则；未完成额度事务前只有明确人工串行，不宣称统一自动调度 |
| R维护与恢复 | 持久控制和锁→原工作收尾→候选／配置切换→完整恢复包与取回→新代次恢复／前端；REL／RFE／REC／RCF联合 | 普通无外发场景先做；含任务／费用／交付的场景依赖对应P2／P3及AUTH／AFE证据。可信供应方补证缺失仍受阻，不能拿普通空库恢复替代 |
| 云目标准入 | 在已获准的x86_64验证环境复核运行包、内核机制、容量／入口及存储恢复；随后核对完整业务与Mac离线运行 | 可尽早验证目标差异，不等待Mac全部页面完成；未采购不影响本地设计／P1，但云生产仍待实际账号、费用及独立证据，ARM通过不继承 |

P2-a／P2-b只细分原P2工作，没有新增产品模式、运行时协议或权限豁免。夹具通过只为是否继续投入提供依据；完整SOURCE／EX／EFE仍须真实包与业务组合。所有故障夹具必须先固定本轮资源归属、截止时间、停止和临时清理；无法证明已退出时保留隔离VM及未知记录，不自动交给下一重任务。

#### 8.2.3 失败影响、日常改码与完成口径

共用运行包、Schema、路径／锁、环境绑定或恢复前提失败会阻断该实例；只影响未启用执行能力的P2失败不取消已经独立通过的P1资格。完整环境声明的required能力不满足时仍必须BLOCKED，不能自动删掉required来演示页面。已经运行的能力失效先封闭相应新派发并保留在途效果／费用未知；是否保留读取和原收尾沿原4.4／4.14，不用本批验收状态直接改业务终态。共享源改变时评估受影响证据，不能以“P1曾通过”覆盖新变化。

开发期间只对实际变化重建相关输入：

| 变化 | 必须更新及检查 | 数据与身份边界 |
| --- | --- | --- |
| 普通页面／未进入Schema sources的业务实现 | 实际program_source／前端输入及相关能力检查；固定产物重建自己的索引，开发Vite按原规则 | 不因代码改动生成新environment_id／data_generation，不改旧原键／草稿归属 |
| 注册来源变化，DDL与objects字节都未变 | 按7.7生成新来源manifest／pin并核对实际加载；同步启动描述和完整部署选择 | 原schema_migrations的fresh checksum及code_schema_state契约仍须通过；不重跑初始化，不把来源刷新当数据迁移 |
| runtime／宿主库／平台变化 | 新运行包及其关联Schema发布、真实加载与受影响能力重新准入 | 只有结构和原初始化事实仍兼容才沿用同库；平台或清单摘要相同名称不能继承证据 |
| DDL、objects或数据绑定规则变化 | 新结构规格、来源和验收；现FRESH_ONLY仅能准备另一个显式新数据目标，不提供隐式升级 | 不能改旧来源标记凑通过、清库或替换当前数据；是否放弃测试数据须按具体任务范围处理 |
| unit／LSM／启动器／原生或工具适配变化 | 相应P2-a／P2-b及实际平台证据失效重核，按原维护部署新候选 | 不热改运行实例权限或认领旧pidfd；不把新源码字节套到旧运行回执 |

只读构造源码文件的摘要校验不等于导入该模块；纯Schema生成不能为取得命令常量而加载平台原生服务。业务开发允许同一逻辑结构的来源更新，但不关闭sources检查换取“快速热更”。后端代码更新遵守原受控停止／启动，前端HMR遵守既有模块完整性检查，不把开发工作区当不可变生产包。

本版的验收结论按“普通业务P1、执行候选机制、固定组合、真实供应方、管理M、维护R、检查／交付P3、云目标”分别记录，并引用原用例及实际输入；这是文档判定维度，不新增运行时状态表。全V2.01仍须大纲第8章的多环境、集成、发布恢复和云范围。未做的检查保留未执行，恢复只读与费用核清分开，设计成稿不填写实施完成。

### 8.3 设计收口与准入边界

本版独立设计于2026-11-20收口为1.0／BASELINED；第2—7章为实现依据，第8.1节为待执行验收，第8.2节为实施依赖。普通业务、管理与维护、模型许可、执行／停止、工具恢复与有限接管、检查／本地Git交付、浏览器隔离和历史缺失处置均已有契约。本次结束持续扩写设计，转入等待实施；不把资源尚未生成或验收未执行重新标成“业务逻辑尚未设计”。

| 类别 | 收口结论／后续责任 | 放行边界 |
| --- | --- | --- |
| 普通业务与分批实施 | 按7.3.1／8.2实施A1→A2→A3→B→C；第4.4.1明确必要读取、混合命令及提交后派发 | P1可独立实施，但仍需真实正常入口、两套scope和浏览器联合验收；不能写成已可运行 |
| 平台与结构资源 | 第7.4—7.8／7.14已定义运行包、wheel锁、DDL／objects、sources、受信pin及FRESH_ONLY初始化 | A按真实字节生成并通过PKG-01—10；摘要、文件数量和权限实物不由文档填造，旧db20-r50保持 |
| 执行部署候选 | 第4.15、4.23及7.11.1—7.11.10固定优先原型输入与退出条件 | P2-a先验证来源／隔离／启动原语，P2-b再验证固定OpenCode组合；SRC-01—66、EX／EFE仍待执行。需要放宽边界或长期fork则退出候选并修订相关设计 |
| 管理、维护、恢复和检查／交付 | 第3—7章已定义共同对象、控制、API、资产及故障规则 | M／R／P3按8.2依赖交付实际Schema、服务、界面和故障证据；MGT／REL／CHECK／GIT等不能由空接口、夹具或P1通过替代 |
| 环境许可与供应方补证 | 第4.16—4.18／4.22及7.12给出原归属、费用、可信范围和恢复提交 | AUTH／AFE／REC／RCF待实现；供应方查询能力不保证所有原记录可补齐。无可信原事实时保留受控只读及外发阻断，不提供人工改账／自动解除 |
| 云生产 | Linux独立云环境和新数据目标已选；实际采购、账号报价、容量、访问及Restic／COS恢复仍待现场证据 | 普通开发不等采购；云实际接入是独立部署阶段，不以本地验收替代。约100元为预算意向，超额不默许提高预算；模型费用另需明确授权 |
| 首期数据兼容范围 | 首次新建用FRESH_ONLY；正常更新准入SAME_SCHEMA及适用恢复，旧Windows数据不迁移 | 不提供通用不兼容结构转换。未来发生具体源→目标结构变化时单独形成转换规格及恢复演练；缺方案拒绝发布，不能清库／改标记凑通过 |

设计收口不把任意Schema转换、自动远端push／PR、多执行节点调度、多用户账户平台或保证完整Agent灾难恢复时限纳入首期。新云数据仍必须持久保存和备份；首期受控只读恢复目标不等于完整外发恢复承诺。大纲完整多环境与发布流程仍为版本目标，P1仅为首批，不以缩减能力宣告全版完成。

实施开始时建立docs/project/v2.01下实施计划、实现进度及docs/traceability/v2.01需求实现映射，绑定本基线和实际代码摘要。从第8.2节依赖启动，逐批记录真实实现与证据；仅实际冲突、原型失败或新增需求重开受影响条款，不重复扩展已收口协议。实际模型／计数／供应方请求、系统策略安装、服务更新、采购、提交／推送及正式规格合并均按后续具体任务授权，本次收口不执行。

当前真实证据及接续位置见[验证记录](../../../verification/v2.01/remote-development-link-2026-11-15.md)。设计与静态核对、历史前置原型、产品实施、产品验收和生产接入分别报告。
