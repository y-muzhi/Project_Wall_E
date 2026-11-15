# V2.0 原生问题答复验证

日期为 2026-11-09。验证本地 master 28a7c9e 上的 API46 工作区增量，采用 BE APP-CODE-QUESTIONS 4.2—4.4、API46、7.4.2—7.4.3，以及 FE 原生问题处理。两份设计保留原字节。测试使用临时 SQLite、受控 Windows 回环、临时 Chrome 和构建目录。

| 环境与命令 | 实际结果 |
|---|---|
| `tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider`，`test_task_question_response.py`、`test_task_native_issues.py`、`test_task_runtime_stop.py`、`test_v20_opencode_instance_control.py` | 联合 19 项通过。覆盖 API46 原 202 和同键回执、题组完整性、会话归属、原版本、旧请求缺失、未知结果、同任务证据及固定版本连续引用。重复请求只读取原回执。模型原窗口只在单一待答复事项已开始派发时允许短队列，其他待处理权限保留。 |
| 同一命令单独运行 `test_original_question_send_intent_survives_worker_and_stop` | 新增 3 项通过。发送后确认事务中断并恢复时保持 UNKNOWN，只保留一次派发。未发即完成原停止时，操作为 CANCELLED、原题为 OBSOLETE。已发但无落库确认时，完成停止仍保留原操作和题目 UNKNOWN，题目无处理时间。 |
| 同一命令单独运行 `test_actual_model_listener_waits_for_original_question_evidence` | 新增 3 项通过。实际回环模型监听、原模型账本和模拟供应方运行同一竞态。已派发未确认时，模型入口只排队；确认事务提交后才产生唯一 LLMUse。结果未知或发现另一权限等待时返回 WALLE_HOLD，供应方收不到请求，也不产生 LLMUse。原本机进程来源证明使用测试夹具。 |
| 最终联合回归，同一命令加 `test_task_resume.py`，包含上述两组新增分支 | 37 项通过。覆盖 API46 与原模型继续、原生观察、终止和控制协议的共同边界。 |
| Windows 本机认证 HTTP／SSE，包含于上面的 19 项 | 同一工作区和进程身份下验证一条原 POST。原生 HTTP 200 且 true 正常确认；丢失响应时仅接受同会话、同原请求、同完整答复的 `question.replied`。仅错误会话事件时保留未知。服务为隔离原生协议夹具。 |
| `tools/verify-v20-command-recovery.py --probe tasks`，隔离 Chrome 和模拟业务 HTTP | 360／1280 像素通过。覆盖整组未填禁用、原题表单焦点、窄屏、从固定版本原文选取连续文本并原样提交、答复提交时的任务快照、丢失响应后原键恢复和本地完整答复的只读恢复、原 202 后禁用重复答复、原确认与权限等待保留。夹具记录 1 次答复写请求。待核对答复只查询原键／原操作，不提供重发。首轮夹具在刷新前看到旧任务版本，修正为等待原问题的 TaskView，同时页面要求原会话及对应 QUESTION 等待已出现才启用提交。固定原文加测补齐选区的键盘与鼠标事件处理，真实键盘操作的最终 Chrome 复测通过。 |
| 前端 `npm run typecheck`、`npm run format:check`、隔离 `tools.quality_gate.run_stage`；后端 `python -m ruff format --no-cache --check backend/app`、改动范围 Ruff F 检查 | 前端类型、格式、566 项和隔离生产构建通过；后端 345 文件格式及限定范围 Ruff 检查通过。SQLite／ASGI 测试输出 FastAPI TestClient 已有的 StarletteDeprecationWarning。 |

公开操作详情仅投影原用户输入与公开状态。私有原生渲染文本、工作区、凭据和原事件 ID 留在受控边界。工作台证据填写已有记录 ID，后端验证真实归属并按可公开字段生成摘要。执行资源未准入沿既有 CONFIG_NOT_READY 就绪门槛。

协议形状对照 OpenCode 固定提交 `810c0eba1a7348036f8bdf61e6632d0c36c6876c` 的 QuestionReplied 和 EventPermissionReplied。后续 API47 的拒绝事件需按实际原会话、原请求与 reply 分项关联。 [固定 OpenAPI](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/sdk/openapi.json#L36191)

实际固定 OpenCode 二进制、受保护正常部署、业务库升级、系统真实 IME 交互、真实供应方及 API47 权限决定待实施或验收。Chrome、Job 和临时输出由本轮隔离工具清理。冻结 db20-r29 的三个物理资源与清单匹配，源码仅保留已有 `windows_local_paths.py` 摘要差异。
