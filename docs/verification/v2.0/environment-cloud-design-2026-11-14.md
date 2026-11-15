# 多环境与云部署设计静态核对

日期：2026-11-14（Asia/Hong_Kong）。范围：独立详细设计0.1及方案／目录导航，工作区已有其他任务修改；未修改源码或正式设计。

只读依据：Get-Content及rg核对启动、数据库、固定运行库、Guard部署、Git工作区、前端请求及存储；Get-FileHash核对BE0.17-draft-17／FE0.16-draft-16。部分大段输出截断，未计作完整阅读；一次Windows通配路径rg未匹配文件，未据该失败作来源清单结论。Python终端曾出现中文编码显示异常，文件采用UTF-8读取并另行复核，不将终端乱码写回正文。

静态检查：Python读取详细设计UTF-8，检查14个主章节、Markdown代码围栏配对、本文本地链接目标存在及无U+FFFD替换字符，均通过。检查命令通过标准输入执行，无持久临时脚本／原始日志；Markdown采用同目录临时文件flush／fsync及原文件复核后原子替换，清理临时文件。

结果：补充目标平台选择、环境身份／启动顺序、受控访问、生命周期、独立可视化管理、跨主机数据迁移、实施与验收映射。只代表文档静态检查，不代表设计全部闭合或代码验证。

未执行：产品专项、类型检查、构建、浏览器、云资源探测／部署、系统安装、真实模型与计数、服务更新、Git提交／推送。目标OS、认证实现、远程管理协议、稳定版本、实际资产及恢复指标仍待后续设计闭合。

设计入口：[现行大纲](../../iterations/pending/v2.01/WALL-E.开发与生产环境分离迭代V1_V_2.01.md)。原V2实施断点保持。

## 详细设计0.2接续（同日，后续设计轮次）

本轮只修改详细设计及方案／目录导航；核对http_errors.py、EmptyState、Guard操作记录的职责，官方HTTP重试及Uvicorn代理设置。未执行产品验证或变更服务。

新增ENV-HOST-1消息及接收／执行／未知恢复、管理路由和计划执行、动作矩阵、P0—P4分期以及ENV-F01—14故障验收。修正只读期不应要求可启动生产的前后不一致；具体Schema和目标运行证据仍未完成。

静态检查命令：Python标准输入脚本读取UTF-8，确认18个主章节、围栏成对、本文本地链接存在及无替换字符；实际均通过。原子保存并清理临时文件。新增官方来源链接未替代项目锁定版本验证。没有运行API／浏览器／并发／故障注入，表内验收仍全部为未来要求。

## 详细设计0.3接续（同日，后续设计轮次）

实际静态读取：src全部localStorage／sessionStorage／IndexedDB引用，两个恢复Store的构造器及创建者；RegistrationInstallation字段、content_paths、content_package与git_receipt_store引用。一次rg通配作为Windows文件参数失败，随后改为目录＋glob搜索完成补查，不用失败结果声称无引用。未读取业务库、凭据或私有数据目录。

本轮EnvironmentSpec文档内JSON Schema使用已安装Draft202012Validator.check_schema通过；内存中3个角色正例通过，11个反例均被拒绝（未知字段、非法角色／ID／revision、bool整数、空／重复能力、非法model_io、秘密额外字段、缺data_ref、生产绑定工作区）。复读文档内Schema与内存对象一致。22主章节、围栏配对、本地链接存在检查通过。所有样本仅内存生成，未保存JSON报告／样本／脚本；Markdown原子保存，临时文件已清理。

只证明草案结构及上述案例，不证明关联对象存在、路径身份、整数词法、权限、宿主启动或产品兼容。Schema其他关联对象／action payload尚未完成；数据库旧宿主身份字段尚未逐表盘点，云迁移未准入。未运行产品测试、构建、浏览器、服务操作或真实调用。

## 详细设计0.4接续（同日，后续设计轮次）

只读核对Schema200列注册、仓库登记写入与baseline读取路径、实例／命令／步骤／交付窗口字段；未打开用户库。Windows rg文件通配有一次失败，后用目录检索补查。输出截断部分未算完整解码器审阅。

新增四类关联配置和七类动作typed_payload草案，Draft202012Validator.check_schema通过，11正例与15反例符合预期；复读Markdown内Schema与内存相等，本地链接及围栏通过。样本仅内存，未保存JSON／日志／临时脚本；Markdown原子写入并清理临时文件。

确认原仓库路径直接参与后续调用，设计禁止自动迁址／重绑旧任务；旧会话、进程和控制代次只保留历史，不跨宿主恢复。完整JSON字段解码、终态恢复读取、真实数据迁移仍未验证；结构正反例不等于运行准入。未改源码／正式设计／数据／服务，未产品验证、提交或真实调用。

## 详细设计0.5较大批次（同日）

只读核对GuideWorker.start、recover_previous_process、recover_workspace_starts、recover_drafts、_advance_delivery_write及repository_reads；task_delivery_reads仅定位列表／包校验入口，未冒充所有历史文件读取闭包。两处猜测的task_start文件名不存在，未据此推断缺能力；实际恢复代码已从真实路径读取。部分大输出截断，后续使用短范围补读关键查询。

配套契约0.2增加WorkspaceBinding、HostRequest、HostReceipt、MigrationPlan；Draft202012Validator.check_schema通过，FormatChecker启用，9个新增正例／14个新增反例符合预期；文档Schema复读一致。本轮检查不替代此前11／15个案例的历史结果，也不声称全部schema回归。主稿及契约本地链接、围栏及UTF-8字符检查通过。

设计补充权限／OIDC建议、页面完整流程、备份、迁移回退和ENV-F15—25；官方OIDC内容仅作协议依据，未选认证产品、未登录或建云资源。原始样本仅内存，Markdown原子保存并清理临时文件。未改源码、读取用户库、运行产品验证、真实模型、服务更新、Git提交推送。

## 详细设计0.6整体审查（同日）

静态定位原维护plan／rehearse／apply入口，未运行维护操作；猜测schema_v20_inspection.py不存在，未据此认定项目没有检查能力。主稿修正只读查询版本锁死、缺HALT动作、迁移摘要含可变状态和观察重启序列问题，收敛第一批范围。

配套契约0.3新增Observation、六类ActionResult、MigrationInspection及HALT_PLAN。完整schema自校验通过；新增8正例／9反例符合预期；本地链接、围栏、UTF-8检查通过。仅结构证据，跨字段语义、全恢复闭包、远程／真实路径／认证／产品运行均未验证。样本仅内存，Markdown原子写入，临时文件清理，未保存JSON报告。未变更源码、用户数据、服务或Git状态。

## 详细设计0.7有限收口（同日）

读取operation_protocol.py完整注册及末尾RESOURCE覆盖、recover_runs、complete_saved_returns、task_stop执行表范围、只读schema_v20_state检查入口。确认保存已有模型返回是启动恢复的一部分，不等同真实供应方调用，也不是只读。

新增AccessPolicy、TransportProfile、EvidenceDescriptor、CoverageManifest；schema自校验通过，4个结构正例、8个反例符合预期，文档Schema复读一致、两文档本地链接／围栏／UTF-8检查通过。作用域权限、真实证书、步骤逐解码及恢复运行仍未验证，操作族清单不冒充完整解码闭包。

新增只读结果接口及ENV-F33。未读取用户库、改产品源码、测试产品、构建、服务更新、真实调用或Git提交。样本只在内存，临时写入按原子替换清理；只保留Markdown。

## 详细设计0.8交叉核对（同日）

只读核对ApiClient错误策略、导航、package脚本、普通启动入口、共享确定序列化和原Windows路径保护入口。确认源码ROOT父级为backend，默认前端位置描述在设计内修正；未更改源码或据此推断现有服务故障。一次猜测的基础设施json_canonical路径不存在，实际读取shared/json_canonical.py。

新增引用装配／跨字段／错误映射及A—F实施范围，缺口收敛G1—G4。契约结构未改，Schema自校验及271处内部$ref目标存在性通过；主稿44章、链接、围栏、UTF-8检查通过。未重跑历史样本，不把内部$ref可解析当实际运维引用已装配。未执行产品专项／构建／浏览器／服务操作／真实模型，文档原子保存及临时清理。


## 详细设计0.9／首期安装与只读管理规格0.1（同日，较大设计批次）

用户要求继续推进、按约半小时工作量处理；本轮交付仍限独立设计及静态阅读，不是代码实施。新增首期安装与只读管理规格，更新详细设计0.9、结构契约0.5、方向稿导航与pending目录；未改原V2实施进度或正式设计。G2／G3已具体化为第一批输入，G1迁移解码闭包和G4云现场仍未闭合。

实际静态读取／定位：普通与冻结启动入口、ai-service启动与离线分支、Vite配置、前端main／navigation及ApiClient，shared/json_canonical、strict_objects、http_errors、http_projection，process_lock、windows_process、windows_private_package、windows_config_source、windows_local_paths、windows_backend_package，database.configured_path、ModelProfile、local_deployment、production_options、GuideWorker.start、service.lifespan、Guide计数／发送、Testing发送、CodingModelGateway.reserve_call／_dispatch。未打开业务库、秘密文件、私有内容或真实服务端点。一次local_deployment猜测路径不存在，已定位code_tasks下实际文件补读；一段静态导入闭包输出被截断，未将其作为完整依赖审计证据。

发现与修正：管理入口不能导入已有业务http_projection／main；管理构建不能复用应用dist；Windows受限句柄不能长期持有待原子替换的current文件；本机不同端口不构成Cookie隔离；runtime-identity改为/api/v1前缀；页面实际版本不能取期望值补齐，观察和能力过期均UNKNOWN；管理响应保留既有包络，首期data结构单独定义。外部依据为RFC6265第8.5节；只用于协议事实，未验证浏览器登录实现。

静态检查命令形态：PowerShell标准输入Python脚本，读取Markdown JSON围栏，json.loads及Draft202012Validator.check_schema，FormatChecker开启；使用内存正反例，不导入产品代码。中间版本8个新对象13正例／24反例符合预期；新增ManagementInstallation及观察约束后重查最终9个新增对象，19正例／33反例全部符合预期。覆盖必需字段、未知字段、DATA归属、秘密格式／文件名、IPC／mTLS互斥、STALE／MISSING／READY组合、证据权限、分页和READ_ONLY安装模式。完整契约324处内部$ref可解析。

另用3个内存反面输入确认结构校验的已知边界：相对根路径、Windows设备文件名、含凭据／查询的HTTPS地址可满足宽字符串Schema，已明确列为目标程序必须拒绝的语义检查；未把这些情况写成Schema已保护。未实现或运行跨字段／引用存在性／路径身份／证书／ACL验证器。原16类对象未因无关改动重复历史案例，不把本轮19／33称为全协议回归。

5份设计与导航文档UTF-8、围栏、50条本地链接、44章主稿结构、旧错误API前缀清除检查通过；原子写入比较原字节后替换，pending目录本轮临时文件剩余0。所有样本及校验脚本仅内存／标准输入，无JSON报告、截图、日志或脚本文件。最后文字调整仅补Bearer请求omit、轮询不续空闲期限及运行身份版本来源，结构Schema未再变化。

未执行产品专项、类型／格式检查、构建、浏览器、并发／掉电／进程故障、安装、业务数据初始化、云部署、真实模型／计数、服务启停、Git提交推送。M01—M12为后续验收目标，不能当本轮运行证据。后续设计以[现行大纲](../../iterations/pending/v2.01/WALL-E.开发与生产环境分离迭代V1_V_2.01.md)为准。


## 详细设计0.10／迁移覆盖规格0.1（同日，接续设计批次）

范围：独立设计与源码静态阅读，未实施。新增云迁移检查覆盖与准入规格；首期安装规格0.2增加多Agent可写依赖／缓存／端口／交接与集成边界；契约0.6修改CoverageManifest及MigrationInspection。方向稿及目录只同步导航，原正式设计与V2实施进度未改。

实际证据：完整读取operation_protocol.py，用受限AST常量／容器／字典推导解析及末尾update重建注册；不import项目模块。得到CODING 16操作62步骤、TESTING 14操作45步骤、RESOURCE 17操作40步骤，总47／147，已逐操作落入文档。静态解析Coding public_task_operation的16种分派；读取START、停止、Testing操作／RUN_TEST归属、仓库与交付目标包读取、check_v20、verify_candidate_package及candidate_materialization相关函数。候选分派定位不等于全部调用闭包已审查；截断输出未算完整阅读。

初次拿旧db20-r1 SQL比对时发现PREPARE_HANDOFF两步骤缺失；随后读取load_release及schema_v20_admission实际pin，确定db20-r49，manifest字节SHA256与pin匹配。重新按当前固定SQL抽取步骤保护，147项与文档全集完全相等；这只证明静态注册一致，未运行数据库／资源准入。步骤状态为PENDING／RUNNING／SUCCEEDED／FAILED／UNKNOWN／CANCELLED，无SKIPPED。若后续源码或pin变化须重新核对，不能按本记录继续当当前事实。

发现：Testing read_original_run要求current_verification_id，不适合任意历史遍历；多个公开投影裁剪私有输入／身份；交付和候选读取依赖原FileIdentity，跨主机复制不能直接承接。内容包校验可保留原binding／seal／manifest，但目录basename和目标新物理身份仍须受控核对。新增历史定位证明设计限定HISTORY_READ_ONLY；物化／重新执行不由此开通。没有实际搬迁或验证目标文件。

检查命令形态：标准输入Python＋ast／re／hashlib读取源码和文档；json.loads、Draft202012Validator.check_schema及FormatChecker检查契约。变更契约5个正例、17个反例符合预期；完整328个内部$ref可解析。反例覆盖COVERED缺程序引用／状态、非法步骤序号及bool、重复／非法状态、UNSUPPORTED无原因或假覆盖状态、FENCED缺屏障。另确认同一owner／step键搭配不同checker能通过结构uniqueItems，已明确要求程序做唯一键及全集校验，不假称Schema能证明。

6份设计／导航UTF-8、围栏、55条本地链接、47行操作表及注册源码摘要核对通过；无本轮临时文件。遇到Windows rg通配参数和猜测路径不存在，已改用实际目录／文件定位补查，未据失败输出推断缺能力。未保存JSON样本／日志／脚本或截图；Markdown采用原字节比较后原子替换。

未执行产品测试、类型／格式／构建、数据库打开、私有凭据读取、服务／云操作、真实模型或计数调用、Git提交推送。MC01—MC12及历史定位补充反例仍是未来验收。G1尚需机器定位契约、逐状态解码／资产读取闭包与实现证据；G4仍需具体云目标现场。接续入口为详细设计第44章及迁移覆盖规格第8章。


## 详细设计0.11／迁移规格0.2／契约0.7（同日，历史资产定位批次）

授权范围保持独立设计与源码静态阅读。新增MigrationAssetMap／MigrationAssetMapSet及DataBinding.migration_asset_map_set_ref草案；迁移规格6.3—6.7细化私有登记、业务整数／管理UUID、确定摘要、集合完整性、连续迁移、历史读取门面、错误与激活边界。主稿当前断点及方向稿／首期稿／目录同步引用，未新建实施计划或修改原V2实施进度。

本轮实际阅读：task_candidate_reads的_saved／_verify_package／_available／列表／详情，task_candidate_content_reads的_read_after／_read_before／read_file／read_comparison，task_delivery_reads的_plan_files／目标包读取及对比，repository_snapshot_reads._snapshot，repository_baseline_query的load_baseline_query／私有查询记录发布／retire，RepositoryRegistrationWorker.read_snapshot及_read_next_snapshot、_run相关装配；另读CandidatePackageBinding／TargetPackageBinding、verify_candidate_package关联的_verify_repository、StoredCandidatePackage读取／原seal核对、authorized_content_settings，以及Testing候选读取与检查输入转运的相关片段。较长输出截断部分不当完整审阅，必要函数另用短范围读取。

已确认三项具体事实：候选比较即使请求AFTER仍读取BEFORE基线；候选列表对本页所有包执行可用性核验，不能迁移后跳过缺失项；基线查询会通过PrivateRecordAppend写snapshot-query记录并经worker／Guard，不能视为纯DATABASE_ONLY检查。候选正文与交付历史分别需要不同资产闭包，不把两类包迁移等同整个业务可迁移。保持原内容容量为profile与原启动授权较小值，迁移不扩大。

只读AST扫描backend/app的直接具名调用：verify_candidate_package 14处、read_stored_candidate_package 9处、export_check_input 1处、materialize_candidate 0处。调用点清单已落入规格；扫描未执行项目模块，且不涵盖动态别名。0个直接调用不意味着可删函数；14处存在不意味着各自调用闭包已审完。适配限定已核对的历史读取门面，共享内容验证函数不提供失败后自动找迁移map的回退。

静态契约检查使用标准输入Python、json.loads、Draft202012Validator.check_schema与FormatChecker；7个正例、24个反例符合预期，覆盖两类资产、二次迁移、空集合、未迁移DataBinding、额外字段、必需字段、错误ID类型、非法scope／basename／时间、源屏障缺失、前一映射条件及集合限额。367处内部$ref可解析。另确认basename与store_key值不一致、entry_count与数组长度不一致仍能通过结构Schema，已明确要求程序语义校验，不宣称Schema已保护。

6份设计与导航UTF-8、围栏、56条本地链接、主稿44章、文档JSON Schema自校验通过；原147步骤注册源码摘要仍与上轮记录相同，未无关重跑所有历史案例。文档按原字节比较后原子替换，临时文件剩余0。全部样本／校验脚本只在内存及标准输入，未留JSON报告、脚本、截图或日志。

未读取业务库或秘密，未执行产品测试、类型／格式检查、构建、浏览器、服务、Guard安装、真实模型／计数、云操作、提交推送。私有资产定位记录尚未实现；MA01—MA10为后续验收。仓库基线可携带证据、147步骤逐状态解码及云平台资格仍未闭合。当前接续见主稿44章和迁移规格8章；避免把已完成的定位字段重新列为未设计。


## 大纲1.4定位与结构整理（同日）

按用户最新指示，本阶段仍按大纲组织，后续独立输出本迭代前后端文档。原大纲整合为8章，明确三阶段交付、可视化入口、云新部署与既有迁移分开验收，以及后端承载共同规则／接口、前端引用共同契约的职责。已有4份技术细化材料保留，顶部仅补编制依据定位提示；其旧断点不再决定当前工作顺序。未新建空壳前后端文档，未合并原正式设计。

静态检查：6份修改文档UTF-8、围栏、63条本地链接及大纲8主章检查通过；未修改技术Schema，无需重复结构样例测试。使用标准输入Python原子保存并复核原字节，临时文件已清理。未改源码／资源／数据／服务，未产品测试、构建、浏览器、真实调用、提交或推送。接续以迭代大纲1.4第8章及用户后续指示为准。


## V2.01单文档合并（2026-11-14）

用户要求合成一份。原大纲更新为1.5，正文保留8章大纲，四类技术材料纳入折叠附录；重复总体说明和独立历史断点移除。合并后核对原2个JSON结构草案代码块保持原内容，再移除4份独立分析稿，历史检查记录引用指向新附录。当前版本目录仅有1份设计及README导航，后续前后端文档尚未创建。

静态检查：UTF-8、围栏、4组折叠区、11条本地链接及显式附录锚点通过，两段JSON解析通过；未改Schema，不重跑产品或历史结构样例。原子保存后按准确文件路径核对原字节再移除源稿；无代码、资源、数据、服务、模型或Git提交操作。
