# R186 Ubuntu x86_64 原生文件与身份边界

2026-11-23，独立 `codex/2.2`。在同一 Windows 主机以便携 QEMU 和已可用的 WHPX 启动隔离 Ubuntu 24.04.5 x86_64。验证盘使用临时 ext4 覆盖盘，虚拟机无网卡与主机监听，使用仓库原 Python 模块和两个真实不同的非 root UID。该单元使用 Ubuntu 自带 Python／SQLite 核对文件及进程边界。

- 实际调用 `check_ext4`、`no_acl`、`persisted_write` 和 `read_protected`。原回执持久写入，重复名字不覆盖，未遗留临时文件。非 root 只能读取受保护的回执，不能改写，符号链接被拒绝。
- 原 `schema_v22_publish.publish_directory` 在真实 ext4 上成功独占发布。`renameat2 RENAME_NOREPLACE` 拒绝覆盖同名目标，同时保留原文件和准备目录，覆盖 R183 依赖的底层原子发布。
- 两个 UID 分别写入自己的实际 SQLite 并由新的进程以只读方式校验 `integrity_check` 和正文。双向拒绝读取另一方数据库与封存文件，也拒绝连接另一方实际监听的 Unix 套接字。所用互访路径仅属于本轮临时虚拟盘。
- 首次未能取到脚本结束标记。使用独立串口输出后，定位到验证介质漏装生产模块引用的依赖，补齐本地 Python 模块树后重新执行，退出 0。此单元没有核定固定运行包、完整业务部署、真实 COS 或生产权限。
