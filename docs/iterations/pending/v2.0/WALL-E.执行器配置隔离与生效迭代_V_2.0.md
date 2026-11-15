# WALL-E V2.0 执行器配置隔离与生效迭代

日期：2026-11-02（Asia/Hong_Kong）。状态：Q20-CONFIG设计收敛；静态源码依据，未实施、未运行验证、未合入正式设计。

## 1. 用户确认与范围

用户已确认：允许OpenCode参考代码仓库中已有的排版、测试、目录等开发规范；WALL-E确认的功能设计、预算和权限优先。本项不要求过滤仓库中的AGENTS.md，也不把它作为程序授权来源。

本迭代先保存，再更新后端0.4-draft-4／前端0.3-draft-3；仍仅文档与静态核对。前项v1.19.5锁定及同会话权限拒绝决定保持。原汇总、V1.5正式设计和已完成迭代／验证记录不改。

## 2. 固定提交的源码事实

以下均指OpenCode提交810c0eba1a7348036f8bdf61e6632d0c36c6876c，读取日期2026-11-02。

| 事实 | 设计含义 |
| --- | --- |
| 配置依次涉及well-known认证、全局、自定义文件、项目文件、配置目录、inline、组织及系统managed；指引及插件存在累计／去重逻辑 | OPENCODE_CONFIG不是唯一配置源，末尾写空数组不等于清除来源 |
| OPENCODE_DISABLE_PROJECT_CONFIG跳过项目配置及部分指引扫描；directories仍包含全局、home/.opencode及自定义目录 | 单个禁用开关不能证明没有额外来源 |
| Global使用XDG配置／数据／缓存／状态路径，home及tmp另行解析；Windows managed默认读ProgramData/opencode | 为受管子进程固定独立路径并核对实际解析；保留真实系统managed检查，不用TEST开关绕过 |
| disableDefaultPlugins跳过内置认证插件，pure跳过外部插件；配置加载仍可能调Npm.install | “无插件”不等于“初始化无安装或联网” |
| Npm.install在目录不可写时返回；已有node_modules时仍核对清单／锁文件中声明的依赖集合 | 执行器依赖应提前准备和核实，再以实际受保护的只读目录运行；不能让任务初始化临时补依赖 |
| Instruction.resolve读取文件时可能继续附加子目录AGENTS／CLAUDE／CONTEXT文件 | 接受作为工程参考，保留真实上下文；不能声称项目配置开关完全过滤仓库指令 |
| PATCH /config写文件、标记实例待销毁，并返回请求payload；PATCH /session合并permission而非替换 | 不把PATCH成功当已生效；运行中不热换原生配置，不把权限合并当原规则已删除 |

## 3. 本期采用：OC20-CONFIG-1

1. 每任务受管实例使用独立运行根，代码根和控制根分开。只为子进程构造允许集合环境；XDG_CONFIG_HOME／DATA_HOME／CACHE_HOME／STATE_HOME、USERPROFILE、APPDATA／LOCALAPPDATA、TEMP／TMP等指向本实例私有位置，必要系统变量／工具PATH精确保留。核对Global实际解析结果；不改变WALL-E父进程或用户真实环境，不使用OPENCODE_TEST_HOME／OPENCODE_TEST_MANAGED_CONFIG_DIR。
2. 禁用项目配置；自定义配置文件固定到运行包内，不继承CONFIG_CONTENT／CONFIG_DIR／PERMISSION等任意外部覆盖。个人认证、账号／组织、个人插件／MCP／技能、代理秘密和供应商环境凭据不复制。系统managed配置存在或不可核对时拒绝准入，不修改／删除／绕过。
3. 外部插件及内置认证插件关闭；MCP为空，LSP／formatter=false，扩展技能／远程指引／实验性并行／后台子Agent不启用，分享和更新检查关闭。主辅模型只指向固定受控入口；辅助请求仍受原预算审计。实际配置不是预期值就不开放模型资格。
4. 执行器运行包在任务外准备完整版本化依赖和目录，包含明确Schema的配置、依赖清单／锁文件／node_modules及必要.gitignore；准入核对实际字节、资源及只读边界。预准备可取得资源不等于本轮授权安装；包未准备／不能证明只读时CONFIG_NOT_READY。业务代码依赖仍按任务已批准命令／网络范围执行，二者不混用。
5. 读取实际GET /config、GET /config/providers、会话GET中的permission，并核对配置来源、路径、依赖、扩展及模型路由；原生读取可触发初始化，所以仅由已经预检环境／网络／凭据的后台准备步骤调用。浏览器普通GET只读持久观察，不去原生探测。
6. 原配置、编译后的期望组及真实观察一起关联TaskConfigurationApplication和原步骤；非秘密摘要可持久，临时网关凭据只存引用，不把完整原生JSON当公开日志。实际相符才APPLIED／EFFECTIVE；不一致或未知分别保留失败／待核对。
7. 无活动实例时可以按完整新配置准备。已有实例只接受不需重载原生全局配置、且可由既有WALL-E控制与原会话权限规则安全落实的变更；先停止受影响活动，再查实际组。权限以追加规则处理，必须核对最终顺序和有效边界。执行器／运行包／原生provider／插件／shell等需重载的变更，本期拒绝应用到活动实例并说明需终止后按新配置新建任务；不自动重启、处置实例或重建会话。
8. 仓库规范可供实现参考；不能改变固定材料、设计、用户验收、程序检查、授权和预算。不为此删除或改写代码库规范文件，也不增加独立业务依据对象。

只读、网络、进程与秘密边界须在Q20-WINDOWS／MODEL实际成立；这些配置开关本身不证明OS隔离。不能证明所需控制时保持ready=false。

生产开关明确使用OPENCODE_PURE、OPENCODE_DISABLE_DEFAULT_PLUGINS、OPENCODE_DISABLE_EXTERNAL_SKILLS、OPENCODE_DISABLE_CLAUDE_CODE、OPENCODE_DISABLE_LSP_DOWNLOAD、OPENCODE_DISABLE_MODELS_FETCH、OPENCODE_DISABLE_AUTOUPDATE=true；问题工具OPENCODE_ENABLE_QUESTION_TOOL=true。这些均为未来子进程环境设计，不在本轮设置或执行。

## 4. 草稿影响与验证边界

后端在既有executor配置中增加runtime_bundle_ref及configuration_policy_version，不新增执行器服务；TaskConfigurationApplication补实际证据引用，保持现有一组应用和原操作。前端只选已登记资源，显示“准备失败／结果待核对／需新任务”等具体原因，不开放原生JSON、个人凭据或插件管理入口。

后续隔离验证覆盖多来源污染、真实路径、managed拒绝、依赖离线准备、禁用扩展、主辅入口、仓库规范参考、权限追加、应用不一致及重载类变更拒绝。当前执行次数0；Q20-CONFIG为设计已定／待运行验证，Q20-WINDOWS／MODEL／CHECKS不因此完成。

## 5. 一手来源与接续

以下源文件已读；未全文审查全部Provider、MCP、技能、工具及Windows底层实现，不宣称这些通道已运行验证。

- [配置加载与来源](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/config/config.ts)、[目录](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/config/paths.ts)、[系统managed](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/config/managed.ts)。
- [全局路径](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/core/src/global.ts)、[Flag](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/core/src/flag/flag.ts)、[RuntimeFlags](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/effect/runtime-flags.ts)。
- [插件初始化](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/plugin/index.ts)、[Npm安装条件](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/core/src/npm.ts)、[配置Schema](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/core/src/v1/config/config.ts)。
- [读取时附加规范](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/instruction.ts)、[ambient指引](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/core/src/instruction-context.ts)。
- [配置PATCH处理](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/server/routes/instance/httpapi/handlers/config.ts)、[会话权限合并](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/server/routes/instance/httpapi/handlers/session.ts)。

静态结果见[配置设计核对](../../../verification/v2.0/opencode-configuration-design-2026-11-02.md)，接续见[设计进度](../../../project/v2.0/设计进度_V_2.0.md)。下一项为Q20-WINDOWS的受管权限／进程与完整停止边界，仍先设计后另行授权验证。

## 6. 受管运行包的原文件与实例目录（2026-11-09）

Guard 只从安装侧登记的固定包及摘要读取，任务原 PREPARE 固定引用须与该部署摘要相同。验证持有原清单和包根，逐个固定实际文件身份和字节。复制时重新打开同一原对象，在原读锁内核对身份和字节后发布到同一 TASK 的新 runtime 角色，保留 opencode.json、依赖清单、锁文件和 node_modules 的原相对布局。目标子目录及文件读回实际 ACL、完整性标签、卷和 FileID；原树以精确清单复核，已写入或结果未知不重建。

config 角色只承载实例只读配置根，配置文件继续指向 runtime 中原封存的 opencode.json。实例 home、数据、缓存、状态和临时目录走同一 TASK 的私有 scratch 角色。子进程环境从允许集合构造，不读取父进程配置变量或凭据。实际系统 managed 配置存在或无法核对时拒绝准备。

本批文件证据汇总仍独立于完整 PREPARE 确认。前置文件均已闭合后，Guard 只保存原依据、工作区、运行包和环境摘要；实际 LPAC、WFP、Job、固定程序及原生配置生效需另行取得证据。

## 7. 固定程序、入口和原执行准备（2026-11-09）

原 TASK PREPARE 在固定运行包之外，固定 OpenCode 程序引用、Job 限额和精确网络入口。Guard 仅接受部署登记的程序，持有官方归档成员匹配的实际 PE 原句柄。原生参数使用固定提交支持的 serve、显式 IPv4 回环主机及原控制端口，并显式关闭 mDNS。凭据及启动后协议核对另走原实例边界。

模型和转发监听先匹配部署登记的专用地址和端口，再在 Windows 原监听表中匹配已认证且仍存活的原后端进程；原控制和应用端口作独占绑定探针，实际启动后的监听归属仍须复验。只为已核对的原范围封存网络计划，原 WFP 规则安装沿既有 SYSTEM 及原意图约束。STOP 统一核对原 Job 和全部写入范围；已有网络封存不能绕过文件持有及原停止事实。

原 Job 绑定固定资源限制、KILL_ON_JOB_CLOSE 及原 LPAC 属性。文件、程序、入口、原 Job 和规则读回只是分项证据；未取得实际 LPAC／网络仲裁及运行资格时，完整 PREPARE 保持未知，不派发进程。

固定 OpenCode 参数对照 [serve](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/cli/cmd/serve.ts) 与 [network](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/cli/network.ts)。监听与端口探针对照 [GetExtendedTcpTable](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable) 与 [SO_EXCLUSIVEADDRUSE](https://learn.microsoft.com/en-us/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse)。

## 8. 原 LPAC profile、挂起令牌和有效文件访问（2026-11-09）

每个原 START_INSTANCE 只按已分配目录 nonce 注册一个每用户 AppContainer profile。Guard 在原普通后端令牌下调用 Windows 原生 API，先保存分配意图，再核对实际返回的 SID 与原角色 SID；已存在、结果未知及重启缺原 owner 均不能接管。调用只在一次性线程上临时使用原令牌，线程退出前复原，持久记录不含令牌句柄。仅在原停止和无进程／在途写入证据成立后回收实际新建 profile。

挂起根必须在既有原 Job 中，实际进程和主线程、原用户／登录、原 PE、TokenIsAppContainer、TokenIsLessPrivilegedAppContainer 及零附加 capabilities 一起核对。Windows 明确不实现令牌查询类时，使用同一原令牌对三组内存 ACL 核对实际 opt-out，要求可使用本包 SID 和 All Restricted Application Packages、拒绝 All Application Packages。原查询仍记为未知，明确返回 false 时拒绝。有效路径核对使用实际原令牌及打开后的 FileID，区分可写工作区／scratch、只读依据／配置、可执行运行包、不可访问的受保护来源及目录删除和改权限能力。实际 WFP 仲裁、完整 PREPARE 和正式派发仍须独立闭合。

原生接口对照 [CreateAppContainerProfile](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-createappcontainerprofile)、[DeleteAppContainerProfile](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-deleteappcontainerprofile)、[GetAppContainerFolderPath](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-getappcontainerfolderpath) 与 [Token 信息类别](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ne-winnt-token_information_class)。

## 9. 原认证管道的 profile 与网络顺序（2026-11-09）

原文件、程序、入口、Job 和网络计划证据齐备后，原 PREPARE 才允许分配 profile。分配和查询各自返回原绑定、Job 与 profile 的非秘密摘要，分配意图已存在时只允许查回。WFP 安装依赖原 profile 的实际复核；安装读回必须匹配同一原封存的派发事实，不能只凭碰巧存在的规则报已安装。原范围组合复核仍是分项证据，完整 PREPARE 需要部署准入、实际仲裁和控制凭据。

STOP 先关闭原 nonce 与文件写入并确认原 Job 无成员，保留原 profile 及其 Job。当前原控制方的 RELEASE 在持久 STOP 确认后才能进入。已派发 WFP 安装时先确认原规则回收，未派发时只回收已证明归属的 profile；两者均不写完整 RELEASE 确认。丢失原 owner 或派发结果未知保持待核对。

## 10. 进程派发前的原网络、控制凭据和工作树复验（2026-11-09）

跨子层检查与原规则逐键读回共用只读事务。遇到可能匹配原包的外部硬允许、callout 或无法解释的动作即阻断。停用／引导期对象以及可证明仅匹配另一个包的对象不作为当前冲突。检查覆盖固定六层的当前规则，实际连接、重定向、系统准入及运行期变化另行取证。

原控制凭据由后端按原启动作用域生成，通过认证管道交给原 Guard 执行准备。原回执只含引用和非秘密承诺。环境中仅在显式请求启动值时注入固定用户名和随机密码。后端原生控制绑定原回环入口，在实际连接归属已确认后才能为固定协议请求组装 Basic 头；停止时 Guard 丢弃原凭据。

后端原固定清单仍决定允许的路径、逻辑模式和字节。发布摘要同时绑定目标文件与目录的 FileID 及实际字节。Guard 关闭原发布写端后独立枚举、锁读、核对整个目标树；同路径原位改写、同字节替换、遗漏、新增和 NTFS 命名数据流均使准备证据失效。目标侧观察采用 16384 个条目和 2 GiB 默认数据流总量的本机安全上限，并服从原请求期限；后端的原配置限制仍生效。旧发布摘要仅保留旧回执，不能用于新启动复验。实际 CREATE 前仍需在最后派发边界保持原写入屏障。


跨子层检查对照 [Microsoft WFP 仲裁](https://learn.microsoft.com/en-us/windows/win32/fwp/filter-arbitration) 和 [过滤器枚举](https://learn.microsoft.com/en-us/windows/win32/api/fwpmtypes/ns-fwpmtypes-fwpm_filter_enum_template0)。连接归属和数据流读回分别对照 [TCP PID 行](https://learn.microsoft.com/en-us/windows/win32/api/tcpmib/ns-tcpmib-mib_tcprow_owner_pid) 和 [FILE_STREAM_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_stream_info)。

## 11. 可信部署与原挂起启动（2026-11-09）

启动资格以安装侧固定证据文件和本机实际身份为输入。文件必须处于原受保护安装目录，按固定字节摘要、Windows 原生架构和构建、Guard 安装、WFP 组、固定运行包及程序核对。固定证据分别指向实际网络允许／拒绝、LPAC／Job、配置、控制鉴权和停止竞争观测，普通后端请求不能声明其已经通过。安装侧索引只读，引用的测试工件由正式部署验收提供。当前没有生产索引。

已知连接和绑定重定向层也在原 WFP 只读事务中检查，外部活动 callout 若不能证明与原包无关，保持未知。原工作树在最后派发观察时保留已核对成员的原 NTFS 锁，并在释放前复核目录清单和字节。单批挂起派发最多保留 4096 个原 NTFS 句柄，超限保持阻断。目录锁防替换，扫描尾部检查新增目录项。

挂起根仅按原部署计划以普通后端令牌派生，创建时原子加入原 Job。验证实际主线程、LPAC 和有效访问，保留原资源和持久原挂起证据。恢复必须先取得原后端确认并遵守同一持久 STOP 屏障，调用结果不明时只观察原资源。实际部署、原生 HTTP 和完整运行／回收仍按分项证据记录。


跨层核对对照 [Microsoft ALE 重定向](https://learn.microsoft.com/en-us/windows-hardware/drivers/network/using-bind-or-connect-redirection)。隔离回归中的程序是测试 PE，固定 OpenCode、正式 SYSTEM 和真实 WFP 仍需部署验收。

## 12. 原 TASK 认证动作与后端交接（2026-11-09）

后端在原作用域确认已查回的启动输入摘要和原子进程标准 I/O。Guard 在派发前保存确认意图及原 PREPARE 回执，丢回复只观察原动作。CREATE／RESUME 只针对原 scope、Job 和实际持有对象，前者重新核对全部启动输入，后者同时要求后端确认原挂起回执。已派发 STOP 先封闭并核对原 Job／根及 I/O，业务终态仍独立。控制方退出监视保留原资源以供后续原回收。生产发布仍依赖实际受保护部署及真实流量证据。


原后端在自己的原私有源根追加动作派发和确认事实，RESUME 读取原 CREATE 回执后才允许发送。管道重连继续使用原作用域和原程序身份。控制方退出只保存平台停止事实，不产生用户 STOP 动作。已派发 RELEASE 必须验证原 STOP、Job 和根退出，再回收原 WFP 规则与 profile；文件范围和完整业务收尾仍待，管道仅报告已证实的分项。

## 13. 业务启动持久边界、原生控制与模型来源（2026-11-09）

业务 START_INSTANCE 只消费原已核实的工作区、依据、配置和原步骤。外派前持久记录同一原操作的意图，未知只查回原实例。实例就绪须同时有原挂起／恢复回执、实际原进程及受控回环健康证据。原生控制请求使用固定动作和真实目录，连接归属先于 Basic 及正文发送；创建和投递的未知结果按原关联查回。

模型入口先由实际 accept 套接字固定五元组。认证 Guard 只核对当前原 TASK 的已恢复根、实际进程句柄、LPAC、Job 和连接两端。应用层先排除无效协议头和凭据，再将 Guard 证据与两次核对的原会话窗口绑定。实例 READY 前按受信安装给定的摘要核对原配置和 provider。任一证据缺失时不派发供应商调用。


## 14. 原 START 的会话和首条消息（2026-11-09）

实例 READY 后先在原第五步事务分配 BACKEND 会话。原生会话元数据绑定任务、实例、会话、原操作、控制代次和原启动 nonce。第五步确认原会话和已准入规则后，仅保存原生会话身份及本地会话引用。发送前固定完整文本、消息与正文段 ID，私有保存实际发送字节，业务步骤绑定摘要和 QUEUED 窗口。原 204 或回执丢失都再读回具体原消息；核对原用户角色、会话和全部正文段后才同事务完成第六步、打开窗口、应用原授权并把任务推进到 RUNNING／BACKEND。

原队列步骤、会话和原消息保持同一原操作。停止、代次改变、控制方失去原实例或原观察不确定时只保留原记录，窗口不可发送。生产仍需要固定 OpenCode、受信配置与实际专用模型入口准入。API17 仅投影本地会话 ID 和原步骤进度，API34 读取持久事实，原接收回执保持不可变。
