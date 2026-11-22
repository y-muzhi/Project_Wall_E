# V2.11 文档类型调整检查

- 2026-11-23，Windows，本工作区 `master` 基线 `30b4516` 加本轮改动。前端 `npm run typecheck`、`npm run format:check`、`node --test --test-reporter=dot tests/*.test.mjs` 均通过。`python -m ruff format --no-cache --check backend/app backend/tests/formation/test_v211_document_types.py` 通过。
- 激活固定 SQLite 后执行 `pytest -p no:cacheprovider -xq backend/tests/formation/test_v211_document_types.py backend/tests/documents/test_v15_documents.py backend/tests/formation/test_v21_independent_operations.py`，19 项通过。隔离 Schema210 通过真实 HTTP 适配器覆盖前端、后端两个类型的空白与框架创建、幂等重复、目录及正文读取，并验证针对当前文档的 AI 写入上下文。历史通用设计及规格模板行为由既有测试覆盖。最初受限环境的测试中止；同键重放用例已改为比较业务结果，逐次 HTTP 请求的追踪标识允许不同。
- 5174 在需求 #4 的新建窗口中实测类型列表仅有设计大纲、前端设计文档、后端设计文档。选择后端设计文档后仍可选择空白文档和固定框架。检查期间未提交真实业务文档。未单独验证更窄的屏幕断点。
- 用户同意重启 8001。重启前确认在途 AI 运行和被 AI 占用需求均为 0。沿用原 Schema210 库和 OpenAI 配置，8001 监听 PID 12212 → 33400。5174 仍为 PID 46692。直接后端需求列表和 5174 代理下需求 #4 检查通过，Vite 返回带新类型选项的文档导航组件。未发起真实模型或计数调用。
