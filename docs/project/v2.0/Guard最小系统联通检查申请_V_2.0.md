# Guard最小系统联通检查申请 V2.0

状态：2026-11-14香港20:30用户已明确授权本固定1954范围，实际执行与结果另见验证记录。2026-11-14三小时接续任务。此文不是永久许可，也不授权正式WFP、TASK、双SERVICE、模型或用户服务更新。

## 唯一范围

| 项目 | 本轮固定值 |
|---|---|
| 全新安装目录 | C:\Program Files\WALLE.RuntimeGuard.V2.Test.20261114-1905 |
| 唯一全新服务 | WALLE.RuntimeGuard.ffac49bed3200a391a19cf7b1480b67d9bc41f17899fc21e329957aced5d33e3 |
| 服务身份及启动 | OWN_PROCESS，LocalSystem，DEMAND_START；注册后STOPPED；无依赖、无故障自动重启 |
| Guard原包 | guard-prepared-20261114-1810，manifest78b68711be8d1a3fcf5edbba4db85869cb2720706256c84467d81490c1bfd57b |
| 后台原包 | prepared-20261114-1900-probes，manifest39f6285a53eddffe71b3674fa55a3f794db637e8dff2c2bbf92f7d22adf577cf |
| 专用安装程序 | guard-installer-prepared-20261114-1952，manifest8b6567e2578eeaca2545686f7ad44b3da4fb40530f293c6c5b6defab9d7de3ee |
| 安装请求 | guard-installation-prepared-20261114-1954/guard-installation.v1.json，SHA256 4ee0f56c2aca50478ab8bbca34bff940ce9709edc8f7f7f8fd20930076db6ce4 |
| 原启动输入 | guard-bootstrap-prepared-20261114-1905-probes；plan5defd3d420054ad1e533f80c57ead6701b7d275e50b9978e4eccb6054330d3cf；deployment5c4b3cda489d1c4f95ae920eaebc1a4decd22b54c3d3e8c150740f772a2e41cf |
| 调用次数 | 新安装1次；有界启动／检查／停止1轮；未知动作不自动重试 |

目录、服务或固定输入已存在／变化则拒绝，不覆盖、修复或自动删除。程序及安装输入Owner=Administrators；SYSTEM／Administrators全权，原普通后台SID只读执行。新journal Owner=SYSTEM、最终SYSTEM-only。只对新资源设置这些权限，不修改Program Files父目录、其他服务或SYSTEM进程／Token权限。

服务仅保留SeAssignPrimaryTokenPrivilege、SeChangeNotifyPrivilege、SeImpersonatePrivilege、SeIncreaseQuotaPrivilege四项。安装工具只在新journal创建作用域临时启用自己原已有的SeRestorePrivilege并精确恢复；不添加特权、不用SeDebug／SeBackup、不更改其他进程Token。

## 实际动作与结束状态

1. 原普通用户检查器持有安装程序／两个源包／原请求全部原句柄；启动原固定普通后台无库读者，核对实际PID／创建时刻／身份，最长300秒。
2. 专用安装程序请求一次Windows管理员确认，只创建上述目录／程序／配置／SYSTEM私有journal并注册唯一新服务，严格读回后保持STOPPED。
3. 新一轮原普通读者和私有READY／STOP检查通道，另请求一次管理员确认，启动上述已固定服务；实际普通后台--verify-guard核对原SCM服务、SYSTEM主Token／镜像及原管道，不发送业务帧。
4. 无论连接检查成功或失败，已成功取得本轮启动归属后都请求停止该服务，核对原进程退出／SCM STOPPED；结束读者及清理本轮私有临时通道。若原停止结果未知，不猜PID终止、不重试，保留准确失败断点。

结束保留新安装程序目录与停止状态的新服务供后续受信部署，不自动卸载或删除。检查成功仅为最小SYSTEM进程／管道可行性，不开启OS、业务、交付或模型ready。

## 运行入口

项目固定Python通过tools/python-v20.py运行backend/tests/infrastructure/v20_guard_system_bootstrap_worker.py；必须显式--allow-system-changes，--install／--start-stop二选一，并提供固定--installer、--installer-sha256、--request、--request-sha256。没有显式标志在任何文件／系统动作前拒绝。实际管理员确认由Windows显示，用户自行决定，不代点击。

只读及普通拒绝检查使用v20_guard_installer_preflight_worker.py，完全不请求提升。1952包替代早期1945准备包：后者未使用于系统安装，服务对象类型及失败启动归属已校正后重新构建。完整实现与检查见[安装验证](../../verification/v2.0/guard-installer-preparation-2026-11-14.md)、[普通后台探针](../../verification/v2.0/backend-deployment-probes-2026-11-14.md)及[当前断点](实现进度_V_2.0.md)。

 
本轮用户明确选择“允许安装并完成一次启动、连接检查和停止”。执行仅限本页固定输入和次数，不扩展为后续安装／重试许可；实际结果见[SYSTEM检查记录](../../verification/v2.0/guard-system-bootstrap-2026-11-14.md)。

 
## 同一授权的真实进展与修正工具

首次1952安装已成功，原1954及已装意图／程序／权限不改。启动前Path错误已修正；2048接续在Windows管理员启动请求处未成功，SCM始终1077／pid0，本轮实际StartService仍0。原错误码未保存，不指认用户取消或系统策略。最终接续工具2059自证新完整包，同时显式完整持有原1952以核对原1954，仅补同一轮尚未派发的启动；不是重新安装或额外次数授权。所有具体摘要及现场依[当前断点](实现进度_V_2.0.md)，实际结果见上述SYSTEM记录。

tools/run-guard-bootstrap-check.cmd封装该唯一前台入口，--help已验证，完整执行未运行。Windows提示情况仍待用户说明，不自动重发。1077仅针对当前启动周期；跨重启或未知结果不沿用本轮许可。


## 23:24实际启动结果（替代前述在途与“启动0次”状态）

用户确认同意Windows管理员请求后，6068真实进入2059管理员工具，首次StartService已派发；检查退出1，未到READY或普通后台连接。23:24:38独立只读SCM核对为STOPPED／pid0／Win32退出1066／service-specific1；所有本轮管理员工具、普通读者与Guard进程已退出。23:22:25 System事件7024同样记录本服务specific1，不能从通用文字“函数不正确”推断根因。当前宿主把各阶段异常统一报告1，具体原因仍需定位。

本次安装1次及实际启动1次已使用。当前保留原安装目录、原程序／配置／意图／回执和停止状态服务；没有修改ACL、WFP、用户数据或用户服务。原要求1077的“未派发接续”与固定CMD不再适用于本现场，不能重复执行。下一步仅只读查自身服务事件和源码，准备可检查的修复及必要离线检查；若需要替换已装程序、改服务参数或再次启动，须明确新范围后取得新授权。当前系统联通仍未验证，不能标通过。


23:46：本原1954申请的安装及一次实际启动已使用，失败现场保留。工作区安全诊断与新冻结包／普通预检已完成；若继续系统检查需明确[新2345申请](Guard启动失败诊断复查申请_V_2.0.md)，不是本许可的自动续期。
