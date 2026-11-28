# WALL-E V2.2 当前源 HTTP 路由专项（R479）

日期：2026-11-26（香港时间）

## 范围与隔离

在 `output/v22-dev-isolated` 的 `codex/2.2` 与 `output/v22-integration-isolated` 的 `codex/2.2-integration` 分别运行相同的三个 FastAPI `TestClient` 路由用例。两个分支 HEAD 仍为 `deacba8a9545122f35a2f85c125a354205e06461`。用各自 `.venv`，pytest 禁用缓存插件；没有开启监听服务、使用业务库或访问模型／计数供应方，端口 8001 未触碰。

## 命令与结果

在两个工作区各自运行：

```text
.venv\Scripts\python.exe -m pytest backend/tests/requirements/test_v15_foundation.py::test_http_new_contracts_replay_errors_and_removed_initialization backend/tests/documents/test_v15_documents.py::test_actual_http_document_paths_and_strict_target_parameter backend/tests/documents/test_v15_editing.py::test_actual_http_edit_requires_document_session_key_and_returns_real_effect -q -p no:cacheprovider
```

开发分支 **3 passed**，9.82 秒；集成分支 **3 passed**，9.79 秒。两个运行各有一条 Starlette 弃用警告：当前 `starlette.testclient` 与 `httpx` 组合将来需切换至 `httpx2`。三个用例覆盖旧初始化接口移除后的错误／重放、严格文档路径目标参数，以及草稿编辑的文档会话键和实际 HTTP 效果。

## 结论与边界

R476 未执行的三个当前 HTTP 路由断言现已补齐并在两个隔离分支通过。这是进程内 FastAPI 路由证据，不等于 Uvicorn 服务、普通安装身份、真实 HTTPS 或浏览器端到端验证；后续证据分别见 R480、R481。没有新增或修改测试源码，HEAD 和索引保持不变。
