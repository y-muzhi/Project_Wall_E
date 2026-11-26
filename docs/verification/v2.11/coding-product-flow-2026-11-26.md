# WALL-E 正式代码任务核对

2026-11-26，香港时间。V2.11 事项 22 修订 6。验收目标为 WALL-E 自身的仓库登记、固定基线、代码任务发起与执行、候选确认及 Git 交付。独立交付样例不计入本次产品验收。

## 8001 实际业务接口

- 只读确认桌面 `coffee-mini` 目录为正常 SHA-1 Git 仓库且已有 HEAD。8001 查原登记幂等键，HTTP 200、`NOT_FOUND`。以同一键、名称与目录重试真实 `POST /api/v1/code-repositories`，HTTP 503、`CONFIG_NOT_READY`，能力码为 `Q20-WINDOWS`、`Q20-GIT`。仓库仍未登记。
- 正式仓库、执行配置、检查集、授权列表均返回 200 和空列表。配置选项目录中 EXECUTOR、PRICE、CAPABILITY、RUNTIME 均为 0。GIT 1 项未就绪，MODEL 3 项均缺 `Q20-MODEL`。系统服务读取时已安装的 WALL-E Guard 均停止，最近验证过的 RepoHold 部署清单的 task、runtime 和 checks 均未配置。8001 当前为普通 OpenAI 启动器，观察时监听 PID 51052。未重启或切换。
- 静态复核 `code_configuration_catalog.py` 的初始目录只接受固定的 Git、模型身份、内容策略和读范围，拒绝其他目录条目并禁止 ready=true。`execution_profile_resources.py::readiness` 固定包含 `Q20-MODEL` 并返回 ready=false。当前发布缺根据真实执行部署、经验证的模型和价格证据生成可用配置的入口。单独启动已有登记 Guard 不会解决后续任务 START。
- 本轮在当前发布没有进入固定快照、任务创建、任务 START 或候选／Git 交付，也未调用真实供应方。独立业务 API 专项两次因未激活固定 SQLite 在初始化失败，显式激活后该试验进程未产出结果并已退出。以上 8001 回执为实机结果。

## TASK 权限修复及验证

- 按[修订 6](../../iterations/pending/v2.11/WALL-E.仓库登记服务部署迭代V1_V_2.11.md)实施。Coding TASK 固定 `registryRead`，通过既有令牌创建和精确 SID 核验，SYSTEM 必须在任务运行证据中核对同一能力。缺少能力字段或加入未批准额外权限的证据会被拒绝。普通项目检查及浏览器驱动保留各自原能力选择。正式已安装包和现有服务尚未替换。
- 普通 Windows 身份执行 `python -B -X utf8 -m pytest -q -p no:cacheprovider --tb=short`，范围为 `test_v20_guard_task_deployment.py`、`test_v20_windows_lpac_profile.py::test_native_task_launch_uses_original_job_and_durable_fence`、`test_v20_windows_lpac_profile.py::test_original_offline_project_job_starts_and_reports_actual_exit` 和 `test_v20_browser_lpac_policy.py`。42 项通过，覆盖实际隔离令牌、原 Job、准入绑定和检查执行边界。`python -m ruff format --no-cache --check backend/app` 通过，修改的三个实现文件 Ruff check 通过。
- 接续以当前实际入口为准。先将受信登记部署与实际后台程序身份绑定，在当前正式入口核对在途后部署。完整任务仍需执行受管网络的实机正负探测、发布可引用的执行器与准入证据、建立实际 Coding 模型使用和价格准入、再跑同一任务从固定基线至 Git 写入。禁止把目录标签或隔离试验当成生产准入。
