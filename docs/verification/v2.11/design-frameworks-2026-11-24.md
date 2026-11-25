# 前后端完整规格模板验证

2026-11-24（香港时间）。工作区基线为 `cd48227` 与 V2.11 事项 15—18。本轮针对事项 18 检查内置资源、创建与读取、升级时的幂等重放及 8001 发布。

## 静态核对

- `python -B tools/build-design-frameworks.py` 通过，冻结资源能由同一完整规格源重建。前端资源为 44,504 字节，SHA-256 为 `029b2fee9728a4a1554d5e7d3650ccee4c1a9e0c8da93ca2cbed6aa275e9f787`，后端为 68,244 字节，SHA-256 为 `a046ca30e9ded4101d1658c61f9aef94de15510bd068a8ac1542e66011e4ae40`。
- `python -m ruff format --no-cache --check backend/app backend/tests/formation/test_v211_document_types.py tools/build-design-frameworks.py` 检查 618 个文件通过。 `git diff --check` 通过。

## 离线和隔离 HTTP

- `python tools/python-v20.py -m pytest -p no:cacheprovider backend/tests/formation/test_v211_document_types.py backend/tests/documents/test_v15_documents.py backend/tests/formation/test_v21_independent_operations.py` 共 21 项通过。使用临时 SQLite，依赖有一条 Starlette TestClient 弃用警告。
- 前后端类型的空白和固定框架 HTTP 创建、读取、同键重放、完整 Markdown 字节、模板块来源及离线 AI 写入上下文已核对。跨版本专项先复现旧请求重放返回 500，原因是创建响应审查要求引用当前模板。修复后按指定类型校验已冻结的框架身份，旧请求返回原结果，新请求保存完整模板。

## 隔离浏览器

Edge 158.0.4370.33 加载现有静态前端和本轮后端。经正常「新建文档」交互分别新建两种固定框架，HTTP 返回后核对正文与源文件逐字节相同、章节和 Markdown 表格已渲染。随后分别在「更多操作 → 人工编辑」修改一个章标题并完成保存，重新 GET 确认仅该标题发生变化，其他 Markdown 字节与模板引用保持一致。隔离数据库的模型调用数为零。未执行跨浏览器检查。

## 8001 线上只读验证

- 切换前从现有库只读确认，在途指引、被指引占用的需求、排队或执行中的代码操作、执行中的代码和测试任务均为零。启动前离线准入为 `OFFLINE_READY`，供应方调用数为零。
- 8001 从 PID 5624 切换至 PID 11356，沿用原 Schema 210 数据库、模型配置、资源发布和静态构建。页面入口与既有静态发布的 SHA-256 `cee817434d97e062bc6c0bd934c5b9a6d81f0a253f8f97d30d1ef314b6485a2e` 一致。5173、5174、8000 无监听。
- 实际 8001 的需求列表与已有前端文档 #9 回读正常，原 `blank-v1`、正文版本 6。模板创建使用隔离库验证。未执行生产文档写入、真实模型或计数请求。
