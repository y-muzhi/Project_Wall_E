# V2.2 开发站文档 AI 实际切换

2026-11-27（香港时间）。用户授权登记和切换真实开发站。使用 Mac Linux ARM64 固定运行时和 SQLite 3.54.1。原开发站有 2 项需求、3 份文档（含 1 份已保存的人工草稿）、4 条版本记录及 0 个 AI 运行。核验期间只读访问正文，记录保留摘要。

## 第一候选与现场回退

- 提交 `2f83300` 的候选 `73a0b4f6-c9e5-4b8f-ae55-bdee49259b98` 已登记并封存。现场使用 `environment-maintenance`、`capture-database`、`check-backup-coverage`、`restore-database`、`seal-result-index`、`check-recovery-chain` 和 `seal-backup-package` 完成停写保全。`check-restore-preflight`、`prepare-restore-data`、`prepare-recovery-replica`、`verify-recovery-replica`、`check-restore-readiness` 证明当前内容可转换及从独立只读应用读取。
- `prepare-restore-generation`、`prepare-release-deployment`、`select-release-deployment` 与 `verify-release-deployment` 在实际开发站闭态通过。开发站和集成站的独立固定运行时经网关工具分别校验。实际 Caddy 同时服务两站，新旧哈希静态资源及闭态 API 通过 `verify-release-gateway`。集成应用进程与绑定保持原值。调整共用 Caddy 配置时有短时 HTTPS 重连。
- 早期窗口在预检时间格式、保全脚本和固定解释器处中断，现场恢复原服务。首次已选目标因保留数据目录未全部纳入应用隔离被拒绝，补齐隔离后发现固定程序把文档 AI 启动错误地绑定到 `recover_on_start`。恢复发布首次开放需要暂停任务恢复，因此启动返回 `CONFIG_INVALID`。每次选代后的失败均使用 `DOCUMENT_AI_RESTORE_REVERTED_CLOSED` 返回原控制，原数据及已准备数据代次均保留。该阶段核验原站重新开放。

## 修复候选

本地提交 `45a9fd8` 将首次开发站开放与任务恢复分开。首次开放仅使用绑定到目标代次的文档 AI 策略，采用持稳定锁的 SQLite 只读事务核对资源与供应方证据。原冻结数据库在正式开放前保持无 SQLite 边文件。双站网关分别验证各自固定运行时。真实模型和计数 API 的调用次数均为零。

最终提交 `6c2c8edf2203a671e7b568ff413f249f1b1b39a6` 保留只读查询的列名访问。以 Mac 固定运行时执行 `test_v22_document_ai.py`、`test_v22_document_ai_cutover.py` 及 `test_v22_release_open_history.py`，22 项通过。开发交付 `a1c8864b-8827-4c08-aca0-b88f5fcac4f0` 和集成交付 `0f7619e2-0e69-4fd8-a6da-913bfff82579` 已登记。固定包 `107d0a48-bc65-48b9-8931-d1c327b96652` 的封存清单 SHA256 为 `1fa72d0f5fac9ce41c7714eedbfbb7ace9de5e7b858b83eea515eb2de4db2c62`。构建、原生应用两次启停与数据读回、Chrome 实测和备份恢复四类证据均已登记。目标数据代次 `bd77f69b-9616-40ef-be2c-1633d499d587`，目标部署 `8f5be84f-50cc-4141-b6ad-b32a983460d0`。


## 实际开放与验收

- 第一次使用最终包开放时，部署配置从默认模型资源误取了文档摘要，实际启动准入拒绝，按闭态路径回退。重新从 OpenAI 目录固定讨论 openai-v6 和文档 openai-v8，离线预检两套准入通过。复用同一已封存程序。
- 实际切换操作 48ddbe79-6bbd-416a-83cc-1502fadcc9bc。原库停写保全包编号 2143d73a-b9da-43d7-8d42-8121476e6548，清单 SHA256 为 439750c4e7b97e479ac396f7ab7ce51781bbcb13f9e8e54e440639967cb70a6f。独立只读检查、目标代次就位、闭态部署与实际 Caddy 网关检查通过。
- serve-release-open 开放原开发 HTTPS，observe-release-open 返回 RELEASE_OPEN_CONFIRMED。开放回执 SHA256 为 d9ed2a1cc9f8c1876b44e68bbaf5db1673d39c6744d726c53f89fc134b0a6286。开发站实际代次为 16de419a-8baf-48e8-9982-00d7231dba81，部署为 9ff3eb9c-530a-41ce-a14f-aa24f11606b9，运行 ID 为 9e6801b3-baf5-4e43-b3e8-593abba88f56，开放控制修订 78。
- Chrome 在两个原地址加载需求工作台。Windows 默认转发端口已占用，本次使用单独的临时转发并已关闭。实站同源 API 读回开发正文，摘要与封存验收一致。对比切换前后数据库逐行一致，共 2 项需求、3 份文档（含人工草稿）、4 条修订、1 条草稿上下文及 3 条人工编辑会话。旧开发代次和错环境请求分别返回对应的 409，开发只读账号的文档 AI 准入关闭。
- 开发编辑账号返回 DOCUMENT_AI=READY。集成应用进程、部署、数据代次及 AI 能力保持原值，共用 Caddy 切换配置时短暂重连。开发、集成、网关、代理的 systemd 单元均为 active，开发、集成及网关的静态校验和开机启用通过。本轮保持实际开放后的进程运行。
- 开发应用账号经 Linux 127.0.0.1:17890 到 OpenAI 的服务器证书验证和 TLS 1.3 通过。未发模型或计数 HTTP 请求，开发库 guide_runs 和 llm_uses 均为零。供应方真实输出仍待专项授权。

用户随后确认开发站文档 AI 验证通过，并启动代码开发及测试验收接入。该确认作为用户验收记录。本次执行未收集用户验证产生的供应方回执。
