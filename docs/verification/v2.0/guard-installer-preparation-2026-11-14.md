# Guard受信安装工具准备验证（2026-11-14）

阶段提示：20:30已获得本轮固定最小系统授权，后续真实安装／Windows启动结果以[最小SYSTEM记录](guard-system-bootstrap-2026-11-14.md)及当前需求映射为准；本页先前“待授权”是当时准备边界，不作为现行状态。

## 基线及范围

本轮HEAD28a7c9e13c73a9d386081a6dd894244b51746a45／起始517行脏工作区，保留其他任务。BE0.17-draft-17／FE0.16-draft-16仍DRAFT，未自动合入设计。固定Python3.13.5／Windows普通用户。源码经同目录临时文件flush／fsync、原字节复核及os.replace保存，固定Ruff结果在内存生成后原子保存。

安装源码位于tools/windows_guard_install_contract.py、windows_guard_install_identity.py、windows_guard_install_files.py、windows_guard_install_service.py、windows_guard_installation.py、windows_guard_installer_package.py及backend/frozen_guard_installer_entry.py。原启动组inspect扩展显式原读者和新安装根绑定。系统检查器v20_guard_system_bootstrap_worker.py只在明确--allow-system-changes下发起Windows管理员确认，普通后台及监督进程不提权。

## 专项及修复

- tools/python-v20.py tools/quality_python.py：安装初版与原启动组两文件回归，86 passed16.35秒，无skip。使用独占临时NTFS输入、原控制方Job，未安装／控制任何OS服务。
- 校正原生服务安全对象类型SE_SERVICE=2，加入实际只读Schedule原句柄GetSecurityInfo检查；原先5代表SE_LMSHARE，1945准备包因此不用于安装。服务DACL通过SetSecurityInfo的显式受保护位设置，严格读回Owner／Group／全部ACE。
- 原文件回读打开模式修正为与完整程序只读租约兼容；新增配置／intent／receipt精确DACL及有效权限核验。
- 仅StartService返回成功取得本轮停止归属；StartService失败不猜PID停止其他调用方服务，不自动重试。
- ProbeChannel／管理员原句柄未知关闭仍关闭其他已知owner，失败owner保留且禁止重复关闭；InstallationOperator进入验证失败也释放其已知原owner。
- 受影响安装专项最终41 passed7.17秒，无skip；覆盖篡改请求／固定摘要／源包／权限／预算／寿命边界、实际普通Token拒绝、原外部读者／新根绑定、原生缓冲边界、已存在服务拒绝、精确四权限及STOPPED注册端口、失败启动无停止归属、原已有本Token恢复特权作用域、无明确授权标志即拒绝及未知关闭。不调用实际提权／服务写入API；端口替代用例不能当SYSTEM实证。
- Ruff check上述源码及两个worker／专项通过。完整最终格式与资源状态检查后续收尾。

## 实际冻结程序和固定请求

1945专用安装程序初次构建／实际--verify-runtime和只读inspect／普通--install拒绝均通过；源文件完整不变，无业务库／服务／测试产物生成。后续服务接口修正产生新1952包，旧包保留原字节，不使用旧请求。

最终guard-installer-prepared-20261114-1952：manifest8b6567e2578eeaca2545686f7ad44b3da4fb40530f293c6c5b6defab9d7de3ee，sources99c3a266e5de7911eb2839d4cfac6fa185d3fd48fdfb78327fe6e4ec6cbd382b，109文件27336698字节。实际--verify-runtime／全包锁／成员读回通过，未携带业务库、SQLite或Git程序。

新guard-installation-prepared-20261114-1954固定请求SHA4ee0f56c2aca50478ab8bbca34bff940ce9709edc8f7f7f8fd20930076db6ce4，绑定上述安装包和原1905启动组，实际原准备器全包读回成功。最终实际inspect／普通拒绝会话78050已退出0：ACTUAL_FROZEN_INSTALLER_INSPECTION_PASSED／ACTUAL_FROZEN_INSTALLER_ORDINARY_INSTALLATION_REJECTED／ACTUAL_INSTALLER_AND_BACKEND_SOURCE_BYTES_UNCHANGED_NO_SYSTEM_WRITES，源请求／程序原字节不变、临时目录清理。

唯一目标与动作见[可审阅申请](../../project/v2.0/Guard最小系统联通检查申请_V_2.0.md)。C:\Program Files\WALLE.RuntimeGuard.V2.Test.20261114-1905和唯一WALLE.RuntimeGuard.ffac49bed3200a391a19cf7b1480b67d9bc41f17899fc21e329957aced5d33e3尚未安装。

## 原生依据与未覆盖

原对象类型及SetSecurityInfo用法依据[Microsoft SE_OBJECT_TYPE](https://learn.microsoft.com/en-us/windows/win32/api/accctrl/ne-accctrl-se_object_type)、[SetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setsecurityinfo)；服务权限及默认描述符依据[Service Security](https://learn.microsoft.com/en-us/windows/win32/services/service-security-and-access-rights)；显式UAC与原进程句柄依据[ShellExecute](https://learn.microsoft.com/en-us/windows/win32/shell/launch)、[SHELLEXECUTEINFOW](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-shellexecuteinfow)。实现成功仍须实际OS核验，文档不替代实证。

尚未获本轮SYSTEM安装／启停许可，未执行受保护安装／SCM写入、SYSTEM正向连接、WFP、双LPAC SERVICE、TASK／Coding／报告／交付准入；无真实模型／计数、用户库／用户服务更新或提交推送。临时程序输出在finally清理，仅保留本Markdown；正式包／请求为正常产品输入，不作为测试报告清除。

 
## 授权状态

香港19:58已向用户提出固定1954请求的最小SYSTEM安装／一次联通／停止授权，当前等待明确答复。不是已获授权；未执行依赖动作，继续其他本轮已授权检查与文档工作。无自动审批拒绝或系统安装错误可报告。

 
## 授权等待期间的原生写入失败检查

仅新增专项，生产安装输入／程序摘要未改。最终test_v20_guard_installation.py 45 passed6.76秒，无skip：在临时当前用户Owner目录中实际执行CREATE_NEW及受保护DACL读回，完整字节写入和已持有源的元数据回读通过；同名原文件保留，部分源故障／短写拒绝且原新文件句柄确实关闭。此夹具不使用管理员／SYSTEM Owner，不证明受保护安装或journal分支。普通后台连接仍待明确系统授权。Ruff check本批通过，backend/app格式509文件通过，frontend format:check通过；不修改原服务／数据。

 
后续新增6类部分安装故障传播、原组／其他特权变化／恢复调用未知以及服务关闭未知等边界；最终安装专项55 passed6.81秒。流程端口明确证明源复制或journal失败时不执行服务注册，writer／service已知owner按顺序收尾；不把这些端口替代当真实SYSTEM安装。生产包及固定请求原字节未改。

 
## 最终准备入口及检查器补验（香港20:20）

最终安装专项63 passed6.90秒，无skip：检查器明确区分注册未启动1077与实际启动后零退出，PID非零／服务特定错误／其他Win32错误均拒绝；停止后1077仍不能作为退出证明。依据[Microsoft RQueryServiceStatus](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-scmr/cf94d915-b4e1-40e5-872b-a9cb3ad09b46)。

最终1952 EXE新增实际负向边界会话13969退出0：错误创建时刻、请求SHA、程序SHA、互斥模式、缺失或不适用的私有channel均拒绝；同用户普通Python不能代替固定后台读者。源程序／请求原字节不变，原读者STOP退出和临时清理通过。

新增prepare-windows-guard-installation.py实际CLI在独占临时目录生成与1954逐字节相同的请求，拒绝覆盖并保持旧输入，拒绝相对路径；会话93357退出0，临时清理。build-windows-guard-installer.py --help正确转入原固定builder。原owner异常不吞为普通拒绝。此后1952构建全部当前输入重新原生快照的source_digest仍99c3a266e5de7911eb2839d4cfac6fa185d3fd48fdfb78327fe6e4ec6cbd382b，两个CLI wrapper不在既有程序运行闭包中；固定程序／请求未换绑。

会话54463实际验证SHELLEXECUTEINFO 112字节结构／完整EXE路径与0x140原句柄、实际创建时刻／镜像、等待零退出和关闭；只把启动端口显式换成普通open来运行原固定安装程序--inspect。实际原后台读者正常退出，临时无业务产物。该检查没有runas、管理员确认、提权或SYSTEM证明，不能代替授权后的真正检查。

最终17个主要源码format通过／Ruff check通过，APP原509文件format和前端format:check通过。12份本批文档497个本地引用存在；git diff --check通过，仅既有application-router测试换行提示；cleanup dry-run JSON=0／screenshots=0。没有提交推送、真实模型／计数或系统写入。SYSTEM授权仍待用户答复。

 
香港20:22收尾原生只读核对：唯一1905安装目录／服务仍不存在，8000／5173／43194无监听；HEAD不变，默认Git脏状态537行（本轮起始517），其他任务改动保留。最后1077修改涉及两检查文件format通过，cleanup dry-run仍0／0。实际推进约2小时，三小时任务未记完成，首次系统授权问题未答复，当前停在这一必需的用户决定处；不是系统安装失败或自动审批拒绝。
