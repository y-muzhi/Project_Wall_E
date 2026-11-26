# R341 真实 Docker 与固定 runsc 文件效果

2026-11-24（香港时间），独立 `codex/2.2`，本机 Ubuntu 24.04.5 x86_64 无网卡来宾。Docker 29.1.3 Ubuntu 发行包，containerd 2.2.1，固定 `runsc release-20261116.0`，与 R339 二进制一致。通用依赖装配时保持默认服务关闭。真实组合另在离线来宾内通过专属 Unix 监听、配置、PID、数据和执行目录启动，非 Docker 身份实际收到权限拒绝。

- 导入仅含受信静态程序的本地合成镜像，镜像 ID `sha256:9dccf31b6a2db9b1606f1024abfb39e4ed313ba34b0b874ee38746ef08ec21dd`。仅按该镜像 ID 运行且不拉取。容器实查固定运行时、systrap 装配的 exclusive 模式、网络 none、只读根、非 root、无能力、无新权限和一个私有任务挂载。
- 四类原子动作与同步在真实 Docker 承载的原 ext4 单挂载中通过。另一次交换后原工作器以 42 退出且无完成回执，保留受保护原派发意图、原内容与 inode。原程序退出后宿主核对布局并同步，新容器读回同一状态。
- 专属容器均已退出并清除，daemon 正常退出，独立 socket 已消失。通用宿主未安装此 Docker 或修改其默认 socket。

`python run-guest.py r341b-test disk-r341-docker.qcow2 offline 280` 退出 0。第一次按旧发行版路径定位 daemon，后按本次发行包实际安装路径确认。未接正式业务工具协议、启动端点、真实 OpenCode 或 ARM64。
