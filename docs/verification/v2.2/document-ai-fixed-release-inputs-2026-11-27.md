# V2.2 文档 AI 固定发布输入

## 固定候选登记、封存及部署描述（2026-11-27）

- 在 Mac ARM64 独立发布登记中完成开发交付 `fa605504-ebed-4732-9150-118eed6397e5`、集成交付 `36104f04-aab8-4162-9c55-6c19f91fe6b5`，均绑定同一 Git 提交及树。
- 构建核验、独立原生应用启停及写后读回、实际 Caddy HTTPS 下的 Chrome 验证、封存备份及独立只读恢复均通过。恢复证明 SHA256 为 `cd374b4115a902d501ed8ae73c0e281590188bf4a0a403b35b66343f107f83e5`。
- `prepare-release-final-build`、`seal-release`、`candidate --require-release-evidence` 通过。发布 `73a0b4f6-c9e5-4b8f-ae55-bdee49259b98` 的封存清单 SHA256 为 `af605e10624054de071e960d2312c022a35c8eb98febb65b2fc008ab704550a7`。候选含 2,407 项应用文件和 516 项静态文件。
- `describe-restore-deployment` 固定真实开发站目标配置 `afcc01fdda7e75402326aafe6c6845111f74118abd29f5d1703c0d0bebbfa4b1`，目标代次 `89f8bb6e-24f4-4640-a7a3-cb625b720fe6`。此时原开发站与集成站仍在服务。真实模型及计数 API 调用次数均为零。

2026-11-27（香港时间）。经本轮授权，`codex/v22-document-ai-release` 在独立工作树提交 44 个相关文件。当前工作树干净，开发、集成和网关的原运行保持。

| 核对项 | 实际值 |
| --- | --- |
| 提交 | `2f8330085258d3708282d0532be8d8bb5bae7bec` |
| Git tree | `c36d780c332cf5089238e035f5600e8f323377c6` |
| 固定源码清单 | `11c073d179f07e6ada7af6fd319ce0b1b372de9a318a5f224ba0b364b8c4fffa` |
| 应用程序快照 | `1650eb7563025d9bb2ed7b2d700abeb14ae659a006dcd494742476bcee50dd0d` |
| 前端索引 | `8fe90303d98e694509752773071582100d65063acfbe34df1215b9da9b0fc9da`，516 项 |
| Mac ARM64 固定运行包 | `bdf8927f66d790ca279b0b5ac249644f338fc6dd2cd01e4e8efda421b66fa843`，SQLite 3.54.1 |
| 文档 AI Schema 清单 | `723f769144b7546f3ec383a1edd6fa549bc961511c63a748f6fa0fb58d1f4b18` |
| 文档 AI Schema 契约 | `98dec17c9581de53bc38d5d6965eae2ea82743243d661f50e7b2ae2276bebb3f` |

`tools/prepare-v22-release-source.py` 用明确的 commit 和 tree 导出固定源码，`--verify-manifest-sha256` 回读通过，独立应用输入 2,406 项、构建输入 1,709 项。使用独立复制的既有锁定依赖运行离线 `npm.cmd run build` 和 `npm.cmd run format:check`，TypeScript、Vite 和 Prettier 通过。Vite 报告大块提示。复制的临时依赖已清理。

Mac 使用临时隔离根、已安装固定运行包的 `admit_target`、依赖与映射验证及非特权构建身份，重算程序与前端索引。旧运行包自带 CLI 没有新 Schema 选项。本轮从经核验的提交源码运行 `build_and_publish(..., document_ai=True)`，完成固定 SQLite 新库重开与转换核验。首次安全解包默认加了所有者写位，固定程序准入拒绝。重传时复原导出清单的只读模式，通过构建，并取回三个 Schema 制品。Windows 随后以同一导出根重读 Schema，逐文件复算前端索引，与 Mac 一致。Mac 临时构建根已清理。

固定源码和前端产物保存在独立工作区旁的 `.tmp/v22-document-ai-fixed-2f83300`，Schema 制品在 `.tmp/v22-document-ai-2f83300`。此记录提供可供受管中转读取的固定输入。在本次核对的 Mac 持久安装目录中未定位到该提交的受管集成交付登记。正式候选仍需登记同一 commit／tree 的集成交付，再走现有中转、候选四项证据和封存。本轮未推送、未切站、未发送模型及计数请求。

### 固定 Git 交付复验

增量交付包 `.tmp/v22-document-ai-2f83300.bundle` 的 SHA256 为 `29d395fba9ea9b37a86d5ef718f32eb533c5006d7afc97056f5b92477b46a5e5`，固定发布分支指向 `2f8330085258d3708282d0532be8d8bb5bae7bec`。本机及 Mac ARM64 独立仓库的 `git bundle verify` 均通过。Mac 用现有基线包补齐两个祖先对象，再从增量包获取发布引用。在两个唯一的隔离工作树使用现有 `load_repository`／`source_evidence` 校验器，实际核对开发与集成两个 checkout 均指向该 commit 和 tree `c36d780c332cf5089238e035f5600e8f323377c6`。隔离工作区观察摘要为 `e8211b98c8727c96db2aaf1d157ea00f2efcac61025c99f3e6e4dc509d53b2bf`。首次夹具的规范 JSON 缺结尾换行，被正确拒绝，修正后通过。此摘要只属于临时工作树。

同一提交在 Mac 固定运行时复跑源导出、发布中转、最终组装、开放历史、关闭态发布及文档 AI 相关的九个测试文件，94 项通过、2 项按恢复副本适用范围跳过。隔离根已清理。扫描既有 Mac 持久运行目录和管理服务单元没有发现可接收本次交付的已部署管理安装／目录。下一步是在获准的受管登记范围内确认管理安装和目录，登记开发原交付，再登记引用它的同提交集成交付。现场服务、凭据及数据没有改动，未发送真实模型或计数请求。
