# WALL-E V2.0 Windows受管执行与完整停止迭代

日期：2026-11-02（Asia/Hong_Kong）。状态：第三项Q20-WINDOWS设计选择已定，待运行验证；未实施或合入正式设计。前两项已确认结论保持。

## 1. 本项输入及真实缺口

当前后端0.4-draft-4／前端0.3-draft-3要求：编码只写本任务工作区；固定依据、运行包、程序配置和其他任务不得由执行器改写；供应商凭据由后端持有；终止应覆盖工具、子进程及本任务应用服务。本期不承诺任意Windows环境强隔离，不默认引入Docker。

目录／网络权限与进程回收是独立机制。当前实现的ProcessLock仅锁定WALL-E服务所有权，execution_lease保护数据库提交；静态搜索未发现现成Job Object或代码执行沙箱，不能按旧单Chat的取消能力声称已经覆盖。

本轮仅Markdown、源码／官方资料阅读与静态核对。不安装执行器／驱动，不创建Windows账户／AppContainer／防火墙规则，不更改ACL、服务、进程、用户环境、源码、数据库或真实调用。CIM只读操作系统查询被客户端拒绝，本轮不升级权限；不据此编造本机OS版本或适配结果。

用户已明确选择“采用Windows内置隔离（推荐）”。当前采用下文A；B保留为未采用方案，不提供自动降级。后端更新0.5-draft-5／前端0.4-draft-4，仍为DRAFT。

## 2. 静态来源事实

| 依据 | 已核对事实与边界 |
| --- | --- |
| Microsoft Job Objects | 适合成组管理／终止进程；常规CreateProcess子进程默认继承Job，breakaway设置会改变归属；其他系统代理创建不受此结论覆盖。Job不能单独承担文件及网络访问控制 |
| Microsoft创建／查询API | 可先CREATE_SUSPENDED，再加入Job后恢复；可查询Job成员／统计。KILL_ON_JOB_CLOSE依赖最后一个句柄关闭，子进程不能继承控制句柄；不能只看父PID／端口或单个通知 |
| Microsoft受限令牌 | 收紧权限与SID可参与对象访问核对；不是仅换cwd或去掉管理员标志就得到目录白名单；本轮不把方案候选当作可运行 |
| Microsoft AppContainer | Windows内置的受约束执行环境，未打包Win32程序可适配；文件、进程和网络能力需明确授权，兼容性需要实际验证 |
| 固定OpenCode Shell | 同提交shell.ts调用原生Shell并继承受管进程环境；cross-spawn-spawner.ts在Windows停止路径调用taskkill，已退出父进程的清理分支不证明遗留服务已被回收。WALL-E仍需自己的外层生命周期 |
| 路径核对 | GetFinalPathNameByHandle可取得打开后真实路径；只做字符串前缀检查不足以约束链接／别名／并发替换。可支持的卷／文件种类必须固定 |

## 3. 已确认的运行方式与未采用方案

### A. Windows内置隔离（已采用）

为代码任务使用专用AppContainer执行身份，按任务授予工作区写入、固定材料及工具读取；WALL-E持有控制根、数据库、配置和供应商凭据。外层Job负责完整进程回收。网络需要同时限制到受管入口及明确批准目标，不能为了连通本地模型入口就开放所有本机服务。

首次环境准备／网络策略可能需要一次管理员配置；日常后端和代码任务不以管理员运行。Windows构建、OpenCode／Python／Node／Shell兼容性、受控入口双向连接与所有必要边界验证之前，ready=false。不得在隔离失败后自动退回当前账户直接执行。这里选择的是设计方向，不表示本轮允许安装或修改系统。

本方案需继续明确AppContainer能力、文件ACL、网络过滤及本地入口接法；任何粗粒度网络能力或loopback例外均不能直接当作精确目标白名单。只声明实际通过的环境，不扩成任意Windows强隔离。

### B. 沿用当前Windows账户权限（未采用）

部署与常用开发工具更直接，仍使用独立工作区、固定配置、后端授权检查及Job回收。但执行代码拥有当前账户可取得的文件／网络能力，不能把只读标志、路径提示或模型规则当作系统级保护。

若用户选择此方案，必须同步修订两份草稿中“不能写固定材料／配置”“不能访问其他任务／秘密”“网络只限授权目标”等强制保证，明确只提供已验证的流程控制及可信本地执行范围。不能保留A的保护承诺却实现B，也不默认提供两套可自动切换的产品流程。


### 3.1 WIN20-ISOLATION-1的具体组成

- 本期执行目标Windows 11 x64、本地NTFS；具体Windows构建及OpenCode／Shell／Python／Node／包管理器组合由不可变运行包清单及证据锁定。没有已经通过的组合，默认不可执行；本轮CIM失败不当作当前主机符合条件。
- 代码进程采用AppContainer的LPAC形式，显式退出All Application Packages隐含访问；每个任务实例独立profile／SID，只有当前任务可写目录和必要只读资源获得授权。缺失能力时拒绝开始，不降为普通AppContainer或当前账户。
- 运行器依然由现有后端决定业务动作。增加一个本机Windows权限组件，作为安装准备的原生Runtime Guard服务，仅处理固定资源绑定、LPAC创建、Job及网络策略；无业务队列，不读取业务库、设计正文或模型凭据，不参与任务规划。后端不整体提权，组件不得向代码进程传递其服务身份或管理员令牌。
- Runtime Guard是Job控制句柄的唯一持有进程；后端只用不透明引用查询。它绑定经过认证的后端进程句柄及owner_epoch，后端退出就封闭启动并终止原Job；Guard自身退出由KILL_ON_JOB_CLOSE回收。不能让另一常驻进程的句柄使“最后句柄关闭”条件失效。
- Guard IPC只接受已登记执行器／运行包／命令身份、任务根绑定、原操作和步骤nonce，不接受提权的任意Shell／任意文件ACL修改；本机管道验证用户／后端程序／进程创建时间及非AppContainer身份，代码进程不允许调用。系统准备可能需管理员，日常任务使用经认证的普通用户派生LPAC令牌；不能直接用Guard服务令牌生成代码进程。
- 工作代码、任务依赖／缓存／临时目录及OpenCode自己的可变数据库可写但均在本实例范围，且后者是非产品／非可信控制数据。固定Revision副本、配置、执行器依赖和受控检查资源只读。WALL-E业务库、供应商凭据、私有快照、目标Git及其他任务完全不授予；真实源仓库和目标交付只由后端操作。
- 网络按AppContainer SID在WFP的IPv4／IPv6 ALE连接、监听和接收层约束，默认拒绝，精确允许所需loopback地址／协议／端口。出站只到本任务受控模型入口及受管网络转发入口；代码不直接获取互联网／内网广泛能力或DNS出口。转发按已授权目标核对主机、端口、重定向及解析结果，不是任意开放代理；目标变更需新授权。模型协议仍留Q20-MODEL。
- loopback默认限制与本项目端口白名单需同时满足。允许为本profile设置必要例外，但必须已证明WFP对其他本机服务及其他任务仍拒绝，不能把例外本身当目标限制。入站仅允许本机访问已登记原生控制／应用测试服务端口；原生控制入口继续Basic鉴权，不向浏览器暴露。
- 必需的默认拒绝策略按受管持久WFP资源保存，避免动态会话消失时先卸掉网络限制；异常保留限制直到关联进程已退出并完成原资源核对。记录资源owner及原操作，恢复只回收本轮所属规则／profile，不清理用户防火墙。仅注册必要WFP管理资源，不引入自定义内核驱动；兼容性、仲裁和BFE边界未验证前不准入。
- 阶段静止允许宿主仍运行；整任务停止要求所属Job和所有启动步骤均核清。LPAC是任务级隔离，不冒充每会话写入栅栏；旧会话取消、工具结束及无迟到写入仍须原生协议证据。缺失时不能交接或捕获；需要结束整个Job时不自动换实例续跑。

以上是锁定的设计要求，权限组件、运行包、隔离网络转发和适配证据均尚未实现。新组件是Windows权限边界的必要职责，不是第二份任务调度或供应商系统。

## 4. 已采用的进程与停止规则

以下生命周期规则按用户确认的A写入两份草稿；没有运行证据。

1. 每次受管活动先保存原启动步骤、任务／实例／代次、随机Job关联和期望程序。创建Job并设置KILL_ON_JOB_CLOSE，拒绝breakaway／silent breakaway；Job访问权只给控制方，句柄不继承到执行器。嵌套Job不兼容时明确拒绝，不能关闭约束继续。
2. 根进程CREATE_SUSPENDED、隐藏窗口、固定可执行文件和显式参数／环境。先关联Job、核对PID及创建时间／程序／归属并保存；持久结果可靠后才ResumeThread。创建或提交未知时保持挂起或结束本次已确认所属进程，不能先运行后补关联。
3. OpenCode及常规工具／开发服务归执行Job；检查进程归明确检查活动的Job。WMI／任务计划／SCM／提权或既有外部服务代启动不属于本期普通子进程保证，须被受管执行边界禁止；不能靠命令文字过滤声称已限制任意脚本的间接后果。
4. 原生idle、模型说完成、HTTP断开和父进程退出均不是完整停止。TERMINATE先持久化意图并封闭新启动／新投递／模型入口，再请求原生abort；按固定停止时限等待，必要时TerminateJobObject，之后核对真实成员退出、所有原启动步骤及在途Git结果。
5. Job终止请求返回或active成员某次为0仍须结合启动屏障及原成员证据；不知道归属、查询失败、拒绝终止或在途写入不明时保持STOPPING／等待事实。端口只作辅助观察，不按端口杀用户服务，不用旧PID重试。
6. 后端退出由Guard持有的控制方进程句柄触发原Job终止；Guard退出由最后Job句柄关闭触发回收。重启不能只凭Job名称消失就标完成；恢复原启动／停止步骤，核对原进程身份和资源。无法补足证据保持待核对，不自动新建会话／工作区。
7. 阶段静止与整个实例退出分别记录。角色交接／候选捕获允许保留无活动的原生宿主，必须另外核对旧会话取消、工具／服务及写入静止证据；不能要求“Job所有成员为0”又声称宿主仍运行，也不能把idle单独当静止证明。确需强制停止整个Job时进入原终止流程，不暗中重建实例续跑。
8. 文件访问限定本地可验证普通目录／文件；拒绝未准入的reparse／junction、跨卷别名、设备／UNC路径、ADS及指向受保护对象的硬链接等；具体内容格式和来源捕获竞态继续归Q20-CONTENT。本条不授权扫描或改动用户文件。

## 5. 后续设计落点与验收目标

- 后端第7.3拆成环境支持、目录／网络边界、启动／所有权、阶段静止及完整停止；扩展既有ManagedInstance／CommandExecution／原操作证据，不增独立业务调度服务。
- 前端从TaskView读取安全投影，分别展示准备失败、停止中、停止结果待核对、阶段静止及已终止；不展示沙箱SID、句柄、秘密或内部路径，不提供“忽略限制继续”。
- 后续隔离验证包括：启动关联前崩溃、父进程先退子服务仍活、嵌套Job／breakaway、后台工具、PID复用、迟到启动、后端崩溃、路径别名、未授权目录／网络、正常Shell／Python／Node开发闭环与停止后资源核对。
- 本轮执行数0。用户选择后已按A把支持承诺写进两份DRAFT；原V1.5、汇总、前两项迭代和历史验证不改写。

## 6. 一手来源

读取日期2026-11-02；只采用官方Microsoft文档及OpenCode固定提交，未运行示例。

- [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)、[Job权限](https://learn.microsoft.com/en-us/windows/win32/procthread/job-object-security-and-access-rights)、[Job查询](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject)、[创建标志](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)。
- [Restricted Tokens](https://learn.microsoft.com/en-us/windows/win32/secauthz/restricted-tokens)、[CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)、[CreateProcessAsUserW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasuserw)。
- [AppContainer isolation](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation)、[未打包Win32适配](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-for-legacy-applications-)、[IPC与loopback限制](https://learn.microsoft.com/en-us/windows/apps/develop/communication/interprocess-communication)。
- [真实路径API](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew)。
- [固定Shell工具](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/tool/shell.ts)、[实际spawn／停止分支](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/core/src/cross-spawn-spawner.ts)、[辅助Process工具](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/util/process.ts)。

Guard协议幂等以控制方／动作／原步骤／nonce为域，资源记录在回复／Resume前可靠保存；重启查无记录不当作未执行。后端OperationView去除Guard／Job绑定、控制方epoch和原始OS证据，前端只读安全状态投影。

当前断点见[设计进度](../../../project/v2.0/设计进度_V_2.0.md)。本项为设计已定／待环境与协议验证，不是可执行环境或新的第三份共同规格。

补充一手来源：[LPAC启动及显式能力](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)、[WFP各层条件](https://learn.microsoft.com/en-us/windows/win32/fwp/filtering-conditions-available-at-each-filtering-layer)、[条件类型](https://learn.microsoft.com/en-us/windows-hardware/drivers/network/filtering-condition-data-types)、[仲裁](https://learn.microsoft.com/en-us/windows/win32/fwp/filter-arbitration)、[对象及动态会话生命周期](https://learn.microsoft.com/en-us/windows/win32/fwp/object-management)、[WFP访问控制](https://learn.microsoft.com/en-us/windows/win32/fwp/access-control)。

本轮记录见[Windows边界设计核对](../../../verification/v2.0/windows-runtime-design-2026-11-02.md)。


## 9. 原 TASK 的新目录权限（2026-11-08）

Guard 只在原私有受管根下，以原 PREPARE 已保留的目录 nonce 创建新执行目录。根目录只授予原用户与原包 SID 穿越权限，不授予列举、创建、删子项或改 ACL。workspace 和 scratch 使用低完整性标签与明确可写权限；basis、config 和 runtime 只授予读取及执行。角色根不授予执行身份删除、改 ACL 或改所有者。对工作区／临时文件的子对象，通过单独继承规则授予工作需要的删除权限，并以 OWNER_RIGHTS ACE 避免默认所有者权限补回 WRITE_DAC。只读角色的 ACL 可继承至后续私有副本。Guard 操作者保留维护权限；原普通用户与原包 SID 分别绑定，其他任务 SID 不加入允许列表。 [Microsoft AppContainer 访问模型](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer) [Microsoft 文件权限](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)

原目录、卷和 FileID 以及实际保护 DACL 和完整性标签须读回。已存在的目录不接管或修复，部分分配保留原 owner 和已知事实供后续原停止流程处理。初始角色目录为空；固定工作区、依据、受管配置与运行包之后由对应原内容路径验证并填入。原后台工作区或依据封存不修改 ACL。目录权限证据和实际 LPAC 进程访问证据分开登记，完整 Guard PREPARE 仍受运行包、入口和 Job 准入约束。


## 原任务输出与停止回收接续（2026-11-09）

原 TASK 根在恢复前交接唯一 STDOUT／STDERR 读取者。读取有上限，超限时继续有界排空以解除子进程背压，只将原输出计数、摘要、EOF 与不完整原因写入后端私有证据。诊断输出与原 Job 停止及任务终态分别核对。停止事务先封闭原模型窗口；Guard 后续仅凭原持久 STOP、实际原 Job 与受管目录证据清理，保留业务依据及审计。跨控制方仍遵守此前已确认的原范围窄恢复。
