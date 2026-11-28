# V2.2 开发站代码开发与测试验收基线

2026-11-27（香港时间）。开发站运行固定提交 `6c2c8ed`。用户确认文档 AI 可用并启动本轮接入。真实模型和计数未由本轮操作调用。

- 从 V2.01 后端 6.1、7.11、8.2 和前端 4.2 核对开放条件。实际发布在浏览器握手、业务方法清单及页面路由均关闭代码开发和测试验收。原页面可从 Git `e26466c` 复用。
- 本地独立分支 `codex/v22-development-checks` 已按独立的 `INTERNAL_EXECUTION`、`INDEPENDENT_CHECK` 握手状态接回原有页面组件和深链接。当前开发站仍会收到禁用状态。`npm run typecheck`、`npm run format:check` 和设置 `WALLE_OFFLINE_TEST_PYTHON` 后的 693 项前端回归通过。
- 在 Mac 固定 Linux Python／SQLite 和隔离数据上执行任务角色链、任务启动、交付、测试计划、测试任务、CLI 与报告回归。第一次缺夹具环境变量 `WALLE_CHECK_TEMP`，补齐后实际 15 通过、11 失败、10 个准备错误。代码启动／交付及 CLI／浏览器检查夹具在 Windows 私有路径准入处拒绝 Linux 路径。测试授权创建先调用 Windows `current_operator_sid`，真实服务端适配须取受信业务身份并执行授权检查。
- 现有开发与集成服务均 active。共用来宾为 ARM64 Ubuntu 24.04，systemd 255、cgroup v2、AppArmor 已有。其内核转储正在通过 `/usr/share/apport/apport` 管道，当前执行角色缺少在读取秘密内存前排除的证据。未见已安装的固定 OpenCode、runsc 或 Chromium 执行包。
- Mac 上新建独立 ARM64 Ubuntu 来宾 `walle-v22-native-lab`。镜像校验 Canonical 固定 SHA256 后启动，没有复制现站业务数据或模型凭据。来宾使用普通文件转储路径，受限探针实际验证了 Unix `SO_PEERCRED`、pidfd、systemd 单元归属、`NoNewPrivileges`、禁用核心转储、无交换及禁止互联网套接字。两组同 UID AppArmor 测试角色可读各自文件，访问对方文件被拒绝。完整 P2-a 秘密控制器未覆盖。
- 独立来宾固定合成仓库提交 `c695ec3808f39ca8a28b596e0425329f85a9dd5d`，由受限 systemd 角色从只读测试夹具运行 `python3 -m unittest`。实际运行一项用例通过，角色无法建立互联网套接字。此项是 CLI 执行证据，应用任务、报告和验收回执仍待验证。
- 在 Mac 固定运行时的隔离副本中，访问策略、恢复、文档 AI 原有离线流程、Coding 授权和零预算 Testing 授权共 99 项通过。验证了拒绝伪造身份头、缺少 `MODEL_AUTHORIZE`、只读身份、带预算的测试批准和另一主体重放。通过的批准记录绑定环境 ID、主体及原访问策略摘要。批准 API 使用隔离夹具提供经准入的主体，实际开发站继续使用原发布记录。
- 固定 `runsc release-20261116.0` 通过官方 ARM64 归档校验。实际 systrap 使用无网络、只读根、UID 1501 和无额外 capability。合成 Git 提交 `87233ebb606cd1bb50eb9ce8269346475e205c66` 的只读内容检查通过，候选写入被拒绝，挂载外哨兵不可见。复跑核实命名空间及临时目录已释放。Docker 集成、项目检查 HTTP／浏览器及权威报告仍待验证。
- 固定 OpenCode 1.19.5 通过官方 ARM64 归档校验。在仅回环网卡、非特权、独立 HOME 下通过健康检查、未认证访问拒绝、会话创建／读取／更新／退出及 `prompt_async`。单个回环模拟供应方流式响应经原会话消息读回。未使用真实凭据、模型或计数 API。此项尚未接入 WALL-E 原 Coding 任务、费用许可、候选交付和管理恢复。
- 在试验来宾使用官方 Playwright 1.58.0 ARM64 wheel，PyPI SHA256 `8f9999948f1ab541d98812de25e3a8c410776aa516d948807140aff797b4bffa`，驱动自带 Node 24.13.0。Chromium headless 构建 1208 的下载实测 SHA256 `6bdb4349429ec33e7c0267e0eaa039c2131fa0b3b2997dec0ec96b0d40f579fd`。补齐八项直接缺少的 Ubuntu 共享库后，ELF 静态依赖无缺项。
- Playwright 初次以 Chromium 沙箱启动被实际 AppArmor 名称空间策略拒绝。仅对实验来宾 root 所有的固定可执行路径临时配置 `userns`，在 `chromiumSandbox: true`、无新权限、仅回环和私有 128 MiB `/dev/shm` 下读取合成应用 HTTP 200、点击按钮并断言结果。结束后删除临时规则，系统级限制值为 1。此项未覆盖 WALL-E 候选页面、可信结果通道或报告回执。[Playwright 固定版本清单](https://github.com/microsoft/playwright/blob/v1.58.0/packages/playwright-core/browsers.json) · [Chromium AppArmor 说明](https://chromium.googlesource.com/chromium/src/+/main/docs/security/apparmor-userns-restrictions.md)
