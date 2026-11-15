# WALL-E C02 仓库观察原目录句柄

2026-11-07，V2.0 待合入迭代。依据 BE7.7.2、7.7.6 与既有原配置导出。受信后端在既有 RepositoryLocationLease 内导出 root、git_directory、common_directory 原文件身份和仅查属性的句柄。三者和原 scope、控制方创建身份、布局及定位摘要一同固定；Guard 从认证控制方原进程复制同访问权限的非继承句柄，通过实际对象核对目录类型、路径、NTFS 身份及原绑定。此批仅验证原目录句柄及寿命，Guard 不按调用文本打开或读取目录，也不派发 Git。

后续固定 WORKTREES／LOCAL_BRANCHES PREPARE 必须把同一定位、原配置摘要及命令回执关联起来，保留原后端的完整元数据租约，复核原 Git 输出并发布观察。此文件不授权不受控路径、附加命令、修改仓库或以目录句柄宣称环境已准入。

资料：[DuplicateHandle](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle)、[File Access Rights Constants](https://learn.microsoft.com/en-us/windows/win32/fileio/file-access-rights-constants)、[Directory Handles](https://learn.microsoft.com/en-us/windows/win32/fileio/obtaining-a-handle-to-a-directory)。

应用侧启动沿已提交的 C02 原回执。只有未曾开始且原两步骤完整的 PENDING 才可启动 READ_REPOSITORY，启动时从已登记仓库取固定根、共同目录及对象格式。已开始原操作不能通过新启动重取。观察发布同样复核原回执及两步骤，保持原观察 ID 重放，拒绝无接收回执的原操作。控制 Git 三个调用的持久作用域和实际 READ_REPOSITORY 完成者仍在后续派发单元。

固定元数据请求仅增加 WORKTREES 和 LOCAL_BRANCHES。每个请求绑定同一控制方、原操作和原步骤内不同 nonce 的配置解析。Guard 查原 PREPARE、STOP 与 RELEASE 的持久 ACK，核对原配置文件／摘要、输出句柄 nonce、正常退出与已清理，再复制当前原配置读句柄和目录属性句柄。受保护后端先从实际完整 stdout 执行既有允许键验证；IPC 只传校验摘要与格式等固定事实，不传原始输出。后端执行期间继续持完整原元数据租约，返回后用同一对象、范围及有界输出解码核对。Guard 依旧只运行固定 Git 和预设参数，工作目录、HOME、空全局配置和 hooks 为原私有资源。

后端沿现有原 Guard MAY／ACK 私有记录持久化三条命令。原 READ_REPOSITORY 一次写入有序的配置、工作树、分支 nonce 及原 owner／回执根，禁止重新分配。只有前一个原作用域已有明确 RELEASE ACK 后才允许下一条 PREPARE；元数据请求必须引用组内首条配置作用域。C01 单命令原存储结构、作用域校验和回执格式保留。此批验证原三作用域派发和实际观察捕获，正式生产队列、C02 POST 及界面另接。

观察保存由原三命令的已确认停止／释放和原 stdout 绑定驱动。发布者核对三项原 PREPARE／STOP／RELEASE 事实、同原 IO 和元数据摘要，再从 WORKTREES／LOCAL_BRANCHES 输出形成 WorktreeHeadLease 及观察。短事务以原步骤保存的固定范围为前提，同时完成 READ_REPOSITORY、写入观察与 SAVE_OBSERVATION，重放只读取原结果。生产队列和 C02 HTTP 接入仍在下一单元。

### 后端队列执行衔接

同一专用线程按原接受序号读取登记与观察。C02仅从已接受回执指向的保存仓库获取根、公共目录及对象格式，实际持有原目录和配置句柄，逐一执行已保留的三个固定范围；整个观察共用一个 Git 时限。释放原范围后才交给下一条。读取的有效输出及文件身份在保存前仍需完整核对。明确的源错误在所有可能派发的范围均清理后结束原读取；无法证明动作或保存结果时保留原操作，查询原范围，不更换 nonce 或重新执行。运行时接收新动作前仍要求同一已配置的仓库执行线程。相同幂等键重放仍读取既有 202 回执。

### 设置页衔接

从已选仓库详情显式提交空对象，经现有命令暂存及恢复管理。已知有未核对请求时提供核对原请求入口。结果从原操作第二步骤取原 observation_id，展示与最近观察导航分开。读取失败保留选中仓库和上次可用观察。
