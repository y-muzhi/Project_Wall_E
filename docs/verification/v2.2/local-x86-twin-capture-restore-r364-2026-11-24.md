# R364 两套正常停机的实际业务库各自备份并恢复

2026-11-24（香港时间）。无网卡 Ubuntu 24.04 x86_64 使用 [R362 两个实际 HTTPS 业务站](local-x86-browser-scope-reload-r362-2026-11-24.md) 正常退出后的 ext4 增量盘。固定 Python 3.13.18、SQLite 3.54.1，源状态分别为 `CLOSED/NORMAL_STOP` 且没有 SQLite 侧文件。

用各自原维护 UID 和共享 GID，从固定 `manage_registry.py` 运行版本 2 的 `capture-database` 及 `restore-database`。实际执行前分别交换两环境的安装锚测试，均明确返回 `DATABASE_CAPTURE_INTENT_MISMATCH`，独立目标目录无输出。两份原捕获、两份独立新代次恢复及各自重放成功。来源数据库、安装锚、控制回执和稳定锁的原摘要保持。

| 真实源 | 捕获数据库 SHA256 | 新代次数据库 SHA256 |
| --- | --- | --- |
| 开发 | `34490087e39a19b1ac09ccf337a3850fb852c9c7905095d7eb71563e75bac197` | `b1eb0c96de043ed3baa9aaa36ae833bcd8cc0c4c26919a39cafb4eeeda98a4a9` |
| 集成 | `7ed86b5d4a6f676f3944f356c7bd857c4e8113276f74e68062cb03e10e5a6df6` | `54c8ba193295690799b0ccd2a0b3a4020dfb7abe6edecca7b8efd02ff1daf41d` |

固定 SQLite 用 `mode=ro&immutable=1` 独立读取四份数据库，实际完整性和外键检查通过，绑定环境和源／目标代次符合各自计划。两套各保留一份当前正文和一份已有服务端人工草稿，没有对方正文或浏览器独有的未提交文字。首次测试命令缺少固定程序摘要，按实际入口补齐后通过。来宾退出码 0。本单元覆盖原生停机捕获和独立恢复。正式目标换代、异机 COS 和实际生产采用有独立准入。
