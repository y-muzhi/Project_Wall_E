# Guard启动失败阶段诊断检查（2026-11-14）

代码状态：HEAD28a7c9e及保留的脏工作区；后端0.17-draft-17／前端0.16-draft-16设计未修改。独立[迭代](../../iterations/pending/v2.0/WALL-E.Guard启动失败阶段诊断迭代V1_V_2.0.md)仍pending。Win11 x64／NTFS／Python3.13.5／项目固定依赖。

## 真实问题与只读结果

6068本次Windows管理员确认成功，首次StartService确实派发；23:22:25服务失败退出，23:24:38 SCM为1／pid0／1066／specific1。只读System事件7024同样只含通用specific1。journal目录LastWriteTime23:22:25是定位线索，不能单凭时间确定具体异常。未到READY或普通后台连接；原安装、一次实际启动许可已使用。已保留旧目录及停止服务，无重复启动或权限修复。

首次普通工具读取事件被拒绝；以普通完整Windows测试身份只读查询同一固定服务事件成功，没有管理员提权或改审计设置。旧原宿主所有构造／运行失败统一为specific1，原异常只存在进程内列表，进程退出后无法精确定位。

## 实现与离线检查

新增guard_service_diagnostics.py定义20个固定阶段、有限Win32错误号，SCM1066的service-specific采用0x57000000 | stage<<16 | native；0表示错误号未知。严格拒绝bool、负数、超16位、未知阶段及旧specific1的推测解码，不输出路径、SID、配置或原异常文字。部署owner保存失败阶段，宿主通过真实SCM状态报告；取消、原线程、未知owner及关闭栅栏保留。只读状态入口只请求SCM_CONNECT／服务QUERY_STATUS。系统检查器在管理员子进程拒绝时先核对并输出有限原状态，不自动派发。

命令：.venv/Scripts/python.exe -B -c 调用tools.quality_gate.environment／stop_owned，在自动清理TemporaryDirectory内经tools/python-v20.py、tools/quality_python.py执行以下四文件，-q -p no:cacheprovider --tb=short --basetemp <临时目录>/pytest：
- backend/tests/infrastructure/test_v20_guard_service_diagnostics.py
- backend/tests/infrastructure/test_v20_guard_service_host.py
- backend/tests/infrastructure/test_v20_guard_deployment_configuration.py
- backend/tests/infrastructure/test_v20_guard_installation.py

45083实际184 passed，10.76秒，无skip；一个既有Starlette httpx弃用警告。覆盖20阶段编码、旧／非法码、敏感错误文字隔离、构造各边界、正常／取消／未知关闭、原SCM回调及新只读入口的最小权限和关闭。之前113项是受影响前三文件的先行结果，不叠加计数。

实际只读命令：.venv/Scripts/python.exe -B tools/python-v20.py tools/inspect-windows-guard-service.py --installation-ref ffac49bed3200a391a19cf7b1480b67d9bc41f17899fc21e329957aced5d33e3。
输出state=1 pid=0 win32=1066 specific=1 stage=UNCLASSIFIED native=UNAVAILABLE，退出0；不触发管理员弹窗或服务控制。不能将新诊断代码用于回溯旧错误。

Ruff check对8个相关Python文件通过；Ruff format --no-cache --check backend/app及5个相关工具／专项文件，515 files already formatted；git diff --check通过（仅原前端测试CRLF提示）；cleanup-test-artifacts.py --dry-run实际JSON0／screenshots0。源码与格式结果均CAS及同目录fsync／os.replace。

## 新程序与固定检查准备

11117使用requirements-build.lock固定哈希依赖，临时构建依赖／PyInstaller工作区自动清理。guard-prepared-20261114-2340-diagnostics实际构建成功：manifest5e5b6a8cc5ad7cbdf16bfbcdbb6b2cc32fc201202d30470817d459f005de44a3；sourcesb4636a0935efe88593e6dc558453d538981fa5d6670729cccd54eafba448bcaf；526成员186508724字节。冻结--verify-runtime、全包自验、来源快照复核通过，没有安装或服务启动。

4477新bootstrap、96764新请求准备均退出0，完整绑定见[复查申请](../../project/v2.0/Guard启动失败诊断复查申请_V_2.0.md)。固定复用旧2059安装工具及1900普通后台，明确其原摘要；不声称其包含新诊断源码。新Program Files目标及唯一服务尚未创建，task／runtime／checks=null。

31347真实冻结工具／普通后台只读预检退出0，ACTUAL_FROZEN_INSTALLER_INSPECTION_PASSED、ACTUAL_FROZEN_INSTALLER_ORDINARY_INSTALLATION_REJECTED及原工具／后台字节不变三项实际通过；使用v20_guard_installer_preflight_worker.py显式--installer／SHA、--request／SHA、--backend／SHA，固定值均见复查申请。不是SYSTEM模式或新安装证据。未取得新最小系统操作授权，不执行安装／启动。新SYSTEM故障阶段、普通后台读取SYSTEM进程／主Token／管道、原冻结根正常停止均未验证；WFP、双LPAC SERVICE、业务报告接收及供应方调用未覆盖。


## 新2345范围已授权（2026-11-14香港23:47:45接续）

用户明确选择“允许安装新诊断服务并完成一次检查”。本申请的新2345根及唯一af0b02…91de服务已获安装1次、实际启动1次／普通后台连接及停止授权；旧1905根／服务保留，其他边界不变。下一执行固定2059＋新2345请求的--install，成功停止核对后--start-stop一次；分别由Windows系统确认，不传原1952接续选项，不重试已派发／未知动作。


## 23:51新2345安装成功，下一启动一次

55618退出0，OWNED_BOOTSTRAP_PHASE_COMPLETED_NO_WFP_TASK_MODEL_OR_USER_SERVICE_UPDATE。实际新服务STOPPED／pid0／1077／specific0，尚未启动；新receipt SHA256 4307663496faf3315036ee92766a9f166764c153d0400d281bac9c3666d7bd4b。原后台读者与管理员工具已退出；保留新目录、完整双程序与停止服务。下一按已获同一新范围授权执行--start-stop一次，不重装、不传旧1952接续参数。


23:52新启动检查99905在途：新服务只读仍STOPPED／pid0／1077／specific0；固定2059管理员工具已进入，正在启动前核对。先收回99905；没有重复派发。实际StartService是否发生须以之后状态／结果判断，不能只从工具进程存在推断。


## 23:53新2345首次真实启动失败：PRIVATE_JOURNAL

99905退出1，子工具实际派发新服务首次StartService；SCM为STOPPED／pid0／1066／service-specific1460338688（0x570B0000），严格解码PRIVATE_JOURNAL／native未知。已经通过SYSTEM身份、部署源及契约、后台程序清单读取与解码，故障发生在LaunchJournal初始化；不能进一步猜所有者／DACL／锁等具体分支。未到READY或普通后台连接，所有本轮管理员／后台／Guard进程已退出。

本新2345安装1次及实际启动1次均已使用，不自动再启动或更改两处已装资源。下一仅只读查询新journal固定文件安全元数据（不读内容、不更改权限）及本地源码复现；旧1905和新2345失败服务均保留停止。此前“在途／尚未启动”均为历史状态，不作为接续依据。


2026-11-15接续：2345实际安装及首次启动均已执行，具体事件为11月14日23:53:11，SCM1066／0x570B0000，故障集中PRIVATE_JOURNAL。后续六阶段／有限原因、普通冻结journal自检、新固定输入及246专项见[新记录](guard-journal-startup-2026-11-15.md)，不是对本旧代码结果的追溯补报。没有再启动两处失败服务。
