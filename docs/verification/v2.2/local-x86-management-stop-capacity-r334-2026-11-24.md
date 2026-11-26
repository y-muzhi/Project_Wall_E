# R334 真实管理登记与停机容量

2026-11-24（香港时间）。独立 `codex/2.2`，Ubuntu 24.04.5 x86_64 无网卡来宾，Python 3.13.18、SQLite 3.54.1、实际 systemd 和 ext4。R325 的合规集成运行环境与隔离开发环境来自独立来宾副本。使用本机已有 Git 对象只读 bundle，复用原 `deacba8a9545122f35a2f85c125a354205e06461`，在来宾创建两个不同的工作目录、分支和目录 inode。实际 Git 观察读取两套工作区的原归属。临时分支没有新提交，未传输源码至外部。

- 用固定 `manage_registry.py` 准备和初始化真实管理库，`observe-attach` 探测停机和实际 Git，原 `ATTACH` 以相同键读回。接着使用真实 `operation / START` 与 `start-runtime`，实际管理授权核对四项原范围后启动 systemd，原键核实实际业务就绪。
- 第一次 `STOP` 经实际 systemd 正常结束，控制到修订 13。宿主原键重复调用返回相同停机回执，管理原键更新为完成，原 START 的内存、CPU、任务数和运行槽四项只按该停止释放。管理原键再次读取保持。
- 新 START 引用原停止并取得四项新预留，产生不同运行 ID。实际业务提交一条测试需求，同时以应用 UID 保持 SQLite 读事务。停机宿主返回退出 3 和 `MANAGEMENT_STOP_EFFECT_UNVERIFIED`，管理原操作和步骤为 `UNKNOWN`，没有完成结果。SQLite 控制仍是 DRAINING／修订 16，四项预留保持。解除事务后同键停机、状态查询和重复提交沿原未知收敛，原派发字节及两次容量结果均保持。另一 START 被拒绝，先提交的需求只出现一次，开发站控制、安装以及原库摘要保持。

执行 `python run-guest.py r334d-capacity disk-r325d-ordinary.qcow2 offline 380`，来宾退出 0。早期夹具修正了 NoCloud 设备识别、登记表列名和非零退出的错误输出采集。实际管理与宿主命令、两个 systemd 单元及业务 Unix 套接字只在来宾内。当前验证覆盖管理命令与 SQLite 回执，未用浏览器发起这两次管理操作。
