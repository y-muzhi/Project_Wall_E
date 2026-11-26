# AI 请求上下文上限验证

2026-11-24（香港时间）。基线 `cd48227` 加 V2.11 当前工作区改动。沿用 V1.5 正式前后端设计中 BND-MODEL-CALL、I38／I39。前端和后端设计 SHA-256 分别为 `b294153e11ef764f36f92b7390dc817c6ed079a81734c770ebbe6f217601e2920` 和 `36d2e28630b5099a30253e5a5881492c8fc50c3cffaf4d9d4a88341bdc24defd`。

## 格式、构建与离线检查

- `git diff --check`、`.venv/Scripts/python.exe -B -m ruff format --no-cache --check backend/app`、`npm run format:check` 均通过。`npm run build -- --outDir ../.tmp/v211-context-limit-20261124/dist` 通过类型检查和构建，Vite 报告既有大分块提示。
- `node --test tests/model-calls.test.mjs tests/api-bindings.test.mjs` 共 18 项通过，覆盖已知预算、缺失字段兼容和解码约束，以及现有调用列表的读取行为。
- 用 `.venv/Scripts/python.exe -B -X utf8 tools/python-v20.py -m pytest -q -p no:cacheprovider --tb=short` 运行 `ModelCallReadTests`、`test_v15_model_calls.py`、`test_context_projection.py`、`test_openai_execution.py`，21 项通过，17 项在旧版需求创建夹具中失败。失败发生在调用记录读取前，旧夹具仍传已移除的 `template_key`、`template_version`、`initialization_mode` 等字段。宽范围结果保留，现行合成 OpenAI 调用返回的上限与详情预算一致。
- 单独复测 `backend/tests/guide/test_v15_model_calls.py::test_eight_saved_wire_sections_actual_count_measurements_and_read_only_http` 通过。验证原默认响应、可选上限、详情一致性及只读行为。无效参数最初返回 500，改用共享枚举校验后返回 422。Starlette TestClient 有弃用提示。

## 8001 发布与实页

- 发布前两次只读检查均确认在途指引、指引占用、排队或执行中的代码操作、处理中代码和测试任务为零。保留 `openai-v6`、既有数据库和 `tools/openai-service.py --start --port 8001` 的原启动配置。新旧进程依次为 11356、6024、58080。
- 新增 24 份哈希资源，复用 95 份字节相同的资源，原子切换静态入口。入口 SHA-256 为 `572bb16145af5a5d9ed93f9fe8d5b4f2412734448c374fa7906e8813e5113b45`。主资源 `index-CmIp7euR.js` 和 `index-_MKH-XRs.css` 的 HTTP 响应与构建字节相同。
- 运行 49／调用 46 的可选字段返回 131,072，实际输入 26,591。默认请求仍按旧结构返回，非法参数 422。需求详情页返回新版静态入口。
- 内置浏览器在原需求页核对 `本次上下文输入 26,591 / 131,072 token` 和 `20.3%`。370px 宽卡片无横向溢出，进度条高度 4px，实际属性为 26591／131072。打开「查看上下文」显示同一上限，关闭后焦点回到原按钮，卡片错误提示为零。多次调用、失败及在途卡片未在正式业务库制造状态进行浏览器验证。
- 真实模型和计数调用均为零。本轮临时构建与测试目录已清理。
