# Guard控制方独立owner（2026-11-06）

按[本机通信细化](../../iterations/pending/v2.0/WALL-E.Guard本机通信实施细化_V_2.0.md)接原连接与执行资源寿命，不安装／更新用户服务。V2未提交，db20-r15／code20-r2不变。

guard_controller_owner.py先确认原程序准入及私有登记，再从实际peer原进程句柄取得ObservedProcess.duplicate，持有独立PrimaryToken和ControlGitRegistry watch。断管只释放连接，原Native source／token／watch仍可核对同一进程；重接必须同原binding及实际当前程序，不能换epoch接管。原actor线程拥有长期资源，处理中拒绝close；关闭须整域封闭和close_watch的原Job空／root退出检查先通过，随后token和原进程副本；失败保留原owner供原资源清理。构造未发布失败只回收本轮未投入执行的原只读对象，不制造Native成功。

windows_process.duplicate同权／不可继承且不按PID重开；close失败也显式保留原ObservedProcess。完整RELEASE的外层Job／IO／配置／程序／目录清理仍须生产资源owner，不以本controller.close或release_native_handles代替。

## 实际检查

- 标准受限环境：owner／恢复策略端口＋自身只读副本／close保留共41通过、1同类警告，1.26秒。程序包／权限正向端口明确不当Native认证。
- 普通Native专项曾被审批服务403阻断两次，没有执行／绕过；随后正常审批恢复，新增实际owner链路及共享回归实际执行：最终22文件395通过、1条既有Starlette弃用警告，83.22秒。范围包括通信／程序包／原登记／只读包／有效权限、原句柄副本／ControllerPrimaryToken、owner端口与新增test_v20_guard_controller_owner_native.py、窄恢复、Registry／Guard崩溃及原生AsUser。计数与上一批413不同，范围不等，不相加。
- 新实际owner用例的进程／独立句柄／PrimaryToken／Registry watch／Journal及pipe均真实：关闭原peer后原source仍RUNNING，真实自有Job终止原控制方后watch确认CONTROLLER_EXITED，再关闭原token／副本。**只有程序准入及其返回登记使用显式端口；真实私有记录保持backend_admission=null**，不把此用例当实际保护程序准入或窄恢复生产放行。
- 224个app文件Ruff format、两受影响模块lint、git diff --check通过；cleanup-test-artifacts.py --dry-run为JSON=0／screenshots=0。临时文件／自有进程退出清理；当前无活动检查或审批阻塞。

## 继续依赖

原七动作的生产资源准备仍未连接。PREPARE在创建新目录／Job／STDIO副本之前，需要先在原Guard归属载体保存完整原请求摘要及预留资源引用；现LaunchJournal只管Native CREATE／RESUME屏障，Registry.register发生于资源已经准备之后，不能把它当完整PREPARE原接收。下一批补原技术动作记录／分配意图及部分资源owner，再接固定Typed命令及实际IPC；不新建业务调度器／任务或第二业务账。

实际受保护walle-backend.exe／SYSTEM／跨用户／LPAC-WFP尚未准入，ready=false，业务HTTP仍19条，无新增页面／真实供应方调用。
