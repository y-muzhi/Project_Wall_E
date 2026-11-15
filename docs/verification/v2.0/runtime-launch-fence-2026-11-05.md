# V2.0 原nonce持久派发与停止屏障

日期：2026-11-05；HEAD 28a7c9e，V2未提交。仅自有项目.tmp及受控离线回调，无正常库、用户服务、Guard安装、模型或计数调用。

runtime_launch_journal.py已接真实OS锁、临时文件／fsync／原文比较／原子替换／读回及严格元数据。原控制方／operation／step／nonce绑定输入摘要；CREATE与RESUME先保存MAY_HAVE_BEEN_SENT再执行可信Native适配器，未知不重发。STOP在无PID时也封闭原nonce，创建先发生保留原资源，关闭先发生不派发迟到创建／恢复。重启先封闭历史nonce；记录缺失不证明未执行。同scope串行，不同scope停止独立；活动请求中不能释放OS锁。

实际命令：tools/python-v20.py tools/quality_python.py backend/tests/infrastructure/test_v20_runtime_launch_journal.py backend/tests/infrastructure/test_v20_windows_job.py backend/tests/infrastructure/test_v20_windows_process.py backend/tests/code_tasks/test_content_paths.py backend/tests/code_tasks/test_git_bundle.py -q -p no:cacheprovider --tb=short --basetemp <项目.tmp专属目录>，配tools.quality_gate.environment隔离。

最终98通过（3.14秒）：屏障15、Job与进程22、路径与Git包61。覆盖输入冲突、派发前持久事实、双顺序STOP、丢创建／恢复回执、元数据失败、重入停止、跨scope竞争、容量、重启关闭、损坏拒绝及原锁竞争。163文件Ruff格式、git diff --check通过。临时目录及自有子进程finally清理；一条既有Starlette弃用警告。

权限证据分开：默认工具实际为AppContainer。屏障IO／并发专项显式使用测试端口OrdinaryOwnedTestRoot，只替换PrivatePackageGuard，保留真实NTFS句柄／OS锁／持久IO；不证明owner-only DACL或非AppContainer操作者。未替换生产边界的专项确认AppContainer在锁／元数据写入前被拒绝。WALLE_TEST_GUARD_PRIVATE_ROOT=1可选择真实私有根，但本轮申请非AppContainer环境时自动审批服务返回HTTP403，未执行，不记通过。

Native创建／恢复仍为离线回调，未绑定生产Root启动器／Pipe认证。记录只证明Guard派发域与历史，不表示OS进程停止、整任务STOP／CLEANUP或LPAC／WFP准入；真实私有根正向、Guard崩溃、控制方退出及全链路后续验证。

后续实际补验：自动审批服务恢复后，以WALLE_TEST_GUARD_PRIVATE_ROOT=1在获准的非AppContainer环境执行屏障15项及私有包6项，最终21通过／6子场景（3.30秒）。本次使用真实PrivatePackageGuard／owner-only DACL／原OS锁与持久IO，全部自有临时包已清理。此前403为当时未执行事实，现正向权限缺口已补；Native回调仍离线，LPAC／Guard服务／完整停止不因此完成。
