# V2.0 原 START 会话和首条消息

2026-11-09 香港时间，Windows NTFS／临时 Schema 200，基线 28a7c9e。相关设计为 BE 4.7、7.4.2／7.4.3、7.5.2、API17／34，FE BND-CODE-TASK。 [独立迭代](../../iterations/pending/v2.0/WALL-E.执行器配置隔离与生效迭代_V_2.0.md)

- `tools.quality_gate.environment` 和临时 `--basetemp` 下运行 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short` 加 `test_task_start_session.py`、`test_task_start_instance.py`，11 项通过（80.35 秒）。实际 SQLite／ASGI 验证原 202、实例和会话登记、QUEUED 与 OPEN、状态和授权同事务、丢结果或重启不派发、停止抢占和公开脱敏。原生返回和专用网关以固定夹具注入。
- `npm run typecheck`、`npm run format:check`、`node --test tests/v20-code-task-creation.test.mjs` 7 项通过。首轮类型发现步骤取值需要显式验证，修正后通过。隔离浏览器另行记录。当前代码仍要求专用模型入口存在后才派发首条消息。
- 用户服务、真实供应方与正式 OpenCode 运行仍待独立验收。固定 db20-r29 的既有来源摘要差异未纳入本批。

- 实际 Chrome、隔离构建与离线 HTTP 场景通过。`tools/verify-v20-command-recovery.py --probe tasks --cli-entry <已安装入口>` 在 360／1280 像素核对工作区开始进度、未知与失败、原开始回执丢失后恢复、首条消息确认进入后端阶段及已开始后禁止重复按钮。共 1 次明确开始请求，浏览器、Job 与临时输出已清理。
