# Coding 修复创建原结果核对验证

日期：2026-11-11，master 28a7c9e、Schema200 db20-r44。BE 0.17-draft-17／FE 0.16-draft-16 的既有摘要不变，独立迭代仍保留 pending。源码均同目录临时文件、fsync、原字节比较及 os.replace。仅自有临时库／NTFS／HTTP／Chrome；无真实模型／计数、正常业务库写入、用户服务或 SYSTEM／WFP 更新、提交／推送。

## 本单元行为

C38 在原 REPAIR 创建未知、SEND_REPAIR 尚未登记、精确替换记录和唯一原等待均完整时，只读原创建意图与 metadata／策略。确认只保存原目标 native ID 并继续原恢复步骤，不派发消息，不改旧操作 session／generation，不宣告新候选或修复完成。后续原 worker 必须重新核对原 Guard／消息和实际字节，锁到发送意图。原消息 C38 保持原独立分支；STOP 抢先阻断核对。

前端读取原 REPAIR 最新事实，区分原创建已核实且发送 PENDING、发送仍未知、原消息已确认，以及读详情时已完成／取消／失败。C38 的 RUNNING 快照不覆盖后续实际终态。

## 实际专项及相关回归

统一使用锁定 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short，并由 tools.quality_gate.environment 在自有 TemporaryDirectory 下运行，结束确认目录已删除。目标模块位于 backend/tests/code_tasks/。

- REPAIRCREATEEXPLICIT：test_task_capture_quiescence.py::test_original_capture_runs_fixed_git_and_recovers_without_source[archived-session-create-reconcile]，连同 test_task_repairs.py、test_task_resume.py、test_task_start_session.py、test_task_runtime_stop.py、test_task_session_replacement.py、test_task_role_chain.py，最终 60 项通过（349.86 秒）。包括实际 NTFS／MinGit 来源恢复、新候选／C30／历史、SQLite／ASGI 接收和已共享的原继续／启动／停止／角色范围；原生创建／完成为定向离线夹具。
- REPAIRCREATEBOUNDS：上述同一函数的 archived-session-create-reconcile 和 archived-session-create-reconcile-stop 两参数，最终 2 项通过（196.48 秒）。创建已生效后丢响应，第一次显式 C38 仍 UNKNOWN、第二次原 ID 读回后 RUNNING，原创建共 1 次且均未发送。停止在 C38 接收后优先，核对和修复推进均不再触及原生读取或发送。本次 stop 只证明接收与栅栏，最终清理另扩专项。
- 原生创建只读身份／策略的真实本地 HTTP 四参数证据另见 coding-role-create-reconciliation-2026-11-11.md；原两次同角色替换及角色交接完整 Guard 联合另见 coding-session-replacement-2026-11-11.md。不将不同证据混成真实供应方验收。

## 页面和静态

已有 Playwright CLI／自有真实 Chrome、临时 Vite 构建和隔离 HTTP：repair-creation-reconciliation、repair-reconciliation、repair-settled-reconciliation 最终均通过，360／1280、取消后确认、单次 POST；创建核实不误报消息已确认，原 C38 RUNNING 但原修复随后 SUCCEEDED 时显示查看新候选与后续检查。对应 V20_ORIGINAL_REPAIR_CREATION_RECONCILIATION_PASSED、V20_ORIGINAL_REPAIR_RECONCILIATION_PASSED、V20_ORIGINAL_REPAIR_SETTLED_RECONCILIATION_PASSED；均有 OWNED_JOB_EMPTY_AND_BROWSER_OUTPUT_CLEANED。最后终态文案调整后已复跑三项，不是沿用更早结果。

npm run typecheck／npm run format:check 最终通过。strict 先指出数组索引可能缺失，已用明确步骤缺失错误处理，未关闭检查或使用 any。node --check 两个相关 mjs 通过。前端原请求／恢复模型两个 Node 文件 12 项通过。后端 475 个生产文件 Ruff format 和本批生产模块 lint 通过。额外检查既有大型 test_task_capture_quiescence.py 的全文件 lint 仍有 20 项（包括显式 pytest fixture 导入和参数重名、旧闭包／with 写法），未记录该检查通过，也未自动移除 fixture 导入。

## 未覆盖

真实 OpenCode／模型、旧实例丢失或无法证明旧写入者静止、正式 SYSTEM／WFP／独立 LPAC 浏览器与完整真实 C64 产品交付仍未验证。最终 TASK 原生停止和清理不是前述只读核对／夹具的证据。

## 创建未知后原停止和隔离清理

将 archived-session-create-reconcile-stop 继续接原 advance_owned_stops，真实 SQLite／ASGI 与 NTFS 的原工作区回收，Guard STOP／RELEASE 回执使用既有 StopDriver 定向夹具。首次 77.44 秒因新增夹具时钟使用 +00:00 而非 Schema 严格 Z 时间格式失败；只修正夹具时钟序列化，不改产品时限或 Schema。REPAIRCREATESTOPCLEAN2 最终 1 项通过（78.95 秒）：创建已生效但未读回的目标 native ID 仍未知；STOP 的优雅中断为 NO_VERIFIED_SESSION，仍按原实例停止／清理；待执行 C38 与原 REPAIR 取消、任务 TERMINATED、cleanup VERIFIED、原工作区回收、外部原来源字节保留，原创建 1 次、读取／消息 0 次。此证据证明隔离状态及 NTFS 收尾，不扩大成真实 TASK 原生停止证明。

## 本轮最终静态与现场

本轮修改时间范围内 20 个生产模块 python -m ruff check --no-cache 全部通过；后端 475 文件格式、前端 strict／Prettier 及 Git diff --check 均通过。旧角色专属入口名字已检索，无生产／工具残留。两份设计原字节 SHA256 与开轮相同，HEAD 仍 master／28a7c9e。当前进度和 pending 索引链接已核对，长过程按文档规则归档并保留归档前摘要。cleanup-test-artifacts.py --dry-run 为 JSON=0／screenshots=0；自有原生／浏览器临时目录和原子写入临时文件均为 0。没有更新用户服务或业务库。

最终扩大格式检查至 backend/app 及本批五个相关 Python 测试／辅助文件，共 480 文件通过。新 cached ACK 后的原策略／metadata 负向和原生控制全模块 45 项／6.19 秒通过，详见角色创建核对验证；这些共享用例有交叉，不与 60 项等相加计算完成率。
