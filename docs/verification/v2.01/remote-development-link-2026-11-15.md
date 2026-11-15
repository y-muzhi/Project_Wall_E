# V2.01 远程开发链路验证

日期：2026-11-15（Asia/Hong_Kong）。状态：P0部分完成，等待Mac本机核对主机身份并添加连接公钥。

## 范围与现场

- 依据：独立架构选型评审修订1.5的第9.3节及P0。用户要求先验证Windows Codex到Mac Linux虚拟机的实际操作链路。
- Git HEAD：`28a7c9e13c73a9d386081a6dd894244b51746a45`；工作区含现有未提交修改，不是冻结候选。本轮未修改产品源码、业务数据或服务，未安装虚拟机、调用产品模型或提交推送。
- Windows：当前项目仍在本地，Codex项目列表没有已登记的远程项目。`ssh -V`为OpenSSH_for_Windows_9.5p2；`codex --version`为0.169.0-alpha.11.1，伴随本地临时目录权限警告，不据此判断远程运行能力。
- Mac：M1 Pro、16GB内存、约500GB可用磁盘、macOS26.3 beta均由用户提供，尚未远程核对。用户明确尚未安装Linux虚拟机，已提供局域网SSH目标和账户；实际地址保留在当前会话，报告不复制登录信息。

## 已执行检查与结果

| 检查 | 方法 | 实际结果 |
| --- | --- | --- |
| 默认SSH配置与已知主机 | 检查Windows用户的`.ssh`目录与Codex项目列表 | 初检不存在`.ssh`目录、配置及已知主机文件；未登记远程项目 |
| TCP与SSH服务 | 对用户指定主机22端口执行限时TCP连接并读取服务标识 | 默认执行环境拒绝套接字；获准局域网访问后连接成功，服务标识为OpenSSH_10.0 |
| SSH握手 | `ssh -v -o BatchMode=yes -o ConnectTimeout=5 -o ConnectionAttempts=1 -o StrictHostKeyChecking=yes -o UpdateHostKeys=no -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no <用户指定目标> 'uname -s'` | 加密握手成功，取得ED25519主机指纹；因首次主机身份未登记，严格检查按预期拒绝继续。未登录，远端命令未执行 |
| 公钥扫描工具 | `ssh-keyscan -v -T 5 -t ed25519 <用户指定地址>` | 当前Windows扫描工具报告不支持所协商的KEX；改用普通SSH完成握手观察，没有修改服务端算法或关闭主机身份检查 |
| 专用客户端密钥准备 | `ssh-keygen`生成ED25519连接密钥，拒绝覆盖已有文件 | 已生成，私钥仅保留Windows用户`.ssh/walle_mac_ed25519`，未写入仓库或输出；公钥尚未添加到Mac |

待Mac本机核对的主机指纹：`SHA256:Nybp0kgrET+tjNbAWwWfUQYFUuUEGlHORUtYFPLEfi8`。该值目前只来自网络握手，不是已完成的可信身份验证。

## 当前断点及下一步

1. 用户在Mac本机核对`/etc/ssh/ssh_host_ed25519_key.pub`指纹，并将本轮Windows专用公钥加入其账户的授权公钥列表。公钥内容可重新从Windows的`.ssh/walle_mac_ed25519.pub`读取；不能重新生成覆盖私钥，不索取或记录用户密码。
2. 对比Mac本机回传指纹与握手值，一致后固定已知主机记录；使用专用密钥完成只读登录，核对系统、架构、容量和现有虚拟机工具。
3. 准备最小Ubuntu虚拟机并检查Windows直连或经Mac跳转的SSH路径，再配置Linux端Codex与远程项目。当前尚无虚拟机、远程项目或已启动的测试服务。
4. 完成临时工作区文件修改、命令与检查执行、Windows浏览器访问及断线重连；浏览器自动化能力独立验证。Mac SSH通不等于Linux虚拟机、Codex远程项目或WALL-E产品验证通过。

本轮不保存原始日志、截图或临时测试报告。此记录为连接准备与现场验证证据，不代表V2.01设计定版或Linux迁移完成。
