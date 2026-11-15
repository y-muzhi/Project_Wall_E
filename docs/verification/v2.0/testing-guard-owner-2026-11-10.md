# V2.0 Testing 原生 Guard 归属

2026-11-10 15:07（香港时间）。master 28a7c9e 本地工作区，Schema200 db20-r36。后端设计 7.6.4—7.6.7 与 7.9。

- 增加私有 WIN20-TESTING-CHECK-1。原 Testing owner、操作、控制代次、步骤、nonce 及控制方进入认证请求、私有账本、退出凭据、原文件传输和恢复选择。Testing 只能进入明确登记的离线项目检查，旧 Coding 运行协议及原持久格式保留。
- 锁定专项运行 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider，目标为 test_v20_guard_control_git_transport.py 中的 TESTING_PROJECT_CHECK／PROJECT_CHECK 及 test_v20_runtime_launch_journal.py。17 项通过。真实 Windows 私有 NTFS、认证命名管道、LPAC 根进程与 Job 完成原 PREPARE、挂起创建、恢复、停止、输入完整性复核及释放。相同操作和 nonce 的旧 Coding 协议、错误 owner、错误代次均不能观察或停止原 Testing Job。模型源动作在协议入口拒绝。
- 先前失败来自共用只读句柄复制层只允许旧 LaunchScope 精确类型。修复共用复制层并将 Testing 文件名绑定完整 scope 摘要后通过。配置专用入口仍限制原类型。
- 专项采用受保护资源夹具和模拟 WFP 登记／核对，真实 SYSTEM／WFP 安装、独立浏览器 CHECK_DRIVER、HTTP 自有端点及 Testing API28 正向另行验证。临时数据库、私有目录及自有进程由隔离专项回收。
