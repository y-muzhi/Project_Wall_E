# 独立 Testing 的原 HTTP 端点与夹具验证（2026-11-10）

按后端设计 7.6.4—7.6.7 与 APP-TEST-RUN 核对。隔离工作区以 master 28a7c9e 为底，当前实施源码及 db20-r38 起的接续版本。

- Windows 真实 TCP 归属专项通过。实际隔离进程处理固定 POST，检查监听 PID、当前进程创建身份和已连接双方的反向 socket 归属。外来监听和无法证明的 Job 在业务字节前拒绝。302 仅作本步实际状态，未跳转至正常端口。截断的原响应保留 UNKNOWN，未发后续步骤。与 CLI、报告及网络策略扩大回归共 42 项通过。
- 真实 Windows Guard／LPAC／Job 的 HTTP 联合在项目 Node 初始化时收到 Winsock 10107，实际已保留原启动与受控停止／清理，HTTP 原账本记录 UNAVAILABLE、零原请求步骤、零断言结果；未修改系统网络准入。当前只证明此主机的安全不可用路径。实际应用成功绑定、生产 SYSTEM／WFP／回环部署、多个真实应用之间联通待独立验证。
- Windows 固定夹具、70,000 字节 STDIN 和现有 Coding 受控命令联合 3 项通过。Guard 验证登记夹具摘要及完整文件闭包后，将正文单独物化到原只读 basis，真实 LPAC 命令读取该副本并产生正确摘要。项目输入和固定夹具在启动、恢复及释放前分别核对。夹具原包和原候选保持原字节。
- 命令使用 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider，范围为 test_v20_owned_check_http.py、test_v20_guard_task_network.py、test_v20_windows_lpac_profile.py、test_testing_cli_run.py、test_testing_report_api.py，以及 test_v20_guard_control_git_transport.py 中 TESTING_HTTP_CHECK／TESTING_FIXTURE_CHECK／TESTING_STDIN_CHECK／PROJECT_CHECK。部署与 WFP 采用隔离准入夹具，未调用真实模型，未开启正常服务，临时原生目录和 Job 由专项回收。
