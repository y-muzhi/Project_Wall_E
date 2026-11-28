# V2.2 开发环境 OpenAI 常驻代理

2026-11-27（香港时间）。Linux 代理入口为 `http://127.0.0.1:17890`，已安装并用开发账号通过 OpenAI TLS、其他域名拒绝及双端代理进程恢复检查。[实机验收](../../verification/v2.2/mac-linux-openai-proxy-installed-2026-11-27.md)

Linux 以 systemd socket 监听回环，将连接转发至 Mac 的虚拟机私有网桥 `192.168.252.1:17890`。Mac 转发器只接受开发来宾 IPv4 `192.168.252.2`，只向 Mac 当前回环代理 `127.0.0.1:7890` 发送固定的 `CONNECT api.openai.com:443`。部署前核对这对地址实际属于专用网桥。Linux 回环端口可由同一网络命名空间内的本机进程访问。开发账号用于验收，开发后端的代理设置随开发环境发布单独切换。Mac 的 LaunchAgent 随已登录用户会话运行，出口依赖该会话内 VPN 代理就绪。[Apple LaunchAgent 文档](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html) · [systemd-socket-proxyd 文档](https://www.freedesktop.org/software/systemd/man/latest/systemd-socket-proxyd.html)

## 安装前检查

通过 `walle-mac` 和 `walle-linux` SSH 别名分别登录。Mac 跳板地址为 `192.168.31.160:22`，见[运行说明](运行说明_V_2.2.md)。确认开发环境及在途任务，尤其是在重启代理前。Mac 以运行 VPN 的图形会话用户执行下方命令，Linux 用现有管理账号执行。

```sh
# Mac
ifconfig
lsof -nP -iTCP:7890 -iTCP:17890 -sTCP:LISTEN
launchctl print "gui/$(id -u)" >/dev/null
command -v python3
python3 --version

# Linux
ip -4 route get 192.168.252.1
getent passwd w22devapp
systemctl show -p User -p ActiveState -p MainPID walle22-mac-dev.service
ss -H -ltn 'sport = :17890'
test -x /usr/lib/systemd/systemd-socket-proxyd
```

确认 Mac 网桥持有 `192.168.252.1`，Linux 路由使用源地址 `192.168.252.2`，Mac 的现有代理在 `127.0.0.1:7890` 监听，双端 `17890` 空闲。如果代理标签、目标文件或端口已在使用，先查明归属，再决定是否保留或替换。

## 获准后安装 Mac 转发

从 Windows 工作区向 Mac 用户主目录暂存转发器。项目工具目录保留了与临时实机验证相同字节的副本。

```powershell
scp tools/linux_runtime/mac_openai_proxy.py walle-mac:walle22-openai-proxy.stage.py
```

用 Mac 用户 shell 执行。安装脚本会检查暂存文件摘要，并使用目标机上实际可执行的 Python 路径生成 plist。

```sh
(
  set -eu
  label=local.walle22.dev-openai-proxy
  domain="gui/$(id -u)"
  work="$HOME/Library/Application Support/$label"
  plist="$HOME/Library/LaunchAgents/$label.plist"
  staged="$HOME/walle22-openai-proxy.stage.py"
  test ! -e "$work"
  test ! -e "$plist"
  if launchctl print "$domain/$label" >/dev/null 2>&1; then exit 1; fi
  expected=ab5bfc6a7ee5b2ea5bd5db7169e8a46ce09a77688029143755ddf8b5a3990c85
  test "$(shasum -a 256 "$staged" | cut -d ' ' -f 1)" = "$expected"
  python="$(command -v python3)"
  test -x "$python"
  mkdir -p "$HOME/Library/LaunchAgents"
  mkdir -m 700 "$work"
  install -m 600 "$staged" "$work/mac_openai_proxy.py"
  "$python" -I -B - "$label" "$python" "$work/mac_openai_proxy.py" "$plist" <<'PY'
import plistlib
import sys

label, python, script, plist = sys.argv[1:]
with open(plist, "xb") as output:
    plistlib.dump({
        "Label": label,
        "ProgramArguments": [
            python, "-I", "-B", script,
            "--bind", "192.168.252.1", "--guest", "192.168.252.2",
            "--port", "17890", "--upstream-port", "7890",
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
    }, output)
PY
  plutil -lint "$plist"
  launchctl bootstrap "$domain" "$plist"
  launchctl print "$domain/$label"
  rm "$staged"
)
```

确认 Mac `17890` 只监听网桥地址后再装 Linux 入口。

## 获准后安装 Linux 回环入口

```sh
(
  set -eu
  base=walle22-dev-openai-proxy
  test ! -e "/etc/systemd/system/$base.socket"
  test ! -e "/etc/systemd/system/$base.service"
  test -z "$(ss -H -ltn 'sport = :17890')"
  test -x /usr/lib/systemd/systemd-socket-proxyd
  sudo sh -C -c 'umask 022; cat > /etc/systemd/system/walle22-dev-openai-proxy.socket' <<'UNIT'
[Unit]
Description=WALL-E development OpenAI loopback listener

[Socket]
ListenStream=127.0.0.1:17890

[Install]
WantedBy=sockets.target
UNIT
  sudo sh -C -c 'umask 022; cat > /etc/systemd/system/walle22-dev-openai-proxy.service' <<'UNIT'
[Unit]
Description=WALL-E development OpenAI proxy to Mac VM bridge
Requires=walle22-dev-openai-proxy.socket
After=walle22-dev-openai-proxy.socket

[Service]
Type=notify
DynamicUser=yes
NoNewPrivileges=yes
ExecStart=/usr/lib/systemd/systemd-socket-proxyd 192.168.252.1:17890
UNIT
  sudo systemd-analyze verify "/etc/systemd/system/$base.socket" "/etc/systemd/system/$base.service"
  sudo systemctl daemon-reload
  sudo systemctl enable --now "$base.socket"
  ss -H -ltn 'sport = :17890'
)
```

## 用开发账号验收

在 Linux 上执行以下探针。它通过回环测试拒绝响应和带 SNI 的 TLS 证书校验。探针在握手后关闭连接，供应方 HTTP 请求及凭据用量均为零。

```sh
sudo -u w22devapp /usr/bin/python3 -I -B - <<'PY'
import http.client
import socket
import ssl

proxy = ("127.0.0.1", 17890)
with socket.create_connection(proxy, timeout=10) as connection:
    connection.sendall(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
    response = http.client.HTTPResponse(connection)
    try:
        response.begin()
        if response.status != 403:
            raise RuntimeError(f"Expected CONNECT refusal, received {response.status}")
        print("example.com CONNECT 403")
    finally:
        response.close()

connect = http.client.HTTPConnection(*proxy, timeout=15)
try:
    connect.set_tunnel("api.openai.com", port=443)
    connect.connect()
    with ssl.create_default_context().wrap_socket(
        connect.sock, server_hostname="api.openai.com"
    ) as tls:
        print("api.openai.com certificate verified", tls.version())
finally:
    connect.close()
PY
```

1. 安装后运行一次探针，确认双端监听及结果。
2. 确认代理空闲后，在 Mac 用 `launchctl print "gui/$(id -u)/local.walle22.dev-openai-proxy"` 记录 PID，执行 `launchctl kickstart -k "gui/$(id -u)/local.walle22.dev-openai-proxy"`，确认新 PID 和网桥监听后重跑探针。
3. 在 Linux 记录 `systemctl show -p MainPID walle22-dev-openai-proxy.service`，执行 `sudo systemctl stop walle22-dev-openai-proxy.service`。确认 `walle22-dev-openai-proxy.socket` 仍 active。重跑探针并确认 systemd 为转发进程分配了新 PID。
4. 以 Markdown 记录双端监听、三次探针、PID 变化及异常。进程重启检查覆盖代理进程，Mac 注销、VPN 退出和整机重启需另行观察。

## 卸载

先确认代理空闲。如果开发后端已通过发布切到此入口，先按开发环境发布流程回退配置。卸载先在 Linux 停服务和 socket，再在 Mac 卸载 LaunchAgent。安装中途失败时，以下命令仅用于清理本轮确认创建的文件。

```sh
# Linux
sudo systemctl disable --now walle22-dev-openai-proxy.socket
sudo systemctl stop walle22-dev-openai-proxy.service
sudo rm -f /etc/systemd/system/walle22-dev-openai-proxy.socket /etc/systemd/system/walle22-dev-openai-proxy.service
sudo systemctl daemon-reload
ss -H -ltn 'sport = :17890'
```

```sh
# Mac
label=local.walle22.dev-openai-proxy
domain="gui/$(id -u)"
if launchctl print "$domain/$label" >/dev/null 2>&1; then
  launchctl bootout "$domain/$label" || exit 1
fi
rm -f "$HOME/Library/LaunchAgents/$label.plist"
rm -f "$HOME/Library/Application Support/$label/mac_openai_proxy.py"
rm -f "$HOME/walle22-openai-proxy.stage.py"
if test -d "$HOME/Library/Application Support/$label"; then
  rmdir "$HOME/Library/Application Support/$label"
fi
lsof -nP -iTCP:17890 -sTCP:LISTEN
```

[临时转发实机证据](../../verification/v2.2/mac-linux-openai-vpn-2026-11-27.md)
