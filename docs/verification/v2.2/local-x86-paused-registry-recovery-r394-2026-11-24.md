# R394 真实非空管理库暂停、快照及独立 WAL 代次

2026-11-24（香港时间），从 [R391 真正登记和关停](local-x86-new-managed-registry-runtime-r391-2026-11-24.md) 的 ext4 增量盘继续。无网卡 Ubuntu x86_64、固定 CPython 3.13.18／SQLite 3.54.1，无监听和宿主端口映射。

- 实际 `pause-registry-dispatch` 暂停管理派发并保留原回执。原两项 ATTACH、START 和 STOP 均可按键读回。新的管理写入返回 `MANAGEMENT_DISPATCH_PAUSED`。没有改变两份普通安装或任何一份业务库。
- 实际 `snapshot-registry` 生成同一暂停绑定的格式 3 快照，`verify-registry-snapshot` 重新打开并核对完整性、外键及原历史。快照回执 `8b3882a0b9a98710afb4e9e6d6cf708c2e4849df31be0384e1612d806d8662e5`。重复捕获得到同一结果。
- 错误暂停摘要拒绝提前制备。正确计划实际进入 `prepare-registry-recovery`、独立 `verify-registry-recovery`、`place-registry-recovery` 和 `ready-registry-recovery`。新代次实物与源库和归档库分别有独立 inode，固定 SQLite 进入 WAL，校验后无侧文件。最新适用管理 Schema 8 验证通过。就绪回执 `10c80fca6702261111b0f58a9cdff18f27491d1386b6dd08d7555ab2d0179f8f`。
- 新库内两代归属明确，四个原请求、全部历史表、原停止释放的四项容量及各自回执逐项等同。原活动锚、管理库、原暂停、封存、普通控制及业务库字节和身份保持。来宾 `r394-registry` 退出 0。活动锚关闭选择和新入口另做实际验证。
