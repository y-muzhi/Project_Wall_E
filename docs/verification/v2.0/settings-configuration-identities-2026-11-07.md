# 代码设置配置身份及版本列表验证

- 日期与代码状态：2026-11-07，V2 工作区。执行配置／检查配置接真实设置入口，沿已存在 C09／C10 及四个 GET 契约。运行时就绪判定以版本 DTO 为准。
- 环境：Node 24.15.0、锁定 TypeScript／Prettier，隔离生产构建、Chrome、实际 IndexedDB 和 sessionStorage。浏览器的 HTTP 由随机本机端口的契约测试服务提供。
- 专项：设置身份 owner、待核对 reader、原身份 DTO 和应用路由四文件 36 项通过。最终前端全量 545 项通过，`npm --prefix frontend run typecheck`、`npm --prefix frontend run format:check` 和 `git diff --check` 通过。
- 浏览器：`tools/verify-v20-command-recovery.py --probe settings --cli-entry <本机 Playwright CLI>`。1280／360px，检查公共分区选择器、已存在原意图阻止创建、草稿跨分区／刷新恢复、列表失败保留数据及重试、未就绪版本原因、处理中按钮、创建成功空版本、响应中断后的原 201 核对。原只读恢复段 11 次 GET、0 写。全程 38 次产品 GET、2 次明确创建 POST，两个原请求体各一次。OWNED_BROWSER_WORKER EXITED 0，测试进程与临时输出已清理。
- 初轮浏览器分页夹具缺少 data.items 包装，修正后完成读写交互。随后断在响应头前的注入捕获到额外 POST，两个原键对应两次夹具写入。改为在 201 响应开始后截断正文，复核应用原回执查询及本轮 HTTP 数。
- 边界：同名新草稿只有命中持久关联的原键及冻结名称摘要才清除；已另有选择时，其他原回执只更新列表。C07／C08 版本发布表单、授权／仓库资源区、当前任务与真实运行时联调仍待实施。
