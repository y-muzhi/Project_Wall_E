# Coding 角色创建原结果核对验证

日期：2026-11-11，master 28a7c9e、Schema200 db20-r44，正式设计原文与原摘要不变。依据 APP-CODE-HANDOFF／C38，独立迭代保留 pending。仅本轮隔离与离线，不更新用户服务／业务库、不调用模型或计数，不提交推送。

## 已实现和当前证据

C38 支持原 CREATE_SESSION 未知的只读观察：TaskNativeActions 原私有意图／回执、精确 metadata 和原策略查回，确认只完成原创建步骤并继续原 SEND_HANDOFF。没有原意图、策略变化、metadata 不同均不发创建或消息 POST。前端角色核对覆盖创建事实，原 RUNNING 结果按真实原操作类型读取，不能把创建成功写成角色交接完成。

通过 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short，test_v20_opencode_instance_control.py::test_created_session_reconciliation_reads_only_original_private_intent 四种参数 4 项通过（1.66 秒），真实本地 HTTP／NTFS 私有意图，原 POST 共一次、随后仅 GET。供应方会话／模型完成不是本项证据。

前端 npm run typecheck 通过；格式与三个原核对 Chrome 范围待后续验证。

## 完整联合

本轮较早 SUCCESSORGUARD2 的两个同角色替换／原角色链及停止会话范围，1 项通过（672.16 秒），见 coding-session-replacement-2026-11-11.md；该结果不包含本项新的角色创建 C38。

新增完整 Guard 场景：FRONTEND 原创建返回丢失，第一次 C38 未知、第二次确认原创建，随后原消息回执丢失、两次原 C38 至原角色完成，继续 INTEGRATION、修复、自检及发布／停止范围。首轮 203.41 秒退出，因原夹具每个角色仅推进 12 步，新增两次创建观察后需要第 13 次读取确认已完成；将该夹具推进次数调整 16，不改产品期限、资源预算或原生重试规则，重新联合中。尚未取得最终结果，不提前记通过。

## 完整联合最终结果

ROLECREATEGUARD2 最终 1 项通过（668.67 秒）。通过锁定 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short，在独占临时目录执行 test_v20_guard_control_git_transport.py::test_authenticated_project_check_transfers_input_runs_and_releases_original_job[PROJECT_CHECK_HANDOFF]。FRONTEND 创建实际离线夹具已生效但丢回复，第一次 C38 无法确认、第二次只读确认原创建；随后原 SEND_HANDOFF 丢回复，继续两次只读 C38 确认原消息并完成原交接。仍保持单次创建、单次发送和两次原 HANDOFF，继续双同角色替换、取消／再捕获／再次修复、真实三阶段受控命令、Testing 发布／复查及 STOP 会话范围。原受控项目命令／Guard、NTFS／MinGit、SQLite／ASGI 是实际隔离运行；原生会话／模型结果为定向夹具，非供应方验收。

前述每角色 12 步不足的首轮仅是失败记录，不替代本次最终通过；16 步只改夹具推进次数。原任务运行／命令超时和重试次数不变。16:38 npm run typecheck、npm run format:check 与 python -m ruff format --no-cache --check backend/app（475 文件）通过。四个创建／消息页面范围待后续 Chrome 专项，不提前记通过。

## 页面最终核对

已有 Playwright CLI／自有 Chrome、临时 Vite 构建和隔离 HTTP 的 role-creation-reconciliation 与 role-reconciliation 两专项均最终通过（每项 360／1280，先取消再确认，写入各 1 次），分别输出 V20_ORIGINAL_ROLE_CREATION_RECONCILIATION_PASSED／V20_ORIGINAL_ROLE_RECONCILIATION_PASSED。创建只显示继续交接，消息接收后才显示交接已完成；每次输出 OWNED_JOB_EMPTY_AND_BROWSER_OUTPUT_CLEANED。所有输出随自有 Job 清理。HTTP 为隔离夹具，非正常用户服务。

## 已有创建回执后的复核

新增 cached ACK 后策略／metadata 变化负向，保留原四参数并扩至六参数。CACHEDCREATEPROOF 通过同一锁定工具及自有临时目录，test_v20_opencode_instance_control.py::test_created_session_reconciliation_reads_only_original_private_intent 最终 6 项通过（1.93 秒）。已有私有创建回执仍对同一原 native ID 重新 GET；策略或 metadata 改变拒绝，原 session POST 始终 1 次，核对新增请求全部为 GET。未改生产流程或放宽比较。

扩大至整个 test_v20_opencode_instance_control.py 的 NATIVECONTROLFINAL 最终 45 项通过（6.19 秒），同一锁定工具／自有临时环境。原创建／消息／问题／权限、只读找回和同角色新作用域的真实本地 HTTP 合同保持通过；这是受影响原生控制范围回归，不扩展为真实模型或正式部署。
