# R349 从公开校验输入重建 x86_64 固定运行包

2026-11-24（香港时间），独立 `codex/2.2`，本机 WHPX／QEMU 11.1.3，Ubuntu 24.04.5、Linux 6.8.0-147-generic、systemd 255 与 ext4。官方 Noble 镜像 SHA256 `04e8f2461a16a44e78a370284471f29616cdd9baf1893df25807b71f985b6c94`。APT 工具只在无项目源码的公共依赖阶段下载。后续覆盖盘无网卡和宿主端口映射。

- CPython 3.13.18 和 SQLite 3.54.1 下载后分别按原项目 SHA256／SHA3-256 校验。31 项固定 wheel 加 pip 26.2.2 逐项核对官方发布文件名、字节数和 SHA256。独立非 root 身份用 `build-cpython.sh` 编译，离线运行 `prepare_wheels.py --wheel-manifest` 安装，再由 `seal_runtime.py` 封存并运行原 `runtime.py probe`。
- 来宾正常停止，真实准入为 `ADMITTED r349-x86-local-runtime`，CPython 3.13.18、SQLite 3.54.1、31 个 wheel；运行清单 `86b7c0d46832f61cf2f81a16a9491835301a748bda00f25576c25d49352a314b`。此阶段没有业务库，ARM64、外部主机恢复及生产另验。
- MSYS2 核验独立 PGP 签名和软件包签名。原公开镜像速度较慢，改用 MSYS2 随包列出的南京大学镜像。首个来宾运行使用 Windows 含中文的绝对固件路径，QEMU 拒绝。改为独立目录内的相对固件路径后，公共依赖和离线编译阶段均正常退出。 [Ubuntu Noble 云镜像](https://cloud-images.ubuntu.com/releases/noble/release/) [MSYS2 安装签名](https://www.msys2.org/docs/installer/)
