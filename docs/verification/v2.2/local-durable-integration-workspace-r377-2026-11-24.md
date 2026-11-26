# R377 保留独立的 V2.2 集成代码工作目录

2026-11-24（香港时间）。在已有 `output/v22-dev-isolated`、`codex/2.2` 之外准备持久的 `output/v22-integration-isolated`，其默认当前分支为 `codex/2.2-integration`。两者各有自己的 `.git` 和对象库。集成目录来自当前开发仓库中已存在的明确基线 `deacba8a9545122f35a2f85c125a354205e06461`，使用本地复制并禁用硬链接，工作树状态为空改动。无远程配置、外部对象路径、原开发配置、依赖、构建输出及工作数据库。

Windows AppContainer 阻止 Git for Windows 拉起本地复制子进程，首次失败后检查目标不存在。经系统自动审批，以普通 Windows 身份在专属目标完成相同本地动作。复读两个实际 `.git` 根、分支和 HEAD 通过。三个项目／工作区 Git 目录及两份工作源码的物理标识互异，集成目录 `git fsck --connectivity-only --no-dangling` 通过。开发的待交付源仍位于 `codex/2.2`，真实集成以 [R371](local-source-candidate-handoff-r371-2026-11-24.md) 明确范围及后续授权执行。

此单元保留后续集成用的物理代码目录和分支。两套真实 Linux 环境、独立构建依赖和隔离服务分别见 [R360](local-x86-worktree-build-isolation-r360-2026-11-24.md)、[R362](local-x86-browser-scope-reload-r362-2026-11-24.md) 和 [R374](local-x86-final-build-reproducibility-r374-2026-11-24.md)。本地集成代码目录尚在既有基线，独立候选安装、实际集成交付及常驻服务有各自的准入。
