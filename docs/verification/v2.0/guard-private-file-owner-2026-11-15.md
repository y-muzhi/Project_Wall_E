# Guard私有文件所有者与未知关闭检查（2026-11-15）

本轮用户“继续推进”接续源码与隔离离线工作；此前“暂不执行系统检查”的范围继续遵守。未进行服务安装／启停或现有SYSTEM journal读取，未触发模型／计数，未打开／升级用户库，未改正常Git、运行服务或系统策略。

HEAD28a7c9e13c73a9d386081a6dd894244b51746a45，保留其他任务改动；BE／FE设计SHA仍分别1a8d277f25de570ce72e74a73ff763bf73f622fcf94b61f0820b78a1a5c6fd37／38557cee854697044ab7daba30f694738429be1235264a153851e8fc808cf3a7。按[独立迭代](../../iterations/pending/v2.0/WALL-E.Guard私有文件所有者与未知关闭修复迭代V1_V_2.0.md)先记录再实施，未改正式设计。

## 实现与边界

新私有文件在CREATE_NEW时明确指定operator Owner及原角色的受保护DACL，保留控制Git仅读执行角色。PrivateRecordAppend及PrivateConfigCopy使用同一描述符入口；journal锁、launch／action临时文件复用原PrivateRecordAppend，保留原句柄、flush、内容校验、无替换发布；最终状态仍原CAS及原子替换。不修已有文件安全属性，不启用新特权。

LaunchJournal关闭成功才清空原组件；异常保存原package／lock guard／ProcessLock及错误，retained_owner指向journal，后续close／enter保持未知且不重复原生操作。配置副本creation_unknown只在实际CreateFileW前设置，描述符准备失败属于已知未派发。共享发布失败继续转换为原LaunchOutcomeUnknown／GuardActionError并携带原retained_owner。

新冻结普通自检实际prepare写入、关闭后重新读取封闭的旧记录。源码与格式结果全部同目录临时文件flush／fsync、字节CAS及os.replace。旧0005 Guard及0010计划／请求保留原字节，不含本次修复，不能用于当前源码验收。

## 本轮实际结果

15254：核心15文件（私有文件／配置副本／journal／action／控制Git读角色、SCM宿主／部署／诊断、安装契约、原控制方记录／恢复、Schema发布／准入）405 passed，6 subtests passed，23.32秒，无skip，1个既有Starlette httpx弃用警告。覆盖显式Owner及受保护DACL真实传入CREATE_NEW、已有目标不替换、已知未派发、失败flush不改变原字节、真实OS锁保留、未知关闭不重试／重入、封闭记录恢复及固定原因诊断。

命令经.venv/Scripts/python.exe -B -c调用tools.quality_gate.environment／stop_owned，在自动清理TemporaryDirectory内使用tools/python-v20.py和tools/quality_python.py执行：test_v20_guard_private_file_owner.py、test_v20_guard_installation.py、test_v20_guard_controller_records.py、test_v20_guard_recovery.py、test_v20_schema_release.py、test_v20_schema_publish.py、test_v20_control_git_read_package.py、test_v20_runtime_launch_journal.py、test_v20_guard_action_journal.py、test_v20_windows_private_package.py、test_v20_windows_private_record.py、test_v20_windows_config_copy.py、test_v20_guard_service_host.py、test_v20_guard_deployment_configuration.py、test_v20_guard_service_diagnostics.py。选项-q -p no:cacheprovider --tb=short --basetemp <临时目录>/pytest；均位于backend/tests/infrastructure。

79184：真实本机管道代表性5项全部通过，108.63秒；REGISTER／REGISTER_THREAD／OBSERVE_THREAD及原配置后固定元数据sha1／sha256两种格式。通过同一隔离入口、-vv、-o faulthandler_timeout=45、--durations=5，临时数据库、Git及原生子进程／管道完成清理。受控程序准入端口仍为夹具，不当SYSTEM/WFP证据。

Ruff check本批APP模块、生成pin、冻结入口及新增／调整的owner和journal专项通过；format --no-cache --check backend/app及入口／专项513文件通过。git diff --check通过，仅原frontend/tests/application-router.test.mjs的CRLF提示。cleanup-test-artifacts.py --dry-run为JSON0／screenshots0；不保存原始JSON报告、截图或日志。

## 关联Schema来源发布

必要扩展回归发现windows_private_package.py属于Schema200来源清单，旧db20-r49按设计拒绝新来源，临时数据库初始化在通信前终止。按原工具.venv/Scripts/python.exe -B tools/python-v20.py tools/schema-v20-release.py --release-id db20-r50新增不可变发布并原子更新代码pin。manifest SHA10ff02e670eb705e6ac537eb9335449a72de9dbc93eeffbe46b16d7d74557f31。r49保留，objects.v1.json／fresh.v1.sql／upgrade-151.v1.sql与r49逐字节相同，Schema200及SQLite3.54.1不变；未操作用户库。未放宽来源检查。

## 新Guard冻结程序

83848构建退出0；backend/distributions/windows/guard-prepared-20261115-1525-private-owner，manifest b14696996269de3e150ead821de7d4e8f8d1e5ad9dd539248823da0f86f500db，sources082fb9b0f3a4cf39d8fc651bce1c32f1f513deb55d7c06678dbece00639ef0ab，526成员186513629字节。requirements-build.lock哈希锁定构建依赖置于临时目录；普通冻结--verify-runtime完成真实journal写入／关闭／重开封闭，自身全包校验与最终来源快照通过。构建工具和工作临时目录自动清理，不安装或取得OS准入。

## 中间失败、修正与未覆盖

首轮233通过、1失败：IO端口新增publish路径在注入fsync失败时没清理其已知新文件，端口已修正；新增Native调用观察器把配置清理OPEN_EXISTING误判为CREATE_NEW，修正为仅观察新建；旧故障端口引用删掉的launch.Path，改为pathlib.Path。异常转换漏导入PrivateRecordError亦已修复，最终上述回归覆盖失败分支。

73307扩展集合600秒超时；分离诊断41931在240秒界限停止本轮原测试进程，未作为通过。首个REGISTER失败单独复现确定为Schema来源变更拦截；另有旧“禁止seal再次发布”注入过宽，拦住正常journal临时文件发布，已限制到controller-seal角色。更新r50后以本轮相关核心集合及5项真实管道路径复查通过。未重跑完整149项通信／恢复诊断集合，不把旧失败或未执行范围写成通过；中间所有临时产物随本轮原进程退出后清理。

具体SYSTEM journal失败分支仍未验证；源代码默认Owner依赖缺口及未知关闭修复不能写为2345真实根因已确认。两处服务沿用上次已核实的停止状态，本轮未重新查询／启停。普通后台读取原SYSTEM进程／主Token／管道、完整正常停止、WFP／正式双LPAC SERVICE、报告接收及C64交付仍待后续授权和证据。系统检查暂停期间不重复提出同一申请。


## 本轮最后输入准备

56998新bootstrap准备成功：guard-bootstrap-prepared-20261115-1530-private-owner，plan2f073c2f3a8f561086cf03ddcc516fba628a934aa8d78546acf903221cf01e05，deploymente65338aef691f61ab099f79ce34e59642abe3b8d01c9e9a02b9a7576b0dc64ce。32918新请求准备成功：guard-installation-prepared-20261115-1530-private-owner/guard-installation.v1.json，SHAfd1aa5cf295310cb49528aa39f6cf0d695319655cf79b30a1b2a752cdc5194a8。只在工作区新建输入，未执行安装器实际预检或系统模式；未创建预定0010系统根或查询／创建其服务。


最终只读复核：新冻结来源摘要仍082fb9b0f3a4cf39d8fc651bce1c32f1f513deb55d7c06678dbece00639ef0ab，程序／请求／r50 manifest摘要匹配；预定0010根仍不存在，未查询或创建服务。8份本轮文档511个本地引用通过；所有本轮检查／构建／准备会话均已收回，无待定工具结果。此为文件及工作区检查，不是恢复系统检查。
