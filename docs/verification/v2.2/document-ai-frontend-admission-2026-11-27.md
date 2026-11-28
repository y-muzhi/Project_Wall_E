# 开发环境文档 AI 前端准入专项

2026-11-27（香港时间）。Windows 独立检出 `.tmp/v22-document-ai`，基线 `990ed2d`。检查范围为能力握手及浏览器 API 请求准入。模拟已绑定 HTTPS 握手和响应，未连接模型或修改 Mac 服务。

- `node --test frontend/tests/environment-binding.test.mjs`，19 项通过。新增测试验证开发环境编辑身份可通过 `DOCUMENT_AI=READY` 握手并读取指引运行，关闭态保持原限制。集成、候选、开发只读身份和恢复态若错误声明 READY 会拒绝启动。未登记方法、路径及代码任务仍被浏览器在发送前拦截。首轮新增测试因构造测试客户端时遗漏第二个参数失败，按正常构造调用修正后重跑通过。
- `npm run format:check` 通过，使用项目锁定的 Prettier 3.9.10。使用 TypeScript 7.0.2 对 `environment-binding.ts`、`environment-actions.ts` 和 `client.ts` 及导入依赖运行严格类型检查，启用未使用变量、参数、索引和可选属性检查，通过。
- 全前端 `npm test` 未通过，独立检出缺少 `@milkdown/kit` 等依赖。`npm ci --offline --ignore-scripts --no-audit --no-fund --logs-max=0` 因 `react-dom` 未缓存而停止，现有其他检出的安装不满足该锁文件。全前端类型、构建和浏览器验收未执行。

本批仅覆盖基础指引请求边界，页面入口、文档进展和建议 API、后端启动和派发、固定组合结构及真实供应方仍待接续。
