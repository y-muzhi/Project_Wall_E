# R270 正常业务跨管理登记换代继续运行

2026-11-23，独立 `codex/2.2`。无网络 Ubuntu 24.04 x86_64 来宾，实际 systemd、ext4、CPython 3.13.18／SQLite 3.54.1 和 Caddy。只使用本轮两套普通测试安装，管理 HTTPS 为来宾回环 9444。依据 V2.01 后端 4.12.3 和 TC201-MGT-01。

- 使用正常受管 START、应用握手和管理对账启动开发环境。退出原管理服务及代理后，普通 Unix API 继续读出原需求。通过实际源暂停、格式 3 一致快照、独立新库和关闭选择。在新管理 HTTPS 的 BLOCKED 阶段及最终 READY 后重复读取同一业务需求。
- 两份实际宿主观测均读到原环境 `RUNNING_OBSERVED`。应用锁 PID 与原普通套接字的 `SO_PEERCRED` 一致，整个过程保持两层进程身份、systemd InvocationID、Unix 套接字 inode 和同一运行 ID。原 START 保持 SUCCEEDED，四项容量在原快照和新库均未释放，原库、两套安装、控制和业务数据库摘要保持。
- 恢复的关闭选择回执 `2eba3e6d4485d9cffa4ebf1815f9f9f1ee6f489d57e0a91de4e85d7b75b831c5`，真实派发开放回执 `2ef609263e977620858721c118b56017fde7b59ca21f541049f33a43ac7dbfdf`。旧 START 按原键返回相同结果。
- 实际新环境详情仍显示 UNKNOWN，STOP 不能执行。当前常规投影只读取当前目录的运行观察，恢复判定中的原运行仍保留在原目录。该缺口进入 V2.2 待合并迭代。验证结束后用来宾内特定原 systemd 单元清理测试进程，确认该单元 inactive 且 MainPID 为 0，来宾退出。本条仅证明服务连续性、容量保全和管理开放。
