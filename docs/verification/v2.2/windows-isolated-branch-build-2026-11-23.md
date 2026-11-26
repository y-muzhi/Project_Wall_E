# V2.2 独立工作区构建

2026-11-23 香港时间。Windows 独立仓库在 `codex/2.2`，检查点 `deacba8a9545122f35a2f85c125a354205e06461`，包含当前未提交的 R156 实施。

- 核对两份前端锁文件字节一致，将已安装的依赖复制到独立仓库的 `frontend/node_modules`。构建仅使用该副本和独立的临时 npm 缓存。
- `npm run format:check`、普通工作台 TypeScript 检查及构建、`vite build --config vite.management.config.ts`、后端 Ruff 格式及 `git diff --check` 通过。
- 隔离构建输出在 `output/build-codex-2.2/ordinary` 和 `output/build-codex-2.2/management`。两个 HTML 入口及各自引用的两个资源均已核对。临时构建目录已清理。
- 构建前后的分支、检查点、源码变更和 Git 暂存状态一致。本轮只执行本地构建及静态检查，实际运行及 ARM64 原生验收分别以独立证据为准。
