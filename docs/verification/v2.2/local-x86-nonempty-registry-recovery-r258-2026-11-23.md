# R258 非空管理登记的 Ubuntu 恢复和原请求读回

2026-11-23，独立 `codex/2.2`。依据 V2.01 后端 4.12.3、6.5、7.9。Ubuntu 24.04 x86_64、ext4、systemd 255、固定 CPython 3.13.18／SQLite 3.54.1 和 Caddy 2.6.2。准入运行清单 `aab55f5775aad86fbe17ca3a5d4a40fbaf573d30a26789f27a4eb97d9e23823e`。普通 Schema 对象契约 `ed057e0ddadbcdbb47bd8e78c541cf009fd719c397ffe79579d3ae2684802fc3`。实际产品验证无网卡，管理 HTTPS 仅在来宾回环 9444。构建阶段从公共 Ubuntu 仓库取得构建工具，之后用离线已核验的 31 个 wheel 完成准入。

- 开发和集成分别用独立应用／维护 UID、数据根、程序根及原 Git 工作树。正常普通 API 分别创建需求和文档并停到 `NORMAL_STOP`。实际固定 `observe-attach` 读回完整工作树，管理 HTTPS 接受两次 ATTACH 并验证同键回放。以新鲜宿主控制观察受理 START，真实 systemd 单元、应用握手和管理回执成功。
- STOP 进入实际持久 `DISPATCHING` 后，只在本测试来宾以 pidfd 短暂停住所属根工具进程，正常管理 RECONCILE 读到 `UNKNOWN`，同键返回原结果。恢复该工具后原系统服务正常退出并生成 `MANAGED_STOP_CONFIRMED`。旧管理操作保持 `UNKNOWN`。集成侧另一条 START 已正常受理并预留四项资源，宿主未派发。
- 对暂停状态生成格式 3 一致快照，快照回执 `fc0d11ea3df737cf8ce7ed5b5869d89b12d615df4d945f9bc56aa327c24e41c2`。通过真实新代次放置、WAL、清册和 33 条宿主观察完成关闭选择，回执 `46f9c92430c297fd709021182f2033d7db6f6d37da19c4bf6e3849b88f201a75`。新管理入口在暂停下正常只读访问。
- 开放检查列出两项未结操作及一项未结步骤。按原操作定位到 STOP 的 UNKNOWN 和 START 的 ACCEPTED，页尾无额外项目。提前开放回读相同阻塞摘要且保留原暂停。错误原意图摘要的处置拒绝。正确 `STOP_COMPLETED` 及 `UNDISPATCHED_RESERVED_CANCELLED` 完成后分别可按同一回执重放，四项加四项容量仅在新库释放，原快照仍保留全部未释放记录。
- 复核无阻塞后实际开放，回执 `10386f1a829852aaf9c015b660d05bc72dbd1528f01721855920cb846bd8affd`。管理 HTTPS 转为 `READY`，旧 STOP 的控制回执和原状态读回相同，另有已核验处置。旧原键改用当前代次提交仍返回 409 `MANAGEMENT_KEY_CONFLICT`，新代次没有重建原业务操作。原管理库、原锚归档和两套普通安装／控制／数据库摘要保持，来宾正常退出。
- 本次覆盖实际受管启停、停止效果已成的未知原操作和未派发预留。含已完成原备份效果、仍活跃任务、云端与生产另验。[R253 离线键契约](local-recovered-registry-key-r253-2026-11-23.md)
