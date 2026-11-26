# R337 管理服务生命周期与真实 HTTPS

2026-11-24（香港时间）。独立 `codex/2.2`。固定 Uvicorn 0.54.0、FastAPI 0.142.2、Starlette、Python 3.13.18／SQLite 3.54.1。用固定原 R325 程序在同一无网卡 Ubuntu 24.04.5 x86_64 复现管理入口在 ASGI 关闭抛错或重复 SIGINT 后跳过关闭时均返回 0。两种真实 Uvicorn 行为都有启动事实，重复信号分支没有关闭事实。

- 普通与管理入口复用 `owned_server.run_owned_server` 判断真实生命周期。管理显式开启 lifespan，原单信号和强制退出策略继续各自处理。正常完成返回 0，启动失败沿固定 Uvicorn 返回 3，关闭抛错或强制跳过关闭返回 2。回归运行实际框架，模拟关闭故障和信号入口，无用户数据库。
- Linux 固定副本的 7 项生命周期专项通过。Windows 固定环境中的普通 3 项通过，Linux 专属管理 4 项按平台跳过。Windows Ruff 格式检查覆盖 663 文件，修改文件 F／I 和 `git diff --check` 通过。
- 在 R334 管理库来宾副本，用本轮更新后的固定程序 `677162bfff46752e32acbacce4f59321821999f1ac37ff041eeaefa720210717` 实际启动管理服务及 Caddy。只在来宾 9444，使用真实隔离 CA、自动化身份和实际 Unix 套接字。未认证的同名伪标头返回 401，越代次返回 409，三项固定可视化资源逐字节一致。
- 当前管理握手报告 RECOVERING，详情展示原集成 Git 分支，资源显示四项已释放和四项仍占用，START 按原冲突不可用。两次停机以原键分别读到 SUCCEEDED 和 UNKNOWN。两项服务正常停止，管理套接字已清理。

执行 `python run-guest.py r337b-check disk-r334d-capacity.qcow2 offline 285`，来宾退出 0。管理实际 HTTPS 和固定资源已验。这次管理 API 使用自动化身份，浏览器原有管理验证见历史 R296，当前普通浏览器证据见 R335。
