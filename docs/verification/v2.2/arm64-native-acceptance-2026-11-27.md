# V2.2 ARM64/Linux 隔离验收补缺

2026-11-27（香港时间）。按 [V2.2 需求实现映射](../../traceability/v2.2/需求实现映射_V_2.2.md) 核对已有证据。Windows 主工作区为 `2fe9615`，同时复核了本机独立检出 `output/v22-dev-isolated` 和集成文档提交 `990ed2d`。受信候选 `27905ed` 已在同日 Mac 双站验收中使用。本轮新增试验仍使用独立安装，文档 AI 工作树和现行两站的数据与进程保持原位。

## Mac ARM64 实机结果

用户提供当前 Mac 地址 `192.168.31.160` 后，按已登记的 Mac 主机公钥通过 SSH 跳板，Linux 来宾也通过原主机公钥校验。实际为 `Linux aarch64`、systemd 255。固定候选 `27905ede384e7b1a216eb735c969825c31507141`、tree `783a92e96ceed8c79425c60394d7c8a03e9cd61f`。使用预发布固定运行包的只读程序和运行输入，运行包摘要 `f75a9b7da9e1e5249c372321e301a3b555373306bd9d9366b1d1a2a0f993959a`，CPython 3.13.18／SQLite 3.54.1。各场在独立临时根创建合成数据与测试进程。

| 验收场景 | 状态 | 实机证据及边界 |
| --- | --- | --- |
| 固定后端专项 | 通过，10 项跳过 | 固定解释器以 `-I -B -S` 准入并运行 `pytest -q -rs --tb=short -p no:cacheprovider --basetemp <独立根> backend/tests/infrastructure/test_v22_*.py`，25 文件，308 通过，10 跳过，9.92 秒，退出 0。2 项属于独立恢复副本，8 项需要 root 所有的隔离发布输入。首次 307 通过、1 项失败，因测试驱动未载入锁定的 pip wheel，补入固定运行包的 wheel 后全范围复验通过。 |
| 普通应用真实启停与隔离 | 通过 | `serve_environment.py prepare-start`／`serve` 各启动实际普通应用。双站独立保存、内容隔离和正常停止通过，单站经两次独立真实启动读回原文，错环境绑定拒绝。Unix 套接字退出后消失。 |
| 管理原 START／STOP、重启及结算回执 | 通过 | 由实际管理 SQLite 接受操作，固定 `manage_registry.py start-runtime`／`stop-runtime` 驱动两轮专属原生 systemd 活跃单元。第一轮 START `43262cd2-817d-4677-861f-fe47e55f1fde`、STOP `d18ccc8f-757f-43bb-9a14-0d7c5078ab02`。第二轮 START `2f73288a-392b-45a8-9339-adc5be104ab2`、STOP `b7d570a7-f1a4-46c3-b36b-e06253690817`。原生服务就绪后读取正文，按首轮停止凭证准入第二轮。按原操作重跑命令和交还管理结算均读回原结果，四项额度逐项关联原停止归还，套接字退出后消失。首次夹具无入口组，实际就绪准入拒绝。补齐入口组和测试对额度归还的断言后整条通过。 |
| 管理备份派发、原结果核对及恢复点登记 | 通过 | `manage_registry.py capture-managed-backup` 在真实管理 SQLite 的 `ACCEPTED/PLANNED` 记录上完成派发及停写库捕获。错计划返回 `DATABASE_CAPTURE_INTENT_MISMATCH`，真实宿主冻结返回 `HOST_RECOVERY_HOLD`，均保留原计划。成功后处于 `RUNNING/DISPATCHING`，实际 SQLite `integrity_check` 通过。宿主冻结后，同一原操作读回完全相同的捕获回执，无二次派发。另由同一物理捕获封包、实际只读恢复及 `complete-managed-backup` 得到 `MANAGED_BACKUP_LOCAL_VERIFIED`，管理登记结算为 `SUCCEEDED`。恢复点列表读到 `LOCAL_VERIFIED`，重复完成及结算保持同一结果。原操作 `ed574b27-1483-4c49-9b78-aef84d0cb6b2`，封包摘要 `9d39850b5e25e0909a92bb93dbbd1aa35fa901372995dc9d052383e5b93b7f8a`。夹具首次直接取维护身份所有的封包父目录，准入拒绝，改用 root 保护下的原字节独立复制包。 |
| 实际备份封包、旧结果及只读恢复 | 通过 | `environment-maintenance`、`capture-database`、`restore-database`、`seal-result-index`、`seal-backup-package`、`verify-backup-package`、`lookup-backup-result`、`rehearse-backup-package`、`prepare-recovery-replica`、`verify-recovery-replica` 均走固定真实入口。归档独立复制，5 条原结果索引，包摘要 `b8bc1ddf00cc81923c2325e7d2cb337dd093ee36918b93c073383e6c98f231f3`。错数据库摘要及错代次拒绝，原数据库、控制及封存包未变。专属进程复核正文与版本历史，保持外发冻结，签发 `LOCAL_VERIFIED`，摘要 `736be8dc487201a6245babb0ba4353b91d42b514c37523d99eabdec5504462b5`，同计划重跑一致。首次恢复夹具缺原维护绑定导致 `DATABASE_RESTORE_SOURCE_CHANGED`，补齐后整链复验通过。 |
| 原生 systemd 启动准备中断和原回执 | 通过 | 保留原 `ISSUED` 状态并实际运行生产准备命令，以新的观察过程接续 `finish_preparation(..., launch=False)`。原操作 `fe15c23e-129d-4b75-a8ed-da3e1db208fd`，InvocationID `1d574097ec7b4480ab150df3f17c2ce3`。错 InvocationID 被拒，原单元不受影响。原状态一次收尾到 `RELEASED`，单元和进程组退出，重复回读原回执 `3971ad34e3fe30ed4a05e9d84e804160231db2561762739d2c5497cd78e668dc`，未重新派发。 |
| 原生已就绪 START 撤回 | 通过 | 第三轮真实 START 已就绪，管理登记仍为 `RUNNING` 时以原控制键请求撤回。`cancel-runtime` 正常停止确切单元，管理状态结算为 `CANCELLED`，四项额度归还，Unix 套接字消失。重复原控制、宿主撤回和管理结算均读回原结果。原 START `418af5a1-d9c0-41bc-8d4c-d002ec549cbe`，控制键 `f0d41bd5-789e-4598-b489-7dbb1777f956`，停止观察 `44bc1731-7ab1-4fea-aca6-1910a7272bbb`。首轮独立账号号段映射错误，修正夹具后实际通过。 |
| 管理登记暂停、一致快照及新代次 WAL 准入 | 通过，限关闭阶段 | 固定 `pause-registry-dispatch`、`snapshot-registry`、`verify-registry-snapshot`、`prepare-registry-recovery`、`verify-registry-recovery`、`place-registry-recovery` 和 `ready-registry-recovery` 均通过。原暂停可重读，原登记锚及 SQLite 摘要不变，新数据 inode 独立并复用原稳定锁。新库完整性检查通过，读回原已成功备份，日志模式为 WAL。快照回执 `6641d460ee0a1347506d253841e8737c166190c8a38cd8b67f4f1ac0232207d8`，新登记代次 `a3693d3d-8714-4850-87a6-d9bc38c41e21`，WAL 就绪回执 `f84a3b9056e5275a4a109f1b1b88208510cd5972d2df74f0a6ed72ea152e8bbc`。管理入口采用与派发复开留待另验。 |
| 新管理登记清册、宿主观察及关闭采用 | 通过 | `inventory-registry-recovery`、`observe-registry-recovery`、`select-registry-recovery` 使用真实安装及同一原暂停。在隔离根原子切换活动锚，原登记库字节及稳定锁保留，新代次仍报告暂停。三步均重读原回执。清册 `96c6a050e1a6774a843aec799d7ea62172e331010768ab2e7602f05f814a4de9`，观察 `cb0476f7cda06a76de5fdf7440d856e0e6a3e8bfa026031a6eea10a048d5f777`，选择 `429125786dc9dae834ce945776f364f76ef58e616ea9919d8020da3603e04be9`。新管理站 HTTPS 入口采用及恢复派发未执行。 |
| 普通环境正式恢复前置、独立代次及关闭选择 | 通过 | 源库后续新写入与已选历史封包区分。真实停写、原现状保全封包、`check-restore-preflight`、`prepare-restore-data`、目标绑定的只读正文及历史核验、`prepare-restore-generation`、`prepare-release-deployment`、`select-release-deployment` 通过。目标属同一环境，稳定锁保持、数据 inode 独立，原源库字节保全，目标保持外发冻结。普通关闭选择摘要 `2e6c5dd58313b9957049a98e45df338f55c56d062817faa17d59dbb89e030bee`，实际新代次 `63ebe65f-4681-4214-ad93-1d6f9de7bfe2`。使用隔离测试候选准入记录，源码、前端、Schema、运行包及数据库均实物核对。早期夹具错误涉及保护父目录、备份验收摘要的引用以及宿主调用解释器，均修正后实测通过。 |
| 选中恢复目标的实际关闭核验 | 通过 | `verify-release-deployment` 启动隔离私有只读进程，核对选中库的正文与历史。`verify-release-gateway` 使用实际 Caddy、证书与监听进程验证固定资产和关闭入口，同伴站点仍然读得到，关闭目标的业务 API 为 502，错凭据为 401。缺少旧数据隔离属性的直接开放被 `RESTORE_RETIRED_DATA_ACCESS_UNVERIFIED` 拒绝，目标仍保持关闭。 |
| 同一 HTTPS 来源采用新代次并实际开放 | 通过 | 专属 NSS 账号的 transient systemd 单元启用生产 `InaccessiblePaths` 等隔离属性，加入测试 Caddy 的网络命名空间，执行 `serve-release-open`。原环境和 HTTPS 来源不变，`/api/v1/environment` 返回新数据代次 `d396da81-84fe-4710-b452-e35ab269f42d`，正文从选定封包读回，源库较晚内容保留在源库。旧代次真实请求返回 409 `DATA_GENERATION_MISMATCH`，外发冻结保持，同伴站点持续可读。正常停止后入口返回 502，原开放凭证仍可读，摘要 `da2be043465a2867f84f4fea39166c4e1f44c2c471b0c92ff5fffdafa501cac2`。systemd 首轮因测试 UID 未在 NSS 登记返回 217，补建专属账号后通过。 |
| 真实服务端换代后的旧草稿与新标签 | 通过 | 用 Playwright CLI 驱动 Windows 独立 Chrome，经临时 SSH 转发接入隔离 Caddy，浏览器固定测试站点证书公钥，Linux HTTPS 客户端另走严格 CA 和 SNI 校验。原真实应用读入已保存正文并建立人工草稿。只在浏览器端注入草稿 PUT 网络中断，旧标签可见未同步文本。服务器实际完成数据换代并在同一 HTTPS 来源开放后，旧标签重新核对，提示数据代次变化，导出原草稿包含原代次与未同步文本。独立新标签读回选定封包正文。新代次 `5dc4f7c5-a781-4219-b41d-a7e2b82851d6`，开放回执 `4f7086c011fdfcd3045d4b55aaabb307a7312f59bf80b9e69f29bc29372b0bd3`，实际关闭后原回执仍可读。未拦截或替换入口、握手或换代响应。 |
| 恢复后的普通重启和保全 | 通过 | 恢复应用经实际 `NORMAL_STOP` 后，再用 `prepare-start` 和受隔离 systemd 中的普通 `serve` 启动。新 run `d70304cb-f80e-4425-8868-207f835d71d7` 仍绑定已选代次 `ed4f49ca-518f-43c2-9804-9f4e3812f12d`，严格 HTTPS 读回选定正文，外发冻结与源库原字节保持。旧开放回执文件原字节摘要 `2dba11e1a00282287777c43cdf4b392e6abd6ed8d88d8cd39fe9a3441719b338` 未变。首轮夹具在新 run 后用现场观察入口查询旧 run，收到 `RELEASE_OPEN_UNVERIFIED`。改用独立读取原回执文件后整链退出 0。 |
| 固定 Restic 快照本地取回 | 通过 | 在隔离根下载官方 Linux ARM64 Restic 0.19.1，压缩包 SHA-256 `a5f64aaab53d51e311fa3829124c5b703f2d14cf187d8640b6be3b2b49376465` 匹配。移开原复制包，以固定 ID `94846b8abefc9a8ed6f9a3314e57dccb214ef51c62e98ee6fc1cab78dbf96227` 走 `retrieve-backup-snapshot`，`LOCAL_SNAPSHOT_RETRIEVED`，18 项，原清单摘要 `0302904481ab3baa401bec9af8025e253570e653b4a0b192d0897d4ac6a67a32` 匹配。下载首轮缺 `bzip2`，改用系统 Python 标准库解压。一次 35 秒下载超时，延长到 150 秒后通过。异机和 COS 留待另验。[官方发布资产](https://github.com/restic/restic/releases/expanded_assets/v0.19.1) |
| root 所有的固定输入破坏矩阵 | 通过 | 单独以 root 身份运行 `test_v22_linux_runtime_targets.py -k indexed_runtime_checks_every_entry`，8 项通过，覆盖正常、改字节、权限、符号链接、目录链接、硬链接、未登记文件及缺文件。初次清理因 root 测试子目录而未完成，复核路径和所有权后定向清理。 |
| 真实 HTTPS 基础路径 | 通过 | 以 `PrivateNetwork=yes` 单独启动 Caddy 2.6.2、测试 CA 和两个真实应用。通过项目 `site_block` 生成保护配置，严格校验 SNI、Host 和证书，双站前端、公开配置、同源 API 和各自正文通过。另一站账号 401，提交旧绑定 409 `DATA_GENERATION_MISMATCH`，系统默认 CA 不信任临时 CA。首轮测试驱动用错预期错误码，按正式契约修正后双站完整通过。同日真实浏览器编辑及整机重启读回已有证据。 |

管理捕获夹具首两次分别在端口白名单及预期拒绝的 stderr 读取处停止，修正测试驱动后复验成功。现行开发、集成、网关 PID 在每次实机隔离演练前后均一致。没有调用模型或计数 API。

收口复查实际服务 `walle22-mac-dev`、`walle22-mac-int`、`walle22-mac-gateway` 均为 `active`，主 PID 分别为 678、679、707，与验收前一致。现行 HTTPS 保持在 Linux `127.0.0.1:9443`。本轮的 transient systemd 单元、测试用户和组、Linux 隔离根、Windows 独立浏览器资料、转发监听及 25 个临时脚本均已清理。仅保留 Markdown 证据及索引，开发站切换窗口无需占用。

## 初次连接与交接输入核对

| 检查 | 状态 | 实际证据 |
| --- | --- | --- |
| Windows 到 Mac SSH 跳板 | 失败 | 在获准联网的执行环境，以 `BatchMode=yes` 和严格主机密钥校验直连 `walle-mac`，TCP 22 超时，退出码 255。`ssh -v … walle-linux exit` 显示嵌套 SSH 停在连接 Mac 跳板。经跳板复查仍在 SSH 标识交换前超时。 |
| Linux 来宾身份、运行包和隔离资源 | 待验证 | 未取得 `uname -sm`、systemd 或 Caddy/Restic 输出。未在宿主启动测试进程、写入文件或读取业务数据。 |
| 初次连接期间的原生产品场景 | 未执行 | 后续恢复连接后的结果见上表。 |
| Windows 交接输入完整性 | 通过 | `Get-FileHash -Algorithm SHA256` 逐项复验 `output/v22-mac-linux-handoff/SHA256SUMS`，79 项通过。`git bundle verify` 通过，包含完整历史与开发／集成两条引用。`git rev-parse '27905ed^{tree}'` 得到 `783a92e96ceed8c79425c60394d7c8a03e9cd61f`。 |

换地址前复查 `walle-linux` 仍在 SSH 标识交换前超时。`ping -n 2 -w 1000 192.168.31.142` 一次由 Windows 返回目标主机不可达、一次超时。直连旧 `walle-mac` 地址的 TCP 22 再次超时。按用户提供的新地址临时覆盖跳板目标并保留原主机密钥校验后恢复连接。

## 接手时的证据边界

| 优先项与映射条目 | 接手时已有实机通过范围 | 接手时的缺口 |
| --- | --- | --- |
| 1. 普通受管启停与回执，M11–M13、R48–R50、R144–R145 | 旧固定版实际 systemd 启动、正常停止、重启和原结果管理页读回。[M11](linux-runtime-stop-m11-2026-11-20.md) · [M12](linux-runtime-start-m12-2026-11-20.md) · [M13](linux-management-lifecycle-m13-2026-11-20.md) | 最新候选从管理受理到真实派发，核对私有回调解释器、原单元/cgroup、Unix 套接字、原回执、额度释放及重启读回。 |
| 2. 中断、撤回与登记恢复，M17–M23、R121–R133、R135–R136、R140–R156 | 旧固定版 READY 撤回和未派发恢复通过。M23 的真实撤回、原回执读回与单槽并发通过。[M17](linux-managed-cancel-ready-m17-2026-11-21.md) · [M18](linux-managed-cancel-unissued-m18-2026-11-21.md) · [M23](linux-r7-m23-results-2026-11-21.md) | 在隔离新登记下分别验证未派发、准备中、已停止待结算、已开放待结算，核对原单元和额度。模拟首次回执丢失，按原键只回读。未知效果须保留原暂停和额度。完成原停止及结算后再复开并重启业务。 |
| 3. 普通备份、取回与恢复，R14–R23、R51–R54、R70–R75、R77、R91 | 旧固定版 R7 已通过停写捕获、审计缺失/空/有内容、新代次准备、同意图续跑与篡改拒绝。[R7](linux-r7-m23-results-2026-11-21.md) | 实际管理备份派发和完整包封存，从独立临时 Restic 仓取回固定快照。核对 SQLite、审计及旧结果索引，启动专属 `RECOVERY_ONLY` 副本验证正文、历史、拒写和外发冻结。在隔离目标完成新代次选择、普通开放及重启读回。异机或 COS 取回证据另列。 |
| 4. 真实 HTTPS、工作台及恢复换代，C8、R32–R33、R75、R109、R120、R138–R139 | 旧固定版两站通过原生 Caddy TLS、认证、来源绑定、实际页面与同代次服务重启。[Caddy](linux-caddy-gateway-c8-2026-11-20.md) · [Firefox](windows-firefox-https-c8-2026-11-20.md) | 独立 Caddy 连接最新候选双站的 Unix 套接字。验证受信 TLS、同源页面和 API、交叉绑定拒绝、断线重接、真实服务端换代后的旧草稿/回执保全，以及管理新入口的只读和复开。 |

## 前序证据

- 同日另有 `27905ed` 的 Mac Multipass Ubuntu 24.04 ARM64 隔离首场。两站分别保存不同正文，单边正常停止时对端继续读，双向重启各自读回，交叉绑定 409，跨站凭据 401。Windows 经 SSH 回环转发，用真实 Chrome 在两个受信 HTTPS 来源编辑保存并刷新读回。随后 Linux 来宾整机重启，三个 systemd 单元自动恢复，Caddy 仍只监听回环，两站经严格 TLS 取得新 run ID 并读回各自正文。来源为独立检出中的 `mac-linux-dual-switch-2026-11-27.md` 和 `mac-linux-service-reboot-access-2026-11-27.md`。
- R535 已在无网 Ubuntu 24.04 AArch64 QEMU 来宾通过实际停写捕获、封包、独立搬移、五条结果索引、恢复演练和私有只读进程。固定 `verify-recovery-replica` 得到 `LOCAL_VERIFIED`（摘要 `cc018bc558074d2da284c5368ecae3d729021761b9687a3cdb5011e423b7d586`），同计划重跑一致。R467 在仿真来宾通过 304 项固定后端专项、2 项平台跳过。来源为 `990ed2d` 中的 `local-arm64-template-recovery-and-twin-ordinary-r535-r537-2026-11-26.md` 和 `local-arm64-native-regression-r467-2026-11-25.md`。

## 仍待验证

- 恢复后的管理站入口采用、实际派发复开，以及登记恢复后的已开放／已停止待结算等完整变体矩阵。已通过的是独立管理登记的原生清册、宿主观察和关闭态采用，以及原生正常启停与撤回场景。
- 普通应用换代后新写入、保存、采用及同键重试的完整矩阵。已实测新代次开放、重启读回和退役数据隔离。
- 实际异机或 COS 备份取回、正式发布候选准入与生产发布。换代联演的候选准入记录由隔离夹具提供，实际固定程序、数据库、操作回执、网关和浏览器结果见上表。
