# Windows Guard 仓库登记联通

2026-11-25（香港时间）。在 V2.11 事项 22 下继续修复实际 8001 的仓库登记。工作区基线为 `cd48227`，保留其他任务的本地改动。依据为[事项 22 修订 2](../../iterations/pending/v2.11/WALL-E.仓库登记服务部署迭代V1_V_2.11.md)。

- 实机对原 Guard 执行一次固定安装器的 SYSTEM 启停。普通后台打开其 PID 时，`PROCESS_QUERY_LIMITED_INFORMATION` 和 `SYNCHRONIZE` 分别返回 Windows 5。组合观察在打开进程阶段失败，未读取令牌。启动检查退出后，安装器负责停止原 Guard。
- 新 Guard 在报告 `SERVICE_RUNNING` 前对自身进程和主令牌保留原 DACL，追加清单账户的进程查询、等待和令牌查询权限。授予失败时拒绝就绪并关闭原载入资源，SCM 提供受限的失败阶段和错误码。普通后台仍按原路径认证 SCM PID、进程镜像、创建时间、SYSTEM 令牌和管道服务端。
- Windows 临时进程调用相同原生处理代码，实读 DACL 验证新增 ACE 分别为 `0x101000` 和 `0x8`，其他 ACE 字节及顺序相同，重复设置仍只有一条目标 ACE。该进程退出后已释放。临时进程测试不替代 SYSTEM 与普通后台的跨账户测试。
- `python -B -X utf8 -m pytest -q -p no:cacheprovider backend/tests/infrastructure/test_v20_guard_service_host.py`，首次 30 项通过，实际资源夹具未模拟新的 SYSTEM 专用步骤而超时。修正夹具后 31 项通过。改动文件 Ruff 格式和检查通过，全 `backend/app` 格式检查另报现有 `suggestions/review.py`，该文件不在本轮范围。
- 固定依赖构建的 Guard 新包清单 SHA-256 为 `43840ecfc1c4ae756d0253c0c6c4ef6de5269ac53c579c9be88aae7e11f9d86e`，526 个成员，包内运行时及完整字节探针通过。第一次构建由工具返回通用拒绝，重建通过，第一次拒绝原因未保留。
- 正常后台候选从 `cd48227` 和实际已发布的设计框架、上下文上限重建，沿用固定 `openai-v6` 及原静态入口。本地事项 20、21 与建议审阅改动不进入此候选。此条记录时 8001 尚未切换。

## 实际安装及第二处故障

- 后台候选清单 SHA-256 `66cdc1d6124b115f67540ce5d5a3677d69f37393546f4ed8f23a5970ec49b6ce`，2768 个成员。缩短构建输出目录后，Schema200、210 探针及 Schema210 隔离 HTTP 检查通过。一次长输出目录构建触发固定完整路径上限。
- `C:/Program Files/WALLE.V211.RepoFix` 已收到 `REGISTERED_STOPPED` 回执。安装器监督进程在登记后的 `inputs.verify()` 重新核对阶段超过时限，随后独立只读验证了同一部署文件摘要、实际 Guard 与后台完整成员和服务配置。没有重跑安装。
- 新 Guard 以 SYSTEM 启动（PID 42876），普通固定后台的 `--verify-guard` 验证进程、令牌和管道成功。随后隔离库登记操作返回 `UNKNOWN / EXTERNAL_RESULT_UNKNOWN`。SCM 事件 7024，停止码 `0xD7140000`，阶段 `SERVICE_LOOP`，内部 `ValueError`。
- 读取已安装的实际 PE 文件复现 `GIT_CONFIG_SOURCE_BYTES_UNSUPPORTED`。Guard 的后台包成员误用 `LockedConfigSource`，拒绝二进制内合法空字节。改用 `LockedFileSource` 并仅对清单保留原始字节，成员使用原生只读文件租约和流式 SHA-256。
- 后台包与 Guard 生命周期 62 项专项通过，包含带空字节成员的真实 Windows 读取及验证。固定 Git 真实本地管道的 CONFIG_PARSE、REGISTER、REGISTER_THREAD 共 3 项通过，保护包验证仍由该夹具的测试端口承担。实际 8001 仍为 PID 53528。

## 停止 V2.11 部署

- 用户计划直接使用 V2.2 独立环境，停止本轮 V2.11 部署。包含两处修复的新 Guard 清单摘要为 `0cb957dd38ae1c60750817dd75c5911001b2116ece69f967e689489d57aea02a`。已准备固定包，新的目标服务不存在，Program Files 目标未创建。
- 本轮曾启动的 `WALLE.V211.RepoFix` 已停止，PID 为 0。8001 保持原 PID 53528，未恢复生产登记。V2.2 接续时按该版本重新固化包并验证实际登记。

## 代码功能试用范围复核

- 用户询问可否先试用。实际 8001 的 `/settings/code`、仓库列表、文档 7 的代码任务列表均返回 200，两份列表为空。复核只读取现有入口。
- 固定 SQLite 与测试离线守卫下执行 `test_task_start.py`、`test_task_start_session.py`，11 项通过，临时目录已清理。首次测试缺少项目临时环境变量，未进入用例，随后按项目离线环境复跑。启动及会话检查使用隔离夹具，未实际发起代码模型调用。
- 已准备的最终 Guard 计划仅用于仓库登记，任务运行时、项目检查均未配置。真实 AI 改代码仍须配置独立工作区、正式执行器和模型授权。本次复核未安装或启动 Guard。
