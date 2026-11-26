# R374 最终普通前端跨宿主和双 Linux 依赖重建

2026-11-24（香港时间）。无网卡 Ubuntu 24.04 x86_64，延续 [R360](local-x86-worktree-build-isolation-r360-2026-11-24.md) 两个真实工作树、公开包缓存和独立 Linux UID。最后一份 [R371](local-source-candidate-handoff-r371-2026-11-24.md) 前端及固定资源放在两份独立源码副本，原工作树、HEAD 和开发未提交测试文字保持。两侧以 Node 24.22.3 分别从独立缓存执行 `npm ci --offline --no-audit --no-fund --ignore-scripts`，依赖物理 inode 不同，原 `package-lock.json` 摘要一致。

两侧分别执行 `npm run build`，包含类型检查。全部 120 个文件的路径、内容及逐文件摘要相同，汇总摘要 `2e6b122bae62de581e7ad54e0dac6b5c7c93fc3db5c1c755cd05e43f07413df0`。和 Windows Node 24.15.0 的本轮隔离构建比对，文件名差异 0，文件字节差异 0。来宾退出码 0。

同轮独立管理前端按 `vite build --config vite.management.config.ts` 构建，三个文件与上一份固定管理构建逐项一致。普通和管理前端产物落入专属验证目录。固定候选仍须由获准的集成交付和候选准入生成。
