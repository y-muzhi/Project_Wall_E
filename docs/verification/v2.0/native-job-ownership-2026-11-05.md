# V2.0 Guard持有的原生Job与创建关联

日期：2026-11-05；HEAD 28a7c9e。仅本轮自有测试根／衍生进程；未运行Git、安装Guard或修改ACL／网络策略／用户服务。

实现windows_job.py：匿名、不可继承的独占Job；设置KILL_ON_JOB_CLOSE、进程数／Job内存限制并真实读回，禁止breakaway及silent-breakaway。有界读取完整PID列表，扩容／变化不足明确complete=false，失败未知；成员快照不当作Task STOP验证。terminate_owned只对本组件新建Job提出终止，不把成功返回当全部退出；关闭后不按名字／PID恢复旧Job。

process_creation_attributes在原Job句柄生存期内构建PROC_THREAD_ATTRIBUTE_JOB_LIST，供CREATE_SUSPENDED实际调用时同时关联Job，避免“创建后再Assign”的崩溃空窗；属性资源finally销毁，不把Job句柄继承给子进程。生产模块此时提供Job／属性原语，完整受管Root创建器、STDIO句柄白名单、LPAC身份／WFP及Guard RPC尚未接入；测试CreateProcessW创建器只在test_v20_windows_job.py，不能当成生产受控启动器。

实际专项：windows_job／windows_process两文件最终22通过（1.14秒）。真实限制读回、初始空Job、关闭拒绝、挂起根在执行任何夹具代码前已经是Job成员；原生终止后真实signaled退出123且无成员；恢复夹具根并实际spawn衍生进程，再关闭本轮Job最后句柄，根及衍生均EXITED。没有普通subprocess代替Job关联或breakaway降级。另修只读进程CloseHandle失败时保留未核清句柄引用，成功后才清空，受影响组合复核如上。

命令：tools/python-v20.py tools/quality_python.py backend/tests/infrastructure/test_v20_windows_job.py backend/tests/infrastructure/test_v20_windows_process.py -q -p no:cacheprovider --tb=short --basetemp <项目.tmp专属目录>，配tools.quality_gate.environment，普通权限。162文件Ruff格式、git diff --check通过；所有夹具根／子进程及目录finally清理，无测试JSON／日志保留。

一手依据：[SetInformationJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-setinformationjobobject)、[JOBOBJECT_EXTENDED_LIMIT_INFORMATION](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information)、[JOBOBJECT_BASIC_PROCESS_ID_LIST](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_process_id_list)、[UpdateProcThreadAttribute](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)及Microsoft SDK的x64布局／属性定义。

剩余：原nonce持久STOP关闭／未知创建恢复、后端身份认证Pipe、完整受管进程创建器、控制方与Guard真实崩溃回收、LPAC／ACL／WFP／模型源证明、原步骤全部归属与CLEANUP仍需完成。显式关闭最后句柄的本轮证据不冒充真实Guard服务进程崩溃，active=0／根退出亦不单独证明整个任务停止。当前无可准入执行配置。
