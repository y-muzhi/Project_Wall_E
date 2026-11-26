# R397 已成功停机的效果处置与管理写入开放

2026-11-24（香港时间）。`codex/2.2` 当前固定程序，Ubuntu 24.04.5 x86_64、原生 ext4、CPython 3.13.18 和 SQLite 3.54.1。延续 R391 的真实受管启停和 R394–R395 的非空管理快照。无网卡来宾，Caddy 9444 与管理 Unix 套接字均在来宾内。

- `refresh-registry-recovery-observation` 实物重核 25 项。未记处置时，`check-registry-recovery-dispatch` 核验格式 3 暂停源通过，只返回一项 `ORIGINAL_OPERATION_UNRESOLVED`。`inspect-registry-recovery-dispatch` 定位为原已成功 STOP。直接用该检查摘要请求开放继续拒绝，原暂停文件和身份保留。
- `settle-registry-recovery-disposition` 使用原管理账号、原暂停、原管理目录身份、原版本、原意图及固定宿主回执。错误原意图摘要拒绝。正确策略写入 `STOP_COMPLETED`，再次执行返回相同回执 `047ff6bcffc240856182b5b1ead903b01c1e44cf574a9119b5e56db3db5cb6e2`。原 STOP 已成功且原容量已释放，本次处置的待释放数为零，原四条释放理由保持原字节。
- 复核无阻塞。错误复核摘要拒绝，正确 `open-registry-recovery-dispatch` 在原写入暂停下开放，并可按同一回执重读。回执 `0faaa45d50d7310dd1ed1574cd0f1e727f76b9c13f686c5a938eaffbe2c0e551`。真实 Caddy TLS 管理 API 同一进程由 `BLOCKED` 转为 `READY`。原键继续读取原结果，以原键提交当前请求返回 409。
- 由新管理 HTTPS 接受集成环境新 START，实际固定 systemd 运行程序启动后从管理端核对完成。随后同一站通过 HTTPS 受理新 STOP，真实正常关闭、锁及套接字释放，新四项容量只按新 STOP 释放。开发站原安装与数据、原管理 SQLite、原锚资料及已转存的暂停记录保留。来宾、专属管理进程和 Caddy 正常退出。

本轮覆盖已终结的原 STOP 和新管理写入。原生 ARM64、异机备份和正式生产开放待各自验证。
