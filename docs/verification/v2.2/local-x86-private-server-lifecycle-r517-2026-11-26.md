# V2.2 私有服务器退出的隔离机制对照

日期 2026-11-26（香港时间）。无网 Ubuntu 24.04 x86_64 QEMU TCG，独立 ext4 覆盖盘。使用当前开发工作区的真实 `create_app(recovery=...)`、`prebind`、`serve_application`、`run_owned_server` 及工具原 `stop_owned`。初始化和资料权限用最小合成 scope 隔离，目的仅为核对服务、信号与文件清理由同一固定进程执行。无真实恢复数据库、发布或浏览器参与。

由专用 UID 14301／GID 14300 运行无额外组、NNP 的应用子进程。父进程验实际 Unix peer PID／UID／GID，应用约 14.57 秒可通过真实 HTTP 返回 READ_ONLY 握手。工具发送原 SIGTERM 后，Uvicorn 依次完成下线、ASGI drain 和应用 shutdown。进程退出码 0，工具停止用时 0.64 秒，同时同一 socket 路径已消失。来宾退出 0，覆盖盘和临时输出清理，原镜像大小和修改时间未改。

机制对照证明当前服务器装配可正常生命周期退出。真实固定恢复的文件、锁、作用域和 shutdown 尚须在完整验证中单独判定。
