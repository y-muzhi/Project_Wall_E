# Mac 开发虚拟机 OpenAI 出口验证

2026-11-27（香港时间）。Mac 用户启用代理 VPN 后，在 Mac 及 Linux 开发服务身份下重新核对。Mac 直接 TCP 443 超时，Loopback HTTP 代理 7890 的 CONNECT 及证书校验通过。Linux 以 `w22devapp` 执行固定 Python 3.13，解析成功，IPv4 TCP 超时，IPv6 无路由。

从独立检出 `.tmp/v22-document-ai` 将 `tools/linux_runtime/mac_openai_proxy.py` 通过已有 SSH 标准输入运行在 Mac 的 VM 专用网桥上，先后两次在到期后退出（45 秒、35 秒）。开发账号通过该转发连接 OpenAI 后完成 TLS 1.3 握手，对其他域名的 CONNECT 收到 403。开发账号侧使用 `http.client.HTTPConnection.set_tunnel` 与默认 TLS 信任库。通过 Ruff 检查、格式检查及 `git diff --check`。未发送供应方 HTTP 请求或读取密钥。Linux 回环 socket 与 `systemd-socket-proxyd` 单元在 Linux 临时目录通过 `systemd-analyze verify`，临时文件已清理。

实机核对临时监听已退出。自动审批拒绝加载长期监听网桥的 LaunchAgent，Mac 未加载该服务，Linux 亦无新增回环监听。开发、集成及网关均保持原进程运行。常驻获准后，应先用 Mac 用户域启用专用转发，再接 Linux 的回环入口，以开发账号重复 TLS 和域名限制检查。开发服务固定配置及网关切换按原换代准入执行。
