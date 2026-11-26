# R192／R193 本机 Ubuntu x86_64 双普通 HTTPS 环境

2026-11-23，独立工作区 `codex/2.2`，Ubuntu 24.04 x86_64、ext4、systemd 255 和本机临时虚拟机。固定运行包摘要 `f6e9721719dbf3cea5c37f69d67d16b265e9a349b69d33839fc5e630cb83786a`，Python 3.13.18、SQLite 3.54.1、31 个锁定 wheel。精确验证子集源归档摘要 `eb3fb616f8b03a8f5f1cf26c1ddd7b4d6abda2abf52a7619d2040adbd29f6844`，Schema200 清单摘要 `1cf399d51321e49b6beea162cca312baabe69f62a6e9d8f53769e81518e0bad6`。普通前端使用现成隔离普通产物 `output/build-codex-2.2-r184/ordinary`。

- Ubuntu 公开仓库 Caddy 2.6.2，软件包及提取后二进制的 SHA256 分别为 `3a71aa97c7d85ea7a285717601306bf45d6f701073875ab689e893fabf6a819c` 和 `9681d054b6e5137d53f6d027188b349e0603fd12ea6334bd0d49da6755432f1b`。初次虚拟机在线取 PyPI wheel 超时。以从官方元数据和字节核对的 31 个 wheel 重用清册离线安装，`runtime.py probe` 准入通过。 [Ubuntu Caddy 软件包](https://packages.ubuntu.com/noble-updates/caddy)
- 运行固定 `runtime.py build-schema`、普通安装 CLI、`runtime.py environment` 和 `serve_environment.py`。两套环境各有程序、应用和维护 UID、连接组、数据库、访问策略和静态索引。通过正式 `environment_gateway.py --site` 从两份实物锚生成一个受信网关配置。修改测试副本的第二套程序字节后，生成器拒绝并未发布错误配置；原字节恢复后启动网关。
- Caddy 以独立非 root 身份运行。TLS 仅监听虚拟机回环 443、9443，TLS 客户端显式校验临时 CA、SNI 及主机名。不修改 Windows 信任链、网络服务或端口。与 `gateway_process` 和 `assert_gateway` 核对真实 PID、启动时间、boot ID 和两枚不同监听 inode；错端口回执拒绝。
- 未认证页面和错环境凭据返回 401，另一站资产返回 404，应用关闭时认证 API 返回 502。正式凭据读取器使用受保护、固定摘要的配置核验独立只读自动化身份。代理拒绝来路冒充，实际握手保持只读；尝试写需求返回 403，错误来源返回 403，错误环境绑定返回 409，同源 WEB 握手通过。
- 两站真实 HTTPS API 各创建本库编号为 1 的需求和文档，并分别编辑保存。正常停止后再次以新运行 ID 启动，读回各自正文。程序确认所属 Caddy 和应用进程退出，Unix 套接字及回环端口释放；测试虚拟机无宿主端口映射。该停机镜像的增量副本供本轮实际备份验收。
- 本次使用真实 TLS 客户端。当前候选浏览器交互、完整受管发布切换、异机 Restic／COS、ARM64 最新候选和生产接入分别待验。
