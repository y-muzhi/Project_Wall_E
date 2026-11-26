# R452 从固定 Git 提交准备独立构建输入

2026-11-25。本地 `codex/2.2` 和 `codex/2.2-integration` 的独立仓库，未提交源码。Windows 固定 Git 只读已有提交 `deacba8a9545122f35a2f85c125a354205e06461`，原 tree `5230b7123a763b944f2cd45cb270f6c0b531b828`。用 `python -I -B -S tools/prepare-v22-release-source.py --git <固定 Git> --repository <工作区> --commit <原提交> --tree <原 tree> --output <独立新目录>` 各自导出。两边各 1,887 个 Git 源文件，清单 SHA256 一致为 `aa04ae2357e8a405717a3ca26741df90922b64208845b42f4eaeeeac2dbd7eee`。

- 读回应用与构建两层的全部 2,303 个文件副本。416 个公用输入在同一出包结果内使用独立文件，两套独立仓库导出也不共享文件身份。每项都按清单原大小和 SHA256 复核。
- 错误 tree、用 tree 代替 commit、已有输出目录和输出落在原工作区内均拒绝。已有输出的文件身份与清单字节保持，原 HEAD、索引和已变更文件集合保持。源文件检查覆盖完整 Schema 来源、两份原设计、冻结资源和前端构建锁。
- 在新导出的 `build/frontend` 内使用原锁相同的独立依赖副本和私有 npm 缓存，离线执行 `npm run build`。TypeScript 和 Vite 构建通过，产生 120 个文件。前端构建输出和依赖均未进入应用输入。Vite 仍提示已有大块。
- 新增专项覆盖同长度内容不符、归档链接、错误大小、LFS、缺必需项和大小写别名。Windows 兼容 runner 把 R451、R452 两套新增专项合跑，最终 15 项通过、1 项因为 Windows 沙箱禁止创建硬链接而跳过。该项随后在 [R454](local-x86-release-build-delivery-r453-r454-2026-11-25.md) 的 Linux ext4 完整执行。此项的实际 Git 读取和前端构建发生在 Windows。Linux 中转和候选安装过程使用独立记录。
- `--verify-manifest-sha256` 在真实离线构建后重读 1,426 个应用源和 877 个构建源，构建目录的 `node_modules` 和 `dist` 有独立位置。错误清单摘要和相同长度的源码改动均拒绝。Windows 路径与打开句柄对同一文件的 `ctime` 表示有所不同，复核按相同视角比较变更时间，原身份、长度和摘要仍分别检查。
