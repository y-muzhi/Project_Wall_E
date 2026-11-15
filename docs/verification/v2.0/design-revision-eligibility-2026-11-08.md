# V2.0 固定设计版本资格验证

2026-11-08，基线 28a7c9e 上的 V2.0 工作区。范围为 API18 历史确认资格及前端读取契约。测试用隔离 Windows SQLite 与真实 ASGI，不操作用户库或服务。

- 使用真实文档创建、空内容确认、编辑保存、版本标记及确认生成事件。API18 返回最新内容顺序，并区分旧版仍有效、仅标记版未确认、空 MAIN 不可用与同一版本可作 MATERIAL。
- 覆盖跨文档版本读取、非法参数和超出末页后的真实总数。公开结果不包含正文和完整确认审计。
- `tools/python-v20.py tools/quality_python.py backend/tests/code_tasks/test_design_revisions.py backend/tests/infrastructure/test_v20_schema_release.py`，4 项通过，7.47 秒。初次专项将保存响应当作嵌套草稿，修正夹具后通过。Starlette TestClient 现有依赖弃用提示 1 条。
- 前端 `node --test tests/v20-code-design-revisions.test.mjs` 1 项通过，`npm run typecheck` 与 `npm run format:check` 通过。验证历史选择、拒绝错误文档归属及越界分页。
- 固定资源 db20-r22 核对源摘要与发布链。API32 写入、实际创建抽屉、浏览器及正式环境验收另行验证。
