# WALL-E V2.2 路由与需求页环境归属验证

2026-11-20（Asia/Hong_Kong）。Ubuntu 24.04 ARM64 开发 worktree `~/walle-v22-validation/scopes/development/source`。以 V2.01 前端 7.1、7.4 和已通过的 C1/C2 为依据。

- 用真实 ApplicationRouter 和浏览器端口测试替身运行同一 URL。旧原始检索和滚动在同代次恢复，新的代次仅保留 URL 并使用默认检索和滚动位置。断言真实读写 history.state 的环境信封，旧代次 sessionStorage 辅助键保留，原浏览器滚动恢复控制仍被设置。第一次测试把默认位置写成 null，实际默认路由使用滚动位置 0。修正预期后通过。
- 使用现有注入点接入要求页阅读偏好、布局、卡片、讨论草稿和移交标记。旧入口未提供作用域时保持原业务行为。对已有代码运行 12 组、113 项离线回归，均通过。覆盖路由、工作台历史、详情布局和读取、阅读选择、对话、传输和人工草稿。
- 命令使用 `node --test --test-timeout=10000` 运行 `tests/` 下 `application-router`、`workbench-history`、`detail-layout`、`detail-read`、`v15-reading`、`conversation-owner`、`guide-composer`、`environment-binding`、`v15-directory`、`manual-recovery`、`manual-end`、`api-client` 对应 test.mjs。运行 `npm run format:check`、`npm run typecheck`、`npm run build -- --logLevel warn --outDir "$scope/web-c3-route"` 均通过，120 个独立构建文件，既有 Vite 主包大小提示仍在。

Coding／Testing 本机存储、命令仓储、浏览器页面启动、真实 IndexedDB 和 HTTPS 验收仍待完成。验证只运行本机和隔离工作区代码，无业务监听、模型调用、Git 提交或生产接入。
