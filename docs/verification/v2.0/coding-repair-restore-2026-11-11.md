# C59 现存变化文件恢复验证

日期为 2026-11-11，原 master 28a7c9e 工作区，当前 Schema200 db20-r44。依据 BE APP-CODE-REPAIR 和 SHR-CODE-SINGLE-WRITER。仅使用隔离 NTFS、SQLite／ASGI、固定 MinGit 及自有测试进程；用户服务和业务库未更新。

## 文件与原请求

同路径同模式的变化文件经完整预检和原写入者静止核对后，固定原文件句柄并拒绝其他写入／删除共享；先持久保存私有意图，再在原 REPAIR 与 STOP 栅栏内无覆盖移动到原 scratch，核对 File ID 和流。随后读取固定包补回原候选，全工作区再次核对且保留文件句柄到原发送意图。恢复文件仅在本任务 scratch 保留，生命周期跟随本任务运行资源清理。

移动不确定时，不重新移动。只从原私有意图和原保存文件核对位置、File ID、大小和摘要，补原 ACK；已有 ACK 逐字匹配。原内容或身份变化会停止处理。额外产品文件、模式差异、目录冲突及不安全文件系统节点仍会阻断。

## 已执行

- 锁定 Python 经 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider，目标 test_v20_task_repair_file.py。最终 9 项通过，覆盖原移动、原文件后续变化、占用、STOP、移动后丢回执、重复观察和保存字节被改动。原生句柄和文件均为实际 NTFS。
- 原修复和原生文件联合 12 项通过。实际 test_task_capture_quiescence.py::test_original_capture_runs_fixed_git_and_recovers_without_source 从固定 MinGit 封存包、真实 HTTP 缺陷／C59、现存字节变化恢复到 SQLite 排入原消息意图、保留原变化字节，1 项通过。原写入者静止和原生发送仍为定向夹具。
- Ruff 471 文件格式及变更生产模块 lint、git diff --check 通过。测试使用自动清理的临时目录。原捕获、私有回执、原修复和文件专项联合最终 35 项通过，耗时 254.65 秒；原私有回执文件命名白名单及其余既有行为保持通过。随后增加归档路径长度预检和私有结构校验后，相关 9 项再次通过。上述范围有交叉，不累加为产品验收数量。

## 未覆盖

正式 Guard 及实际 OpenCode／供应方没有执行。额外文件和路径冲突的恢复、同角色新会话及完整真实修复到新候选仍待完成。今日 8000／5173／5174 无监听。

## 13:22 接续批次（执行中）

新增完整的私有恢复清单：第一次变动前固定所有变化文件及额外产品文件，绑定原 REPAIR、候选和封存摘要。中断后逐个核对原保存文件，未移动的原文件必须与原清单的身份和字节完全一致。额外产品文件可移入原 scratch；文件占住候选目录名时使用完整命名空间投影预检，真实目录冲突仍阻断。排除内容不移动。

当前锁定 Python 经 tools/python-v20.py tools/quality_python.py 运行 test_content_paths.py、test_task_repair_source_plan.py、test_v20_task_repair_file.py，57 项通过（2.05 秒）。Ruff 472 文件格式、变更模块 lint 和 git diff --check 通过。真实 MinGit／NTFS、HTTP／SQLite 两场景仍执行；另新增首个移动完成但 ACK 未写时退出的同操作重入，待验证。未将这些结果记作正式 Guard 或真实模型验收。

## 接续第二批实际结果

- 两种实际恢复场景和原修复联合最终 6 项通过，305.22 秒。命令目标 test_task_capture_quiescence.py::test_original_capture_runs_fixed_git_and_recovers_without_source 和 test_task_repairs.py。
- 上述场景新增移动后、ACK 前退出，再以同一原操作重入，单独 1 项通过，123.96 秒。继续扩到离线原生完成后，使用实际 SQLite／ASGI、MinGit／NTFS 捕获唯一新候选，旧候选不变，旧报告和交付计划资格清除，自检尚未执行，单独 1 项通过，175.16 秒。均通过 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider，在自有临时目录执行并清理。
- 清单严格字段、原路径及原生文件 63 项通过；test_content_selection.py、test_content_manifest.py、test_v20_candidate_workspace.py、test_v20_windows_private_record.py、test_task_role_chain.py 的关联 118 项通过。结果与前面范围有交叉，不累计为产品验收总数。
- 加入既有 PROJECT_CHECK_HANDOFF 的真实 Guard／项目命令联通：已完成三阶段后明确修复，再捕获、复查三个阶段、Testing 发布及停止；正在执行，未提前记通过。模型发送／完成仍用离线夹具，没有供应方调用或 SYSTEM 安装。
- 本轮临时产物 cleanup-test-artifacts.py --dry-run 显示 JSON=0、screenshots=0。

## 接续第三批：互斥修复与页面

三阶段 Guard 扩展首次执行失败（295.28 秒）：启用修复资源后，原交接中的 task detail 在读取未完成角色来源时返回 STORAGE_UNAVAILABLE，尚未进入新增修复。修复 task_repairs.py，先查询除可安全撤销的原待交付外的活动操作，资格与正式接收均互斥并关联原操作。原修复 HTTP／SQLite 最终 4 项通过（85.96 秒）；初次专项夹具试图删除原操作，被 HISTORY_MUST_BE_RETAINED 拒绝，改为记录 CANCELLED，未移除历史。

三阶段第二轮在首个项目命令的 CREATE_SUSPENDED 原管道读期限失败（160.96 秒），没有新增修复证据；正在不并行重型检查的情况下串行复核。未放宽程序运行期限、Stop 或 Guard 规则，未把本轮失败写成通过。

前端修复占用原因按独立 pending 迭代补正。npm run typecheck、npm run format:check 通过。通过 tools/python-v20.py tools/verify-v20-command-recovery.py --cli-entry <本机已安装 CLI> --probe coding-delivery，以实际 SPA／Chrome 和隔离 HTTP 核对 360／1024／1280／1920、禁用占用、取消保留、原请求单次提交。首轮将本地原请求待核对错当成其他操作占用，导致夹具断言超时；拆为独立 busy 场景后最终 V20_CODING_DELIVERY_PASSED，writes=1，OWNED_JOB_EMPTY_AND_BROWSER_OUTPUT_CLEANED。前端其他操作占用提示和原请求待核对提示仍分开，没有触发真实修复模型。

原生／清单来源绑定补验 7 项通过，覆盖原剩余文件 NTFS ID 变化与已移动文件绑定不同原条目时拒绝；Ruff 472 文件格式及变更生产模块 lint 通过。后端没有浏览器／供应方效果主张，前端没有真实 Guard 效果主张。

## 接续第四批：三阶段 Guard 联合完成

- 经 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider 执行 test_v20_guard_control_git_transport.py::test_authenticated_project_check_transfers_input_runs_and_releases_original_job[PROJECT_CHECK_HANDOFF] 最终 1 项通过，555.44 秒。范围为真实隔离 Guard、受控 MinGit、原项目命令及 SQLite／HTTP；按两次真实原交接到三阶段后，C59 单次发送（模型为离线夹具）、新候选、三阶段自检、Testing 发布／重查及原停止均完成。未新增完成角色，原会话数量仍 3。与正式 SYSTEM／WFP、真实 OpenCode／供应方及独立 LPAC 浏览器报告分开。
- 串行第三次已到新 C59，但新增夹具使用 msg_repair_checked，因不符合原生身份格式返回 CONTENT_NOT_READY，451.74 秒。独立 ModelWindow 确认 ORIGINAL_MODEL_NATIVE_ASSOCIATION_REQUIRED；第四次诊断运行在已明确该夹具缺陷后取消，核对专属 PID 和 Job，外层临时目录已自动清理。改用 OpenCodeMessageIds 后最终通过；没有削弱原生身份校验或放宽产品期限。
- 本日真实封存包流程追加 C30 读取旧候选的 original bytes 和新候选的 corrected implementation，并读取公开修复 source／result 历史，1 项通过，193.14 秒。读的是实际私有候选包，非固定 HTTP 内容返回。
- 私有恢复清单规范序列化补验 8 项通过，1.34 秒，包含数值绑定 81.0 不能冒充整数操作 81；另有 NTFS 原 ID、剩余来源和保存文件绑定核对。

## 接续第五批：原生取消恢复（执行中）

新代码将已确认原生取消与未发送区分：原始 QUIESCE 观察及发送绑定保存后关闭窗口，原修复和后续捕获取消，保留原候选，只接受新的明确动作。资格专项最终 1 项通过，22.75 秒，错误代次不取得资格、错误原消息拒绝。初次用仅含元数据的候选夹具读取完整详情，因缺少实际捕获步骤失败；改为资格层专项与实际封存包详情分开检查。随后定位取消步骤 ended_at 缺失，修正已观察步骤结束时间，未开始捕获仅记取消／结束，不伪造开始时间。

当前实际封存包／详情页与原修复、继续、角色链联合仍执行中，未计通过。Ruff 473 个生产文件格式和变更模块 lint 通过。独立规则保留于 pending 迭代，不合入正式设计；没有真实模型／计数 API 或用户服务操作。

## 原生取消已取得的范围

- 新的原生取消资格专项 1 项通过（22.75 秒），实际 NTFS／固定包、HTTP／SQLite 的 cancelled-turn 参数 1 项通过（125.99 秒）。取消后任务详情正常读回，当前候选未替换，QUIESCENT 时间来自本轮 REPAIR 的原 QUIESCE，原操作及捕获为 CANCELLED，新的明确修复可接收。纯元数据夹具仅证明资格及错代次／错消息拒绝，不作完整详情证据。
- test_task_repairs.py、test_task_resume.py、test_task_role_chain.py 联合 27 项通过（201.89 秒），含共享步骤取消 ended_at、原消息未知／C38、STOP 及角色来源。锁定 Python 经 tools/python-v20.py tools/quality_python.py，无真实模型调用。
- coding-delivery 真实 Chrome 再次通过：取消原进度被读取并结清本地原请求，原历史显示已取消，无“本次修复未发送”误述；重新选择缺陷、打开新确认框并取消，全程原修复 POST 仅 1 次。取消历史在 360／1280 检查溢出，既有交付检查维持 360／1024／1280／1920。输出为 V20_CODING_DELIVERY_PASSED／OWNED_JOB_EMPTY_AND_BROWSER_OUTPUT_CLEANED。
- 后续追加的“取消后新的 C59 实际完成到新候选／C30／双历史”和扩展 Guard 三阶段重试链仍在执行或待执行，不提前记通过。正式供应方、SYSTEM／WFP、独立 LPAC 浏览器和新同角色会话仍未覆盖。

## 接续第六批：明确重试完成及取消后再捕获

- 实际封存包／NTFS、MinGit、SQLite／ASGI 的 cancelled-turn 场景已完整到新的明确 C59、单次原消息发送、新候选、C30 旧新精确字节与两条不可变修复历史，最终 1 项通过，179.50 秒。使用 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider，目标 test_task_capture_quiescence.py::test_original_capture_runs_fixed_git_and_recovers_without_source[cancelled-turn]。首轮在业务已完成后因夹具将历史倒序理解成正序失败（165.74 秒），改按 operation_id 关联原历史，程序排序未改。
- 扩展 PROJECT_CHECK_HANDOFF 首次加入取消后重试，在 678.01 秒被原外层 650 秒总预算终止，无最终成功标记，不计通过。新增多次捕获和真实三阶段自检后，专项任务与外层预算配套改为 1200 秒；产品原命令、Guard 管道和停止期限未放宽。
- 再扩到取消后用户明确捕获当前代码，再明确登记新候选的缺陷并发起新的 C59。当前 task_cancelled_repair.py 必须验证新捕获同会话／代次／原取消消息／工作区的实际 QUIESCE，摘要使用新捕获时间，旧缺陷不能直接用于新候选。task_records.py 对原 CANCELLED 修复的审计重读先核对完整原静止证明，沿原事件身份去重，不授予原消息重新派发权。
- 最新完整 Guard 联合已加入非空原生消息审计与取消后再捕获，正在串行执行，未计通过。自检及 Git 使用真实受控命令，原生模型发送／完成仍为离线夹具；当前不宣称真实供应方、独立 LPAC 浏览器或 SYSTEM／WFP 验收。

## 接续第七批：扩展 Guard 联合通过

最终命令仍经 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short，目标 backend/tests/infrastructure/test_v20_guard_control_git_transport.py::test_authenticated_project_check_transfers_input_runs_and_releases_original_job[PROJECT_CHECK_HANDOFF]。最新 1 项通过，809.12 秒；隔离目录 walle-v20-GUARDRECAP-* 已不存在。

本轮范围含原 BACKEND→FRONTEND→INTEGRATION、普通明确 C59、新候选三阶段复查、原生取消、明确再捕获和三阶段复查、旧缺陷跨新候选拒绝、新缺陷与新 C59、新候选三阶段复查，最后 Testing 发布／重查及原 STOP。非空原取消消息在再捕获后按原事件读取仅一条，原角色链仍三会话、两次原交接，没有虚构新完成阶段。受控 MinGit、项目命令、Guard 管道及 SQLite／HTTP 为实际隔离运行；原生模型发送及完成仍是离线夹具，没有真实 OpenCode／供应方、SYSTEM／WFP 或独立 LPAC 浏览器合格报告的新增结论。

Ruff format --no-cache --check backend/app 及本批五个测试／辅助文件共 478 文件通过；变更生产模块和新增 v20_coding_repair_worker.py 的 Ruff lint 通过，git diff --check 通过（既有前端测试换行提示不涉及本批源码写入）。额外将旧测试文件纳入全规则 lint 时暴露 51 项既有及测试夹具规则问题，包括导入夹具 F811、旧分支 current 未定义及导入排序；未将其称为全测试 lint 通过，也未扩改其他任务分支。本批辅助文件新增导入组空行已原子修正。

最终只读现场：master 28a7c9e，git status --short 为 417 行（展开所有未跟踪文件则 1509 行，两者统计口径不同），原其他任务改动保留。BE／FE 摘要与文首基线相同。8000／5173／5174 均无监听；GUARDRECAP／GUARDRETRY／REALRETRY2／已取消 REPAIRCHECK4 专属临时目录均为零。cleanup-test-artifacts.py --dry-run：JSON=0、screenshots=0。未更新用户服务、未写普通业务库、未提交／推送或付费调用。共享原消息审计／静止边界关联补验最终 5 项通过，74.97 秒：test_task_capture_quiescence.py::test_only_original_native_turn_and_guard_may_record_quiescence 的四种参数，加 test_task_repairs.py::test_repair_request_recovers_original_send_and_reserves_one_new_capture[native-cancelled]。覆盖原消息事件去重／安全展示、错误回执、读取期间版本变化、未知操作及取消资格；结果不与前面交叉范围累加。
