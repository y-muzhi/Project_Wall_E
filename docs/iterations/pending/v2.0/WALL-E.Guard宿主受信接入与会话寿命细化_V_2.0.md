# Guard 宿主受信接入与会话寿命细化

来源为后端 BE0.17-draft-17 7.3.1—7.3.3、已确认跨控制方窄恢复及既有程序包准入细化。宿主按受信安装配置的本机安装引用、后端 SID、包根及 manifest 摘要取得原入口 ExecutablePin，随后独占原首次管道端点。请求中的身份、路径、摘要不能选择入口或包。

每次接入由宿主上游提供独立登记且正在持有的原 ObservedProcess。宿主在等待连接前核对其创建身份、普通后端 SID 和已固定程序路径，并持有原句柄副本，随后用现有实际管道 peer、程序保护及 owner_epoch 核验处理每个动作。GetNamedPipeClientProcessId 仅作连接侧交叉核对。保留这个区分是因为 PID 不能在进程退出后独立证明原进程对象。

连接故障不重播动作。旧 IO 确实退役且原端点证实对端已关后才可重接。同一服务宿主的控制方原记录与 Job 寿命独立于连接。未确认的 IO、断连或作用域释放保留所属对象并拒绝继续接受；接受超时要区分原 CONNECT 确认取消、已完成及仍未知。确认取消可退役该 IO，再在原端点重新接受。已完成则仅在旧对端确已关闭后退役。未知保留原 owner，任何分支都不把失败的流用作协议请求。

本单元交付可调用的 Guard 宿主接入边界和原资源寿命。实际 Windows 服务控制入口、受信注册上游与受保护打包随后接入。隔离验证使用自有 Job 和临时文件；普通账户及程序准入端口结果不能证明 SYSTEM、跨用户、LPAC/WFP 或正式部署准入。

依据：[GetNamedPipeClientProcessId](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getnamedpipeclientprocessid)、[Process Handles and Identifiers](https://learn.microsoft.com/en-us/windows/win32/procthread/process-handles-and-identifiers)。

## 后端连接已登记 Guard 服务

固定服务键名为 WALLE.RuntimeGuard.<原安装引用>，与原管道安装引用同源。后端使用本机 SCM 的 CONNECT 与原服务 QUERY_STATUS，严格要求独立 Win32 进程、运行状态和非零 PID。打开原进程查询／同步句柄并核对 LocalSystem、进程活性；再以受信固定映像及原服务进程连接现有 GuardPipeClient，连接前后复核原 SCM 状态与原进程。进程身份不来自请求，查不到或状态变化即保持不可用。查询不授予启动、安装、变更服务或重派旧请求的权力。

依据：[QueryServiceStatusEx](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-queryservicestatusex)、[SERVICE_STATUS_PROCESS](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/ns-winsvc-service_status_process)、[Service Security and Access Rights](https://learn.microsoft.com/en-us/windows/win32/services/service-security-and-access-rights)。

## 后端原登记执行所有者

原 SQLite PENDING 登记是队列来源，依原操作 ID 顺序，每次最多取一条。执行线程持同一个 ProcessLock、Guard 控制方绑定与私有登记回执目录，并使用真实已认证连接。独立作用域只走原 runner。原准备或资源结果未知且本地 owner 尚不能关闭时，阻止该执行所有者选择下一条。仅在新鉴权连接上核对原 cleanup，确认可释放后退役旧 owner。已开始、已失败及 UNKNOWN 操作不会被当成新登记重派。HTTP 唤醒及系统宿主启动将在此边界上接入。

## 登记专用线程与持久队列唤醒

受信入口交付固定 Guard 映像及摘要、安装引用、后端 SID、私有回执根、隔离路径及读取限制。专用线程在同一普通后端进程持有实际数据库的 ProcessLock epoch；该线程打开映像与私有原回执、检查原队列，按每个原登记工作连接固定服务。显式唤醒缩短提交后等待；即使唤醒前回执丢失，周期性检查 SQLite 仍能发现已提交的原操作。空队列不创建 Guard 连接。

连接或暂时运行失败间隔后再核对。若 actor 保留原执行，之后每次连接先处理原 STOP／OBSERVE／RELEASE，完成后才继续取件。关闭先阻止取件并取消在途等待，再限时尝试原资源核对；未核清的关闭返回未知并保留所属原资源。专用线程接入本身不提供部署配置、不证明受保护服务或程序已准入，也不自行打开登记 HTTP 写。
