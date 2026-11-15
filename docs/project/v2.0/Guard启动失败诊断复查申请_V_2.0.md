# Guard启动失败诊断复查申请（V2.0）

日期：2026-11-14。状态：用户23:47:45之前已明确同意；55618新安装在途，启动尚未派发。

上次管理员确认已成功，1954范围实际启动一次后服务失败停止，原许可已使用。原服务错误仅1066／specific1，无法得知具体异常；新源码已增加固定阶段与原Win32错误号诊断，相关184项通过。新Guard已实际构建、自验；该改动没有部署到旧服务。

## 拟执行的有限操作

仅新建C:\Program Files\WALLE.RuntimeGuard.V2.Test.20261114-2345，注册唯一新服务WALLE.RuntimeGuard.af0b02a6dbe585cb5eecd050d8ab17527374b0d565c7fae23c759355781f91de。先安装为停止状态，核对字节、权限与服务配置，再实际启动一次，用原普通后台验证原进程／SYSTEM主Token／固定镜像与管道连接，停止并核实原进程退出。失败不重试；结束保留本新目录与停止服务。

安装和启动检查为两个固定阶段，预计分别出现Windows管理员确认。普通后台保持普通身份，不自动点击系统确认。原1905目录及失败服务保留，不替换或修复；不更改其他服务、用户数据、正常Git、网络策略或SYSTEM进程／Token权限，不调用模型。

## 可复核的固定输入

- 新Guard：guard-prepared-20261114-2340-diagnostics；manifest5e5b6a8cc5ad7cbdf16bfbcdbb6b2cc32fc201202d30470817d459f005de44a3。
- 普通后台：prepared-20261114-1900-probes；manifest39f6285a53eddffe71b3674fa55a3f794db637e8dff2c2bbf92f7d22adf577cf。
- 固定安装工具：guard-installer-prepared-20261114-2059；manifest1fafdfb8a68e2b500b448f3ec95043f6f9c0a0df89f999c3011d4ffd9fd4849b。复用其原已验证字节，不声称为新诊断源码构建。
- 新计划：guard-bootstrap-prepared-20261114-2345-diagnostics；plan1818486447221148e57635e878a307ff142794b0fd57cf9f0d93def35100c7ed；deploymentbe2e77b49c1b6c324914a1bf1479f3ec01f67c26c4c4fa192348427752b6fda1。
- 新请求：guard-installation-prepared-20261114-2345-diagnostics/guard-installation.v1.json；SHA0cf2a7c5dcf8cace0048a6505dd026f341bcb614536f04d03bff2232bd56528c。task／runtime／checks=null，不取得产品执行准入。

工具入口仍为backend/tests/infrastructure/v20_guard_system_bootstrap_worker.py，明确--install或--start-stop及--allow-system-changes、上述固定2059及新2345摘要；不传旧--original-installer-package。任何不同根、服务、程序、请求、额外启动／修复或新权限均不在本申请中。未获本次明确同意前，停留于项目内准备和只读核对。

证据：[诊断与检查](../../verification/v2.0/guard-startup-diagnostics-2026-11-14.md)；[原实际失败](../../verification/v2.0/guard-system-bootstrap-2026-11-14.md)；[当前断点](实现进度_V_2.0.md)。

31347普通预检已完成，固定冻结工具inspect成功、普通身份安装被拒绝，工具／后台／新请求字节保持不变，无系统写入。184项专项及新Guard构建已通过；申请状态仍待明确新授权。


## 新2345范围已授权（2026-11-14香港23:47:45接续）

用户明确选择“允许安装新诊断服务并完成一次检查”。本申请的新2345根及唯一af0b02…91de服务已获安装1次、实际启动1次／普通后台连接及停止授权；旧1905根／服务保留，其他边界不变。下一执行固定2059＋新2345请求的--install，成功停止核对后--start-stop一次；分别由Windows系统确认，不传原1952接续选项，不重试已派发／未知动作。


## 23:51新2345安装成功，下一启动一次

55618退出0，OWNED_BOOTSTRAP_PHASE_COMPLETED_NO_WFP_TASK_MODEL_OR_USER_SERVICE_UPDATE。实际新服务STOPPED／pid0／1077／specific0，尚未启动；新receipt SHA256 4307663496faf3315036ee92766a9f166764c153d0400d281bac9c3666d7bd4b。原后台读者与管理员工具已退出；保留新目录、完整双程序与停止服务。下一按已获同一新范围授权执行--start-stop一次，不重装、不传旧1952接续参数。


## 23:53新2345首次真实启动失败：PRIVATE_JOURNAL

99905退出1，子工具实际派发新服务首次StartService；SCM为STOPPED／pid0／1066／service-specific1460338688（0x570B0000），严格解码PRIVATE_JOURNAL／native未知。已经通过SYSTEM身份、部署源及契约、后台程序清单读取与解码，故障发生在LaunchJournal初始化；不能进一步猜所有者／DACL／锁等具体分支。未到READY或普通后台连接，所有本轮管理员／后台／Guard进程已退出。

本新2345安装1次及实际启动1次均已使用，不自动再启动或更改两处已装资源。下一仅只读查询新journal固定文件安全元数据（不读内容、不更改权限）及本地源码复现；旧1905和新2345失败服务均保留停止。此前“在途／尚未启动”均为历史状态，不作为接续依据。


2026-11-15最终状态：本2345范围55618安装成功、99905首次实际启动在PRIVATE_JOURNAL失败；本许可已执行使用，不再适用“在途／等待新授权／未启动”。两处既有服务保持停止。下一尚待选择的范围见[私有记录排障申请](Guard私有记录初始化排障复查申请_V_2.0.md)，不自动沿用。
