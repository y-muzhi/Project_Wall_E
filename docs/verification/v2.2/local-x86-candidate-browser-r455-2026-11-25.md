# V2.2 R455 固定候选的真实浏览器流程

2026-11-25（香港时间）。独立 Ubuntu 24.04 x86_64、ext4、无网络适配器、无宿主端口转发。使用原已存在的集成交付及 R457 固定应用和前端。候选实际业务流程和索引见 [R457](local-x86-release-source-binding-r457-2026-11-25.md)，双独立前端构建及同一索引见 [R461](windows-fixed-frontend-twin-build-r461-2026-11-25.md)。

- 先以同一候选的实际应用及固定 Linux 运行工具经 Unix HTTP 创建需求和文档并保存。以产品 `environment_gateway.py` 从真实候选安装生成 Caddy 配置。Caddy 独立低权限身份只监听来宾回环 9443，测试 CA 仅在本轮独立浏览器信任库。以实际 TLS 校验证书、主机名、未认证 401，浏览器不忽略 HTTPS 错误。
- 经专用用户、独立临时资料、实际 Playwright CLI 0.1.25 和官方 Google Chrome 158.0.8127.88 运行。稳定版 Debian 包通过官方 APT 主密钥和索引 SHA256 验证，包 SHA256 `a656b2db00a8cb7f13a1d754f6aad91f84014906452c6dfb7f3ead93035da03b`。依赖下载来宾无项目资料，仅校验公开包转入无网验证来宾。 [Google Linux 软件包签名](https://www.google.com/linuxrepositories/)
- 初用 Chrome for Testing 159 Headless Shell 被 Ubuntu 拦住用户命名空间。稳定版位于发行版现有 AppArmor 配置匹配的路径，内核限制值仍为 1，浏览器启用沙箱。实际 `chrome://sandbox` 显示第一层 Namespace，PID namespaces 与 Seccomp-BPF 为 Yes。 [Ubuntu 24.04 原发行说明](https://discourse.ubuntu.com/t/ubuntu-24-04-lts-noble-numbat-release-notes/39890) · [Chromium 沙箱说明](https://chromium.googlesource.com/chromium/src/%2Bshow/4d2a0479fdeac1ed92a5f8dc0964fa247a6ee0bd/docs/linux/sandboxing.md)
- 从候选 HTTPS 打开真实需求，看到原正文，点击“更多操作”“人工编辑”，输入本轮标记并点击“完成编辑”。实际业务 GET 确认新正文，浏览器刷新后再次看见同一正文，业务再读一致。测试专用浏览器、Caddy 和应用随各自安全清理退出。
- 早期验证夹具误用了旧快照、CLI 参数或沙箱状态表旧标签，改用当前快照及实际标签。PID 22316 来宾已输出完整的浏览器成功事实，随后的独立集成站夹具因测试目录名称重用退出，例证在浏览器和服务已结束之后。目录名称隔离后继续整套 R460。

本轮覆盖固定候选的本机浏览器交互。目标部署和生产采用各自单独取证。
