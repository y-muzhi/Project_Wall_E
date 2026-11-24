# R114 恢复时仍运行的环境资源

2026-11-22。独立 Windows 源使用实际 SQLite 文件和模拟的 Linux 控制／进程／权限观察。

- 对仍运行环境核对活动控制、原锁持有者、运行凭证、业务 DB 身份、路径根及活动套接字。确认期间任一事实改变均保持待核对。原运行和占用由本逻辑只读。
- `backend/tests/infrastructure/test_v22_registry_recovery_dispatch.py` 在 Windows 常规运行 1 项通过、6 项 Linux 相关用例跳过。套用本轮 Linux 系统事实适配后全部 7 项通过。覆盖原锚不可写、原归档暂停损坏拒绝、实际 SQLite 文件身份、五种观测变化及原套接字匹配和漂移。
- 管理及固定入口未定义变量专项通过。ARM64 上正常业务不中断的实际 systemd、运行锁和套接字仍待联验。
