# V2.11 AI 输入区纵向空间检查（2026-11-20）

- 环境为当前工作区未提交前端改动，运行中的 Vite 5174 代理 8001。只读打开需求 #2，未启停服务、发送 AI 请求或保存文档、主题及关联。
- 在 `frontend/` 执行 `npm run format:check`、`npm run typecheck`，均通过。`node --test tests/v15-ai-composer.test.mjs tests/v15-composer-feedback.test.mjs tests/v15-discussion.test.mjs tests/detail-layout.test.mjs` 共 34 项全部通过。Vite 使用 `build({build:{write:false,reportCompressedSize:false},logLevel:'warn'})` 完成内存构建。
- 5174 实际返回 `composer-view.tsx`、`conversation.tsx`、`detail.tsx` 的转换代码及关键组件导出，两份样式返回本轮布局规则。模块均为 HTTP 200。
- 浏览器实测工具栏可用宽度约 489 px 时三个折叠控件同排，工具栏高 33 px。可用宽度约 312 px 时讨论主题排到第二行，工具栏高 69 px。两种宽度下输入框均为 57 px。
- 展开关联文档及讨论主题均使用工具栏整行，收起恢复同行。打开主题可见当前主题和选择器。切换至写入后，范围选择提供整篇文档及实际章节选项，显示文档 V2 和另存新版本的说明，未选范围时显示原因并禁用发送。检查后在验证页切回讨论。
- 浏览器未覆盖超长主题、在途 AI、人工编辑、历史运行和故障恢复状态。占用、未知结果及重试边界由原有离线专项覆盖。生产构建仅在内存执行，实测页面使用开发服务。
