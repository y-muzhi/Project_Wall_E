# Coding 同角色会话替换验证

日期：2026-11-11，master 28a7c9e，Schema200 db20-r44；BE 0.17-draft-17／FE 0.16-draft-16 摘要沿原基线。只修改当前工作区、隔离测试及 Markdown；不更新用户服务、业务库或真实模型／计数，不提交／推送。

## 范围与不变量

依据 APP-CODE-REPAIR、SHR-CODE-SINGLE-WRITER、TC20-96 和 pending 同角色会话替换迭代。归档旧会话只有同一原消息／Job／Guard／工作区已核实静止才可退役。原 REPAIR session_id 和 control_generation 不变，创建新同角色会话及递增代次的授权保存在原 RESTORE_SOURCE 不可变 external_identity；确认创建和来源恢复后才形成新模型窗口。旧／新候选与原角色交接保留；新候选必须重查，不继承旧报告。

## 已执行

通过 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider 在自有临时目录执行 test_task_session_replacement.py 和 test_task_role_chain.py，20 项通过（1.10 秒）。新增来源读回覆盖错代次、错角色、旧窗口篡改、Guard 变化、缺少静止证明、候选不符、原生 ID 冲突、创建未完成和浮点身份，原角色链仍保持通过。纯 SQLite 读取证明不作真实原生创建或模型效果证据。

## 正在执行与未覆盖

新运行路径已接 reserve_repair_session／advance_repair_session、共享 SuccessorSessionScope、TaskNativeActions 原意图、模型入口和捕获记录，均原子保存。原修复及原生控制关联正在运行，真实 NTFS／MinGit／SQLite／HTTP 的已归档同角色替换到新候选场景刚加入，尚未计通过。旧实例丢失、无法核实旧写入者、正式 SYSTEM／WFP、独立 LPAC 浏览器与真实供应方均未覆盖。

## 第二批：原流程及实际 HTTP

- 原修复、来源读取、原角色链及原生控制联合 51 项通过（85.59 秒）；目标 test_task_repairs.py、test_task_session_replacement.py、test_task_role_chain.py、test_v20_opencode_instance_control.py，经同一锁定 Python／quality_python 执行。最初命令误引用不存在的 test_task_model_ingress.py 未执行任何测试，纠正目标后取得上述结果。
- 新增原生 HTTP 9 项最终通过（2.59 秒）：原 REPAIR 步骤 1 的独立私有作用域可以创建与首次投递，分别丢失回执后只读原身份，POST 各 1 次；归档／未归档／缺少 time、busy、pending、metadata 不同、Guard 变化及非整数归档时间分开核对。首轮暴露既有计划消息的私有文件名白名单缺 initial-planned，已精确增加这一项，不放宽 session-planned 等其他命名。
- 固定 OpenCode 原 OpenAPI 的 Session.time.archived 和 PATCH time.archived 已只读核对；程序只接受正安全整数归档时间，归档不证明静止。来源为 [固定原文](https://raw.githubusercontent.com/anomalyco/opencode/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/sdk/openapi.json)。未访问真实运行实例或模型。
- 实际 NTFS／MinGit／SQLite 场景前两轮分别暴露预留时关联修复状态未与操作同步（112.20 秒），以及 PREPARING 目标被详情的原角色检查提前拒绝（98.73 秒）。已在同一事务同步状态，详情只对完整验证过的进行中替换保留原修复进度；确认后 BACKEND 沿不可变替换链追溯原 START。第三轮已进入首次发送，但新增夹具漏 ModelWindow 导入（82.93 秒），补齐后重跑中，未提前计通过。生产运行器仍在进行中。

## 第三批：实际来源恢复到新候选通过

通过 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short，目标 test_task_capture_quiescence.py::test_original_capture_runs_fixed_git_and_recovers_without_source[archived-session]，最终 1 项通过（124.42 秒）。实际 NTFS 保留变化／额外文件并恢复原候选，SQLite／HTTP 接原不可变 C59，旧 BACKEND 会话退役、同角色新会话与新代次单次创建／发送，原操作 session_id／control_generation 保持，角色链仍只有 BACKEND。完成真实 MinGit 新候选封存、旧新 C30 精确字节与原修复 source／result 历史；新候选自检仍需后续执行。

完整 PROJECT_CHECK_HANDOFF 已将首个明确修复扩为 INTEGRATION 同角色替换，再接原取消／再捕获／再次修复分支、真实三阶段命令、Testing 发布／复查与 STOP，正在串行执行。该项未取得结果前不计通过；原生创建／消息仍用定向离线夹具，原私有意图回执另由真实 HTTP 9 项证据覆盖。

## 第四批：停止范围及页面未知状态

新 STOP 来源遍历同时纳入原两次角色交接和同角色 REPAIR 创建记录，保留全部旧新会话，不把第四个会话算第四个角色。已确认、创建未完成、创建未知和无关会话专项连同原来源／角色链 24 项通过（1.22 秒）。完整 Guard 第一轮在旧 STOP 遍历缺少替换时失败（617.20 秒），前序替换／候选／三阶段自检／发布已执行，整体不记通过；该进程导入的是修复前 STOP 实现。新遍历及末端四会话／停止代次 5 的夹具将重新联合。

前端 unknown 提示按 pending 迭代改为原修复“操作”结果待核对，覆盖尚未发送的创建未知。npm run typecheck、npm run format:check 通过；已有 Playwright CLI＋隔离 SPA／HTTP 的 coding-delivery 真 Chrome 最终通过，覆盖新 source-unknown 详情、360／1280 未溢出／重复修复禁用、原取消与确认保留，以及既有 360／1024／1280／1920 交付范围，写入仍 1 次。输出 V20_CODING_DELIVERY_PASSED、OWNED_JOB_EMPTY_AND_BROWSER_OUTPUT_CLEANED；未操作用户服务或真实模型。

已扩实际 NTFS／MinGit／SQLite 场景到丢创建回执、丢消息回执后 C38、预留后 STOP、取消后新修复和取消后连续替换；这些正在执行，未计通过。取消后原候选仍可能是上代固定来源，新修复必须经原取消静止／消息证明接续；若再次替换，逐条校验前一替换及同一旧候选、取消步骤和真实 QUIESCE，不凭旧候选 ID 取得新代次授权。

## 第五批：创建后的来源再次核对及恢复边界

新增 observe_replacement_source 从同一实例重读原已退役会话的固定消息完成／取消、全实例 idle／pending，独立复核原 Guard、只剩根进程及原 NTFS 工作区。创建成功后，沿原恢复清单再次核对完整实际字节，锁住源文件至原发送意图提交；不依赖创建前的旧来源计数放行。对应真实 HTTP 的原消息变化／新增 pending／Guard 不同与原来源、角色／停止范围及浮点身份联合 30 项通过（2.16 秒）。

实际未知创建场景已单独取得通过（本批首次五场景联合中的第 1 项），但同批第 2 项丢消息／C38 场景在继续捕获时碰到原观察冷却期，185.32 秒以 1 通过／1 失败退出，未执行后续三个参数。测试仅将该夹具的观察间隔设 0，产品 2 秒间隔未改。最新批次串行执行丢消息／C38、预留后 STOP、创建后实际源码漂移、取消后新修复及取消后再归档连续替换，目前未完成，不提前计通过。

最新完整 Guard 场景进一步加入 BACKEND 同角色替换后原两个角色交接，再做 INTEGRATION 同角色替换和原取消／再捕获分支。最终应为五个会话、三个角色、两次 HANDOFF，原实例代次 1／停止代次 6；预期会话数变化来自两个真实 REPAIR 创建，不改变角色完成定义。待正在执行的实际边界批次完成后串行运行该最新 Guard 范围。

## 第六批：五个实际恢复边界通过

最新 SUCCESSORBOUND2：test_task_capture_quiescence.py::test_original_capture_runs_fixed_git_and_recovers_without_source 的 archived-session-lost-message、archived-session-stop、archived-session-source-drift、archived-session-cancel、archived-session-cancel-archived 五个参数，最终 5 项通过（536.56 秒）。通过原锁定 Python／quality_python／自有临时目录串行执行。范围包括实际 NTFS／MinGit／SQLite／ASGI、创建及消息离线夹具、C38 仅读回单次原消息、预留后原 STOP 栅栏拒绝继续创建／发送、创建期间实际源码被改动时不发送也不覆盖该变动，以及取消后明确重试／连续两次同角色替换到新候选、C30 精确字节和两条修复历史。

取消后仍是上代固定候选时，新动作只依据实际原取消消息和 QUIESCE 接续；连续替换逐条核对原来源、真实旧新会话、旧取消步骤与回执，不修改旧操作代次。已调整共享消息作用域，让新目标与真实旧来源窗口分开表达，不再用新会话 ID 构造旧消息窗口。该最后表达调整与最新 STOP 遍历，将由正在执行的 SUCCESSORGUARD2 和后续关联专项补验。上述 archived-session-stop 证明受理与原栅栏；新测试没有真实 OpenCode TASK 的最终原生停止／清理证据。Guard 场景证明受控项目命令收尾和 TASK 停止会话范围，不能扩大成真实供应方／正式部署验收。

最新 Guard 已启动：BACKEND 替换→原两次角色交接→INTEGRATION 替换→取消／再捕获／新修复→三阶段检查／发布及停止范围；5 会话、3 角色、2 HANDOFF、停止代次 6 预期。正在执行，不提前记通过。

## 第七批：两次同角色替换和原角色链完整联合通过

SUCCESSORGUARD2 最终 1 项通过（672.16 秒），命令为锁定 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short，目标 test_v20_guard_control_git_transport.py::test_authenticated_project_check_transfers_input_runs_and_releases_original_job[PROJECT_CHECK_HANDOFF]。实际原 Guard／受控项目命令、NTFS／MinGit、SQLite／ASGI：BACKEND 同角色修复替换后两个原角色交接，INTEGRATION 再次替换，取消／明确再捕获／再次修复，新候选三阶段检查、Testing 发布／复查，停止受理及会话范围为五会话、三角色、两次 HANDOFF、原实例代次 1／停止代次 6。模型创建与消息完成仍是离线夹具；不声称真实 OpenCode TASK 最终原生 STOP／CLEANUP。

共享 Continuation 的真实旧 ModelWindow 和显式新目标、严格整数身份以及 STOP 来源，另与原来源／角色联合 33 项通过（1.17 秒）。本次同时扩大角色创建 C38 联合的 ROLECREATEGUARD2 最终 1 项通过（668.67 秒），具体新增范围见 coding-role-create-reconciliation-2026-11-11.md，不重复累加为产品验收数。

16:38 前端 strict／Prettier 和后端 475 个生产文件 Ruff 格式检查通过。修复创建的显式 C38 另登记独立 pending 迭代，实际专项正在执行；没有提前记录通过。
