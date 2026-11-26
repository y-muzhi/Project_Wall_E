# V2.2 R464 本机候选兼容、停写与关闭选择

2026-11-25（香港时间）。Ubuntu 24.04.5 x86_64 WHPX 本机来宾，固定 CPython 3.13.18／SQLite 3.54.1 运行包 `0241128f2faa82bcc1f34d3f87196b0b817333caec2d070bf5a91f0cd3998e9e`。项目来宾没有网卡或宿主转发。隔离候选用实际提交 `deacba8a9545122f35a2f85c125a354205e06461`，当前工作树只执行涉及新选项的装配器及测试辅助。实际应用由该候选固定程序提供。

## 实际结果

- 独立候选从原 Git 字节和原前端索引装配。真实 API 新建需求和文档、保存、正常停启及读回。独立浏览器以原生 Chrome 沙箱访问 Caddy TLS，编辑保存、刷新及 API 回读成功。普通集成另有独立应用、库和账户，错误环境请求拒绝。
- 普通集成在原锁上正式进入维护。格式 2 停写资料完成原键索引、可移动封存、异目录拷贝、内容和原键验证。备份清单 `630290b34e82829a9ed0c7eda5141f234c1e08d7d75b9a0ba94fba108812f0d3`，从中读回原操作共 5 条。实际私有 WALL-E 恢复到另一代次，原正文与历史经 `LOCAL_VERIFIED` 通过，凭证 `76305d843d13a52901d9b09c27f16eec79c83bec3aaf0d74712f7c9cf01e8da7`。
- `record-release-compatibility` 从原普通集成和实际固定中转回读同结构凭证 `046edb6c34837efcf7f4a729dfe14b21e8643d391add253a6cdbb8beb2cf5a78`。经过定向反例和四类严格证据，`prepare-release-final-build`、`seal-release` 及 `candidate --require-release-evidence` 完成。封存候选 `ae393b5227f2e12ca173efa04aca16fe33000ed825ef3b025dd2a32d08d37c3c`，原中转工件保留。错摘要、错目标索引以及重复引用不生成最终输出。
- 首次维护前置测试计划误把私有恢复策略文件的摘要写进可移动备份验证策略引用。实际产品以 `BACKUP_PACKAGE_INTENT_MISMATCH` 拒绝，原关闭控制及数据保留。在停机来宾的独立只读继承盘复现后，用两个实物分别校验各自路径和摘要，仅修正测试计划。实际原程序 `check-release-preflight` 连续两次同回执通过，摘要 `b0bd419d728994c97e85b432a6f28d76c6781b43c1ebc508b8d38167746f2e5c`。
- 按真实封存候选及兼容凭证运行 `prepare-release-deployment`，重复取得原回执。错前置摘要的 `select-release-deployment` 被拒绝并保留控制。正确摘要进入 `RELEASE_DEPLOYMENT_SELECTED_CLOSED`，重复选择读回同回执。新部署根和部署 ID 独立，原环境 ID、数据代次、稳定锁和数据库文件身份及字节保留，未监听应用 socket。关闭选择来宾退出 0。供下一阶段复核的测试交接摘要 `68cf19fe3810c18e201eb0f48fa892ffed7f2667a0b8367db14e610c4e70195d`。

## 冷启动后的私有验证拒绝

从实际选中部署启动独立无网继承盘。现有 `verify-release-deployment` 以 `RELEASE_VERIFICATION_UNVERIFIED` 保持关闭，未写出新的私有凭证，普通 socket 和私有核验 socket 均未建立。原程序以独立身份直接运行原私有核验，退出 3。其 `snapshot_signature` 在检查 SQLite 边文件时拒绝。只读查看实际盘确认主库 inode／设备身份与原切换记录一致，主库摘要及关闭控制保持，旁有 0 字节 WAL 和 32,768 字节 SHM。旧提交的关闭覆盖使用普通只读事务，原选择分支缺少当前实现的边文件检查。此项保留为旧真实提交的拒绝证据；本机正向联验另从当前普通环境产生原始干净数据和独立封存候选，避免改动失败现场。

本记录覆盖独立候选、私有恢复、维护前置、实际关闭选择及含边文件的后续拒绝。网关开放、最新受信集成交付、真实异机仓库及生产另验。
