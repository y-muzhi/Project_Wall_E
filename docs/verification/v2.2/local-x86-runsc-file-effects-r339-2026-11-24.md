# R339 固定 x86_64 runsc 的文件效果原型

2026-11-24（香港时间），独立 `codex/2.2`。Ubuntu 24.04.5 x86_64 无网卡来宾、原生 ext4。固定实际 `runsc release-20261116.0`，二进制 SHA256 `946f34ba34c45c0e97d0a9871a29b27ba8fe21e5389ede2c04729c9f16bad51b`；公开闭包归档以官方 SHA512 校验。依据 V2.01 后端 4.23.1、7.11.5、8.2 P2-a。

- 独立 OCI 装配固定 systrap、`network=none`、只读根、UID 1501、无 capability、无新权限。受信静态夹具只见同一任务挂载内的 workspace 和外侧私有准备区，挂载外合成哨兵不可见。使用 `file-access-mounts=exclusive`，单次不覆盖创建、占用目标拒绝、带新旧锚点交换、移到私有隔离名以及新父链整体发布均通过。文件、锚点和目录 `fsync` 成功。
- 两组异常用例分别在交换前和交换后退出，未生成原完成回执。全部原工作器停止后，从宿主核对精确原 inode 与锚点、字节、链接数和布局，两种状态可区分。已交换样本同步原目录，新 sandbox 读回同一布局。原派发意图在受保护宿主目录保全，未重复原动作。
- 同一闭包的 `shared` 比较在真挂载拒绝 `RENAME_NOREPLACE`，原准备及原目标保持。此项说明两种模式具有不同语义。验证全程使用原 systrap，结束时专属 OCI 状态无存活容器。

执行 `python run-guest.py r339b-files disk-r339-runsc.qcow2 offline 245`，来宾退出 0。此项覆盖本机文件机制、受限合成根与两个退出断点。正式 Docker 固定入口、真实工具协议、所有故障点、底层卷重建证明和 ARM64 仍需按目标独立验收。[gVisor 安装及闭包](https://gvisor.dev/docs/user_guide/install/) · [gVisor 平台](https://gvisor.dev/docs/user_guide/platforms/)
