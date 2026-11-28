# Mac 至 Linux OpenAI 常驻代理实机验收

2026-11-27（香港时间）。按用户授权，在 Mac 的 VPN 用户图形域和 Linux V2.2 开发来宾安装[运行手册](../../operations/v2.2/Mac至Linux开发环境OpenAI代理_V_2.2.md)中的代理。Windows SSH 以单次 `HostName` 及 `ProxyCommand` 覆盖连接 `192.168.31.160:22`，保留原受信主机密钥别名及严格校验。Windows 的永久 SSH 配置无需参与常驻代理转发，本次使用命令行覆盖。

- Mac `local.walle22.dev-openai-proxy` 由 VPN 所在的 `gui/501` 管理，仅监听网桥 `192.168.252.1:17890`，使用 ApexCore 的 `127.0.0.1:7890`。来宾到网桥的实际源 IP 为 `192.168.252.2`。Mac 安装命令末尾因 PowerShell 标准输入添加的回车报告退出 127，随后用 `launchctl print`、`lsof` 和暂存文件检查确认安装成功且暂存已清理。
- Linux 两个单元通过 `systemd-analyze verify`，`walle22-dev-openai-proxy.socket` 已启用并仅监听 `127.0.0.1:17890`。WALL-E 开发、集成及网关仍为原进程 PID `678`、`679`、`707`，均为 active。

| 阶段 | 实际复验 |
| --- | --- |
| 双端安装后 | `sudo -u w22devapp /usr/bin/python3 -I -B -` 通过 Linux 回环执行探针，OpenAI 证书及 TLS 1.3 成功，`example.com:443` 返回 CONNECT 403 |
| Mac 代理重启 | 确认 Mac 代理无已建立连接后执行 `launchctl kickstart -k`，代理 PID 9259 → 9301。重复探针，TLS 1.3 和 CONNECT 403 均通过 |
| Linux 代理重启 | 确认无已建立代理连接后停止 `walle22-dev-openai-proxy.service`，PID 4966 → 0，socket 仍 active 且 enabled。重复探针激活 PID 5251，TLS 1.3 和 CONNECT 403 均通过 |

已验收入口为 `http://127.0.0.1:17890`。验收完成于进程重启场景。Mac 注销、VPN 退出及整机重启未覆盖。探针止于 TLS 握手，模型及计数调用均为零。应用启用 OpenAI 继续走开发环境的发布流程。
