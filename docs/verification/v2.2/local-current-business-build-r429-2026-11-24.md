# R429 当前业务对照和独立构建

2026-11-24（香港时间）。开发 `codex/2.2` 当前源码及本轮开始时的 7 份原实现。主要业务对照使用独立无网 Ubuntu 24.04.5 x86_64／ext4，固定 CPython 3.13.18、SQLite 3.54.1。浏览器与原生服务验证见 R420、R426、R427。Windows 前端依赖来自独立开发工作区的原锁定安装，构建输出使用本轮专有目录。

- 固定解释器及 SQLite 对本轮开始与当前代码各运行相同 9 项。范围为需求创建、失败事务回滚、Schema 重复初始化、多个独立文档、精确读取、确认绑定 Revision、文档失败事务回滚和评论对象与生命周期。两个版本各 9 项通过，逐项状态与阶段一致，指纹 `8333be21948759cee0f6e60f5b6e2262d2cf7e82d9f4f389c0880069bc2a0153`。前两次扩大的历史目录对照均在旧版本的 410 秒上限到时，未形成两边对照；样本结果仅覆盖以上 9 项。
- Windows 开发工作区执行 `npm run test`，固定 `WALLE_OFFLINE_TEST_PYTHON`，609 项通过。普通前端的 `npm run build -- --outDir <本轮目录>` 和重复构建得到 120 项相同文件，TypeScript 及 `npm run format:check` 通过。
- 在同一开发目录分别执行两次 `vite build --config vite.management.config.ts --outDir <本轮不同目录>`，管理的三个产物路径及字节摘要逐项相同。管理 `index.html` SHA256 为 `1b507a7af77824d30aa56e30e37ee2b0ba3d07ef883fcd2aa4f46ecfa8199702`，CSS 为 `2d51c6d247e9b1b3a9062772f2d62947b4bf135278fd6d9a07bdb79c3340537e`，JS 为 `c8076aae8f51ddc5b0c8801762427fe97687ae9848da7a63785433256669d9e6`。
- 当前开发改动与来源复核见 [R415](local-candidate-source-tree-r415-2026-11-24.md)。不含真实供应方、正式集成交付、生产或异机验证。
