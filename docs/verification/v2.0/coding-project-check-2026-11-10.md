# V2.0 Coding 开发自检的固定资源与 Windows 原执行边界

2026-11-09 至 11-10（香港时间），本地 master 28a7c9e 的 V2 实施工作区。依据为后端 0.17-draft-17 的 APP-CODE-CAPTURE／VERIFY、SHR-CODE-VERIFY-STAGE、OBJ-CODE-VERIFICATION 及 7.6.1—7.6.7，前端 0.16-draft-16 的 BND-CODE-CHECKS。两份设计摘要分别为 1a8d277f25de570ce72e74a73ff763bf73f622fcf94b61f0820b78a1a5c6fd37、38557cee854697044ab7daba30f694738429be1235264a153851e8fc808cf3a7。

| 专项 | 实际结果及边界 |
| --- | --- |
| test_v20_check_runner_bundle.py | 21 项通过。核对原登记 Runner 清单、原 NTFS FileID、大小与摘要、只读清单锁、额外目录／文件、硬链接、备用流、退出时闭包变化；资源闭包单独保存，需实际部署准入才允许执行。 |
| test_v20_windows_lpac_profile.py 的 CHECK 工作区及正常 TASK 回归、test_v20_windows_task_directories.py | 7 项通过。实际 LPAC 令牌读取固定副本，拒绝改写／删除／新增及读取原私有源，允许写独立 scratch。原内容变化报 INPUT_CHANGED。 |
| test_v20_guard_task_network.py、隔离 CHECK 环境、test_v20_opencode_runtime_bundle.py | 35 项通过。按 CHECK 专用 SID 封存 IPv4／IPv6 的六个阻断规则，不接受模型、转发、控制或应用端点。命令环境从原目录重建，继承配置、模型凭据、Node／Python 启动注入及代理不入检查环境。WFP 安装、读回和移除的组合为隔离夹具。 |
| test_original_offline_project_job_starts_and_reports_actual_exit | 实际 Windows LPAC／Job 专项 1 项通过。未证实 WFP 原派发时拒绝创建，原凭据模型入口拒绝 CHECK；受控夹具的 WFP 原事实就绪后，注册 PE 从挂起到恢复、真实退出 0、原 Job 空、原 STOP 读回及 profile 收尾通过。 |
| test_authenticated_project_check_transfers_input_runs_and_releases_original_job 的 PROJECT_CHECK／PROJECT_CHECK_REJECT | 2 项通过。实际后端进程、原只读句柄、认证命名管道、原副本及 LPAC Job、退出及输出摘要、五项原动作意图和回执、原清理。损坏输入无进程启动，原准备目录有清理回执，原源仍保留待核对。 |
| 同专项 PROJECT_CHECK_DURABLE | 1 项通过，103.35 秒。真实七项候选 Git 命令、NTFS 候选、原配置应用引用、原项目 CHECK、实际退出与停止／清理、原结果重放零额外写入、当前任务引用和 ASGI 的 API24／54 均核对。覆盖同候选详情与分页、空页、非法目的／重复页码 422、跨任务 404 和撤去准入后保留历史并返回 RESOURCE_NOT_READY。初始原生配置观察使用隔离夹具。 |
| 普通 TASK 的 execution_pipe_watch、CONFIG_PARSE、原模型入口前置及 Windows 输出捕获 | 普通 TASK 实际命名管道 1 项、CONFIG_PARSE 1 项、原模型入口前置和输出捕获联合 25 项通过。旧前置测试写 RUNNING 时补齐 schema 所需 started_at。 |

专项使用锁定 Python 的 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider，独占 Windows 目录、Job 和随机 AppContainer profile。系统 findstr.exe 带硬链接，首次固定程序校验明确拒绝。改为测试私有独立字节副本，仍执行同一固定程序摘要。首轮测试 profile 释放调用次序不正确，按已核实原 STOP 回执修正，并使用原生 API 清理单个精确随机测试 profile。原系统文件保留。

正常业务库、用户服务、真实模型或供应商未参与。真实 SYSTEM 安装下的 WFP 数据面和正式 Runner／项目资源发布另待验证。API50／51 仍待完整公开执行入口。独立 Testing、CHECK_DRIVER、CasePack、后续 Coding 角色及前端展示未纳入本轮实测。


静态核对：本轮后端应用目录 Ruff 格式检查 375 个文件通过，相关新增及修改后端模块的 Ruff 规则检查通过，Git diff --check 无空白错误（原前端测试文件另有 Git 行尾提示）。db20-r31 清单 39 个构建来源和 3 个资源摘要全部吻合，正式设计摘要及 Git HEAD 28a7c9e 保持。现场 5173／5174／8000 未监听，隔离专项走测试进程自有认证管道，无正常服务启动。


联合检查修正了夹具重复参数和检查数组序列化。发布清单中的 service.py 恢复原摘要，路由从已有注册后台读取准入引用。低测试预算曾在原 Guard PREPARE 后导致挂起创建回执超时，原 CHECK 持久为待核对。只提高联合夹具的任务及命令预算后复跑通过。早前普通 TASK 回归曾被误记为 SQLite 联合通过，本表以明确执行的三个项目测试节点为准。
