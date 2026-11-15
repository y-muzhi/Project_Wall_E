# V2.0 Coding 缺陷登记与原执行记录

2026-11-10（香港时间）。BE APP-CODE-REPAIR、APP-CODE-CONTROL、APP-TEST-REPORT、ExecutionRecord、Coding API26／41／58／60 及 FE Coding 执行／独立测试、Testing 报告。实际隔离 ASGI／SQLite 3.54.1，测试中的原生 OpenCode 结果采用固定协议夹具。

- tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider 运行 backend/tests/code_tasks/test_task_defects.py、backend/tests/test_testing_report_api.py，共 5 项通过。人工缺陷在同一事务保存固定原文、同任务子证据、原回执及版本推进。拒绝错误原文、外来证据、混合输入及过期版本。归因后可显式导入原 PRODUCT Finding，重复导入被拒绝，后续归因变化保持已存报告原内容。候选和原运行证据来自报告专项的持久夹具。
- 同命令运行 backend/tests/code_tasks/test_task_start_session.py 和 backend/tests/code_tasks/test_task_question_response.py，共 18 项通过。START 原生确认后才出现首条记录，原操作、会话筛选与空页从真实 SQLite 读取。工作端丢失、晚到答复、停止及同键重放沿既有约束。由任务、实例、代次、会话与原来源共同决定记录归属。
- 同命令运行 backend/tests/code_tasks/test_task_permission_response.py，共 7 项通过。完整权限决定追加对应原操作控制摘要，部分确认、派发未知、停止抢占和拒绝均无对应成功记录，原命令及事件私有标识不进入公开摘要。
- tools/verify-v20-command-recovery.py --probe coding-report-link。Chrome 360／1280 已覆盖人工草稿刷新、取消、丢响应后原键读回与导入，并核对执行记录按当前会话筛选、真实第 2 页、空页／空列表及读取失败恢复。初轮捕获了分页元数据误读和轮询函数不稳定，修正后通过。
- tools/verify-v20-command-recovery.py --probe testing-task-workspace。Testing 报告先核对 Coding 的当前固定候选，360 像素验证历史候选禁用写入，1280 像素验证确认／取消及恢复。用户确认后发送唯一 C58，响应截断后重载，按原键找回同一缺陷。后端仍复核源归因、原文及任务归属。
- Schema200 db20-r41 的原回执与 Schema 资源专项共 9 项通过，含旧 151 普通入口边界。
- npm run format:check、npm run typecheck、npm test 共 566 项通过。Ruff 目标 lint 及 backend/app 全量格式通过。

原控制摘要仅写已确认的首条消息、答复或完整权限决定。未覆盖原生消息正文／工具轨迹／命令输出与错误的实时采集、API59 实际修复、真实模型及正式 OpenCode 部署。仅保留 Markdown，隔离进程与存储由测试回收。
