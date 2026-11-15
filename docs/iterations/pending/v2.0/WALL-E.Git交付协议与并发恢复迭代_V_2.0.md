# WALL-E V2.0 Git交付协议与并发恢复迭代

日期：2026-11-03（Asia/Hong_Kong）；编号M20-GIT-01；对应Q20-GIT；状态：设计已定／待固定程序与真实Git故障验证。保留pending；共同契约归后端，页面归前端，不另立共同规格。

## 1. 任务与边界

按用户“继续完成任务”接续第六项。起点后端0.7-draft-7／前端0.6-draft-6，均DRAFT；前五项及用户确认保持。本轮仅7份V2.0 Markdown、官方资料／源码和静态核对；不写产品源码、资源、配置、数据库或用户Git对象／分支，不安装／下载运行包，不执行Git写入、故障／恢复试验、测试／构建／浏览器／模型／计数，不启停服务或提交推送。

本轮只读git --version --build-options，现场为2.51.2.windows.1、x86_64、来源bd2ecbae58213046a468256b95fc4864de25bdf5；它不是本方案已准入程序。仓库HEAD仍8c5df4c6683e10c265e2f719a4fdc09ba4210ea0，原并行改动保留。误定位不存在的lease.py仅为静态搜索路径错误，不运行／创建该模块。

## 2. 采用GIT20-LOCAL-1

### 2.1 程序和运行包

固定Git for Windows v2.56.0.windows.4，源码提交581291682ad5a238c08c93d1f5bd4518382a3230，标签对象e878704e2f40adc59f4b0d4e15424511456163db。Windows x64选官方MinGit-2.56.0.4-64-bit.zip，39846926字节，发布方SHA256为e3bf78351fe777fba47ddee5950082f8a98bb0f02604fdc7ba3ee2cb68ffa877。只取得发布／标签元数据与源码，没有下载、解包、签名验证或运行。

受管运行包固定git.exe、配套DLL／必要内建命令及环境清单，实际摘要／版本／能力都核对才可用；不调用PATH中的个人Git，不自动替换现有Git或继承个人Shell。部署登记code_git_bundle_ref用于任务前仓库操作，ExecutionProfileVersion.git显式引用同一已准入包和GIT20-LOCAL-1；不另建供应商或通用Git服务。任务创建后Git组固定，变更需新任务，部署升级不热换历史任务Git。

### 2.2 隔离配置与来源

后端在独立环境调用绝对程序路径／参数数组；清空继承的Git重定向、代理、askpass、编辑器、pager、trace、身份及配置注入变量，重建私有用户目录／TEMP／受控PATH和必要Windows环境。启用GIT_CONFIG_NOSYSTEM=1、私有空GIT_CONFIG_GLOBAL、禁提示／懒取／replace／可选锁及字面路径；CLI固定core.hooksPath为空受控目录、core.fsmonitor=false、gc.auto=0、maintenance.auto=false、protocol.allow=never，不运行外部diff／textconv／签名／hooks或联网。

仅改HOME及关闭系统配置不足以隔离本地仓库config。程序先以句柄核对.git／gitdir／commondir与仓库身份，在内存固定实际config字节；在私有非仓库目录以config --file <本次临时副本> --no-includes --null --list解析。临时副本不作为审计保留，finally清理，原配置不写；输出和内容先容量校验，日志不记远端URL／个人身份等秘密值。

首期允许结构core.repositoryformatversion／bare／filemode／ignorecase／symlinks／logallrefupdates、extensions.objectformat及files引用格式，以及纯描述user.name/email、remote.<name>.url/fetch、branch.<name>.remote/merge/rebase；值依协议类型核对。include/includeIf、worktreeConfig、core.worktree／hooksPath／fsmonitor等自定义执行／路径键、签名要求、其他未登记键拒绝，不静默绕过仓库要求。元数据有reparse／重定向、reftable、alternates／http-alternates、shallow／promisor／grafts／replace等特殊布局拒绝；不fetch、不prune、不修用户配置。正常linked worktree的.git指针／commondir经真实路径核对后可读，任意父路径遍历或符号引用不冒充已登记仓库。

第一次Git仓库调用前检查、prepare持锁后再核对config／身份指纹；不把任意外部篡改元数据当本期可防御范围。固定程序、参数、仓库布局和敌对配置证据未取得则ready=false。

### 2.3 对象、提交与写入范围

已有本地直接分支、同对象格式、完整候选树、单父提交，不自动merge或保留目标独有文件。目标工作树／索引不改。准备预览时将expected目标提交的完整树按CONTENT20-STORE-1复制为Plan私有目标包，固定target_tree_oid／target_manifest_sha256；与候选包按精确清单比较，不依赖用户后续保留旧Git对象。目标条目不静默排除，秘密／特殊类型或容量不符则整次准备失败；包私有引用不发前端。从固定清单原字节重建blob／tree到目标对象库，分别使用hash-object -w --stdin --no-filters和mktree -z；核对同OID及独立内容SHA256。没有clone／fetch／checkout／pack管线或把目标对象目录作为候选alternates。

提交原始字节一次固定：tree、唯一parent=expected_target_commit、显式作者／提交者、实际固定秒数／+0000、空行、配置消息及WALL-E-Delivery: <delivery_id>尾注。姓名／邮件／消息禁止头注入，UTF-8／LF及最终LF固定，不使用个人Git配置或签名。引用事务的GIT_COMMITTER_NAME／EMAIL从固定配置重建，DATE固定该原事务准备时真实秒数／+0000；不依赖个人身份生成reflog，且它不改变原提交payload。hash-object -t commit --stdin --no-filters计算，再加-w写同一字节；保存commit_input_ref／摘要及planned_commit_oid后才可更新目标。尾注使不同Delivery不因同树／同时间得到相同提交。

对象写入不是分支交付；未引用对象不自动从用户库删除。引用写入只允许原计划分支及Git相应reflog，不创建别的用户分支、改HEAD、切换工作树、推送、部署、回滚或更新用户服务。

### 2.4 引用事务与符号引用

固定源码确认：--no-deref可覆盖符号引用本身，不能单独证明目标仍是直接分支。采用交互式update-ref事务，不把prepare／commit一口气发出：

~~~text
git update-ref --no-deref --create-reflog -m WALLE:<delivery_id> --stdin -z
start NUL
update <full_ref> NUL <planned_oid> NUL <expected_oid> NUL
prepare NUL
# 收到真实start: ok及prepare: ok，持锁复核直接引用／配置／worktree／窗口
commit NUL
~~~

NUL表示字节0，示意换行／注释不进入wire。所有OID为已验证全长OID，full_ref经check-ref-format且必须refs/heads/*；禁批次部分成功参数。prepare成功后，用for-each-ref的refname／objectname／symref字段精确核对该分支，symref非空、缺项／歧义、对象／仓库变化均abort，不commit；合作式外部Git遵守锁。本期不防直接绕过Git锁的任意文件篡改。

原操作先持久保存MAY_HAVE_BEEN_SENT，再经控制写入栅栏核对停止／代次与窗口、发送一次commit。ACK为固定源码report_ok的真实响应，不凭退出0／端口或模拟文本伪造。commit可能发出后，非零／超时／断线都不证明没写，转核对，不重发。停止在commit发送前阻止该发送；已发后的停止只结束受管活动并核对原结果，不声称撤回。

### 2.5 worktree与交付窗口

WALL-E仓库互斥和ref CAS不能阻止外部随后checkout／新增worktree。首期采用合作式交付窗口：接收前确认“交付期间暂停此仓库的其他Git写操作”，保持至本次交付结束；用户不能提供该条件则不自动交付。此确认不扩大权限，也不是已锁住外部Git的证明。

AcceptCode加入repository_quiescent_confirmed:true。后端即时创建本次DeliveryWindow，期限取明确max_delivery_window_seconds（≤300），从接受确认时起计，不从排队结束重新算；窗口只对当前控制方进程有效。B2未启用交付、排队超时、重启／控制权变化均不留未来自动写资格。窗口失效但尚未发commit，原Delivery等待；用户通过既有RESUME对同一Delivery明确重确认，不重建Acceptance／Delivery或偷偷重放旧请求。

worktree list --porcelain -z解析main／linked／detached／locked／prunable的真实记录；目标被任一HEAD检出就阻止。首期拒绝refs/heads内任何symref及名称别名，每份worktree HEAD只允许detached完整commit或一次指向直接本地分支，避免别名链漏判目标已检出。locked是防prune标记，不代表没有活动，prunable／不可读／缺失不得当安全忽略。prepare后再查并对照清单／HEAD身份；新worktree／HEAD变化abort。commit后再读实际目标和worktree；违反窗口的外部操作可导致冲突／未知，不承诺任意外部并发下工作树原子一致。

### 2.6 进程归属、结果与恢复

控制Git是后端受信程序，不是AI的允许命令。任务存在时复用CommandExecution，purpose新增CONTROL_GIT；任务前Git操作挂原资源OperationStep及Guard回执，不创建占位任务／命令；Guard绑定run_kind=CONTROL_GIT按真实后端调用者的非提升用户令牌执行固定Git，无AppContainer，不能用Guard服务身份。只有任务执行器run_kind=TASK使用LPAC，模型入口拒绝CONTROL_GIT身份。两类均由Guard／Job管理、受停止／崩溃回收及资源时限约束；不降级AI代码隔离、不向浏览器暴露任意Git。前项Windows／模型迭代原字节保留，本迭代记录这一控制程序类型的补充。

Delivery.git_write_status只描述目标引用commit：NOT_DISPATCHED／PREPARED／MAY_HAVE_BEEN_SENT／CONFIRMED／ABORTED_UNSENT／UNKNOWN；COMMIT发送可能性一旦成立不能靠当前分支等于旧值恢复为未发送。私有Git回执归原操作／步骤／受管进程／nonce及planned_oid，可靠保存prepare、发送可能性、真实ACK和读回事实。

| 事实 | 处理 |
| --- | --- |
| commit未派发有可靠证据，原对象／计划仍适用 | 活跃新窗口及未停止条件下续原步骤，planned_oid不改 |
| 当前分支为planned或其可证实后代，或已有可靠成功ACK | 补原交付成功；外部后来前进不覆盖。delivered_at为首次核实该事实的时刻 |
| commit可能派发，当前分支又等于expected | ABA／外部reset仍可能发生，保持UNKNOWN，不自动重发 |
| 目标已变且可靠证明原commit未派发 | BLOCKED；重新预览／接收，不自动merge |
| 分支缺失、历史重写、对象／配置损坏或进程结果冲突 | 保留UNKNOWN及相关互斥，不因找不到提交就认定未发生 |
| reflog存在／缺失 | 仅辅助证据，单条log不代替引用成功／ACK，缺log不证明没写 |
| Git进程硬停、残留.lock | 核对原受管进程；不自动删除Git锁或覆盖他人锁，维护另行明确处理 |
| 终态／停止后收到迟到成功 | 只补原交付，保留未撤回事实，不恢复写入／编码 |

Delivery.postcheck_status为NOT_RUN／VERIFIED／CONFLICT／UNKNOWN，与实际引用成功分开。已成功但postcheck冲突／未知显示“已交付，仓库状态待核对”，不假报未交付，也不让任务自动COMPLETED；无停止且后核对VERIFIED才收口。仓库互斥至原写结果和受管进程核清才释放，不能超时放给第二交付。

## 3. 契约及影响映射

| 范围 | 同步内容 | 实施／验证状态 |
| --- | --- | --- |
| 配置／仓库 | 明确git包引用、GIT20-LOCAL-1及Git时限／输出／交付窗口限制；受控GIT目录选项 | 未发布程序包或安装，不继承PATH Git |
| 接收／继续 | 接收本次暂停Git写入确认；既有RESUME仅在原交付等待时接受同一确认 | 不新建交付流程或任意Git接口，B2不消费未来执行资格 |
| 存储／进程 | DeliveryWindow子表／真实外键，Delivery当前窗口、写入／后核对状态，CommandExecution控制Git类型 | 设计未实现，复用现有操作／停止／Guard |
| 前端 | 本次确认不持久默认勾选，过期重确认；实际交付和后核对分别显示 | 未实施／浏览器验证 |
| 验收 | 追加TC20-69—76、TC-FE20-47—49 | 目标场景，本轮执行0 |

后端计划0.8-draft-8／前端0.7-draft-7，均DRAFT。具体结构归后端7.7及原对象章节；本稿不复制为第三份正式规格。

## 4. 一手来源与已读边界

资料读取2026-11-03：

- [固定官方发布](https://github.com/git-for-windows/git/releases/tag/v2.56.0.windows.4)、[标签对象](https://api.github.com/repos/git-for-windows/git/git/tags/e878704e2f40adc59f4b0d4e15424511456163db)提供版本、源码及资产摘要；GitHub发布方信息不是本机解包／签名／运行证据，不自动安装。
- 同标签[update-ref文档](https://github.com/git-for-windows/git/blob/581291682ad5a238c08c93d1f5bd4518382a3230/Documentation/git-update-ref.adoc)、[builtin/update-ref.c](https://github.com/git-for-windows/git/blob/581291682ad5a238c08c93d1f5bd4518382a3230/builtin/update-ref.c)、[refs/files-backend.c](https://github.com/git-for-windows/git/blob/581291682ad5a238c08c93d1f5bd4518382a3230/refs/files-backend.c)核对输入解析、ACK及no-deref旧值／symref处理。不是全文Git安全审计。
- 官方[Git环境](https://git-scm.com/docs/git)、[配置](https://git-scm.com/docs/git-config)、[worktree](https://git-scm.com/docs/git-worktree.html)、[仓库布局](https://git-scm.com/docs/gitrepository-layout)、[hash-object](https://git-scm.com/docs/git-hash-object)、[cat-file](https://git-scm.com/docs/git-cat-file)及[merge-base](https://git-scm.com/docs/git-merge-base)相关段落；环境、窗口和配置白名单是本方案选择，不是工具已经提供全仓库外部互斥。
- GitHub插件后续文档读取出现传输错误，Git官网一次打开受限；按可用官方搜索／文档继续，不把失败请求算已读全文，不升级权限或运行替代Git试验。未取得完整Windows运行包、全部源码／配置实现或真实敌对仓库证据。

## 5. 核对与接续

静态结果另存[Git交付设计核对](../../../verification/v2.0/git-delivery-design-2026-11-03.md)。Q20-GIT设计已定／待固定程序及真实Git协议／故障验证，默认ready=false。

下一项Q20-CHECKS：首期受支持技术栈、真实受控runner／独立夹具／版本、环境准入及可采用资源。先读既有检查及资源，不把项目npm test或AI自报当独立验收，也不在没有当前授权时真实调用模型或安装工具。

## 2026-11-10 实施接续

原 B2 预览按完整目标包与固定候选包比较，保留删除项、两侧字节、原报告及风险确认。实际 C64 保存 Acceptance 和待交付记录。B3 复用原认证 Guard、固定 MinGit 及原 Windows Job，阶段分别保存固定提交字节、对象构建、原锁、持久 MAY、单次写入、只读核对及自然收尾。

锁内使用精确分支查询，原目标仍是 expected 才准许继续。原 MAY 已保存之后，SQLite 写栅栏只容纳一次有界非阻塞管道写入，Git 的等待在事务外。当前目标回到 expected 保持未知。真实 ACK、原计划目标或严格验证的后代按原提交与树字节核对。后核对冲突独立记录，原交付首次确认时间保持。STOP 和 CLEANUP 分开核实，未取得两项证据时不完成任务。

本轮 C36 重新确认先覆盖无 Git 命令派发的原交付，包含固定提交已落私有文件但 SQLite 回执丢失后恢复原字节的情形。原 MAY 或其他未决活动不能凭确认取得写权。隔离 Windows Guard／MinGit 通过 SHA-1／SHA-256 原引用、对象和祖先关系检查，Chrome 与隔离 SQLite 的证据及未覆盖范围见[本轮验证](../../../verification/v2.0/coding-repair-delivery-2026-11-10.md)。正常部署准入仍关闭，正式设计保持原修订。
