# V2.0 Testing 快照与原验证组

2026-11-10 15:42（香港时间）。BE 7.2、7.6、APP-TEST-ASSETS／RUN、API19—21／28。Schema200 db20-r37。

- tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider 运行认证 Guard TESTING_SNAPSHOT_CHECK／TESTING_PROJECT_CHECK／PROJECT_CHECK 与 test_testing_cli_run.py，共 5 项通过。实际 Windows 命名管道、LPAC、Job、原停止、清理及固定输入复核。快照测试中的原文件流来自固定夹具，正式 MinGit 原查询仍需联合。SYSTEM／WFP 准入使用隔离夹具。
- 相同命令运行 test_testing_cli_run.py 的验证组隔离专项，1 项通过。真实 ASGI／SQLite 与已保护参考目录，Git 登记由明确夹具固定。原 C19 同键仅创建 1 组，正／正／负／负 4 个孩子顺序固定。无运行资源时所有孩子得到真实未执行报告，组 UNAVAILABLE，C21 禁止发布。没有模型或正常服务参与。

## 16:25 原生正负联合

真实 MinGit 登记两份固定提交，API19 的原分配依次执行正参考两次与负控制两次。每个子任务实际读取原登记树、进入独立 Windows LPAC／Job 并保存两份受控退出事实。四份报告顺序为 PASSED／PASSED／FAILED／FAILED，实际退出为 0×4／1×4，八例均有原命令证据。验证组 PASSED 后原 C21 明确发布同一测试包。模型调用数为 0。

实际命令为 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider backend/tests/infrastructure/test_v20_guard_control_git_transport.py::test_authenticated_project_check_transfers_input_runs_and_releases_original_job[TESTING_VALIDATION_GROUP]，1 项通过，699.23 秒。早先两次观察到原回复未核清，未保存通过或发布。当前使用独立 WFP／安装准入夹具，Windows 管道、Job、ACL、快照、断言和 SQLite 为实际执行。

## 16:56 原结果丢失与未派发继续

同一认证管道专项的 TESTING_VALIDATION_RECOVERY 单独覆盖一个正向参考子任务，Schema200 db20-r41。实际第一例已取得原停止和清理证据，在写 SQLite 结果前注入一次丢失。任务进入 WAITING，原命令 UNKNOWN，第二例仍 PENDING。C32 按原 Guard 范围核对，后台从原私有结果补写第一例。C30 保留同一原 RUN_TEST 和命令 ID，仅允许第二例首次派发。两例真实 PASSED，保存该子任务唯一 PASSED 报告。测试进程、原 Job 和私有输出清理通过。

同上命令选择 [TESTING_VALIDATION_RECOVERY]，1 项通过，324.08 秒。此前把故障恢复并入整组的尝试，在后续负向子任务的原 RESUME 收到 JOB_MEMBER_LIMIT_CONFLICT，整组未取得新的发布证据。16:25 的无注入整组发布证据单独保留。Windows Job 成员计数间歇冲突仍待定位，未放宽成员、停止或清理验证。
