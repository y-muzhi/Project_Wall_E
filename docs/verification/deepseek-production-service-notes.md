# 正式 AI 默认服务接线检查

2026-10-08。D-015 的 148 项离线专项与唯一 6＋6 真实观测完成后，生成独立固定生产准入配置。证据摘要在 [原专项记录](deepseek-availability-notes.md)，该文件已被准入配置按 SHA-256 引用，接续结果放本文件以保持原记录字节。

执行 `backend.tests.infrastructure.test_deepseek_availability.PracticalOrchestratorTests.test_default_service_http_worker_count_chat_audit_and_c07_uses_real_admission`，结果 1 项通过，4.050 秒，退出码 0。

该用例在临时真实 SQLite 上使用默认 `create_app` 和正式 Worker，通过 HTTP 创建需求，沿默认精确模型/实际固定准入运行。仅远端计数和模型 HTTP 传输替换为本机真实 TCP 服务；未替换准入、Builder、审计、可信产出、C07 或公开业务结果。实际运行 COMPLETED、一个计数请求及一个 Chat 请求、v3 审计和助手消息已持久化。临时目录已清理，没有访问正常业务库或真实 Provider。

另运行 `.venv\Scripts\python.exe -X utf8 tools/ai-service.py`：精确模型、六种 Function 和固定资源校验通过，返回“准入：已启用实用预算控制”。默认离线分支没有读取密钥、启动服务、调用 Provider 或打开业务库。

没有恢复浏览器、完整回归或效果验收。没有追加付费调用，没有生成测试 JSON、截图或原始日志。资源 `admission.json` 是批准条件满足后生成的正式运行配置，不是测试结果报告；包含证据 Markdown 的摘要哈希，不包含原始响应。

正式本机服务已用 `.venv\Scripts\python.exe -u -X utf8 tools/ai-service.py --start` 启动，PID 55460，绑定 `127.0.0.1:8000`，生命周期启动成功。项目已有前端构建继续使用，本批没有构建前端。只读访问 `/requirements` 与 `/api/v1/requirements` 均为 HTTP 200；未通过正常业务入口追加模型调用。批准稿、采用记录、v3 策略、准入配置及两份引用 Markdown 的 SHA-256 均核对一致，准入为 true。`.env.local` 仍被 Git 忽略。
