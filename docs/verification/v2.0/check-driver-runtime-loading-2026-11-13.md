# CHECK_DRIVER运行加载与组合诊断（2026-11-13）

本次独立两小时时段香港16:35:30开始，目标18:35:30。代码master／28a7c9e，接续已有461条工作区变动；保留其他改动。BE0.17-draft-17／FE0.16-draft-16、Schema200／db20-r48未改变。授权隔离离线诊断，不包含真实模型／计数、用户业务库／目标Git写入、用户服务启停、SYSTEM／WFP安装或提交推送。

## 已实际取得的证据

- 香港16:44之前：在原挂起LPAC／原Job／原令牌下，以真实CreateFileW读取和执行所需权限检查复制入口、5项Python依赖与8项System32依赖，共14项全部允许；专项1 passed／1.74秒。没有增加Capability或修改系统ACL。只证明文件访问，不证明DLL初始化或Python启动。
- 香港16:47：原CreateProcessAsUserW加DEBUG_ONLY_THIS_PROCESS，仅本测试线程创建的独占子进程；原LPAC退出All Application Packages、原Job及目录政策不变。真实加载事件顺序为python.exe、ntdll、kernel32、KernelBase、ucrtbase、vcruntime140、python313；随后SXS BasepCreateActCtx／BasepSxsCreateStreams失败，实际退出0xC0000022，无驱动首帧。
- 香港16:49：同一复制Python／python313／zlib内嵌manifest，以CreateActCtxW只创建并释放上下文，不激活、不运行DLL。在operator上下文3项成功，在原LPAC令牌模拟下3项均WinError5拒绝。原实际子进程随后仍在同一SXS阶段退出。该比较进一步定位激活上下文边界，不能据此断言具体注册表键／系统路径根因。
- 静态PE导入及内嵌manifest只读检查：当前Conda Python3.13.5依赖python313／VCRUNTIME／CRT APIsets，python313另导入VERSION／WS2_32／bcrypt／zlib；Python及DLL manifest含Common-Controls依赖，zlib只有asInvoker。未更改原二进制、系统清单或正式运行包。

诊断首次出现测试辅助字段名pids与实际process_ids不符，导致本轮诊断测试失败且原调试事件未继续，fixture等待退出超时。已修复字段并将所有断言／Resume移入有界清理域，补充fixture退出事件清理；此后两轮均无清理错误。该辅助错误不能归为产品运行根因。外层TemporaryDirectory在pytest进程退出后完成清理，没有保留原始日志。

## 命令及当前结果

隔离工具入口：tools/python-v20.py tools/quality_python.py backend/tests/infrastructure/test_v20_driver_runtime_loading.py -s -q -p no:cacheprovider --tb=short --basetemp <本轮独占临时目录>/pytest；外层70秒限时，Popen原进程树停止及临时目录finally清理。

最近结果：1 passed、1 failed／3.39秒，失败项要求Python正常exit91，实际exit0xC0000022；作为尚未恢复的真实失败保留，不能记驱动首帧或真实浏览器通过。未运行完整产品验收、真实浏览器／前后端链、SYSTEM服务或供应方。

## 依据与边界

Microsoft原生调试事件布局及句柄职责：[DEBUG_EVENT](https://learn.microsoft.com/en-us/windows/win32/api/minwinbase/ns-minwinbase-debug_event)、[WaitForDebugEvent](https://learn.microsoft.com/en-us/windows/win32/api/debugapi/nf-debugapi-waitfordebugevent)；事件进程／线程句柄由系统在退出事件Continue时关闭，image／DLL文件句柄由本诊断关闭。仅创建本轮原进程的调试标志，不按任意PID附加、不启用Debug权限、不安装跟踪器。

[ACTCTXW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-actctxw)及[CreateActCtxW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createactctxw)定义了资源manifest、来源及失败句柄。官方LPAC说明确认额外系统能力需明确授予；本轮没有据此直接添加registryRead等宽能力或放松隔离。

下一步继续区分激活上下文需要的实际系统访问与运行包兼容性，再推进原复杂TestingValidationGroup有界阶段诊断。此记录为进行中，非环境准入。


## 17:06修复与实际验证

已把两层原因分开：原零能力LPAC在SXS失败；仅诊断registryRead可越过SXS，继而真实stderr提示ModuleNotFoundError: linecache。补齐固定3.13夹具标准库后，普通干净环境及显式能力LPAC均正常exit91。没有关闭LPAC、增加网络能力或修改系统ACL。

生产路径新增browser_driver_lpac_policy.py及windows_lpac_capabilities.py，沿原CHECK20 file_entries／SHA固定windows-lpac-policy.json，仅允许空能力或registryRead；默认不存在仍零能力。BrowserDriverProgram保存策略于原不可变文件事实，原启动摘要绑定，原Job创建及LpacProcessToken主／模拟令牌逐SID／属性／数量精确核对。TASK和项目CHECK不取此策略。正式Guard准入对非空能力额外要求精确能力名及lpac_capability_identity_and_denied_boundaries证据；旧证据不能覆盖新增能力，未生成正式证据或开ready。

- test_v20_driver_runtime_loading.py＋test_v20_browser_lpac_policy.py：27 passed／4.68秒。含实际原令牌14文件RX、零能力SXS失败的真实诊断、显式能力3项激活成功／exit91、默认校验拒绝额外能力、私有宿主文件读／写均拒绝及严格策略负例。零能力诊断通过只代表准确采集该失败，并非其运行兼容通过。
- test_v20_guard_browser_driver.py：2 passed／132.46秒，零skip。cleanup-proof仍核对默认策略失败后的原清理；trusted-frames采用manifest固定的显式策略，原生产Guard／Job／LPAC／进程令牌／结果管道实际接收到BEGIN／CASE_RESULT／END，原资源释放和丢释放观察恢复均通过。原pytest.skip已删除。System/WFP及受保护程序角色为原显式夹具；该程序没有启动Chromium或真实候选前后端。
- test_v20_check_deployment_composition.py＋test_v20_check_deployment_sources.py＋test_v20_check_runner_bundle.py：79 passed／12.36秒，含4项新条件准入及原正常main／固定资源持有。最初在工具受限上下文运行被原APPCONTAINER_OPERATOR_REJECTED阻止（55 passed／4 failed／20 errors），未改门槛；切换真实普通用户上下文后完整通过。
- 本轮7个生产新增／受影响模块Ruff lint已通过；导入排序经内存修正及同目录fsync／CAS原子保存，无原地格式化。Schema SOURCE_NAMES不含本轮改动，db20-r48保持，不为这些隔离模块重发布数据库资源。

下一单元：原TESTING_VALIDATION_GROUP阶段耗时诊断；完整真实Chromium／前后端及正式SYSTEM/WFP／受保护分发包仍未完成。


## 17:12共享回归与Testing进行中

原test_v20_windows_lpac_profile.py＋test_v20_windows_job.py：23 passed／20.53秒，原创建／额外能力拒绝／普通AppContainer负例、任务／项目隔离、挂起／取消／停止及真实后代Job收尾均保持。backend/app＋backend/runtime_guard Ruff format504文件通过。

复杂TESTING_VALIDATION_GROUP本次增加仅临时最后阶段和有界慢派发观察，不用faulthandler或原始报告；17:09开始，外层600秒限时，本轮独占TempDir／Popen原树收尾。已观察参考正／负快照依次完成并推进到WORKER_ADVANCE_07，单CREATE_SUSPENDED约3秒；尚在执行，不提前记通过。

独立只读cProfile完整verify_bundle_bytes：375成员、展开96237338字节、固定manifest 4e888e998f1f08e8b78559c212d30c51aaa3cc30e85b9cdafcf7b44249a4e215，3.485秒。3640170函数调用；LocalPathGuard.__enter__831次累计2.176秒，其中单独包清单遍历1.333秒；ZIP解压约0.290秒。主要开销是每文件两次完整祖先／对象核对，不能仅据此跳过固定包或缓存路径通过结论。后续仅在完整当前轮结束后调整重复遍历，保持源ZIP／实际所有文件的每次全量验证。


17:16复杂组最终结果：1 passed／364.42秒；阶段VALIDATION_DONE，原四子任务／八案例结果及发布均被实际断言，原Guard／Job／管道及目录收尾完成。源代码尚未做Git包优化，这是优化前基线。300秒限时的历史结果不是死锁证据；旧访问异常本次未重现，原因仍未知。首次调试字段错误遗留的唯一profile（本轮已知nonce）已按系统返回路径核实后，通过原DeleteAppContainerProfile释放；其他配置未枚举或删除。


17:22 Git包优化后：test_git_bundle.py＋test_git_bundle_actual_inventory.py＋test_task_runtime_workspace.py共35 passed／4.63秒；含同FileID／同长度／同mtime篡改、每次完整清单、ZIP／manifest漂移、文件／目录／根／元数据ADS、硬链接、junction及原读租约期间写入拒绝。新共享windows_file_streams.py沿原算法，workspace原错误码不变；git_bundle.py删除旧仅清单遍历，复用原LockedFileSource，一次实际遍历逐个全hash并检查隐藏流。正式Git资源原字节未修改。

同固定375成员包只读剖析2.689秒，LocalPathGuard进入456次（原831），完整成员／展开字节／manifest摘要不变；为单次观测，不能当稳定性能结论。三受影响生产模块Ruff lint通过。修改后复杂GROUP＋RECOVERY两参数17:22在途，外层900秒，结果稍后追加。


17:39最终复杂组合：GROUP在新create-only阶段标记下1 passed／347.79秒，四子任务／八案例及发布、原资源收尾通过。之前修改后首次GROUP＋RECOVERY为1 failed／1 passed（351.81秒），失败仅新增观察文件os.replace竞态，RECOVERY原命令丢结果／核对／恢复通过。已改最多256个只创建一次的空标记，观察器仅枚举名字，I/O失败返回不可用不打断业务；观察器2项并发／失败专项1.73秒通过。原100ms文件读取改为share-delete仍在压力下偶发替换失败，已被create-only方案替代，不再留旧替换实现。没有新增产品skip或削减固定Git字节核验。


18:00后联合收口：原LPAC／策略／完整Git／workspace／诊断／构建准备等172项168.25秒通过，无skip。该组早于端口入口变动；随后端口／Schema来源及部署组合26项24.37秒通过，实际r49冻结EXE及当前前端HTTP／IAB证据见[构建验证](backend-package-preparation-2026-11-13.md)。Schema r49仅更新正常main来源pin，三业务资源与r48原字节一致，不改变本节隔离策略。历史失败及其修复过程仍保留，不将普通浏览器等同正式CHECK_DRIVER。
