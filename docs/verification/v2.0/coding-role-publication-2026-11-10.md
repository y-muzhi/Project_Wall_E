# V2.0 Coding 原角色交接、原投递核对及发布专项

2026-11-10，master 28a7c9e 的工作区增量。正式 BE 0.17-draft-17／FE 0.16-draft-16，设计摘要同实现进度。核对 APP-CODE-HANDOFF、SHR-CODE-VERIFY-STAGE、BND-CODE-API-38／68、BND-CODE-WORKBENCH 及 CHECK20。独立 Schema200 临时库、Windows Guard 认证命名管道、MinGit、项目 LPAC Job 及 WFP 测试夹具，原生 OpenCode 的会话、消息及模型回执由确定性原协议夹具提供。

- `tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider backend/tests/infrastructure/test_v20_guard_control_git_transport.py::test_authenticated_project_check_transfers_input_runs_and_releases_original_job[PROJECT_CHECK_HANDOFF]` 对应专项模式，最终联合 1 项通过（308.09 秒）。实际接续两次固定交接；原发送响应丢失后首次 C38 核对仍未知，第二次从同原消息确认恢复，未重复发送。验证后端／前端／联调三个阶段检查、C68 原请求及原回执；复检原发布候选分配新 Verification，合格回到待独立测试并保留原发布事实。C68 不创建 TestingTask。初次运行暴露 TaskView 未声明实际未知原因、终止关联仍使用早期会话及单独测试装配缺原回执路由，已分别修正。
- 前序受影响联合 24 项通过，覆盖原停止、续跑、捕获、原始会话及停止观测。原 Git 起点组件联合 2 项通过（346.60 秒），另见固定内容专项。
- `tools/verify-v20-command-recovery.py --probe tasks` 实际隔离 Chrome 通过 360／1280 视口下角色五步展示、明确发布、丢失原成功响应后的原回执恢复，继承原候选、分页、检查及任务控制场景。浏览器采用隔离 API 夹具，C38 服务端联合与浏览器专项分别取证。试验自有进程及临时输出已回收。
- `npm --prefix frontend run typecheck`、`npm --prefix frontend run format:check` 通过。尚待真实 OpenCode 与模型环境准入、SYSTEM／WFP 正式部署、原角色其他未知步骤、独立 Testing Driver 和最终接收／Git 交付。

C38 目前仅核对原 HANDOFF_ROLE 最后 SEND_HANDOFF 的已保存投递意图，其他未知资源仍保持互斥。后续角色由原成功交接、前一阶段自检、QUIESCE、旧窗口撤销及新原生会话和首条消息决定；单纯修改角色文本不会解锁。

- `tools/verify-v20-command-recovery.py --probe role-reconciliation` 的独立 Chrome 360px 专项通过。核对原角色请求只发一次，202 接收后仍显示待核对，读取同操作记录的原消息接收证据后才显示交接完成。附加到全量任务浏览器用例的一次运行触及 180 秒上限；该次临时资源已回收，随后单独运行。短专项首次夹具使用短分支名及错误的活动会话／操作投影，按真实 TaskView 改用固定完整分支名、已撤销旧会话与原 HANDOFF_ROLE 记录后通过。生产角色执行、原生 OpenCode 与模型环境证据范围同上。
