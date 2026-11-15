# Guard最小SYSTEM安装与联通检查（2026-11-14）

## 当前授权与固定范围

香港20:30接续。用户对固定请求1954明确答复“允许安装并完成一次启动、连接检查和停止”。仅新建C:\Program Files\WALLE.RuntimeGuard.V2.Test.20261114-1905和唯一WALLE.RuntimeGuard.ffac49bed3200a391a19cf7b1480b67d9bc41f17899fc21e329957aced5d33e3；新安装1次、有界启动／普通后台连接／停止1轮，结束保留新目录及停止状态新服务。Windows管理员确认由用户决定，不代点击。

不修改现有服务、用户库／正常Git目标或网络策略，不调用模型／计数，不提交推送；不授权进程／Token权限授予、WFP、任务或双SERVICE准入。未知动作不自动重试／删除／修复。

## 基线与安装前现场

HEAD28a7c9e13c73a9d386081a6dd894244b51746a45，默认脏状态537行，保留其他任务。原正式BE／FE摘要不变。实际普通非AppContainer监督者与请求backend_sid一致，新目标及唯一服务仍不存在。

安装程序guard-installer-prepared-20261114-1952固定manifest8b6567e2578eeaca2545686f7ad44b3da4fb40530f293c6c5b6defab9d7de3ee；安装请求guard-installation-prepared-20261114-1954/guard-installation.v1.json固定SHA4ee0f56c2aca50478ab8bbca34bff940ce9709edc8f7f7f8fd20930076db6ce4，原字节复核通过。Guard1810、后台1900、1905启动组均原固定输入，不换绑。

## 实际执行

通过项目固定Python和tools/python-v20.py运行backend/tests/infrastructure/v20_guard_system_bootstrap_worker.py，显式--allow-system-changes及上述--installer／--installer-sha256／--request／--request-sha256；--install与--start-stop分开一次执行。监督者保持普通，真实原程序／输入全包锁、原后台读者、原管理员进程句柄及私有READY／STOP通道由现有检查器持有。临时资料finally清理，仅记录本Markdown；正常程序、安装intent／receipt／journal是正式资源，不作为测试报告删除。

本记录建立时尚未执行系统动作。先安装STOPPED，收回实际结果后才决定是否进入已授权的一轮启动／连接／停止，不提前记通过。若安装失败，先只读核对实际目标／SCM及原进程，不能重试或假定零副作用。

[固定申请](../../project/v2.0/Guard最小系统联通检查申请_V_2.0.md)／[准备验证](guard-installer-preparation-2026-11-14.md)／[当前断点](../../project/v2.0/实现进度_V_2.0.md)。

 
香港20:31:48派发首次--install（会话18351），固定输入如上；20:32:56实际输出REQUESTING_INTERACTIVE_WINDOWS_ADMINISTRATOR_APPROVAL。已发起真实runas，当前结果未回收，不记安装成功、不自动重试。源普通监督者／后台读者及输入由该原会话持有；结束后核对临时清理与资源状态。

 
## 首次安装实际结果（香港20:34:36）

18351退出0，实际输出OWNED_BOOTSTRAP_PHASE_COMPLETED_NO_WFP_TASK_MODEL_OR_USER_SERVICE_UPDATE。真实1952安装程序完成--install并返回0，普通监督者随后原SCM只读核对STOPPED／初次未启动状态、重新核对原源输入及全包，原后台读者STOP／原句柄EXITED／临时清理均通过。目标顶层实际为guard、backend、guard-deployment.json、installation-intent.v1.json、installation-receipt.v1.json、journal六项；安装程序在成功前实际核对Owner／Group／受保护DACL、原普通读者有效权限、SYS-only journal及服务精确四特权。不是mock或普通Owner替代。

首次安装授权已使用1次，不重做--install。尚未启动Guard，接着执行已授权的一轮--start-stop；进程／管道联通和实际停止结果待收回。

 
香港20:36独立原生只读回读：安装receipt SHA e360a3f86470a2e5181cc6dc56750238a6b2d8f8e4aa9d7cb70d21f662f8b334，root file_id14ec0c00000050000000000000000000，journal file_ideb33050000009f000000000000000000。SCM kind16／start3／LocalSystem、精确四特权、failure_count0；初次state1／pid0／Win32 exit1077，与从未启动的实际语义一致，不把1077当停止证据。

20:35:27派发唯一一轮--start-stop（会话31131），20:36:14已实际输出REQUESTING_INTERACTIVE_WINDOWS_ADMINISTRATOR_APPROVAL；等待实际启动／连接／停止结果。该轮已派发，不重做或并行发第二轮。

 
## 已知未派发的启动前错误与修复

31131退出1，管理员检查器未产生READY；SCM只读仍state1／pid0／1077／specific0，未产生任何实际StartService启动。不得把此结果记为SYSTEM启动或普通后台无法读取SYSTEM进程。

只读42356复用原文件权限算法、限READ_CONTROL|FILE_READ_ATTRIBUTES且OPEN_EXISTING的明确端口，不模拟管理员身份、不含写入API：原源／祖先、实际已装双完整包、全部精确DACL和原普通读者权限全部通过；随后普通原通道构造实际重现CODE_DEPLOYMENT_ABSOLUTE_PATH_REQUIRED。根因ProbeChannel调用只接受str的absolute_path，而main传入已校验Path，在service.start之前必然拒绝。receipt／两个原输入摘要及实际根FileID分别只读核对一致。

修复内部路径用原local_absolute_path，实际私有目录Path／STOP专项通过；新增原工具完整租约的显式接续，仅--start-stop并强制原SCM1077／pid0／无specific错误；不改原1954、intent／receipt、Guard／后台、服务参数或权限。新工具单独新完整包自证，同时另持原1952完整包以重建原1954；不把新工具摘要替代成旧原请求，不授安装／修复，也不对已派发或未知状态接续。用户本轮授权的一次实际启动仍为0次，继续该同一范围。完整规则已先记独立pending迭代。

修复相关安装专项最终67 passed7.79秒，无skip，Ruff check通过。2048新工具构建在途，取回实际新摘要后才执行唯一未派发启动的接续；当前不执行第二次安装或未知重试。

 
香港20:49修正工具guard-installer-prepared-20261114-2048实际构建成功：manifestd7f65efd3e56c24d446b6deaa2a4c567b289b7097dce976df9658372742e316a，sources5a5ea43be7f1bd998214b6a4b2d594b1bc37f5e23b5e2a9d1ad1bc7679cd72a4，109文件27337847字节。新实际--verify-runtime／完整包核对通过，未执行任何系统变更。原1952完整包／1954／已装资源不改。接续同一1954时显式新工具自身SHA加--original-installer-package指原1952，原SCM必须1077；只补本轮0次实际StartService中的唯一启动，不重装、不把未知结果当未派发。

普通后台连接失败时，监督者在请求原STOP之前追加只读SCM／原SYSTEM进程身份诊断，只输出固定类型／code／native数字，不提升、不修改任何权限；这不是身份校验降级或运行准入证据。

 
20:50:45派发同一未派发授权接续51907；派发前再次原生SCM1077／pid0／specific0。新工具自身使用d7f65e…316a，原1952包由显式--original-installer-package持有，原1954请求及所有安装资源／服务配置未改。当前等待结果；不并行或重复启动。

 
## Windows启动请求未成功返回（香港20:54:35）

51907退出1，失败在AdministratorAction.__init__的ShellExecuteEx：返回失败或未给原管理员进程句柄，尚未进入2048工具；新服务仍state1／pid0／1077／specific0，实际StartService仍0次。该结果不同于31131的路径程序错误。旧检查器没有保存GetLastError，不能断言用户取消、Windows策略或自动审批拒绝；没有工具自动审批拒绝记录。

CodeIntegrity／AppLocker／Defender三事件通道的本轮路径匹配只读查询均无可用匹配结果（UnavailableOrNoEvents），不能据此判定没有阻止策略。当前未见本轮consent／installer／runtime-guard／backend进程，原会话和临时资料已收尾；未重发UAC或重试启动。已向用户询问实际是否见到／取消／被阻止的提示，仅为定位系统UI结果，不重新询问项目授权。

补齐监督者立即捕获native_error／accepted／original_handle；原固定stop150秒内等待SCM STOPPED后的冻结根真正EXITED且进程码0，非零仍拒绝。相关专项69 passed7.24秒；新2059工具构建在途，仍只生成本地包，没有新的系统启动动作。正式原后台／SYSTEM进程／管道及完整停止尚未验证。

 
## 最终工具与只读收尾（香港21:11）

最终guard-installer-prepared-20261114-2059：manifest1fafdfb8a68e2b500b448f3ec95043f6f9c0a0df89f999c3011d4ffd9fd4849b，sourcesf1ad413b67518a821da917ac04117c7fa1cfb676d59e75053408d9eef8b12034，109文件27337930字节；实际runtime／全包构建通过，未发起该包管理员请求。

只读诊断在原包锁之前不再读取可变头选择EXE，先持有原GuardBootstrapSources及全后台包；补强时50486因诊断端口初始化字段遗漏失败，无系统或数据写入，已修正。最终专项71 passed7.32秒、check／format通过，69321实际退出0：原源／祖先、完整已装双包、精确全部DACL与原读者权限、真实私有通道Path／固定descriptor均通过；原后台读者与临时资料清理。只读证明不模拟管理员，不代替SYSTEM启动。

事件查询具体错误ID后续核实为三个通道均NoMatchingEventsFound，非已确认读取拒绝；仍不能证明没有阻止策略。UAC设置EnableLUA1／ConsentPromptBehaviorAdmin5／PromptOnSecureDesktop1／ValidateAdminCodeSignatures0／EnableInstallerDetection1。Codex／explorer与工具均Session2，工具自身借用句柄的GetProcessWindowStation／GetThreadDesktop／GetUserObjectInformation只读返回WinSta0／Default／receiving_input=True；未关闭借用句柄、切换桌面、代点击或修改设置。依据[窗口站](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getprocesswindowstation)、[对象信息](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getuserobjectinformationw)。这些当时事实不能补回旧ShellExecuteEx错误码。

新增tools/run-guard-bootstrap-check.cmd，只封装现有检查器的固定2059／原1952／1954参数，普通监督者且仅后台无库读者，Windows另确认专用工具；--help实际退出0，无管理员或服务动作。完整执行未运行，供用户在前台直接看到系统确认／错误结果。未知结果不重复点击，跨系统重启不沿用本轮许可；1077仅表明当前Windows启动周期未尝试启动，不是终身未运行证明。

默认Git脏状态539行，原HEAD不变、保留其他任务。cleanup dry-run JSON0／screenshots0。无本轮在途进程或窗口确认，唯一服务最后state1／pid0／1077；真实普通后台／SYSTEM进程／管道及停止尚未完成。下一仍需用户说明当时提示，再执行当前已授权但尚未派发的唯一启动；不把此处描述成缺项目授权、自动审批拒绝或SYSTEM进程不可读。

 
香港21:16最终收尾：2059当前全部构建输入source_digest仍f1ad413b67518a821da917ac04117c7fa1cfb676d59e75053408d9eef8b12034，实际完整新程序再次原生核对通过。10份本批文档520本地引用均存在，源码check／format通过，git diff --check通过（仅原application-router测试CRLF提示）；cleanup dry-run仍JSON0／screenshots0，未见本轮consent／installer／runtime-guard／backend进程。最后原SCM仍state1／pid0／1077／specific0，尚无实际启动／连接／停止证明。全部进度与需求映射、运行说明及归档已同步，等待用户的Windows提示说明；没有重新请求项目授权、没有再次发起UAC。

 
## 用户明确要求重试（香港22:49）

用户更正：刚才关闭了屏幕，明确要求“你现在重试一下”。继续原同一最小范围，不推断为取消，也不重复索要项目授权。执行前只读核对最终2059／原1952／1954三个固定摘要、原普通身份／backend_sid以及原SCM STOPPED／pid0／1077／specific0均通过，实际StartService仍0。HEAD及539行不变。现在重新发起该已授权但尚未派发的一轮，等待用户在可见屏幕处理Windows确认；不重装、不改已装意图／权限／网络／用户数据。

 
22:50:15派发最终2059同一范围接续38993，22:51:12进入真实Windows管理员确认；22:52:10只读见consent402040和原后台读者55204均Session2，尚无已启动Guard。确认程序存在不当窗口已被点击或SYSTEM成功；不代点击、不重发，继续持有原会话直到结果。

 
## 本次重试的明确Windows结果（香港22:54—22:58）

38993退出1，ShellExecuteEx即时保存结果为native_error=1223、accepted=False、original_handle=False。Microsoft将1223定义为ERROR_CANCELLED，表示操作取消；本结果不能单独区分主动点击取消与确认未完成等具体交互原因，也不能解释成工具自动审批拒绝。依据[Windows系统错误码](https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--1000-1299-)。

此前确认程序consent402040实际运行于Session2；返回后未见本轮consent／installer／runtime-guard／backend进程。独立原SCM再次state1／pid0／1077／specific0，实际StartService仍0，原安装程序／配置／权限／网络未更动。22:57只读WTSGetActiveConsoleSessionId与ProcessIdToSessionId均返回2，只说明当前物理控制台与工具同会话，不推断故障当时的可见状态；[接口依据](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-wtsgetactiveconsolesessionid)。

不连续重发确认请求、不代点击、不改UAC设置。已向用户核实本次是否实际看到／已点“是”／没有点“是”，仅诊断交互结果，原项目授权有效。前台run-guard-bootstrap-check.cmd仍为同一固定范围入口，实际启动／连接／停止未完成；等待明确窗口反馈后接续。

 
## 用户现场确认后接续（香港23:20—23:22）

用户再次明确要求现场重试；固定2059／原1952／1954与SCM1077／pid0复核通过，派发6068。用户随后答复“我确认同意了”，23:22:14只读检测原后台读者123272／管理员工具118040均Session2，真实工具已进入运行；此前1223的取消结果不当本轮新结果。保持原会话，实际SYSTEM Guard启动／普通后台／停止结果未取，不提前记通过、不重发。


## 23:24实际启动结果（替代前述在途与“启动0次”状态）

用户确认同意Windows管理员请求后，6068真实进入2059管理员工具，首次StartService已派发；检查退出1，未到READY或普通后台连接。23:24:38独立只读SCM核对为STOPPED／pid0／Win32退出1066／service-specific1；所有本轮管理员工具、普通读者与Guard进程已退出。23:22:25 System事件7024同样记录本服务specific1，不能从通用文字“函数不正确”推断根因。当前宿主把各阶段异常统一报告1，具体原因仍需定位。

本次安装1次及实际启动1次已使用。当前保留原安装目录、原程序／配置／意图／回执和停止状态服务；没有修改ACL、WFP、用户数据或用户服务。原要求1077的“未派发接续”与固定CMD不再适用于本现场，不能重复执行。下一步仅只读查自身服务事件和源码，准备可检查的修复及必要离线检查；若需要替换已装程序、改服务参数或再次启动，须明确新范围后取得新授权。当前系统联通仍未验证，不能标通过。


23:46后续：不重复启动旧服务，完成工作区安全阶段诊断、184项专项、新2340 Guard包及新2345请求的实际普通预检；详情见[独立诊断记录](guard-startup-diagnostics-2026-11-14.md)。新系统目标未创建，旧Guard根因仍未知，不改写本次失败或当作SYSTEM通过。
