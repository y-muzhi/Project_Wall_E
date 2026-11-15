# Guard受信安装与最小SCM启动准备迭代V1（V2.0）

2026-11-14香港19:09，承接三小时工作、真实Program Files祖先权限及普通后台读者。先登记后实现，仍不合并两份DRAFT设计。当前仅代码与隔离检查，不授予实际SYSTEM安装／启停或WFP许可；待完整可审阅工具／输入和必要检查后确认具体系统操作。

## 固定输入和操作范围

安装输入是原始SHA固定的启动组、两个实际完整程序包、实际普通后台源EXE读者PID／创建时刻，以及另行固定的专用安装器程序包。通过共用算法生成不可变installation request，明确原启动plan SHA、安装器程序SHA、安装目标、安装标识、源程序SHA和完整SCM／权限／时限；消费方从原资源重组后比较canonical字节，未知字段／配置漂移拒绝，不接受任意Shell、服务名、账号、权限或路径修复。

只在计划中的全新Program Files私有目录及全新WALLE.RuntimeGuard.<installation_ref>服务操作；原服务／根存在时不覆盖、不自动升级、不自动清理或重试。现有C盘／Program Files权限不改。用户服务、业务SQLite、源／目标Git、模型、WFP及任务运行不在本次最小安装范围。task／runtime／checks必须null。

安装器为专用冻结walle-guard-installer.exe，固定本完整program-sha256，拒绝普通Python及其他PE；安装前必须实际高完整性／非AppContainer／同backend_sid的管理员用户，主Token默认Owner必须Administrators，禁止模拟线程或服务身份。没有管理员身份在新目录／SCM写入前拒绝。普通后台和浏览器不提权。

## 新资源权限与原字节

程序目录／文件／部署／安装意图仅SYSTEM和Administrators全控，backend_sid仅读执行，Owner为Administrators；每个新对象在原生CreateDirectory／CreateFile CREATE_NEW时指定保护DACL和Owner，不先建普通用户可改文件再补ACL。源逐块验证／实际写长度、FlushFileBuffers和关闭后原生读回，完整清单与全部目标再核验；不得只看副本内存摘要。发布和服务启动之前以原外部后台Token核对目标全部祖先、目录和文件有效权限，所有者和完整DACL也实际读回，不只检查后台一个用户的拒绝。

journal只属SYSTEM，Owner为SYSTEM，使用新目录创建时的临时SYSTEM／Administrators DACL取得原句柄，再在此新对象上封为SYSTEM-only并用原句柄读回；不修改既有目录。仅此SYSTEM Owner创建时允许安装器自身主Token临时启用其原有SeRestorePrivilege，结束立即恢复原启用状态并核对；不增加不存在的特权、不调整后台或共享SYSTEM Token，不启用SeDebug或全局权限。恢复／关闭未知保留owner并终止本安装器，不当成功。没有该原特权则安装拒绝，已有新资源保留明确失败，不自动修复。

## 新服务与最小测试

服务固定OWN_PROCESS、LocalSystem、DEMAND_START、无依赖、无自恢复动作，精确原SCM image_path与参数。仅保留SeAssignPrimaryTokenPrivilege、SeChangeNotifyPrivilege、SeImpersonatePrivilege、SeIncreaseQuotaPrivilege：分别承载原普通令牌挂起创建、路径遍历、原控制者新登录来源模拟及创建配额；不含备份／恢复／调试等安装器权限。配置与实际读回精确一致才允许启动。

SCM服务Owner为Administrators，SYSTEM／Administrators完整服务管理；backend_sid仅QUERY_CONFIG／QUERY_STATUS／READ_CONTROL，禁止启动／停止／改配置／改DACL／owner。仅创建本轮新服务后设置，不更改既有SCM对象。安装阶段不自动启动；实际启动／停止必须为明确后续动作，同一固定request校验安装意图、原程序／ACL／服务配置和原读者。

有界启停仅操作该已创建服务，按原SCM状态捕获SYSTEM进程原句柄／创建时刻／实际镜像，RUNNING后允许普通后台独立原连接探针。协调通道只属本轮新私有临时目录，固定相关标识和READY／STOP消息，CREATE_NEW写新标记、原字节读回，不接受任意命令、覆盖、删除或业务路径。STOP、原普通读者退出或固定时限到达均请求原服务停止；等待原SCM STOPPED及原进程退出／服务退出码，未知时保留资源和失败，不凭PID消失或端口空闲宣告成功。

本项不自授SYSTEM进程／Token查询权限，不跳过普通后台现有原Guard身份核验。实际系统启动后如原连接仍被拒绝，记录真实边界并先提出具体技术规则；不得修改共享SYSTEM Token或用模拟对端／SCM字符串替代。

## 验证及交付

先做严格request／权限描述／原字节／序列／失败及取消专项，普通身份实际拒绝；涉及SCM写入的测试用明确端口替身，不能写正式OS通过。按固定构建锁生成安装器、验证真实EXE无业务导入／普通身份拒绝／完整包。然后提供具体request与目录／服务范围供系统操作授权；未授权不执行安装／启停。检查只留Markdown，产品request／安装意图是正常输入及安装状态，不把原始测试JSON留存。

 
## 原生接口与关闭归属补充

服务安全对象类型必须使用Windows SE_SERVICE=2；SE_FILE_OBJECT=1仅用于NTFS文件目录，不能把SE_LMSHARE=5当服务。原生服务安全设置先指定Owner／Group／DACL，再通过SetSecurityInfo(SE_SERVICE,PROTECTED_DACL_SECURITY_INFORMATION|DACL_SECURITY_INFORMATION)封闭继承，原句柄严格读回。依据：[SE_OBJECT_TYPE](https://learn.microsoft.com/en-us/windows/win32/api/accctrl/ne-accctrl-se_object_type)、[SetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setsecurityinfo)。

StartService返回成功后才能取得本轮停止权限；原停止状态预核通过但StartService失败时不猜测PID或停止可能由其他调用方启动的服务，不自动重试。SYSTEM-only journal最终对普通／管理员读者不可读，安装阶段通过收紧前持有的原句柄核对身份与最终权限；后续实际Guard SYSTEM启动复核该journal，管理员回读流程不得暗中使用SeBackup或放宽权限。

 
## 可直接使用的准备入口

新增tools/build-windows-guard-installer.py仅转入原固定安装程序构建函数，tools/prepare-windows-guard-installation.py仅转入同一prepare_request；不增加另一计划或安装流程。后者明确--prepared／--plan-sha256／--installer-package／--installer-sha256／--output，沿原规则要求绝对本机NTFS路径，不隐式解析相对位置或覆盖已有输出。原owner未知异常原样传播，不吞成普通拒绝。两入口不进入SYSTEM安装、服务、WFP或模型调用。固定1952安装程序及1954请求原字节不变；新wrapper不参与该既有程序的运行依赖。

 
## 真实安装后的已知未派发接续（2026-11-14香港20:44）

1954首次真实安装成功，31131启停检查在发送StartService前被ProbeChannel拒绝：main已将CLI通道路径校验成Path，ProbeChannel又调用只接受str的deployment.absolute_path，必然CODE_DEPLOYMENT_ABSOLUTE_PATH_REQUIRED。只读原算法复核实际已装双包／全部DACL与原读者权限均通过，临时原通道构造重现同一错误；SCM仍state1／pid0／1077，正式从未尝试启动。不是未知运行结果，不扩大权限或猜测重试。

修复统一使用既有local_absolute_path接收已校验Path，仍拒绝相对／UNC等不合规位置；不改原1954、安装intent／receipt、Guard／后台程序、服务参数或ACL。原1952包保留完整原字节，修复工具生成新完整包，明确自证新自身摘要。为了延续原1954不可变安装意图，--original-installer-package仅允许--start-stop，另外持有原请求所固定的1952完整包；原请求仍由原1952摘要重建比对，新工具自身另由新摘要完整核对，不把新摘要假装原1954，也不改旧JSON。

此接续仅允许原服务STOPPED／pid0／1077／service-specific0，固定原1954请求和原安装receipt／目录ID均再次核对；已经启动过或停止结果未知的服务不可使用该接续。修正不授安装／覆盖／修ACL，也不增加原授权的实际启动次数。失败输出补固定公开原因码，不输出路径／输入或任意异常正文。当前用户已明确同轮一次启动／连接／停止，实际StartService为0次，继续该同一授权；未知动作仍不重试。

 
## 管理员启动观测与原服务停止边界补充

2048接续51907在ShellExecuteEx处返回失败或无原进程句柄，尚未进入新工具，SCM仍1077。旧检查器未保存该调用的GetLastError，因此不猜是取消或系统策略；新检查器立即捕获原native_error和accepted／original_handle布尔值。事件通道只读查询无可用匹配证据，不能当没有策略阻止；不重发UAC，先向用户核对实际提示。

停止判定分开SCM和原根退出：ServiceMain报告STOPPED后，冻结根还需退出dispatcher并关闭完整程序租约；SCM零退出且原根仍RUNNING时在原固定150秒截止内等待原句柄，不能立即误报失败。最终必须原进程EXITED且进程退出码0；SCM非零／原根非零仍拒绝，超时不重试STOP或猜PID终止。此为原生命周期必要检查修复，不扩大授权和服务控制次数。
