# R203 Ubuntu 管理登记新代次放置、WAL 与冻结

2026-11-23，独立 `codex/2.2`。以 V2.01 后端 4.12.3 与 [本机固定管理入口 R201](local-x86-management-tls-snapshot-r201-2026-11-23.md) 为依据，无网络 Ubuntu x86_64、原固定 Python 3.13.18／SQLite 3.54.1、ext4、真实管理暂停记录与格式 3 快照。

- 实机先定位 `/usr/bin/python3 -I -B -S manage_registry.py place-registry-recovery` 被固定运行映射拒绝。用同一个已固定意图直接进入固定解释器可放置，系统解释器无权绕过映射检查。入口改为先核对原运行及程序，再重新执行自己进入固定解释器，并检查实际解释器、环境锁库与宿主映射。专项固定并检查原参数、调用顺序及最少环境变量。
- 在全新临时增量盘从旧管理快照走 `prepare-registry-recovery`、`verify-registry-recovery`、`place-registry-recovery`、`ready-registry-recovery`、`inventory-registry-recovery`。准备回执 `06008b785a7c9526496769b15533eae125fd1379ec98869e42c709e9b121a300`。同一原键可读回相同放置、WAL 及四类清册摘要，新登记 Schema 8，原管理者与宿主不变并保留两个数据代次身份。
- 放置回执 `92b8235884240dcba18586d125ccf0abb9d3d672289ecba18bb9ee5cd7b46a43`，WAL 就绪回执 `a52e94df765d78060d5539b7e9d23206db3cf3d2e17e0a51ea7d8b75ea9f350d`，清册回执 `9f51a856135789db64996063bac0666dcf5f39292a0f99036eca1704335f5652`。固定 SQLite 只读连接验证完整性、外键、管理者、宿主和新库绑定。新库使用新的物理文件，原锁、旧管理锚、旧库摘要、两个普通业务库及原控制保持，真实派发暂停可查。
- 183 项相关后端专项、16 个子项、Ruff F／I、664 个文件格式及 `git diff --check` 通过。当前记录使用隔离新空登记库，未包含原已登记任务的宿主观察，也未接入生产管理或外网。
