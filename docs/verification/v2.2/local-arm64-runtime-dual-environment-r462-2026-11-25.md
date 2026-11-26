# V2.2 R462 本机 AArch64 固定运行包与普通环境

2026-11-25（香港时间）。Windows 宿主上的 QEMU TCG AArch64，来宾 Ubuntu 24.04.5／Linux 6.8.0-147-generic，Cgroup v2。测试运行包和项目来宾均无网卡及宿主端口转发。公开镜像、APT 和轮包输入在独立来宾处理，项目与用户数据未交给公开下载来宾。

## ARM64 固定运行包

- 官方 Ubuntu Minimal ARM64 镜像来自 `release-20261105`。用官方云镜像公钥核对发布清单签名，镜像 223,870,976 字节，SHA256 `3dc8370d923978d4b610fa7964d1b36ba040eefb43198809ca5bc8ac51777b18`。[Ubuntu 镜像及签名清单](https://cloud-images.ubuntu.com/minimal/releases/noble/release-20261105/)
- 在 AArch64 来宾内运行原 `build-cpython.sh`，按锁定源包编译 CPython 3.13.18、SQLite 3.54.1 和稳定锁库。实测给出 x86_64 前置条件时早拒绝并保留空输出。使用原 `prepare_wheels.py` 在无网来宾安装 31 项固定依赖。原 ARM64 轮包清单 `22b07c01b1adaeb4f9b7d678f7453fe5c03985dd4dbbeaa69678a5dfc5b909ef`；两项本机特定轮包与 R407 原 SHA 一致。固定依赖检查无损坏项。
- `seal_runtime.py` 实际封存 4,324 项、18 项宿主动态库。测试驱动最初误把运行包清单路径写到 `metadata/`，编译和封存已成功，后续校验未执行。在独立无网启动盘以实际根清单重放，固定非 root 身份通过 `runtime.py probe`，摘要 `d1dd25086a50ee3ec01af0ccb345b28ae52b6b85231590fcc57b47a332976c98`、Python 3.13.18、SQLite 3.54.1、31 项依赖，并核对 AArch64 ELF。

## 当前源码与业务接续

- 原设计五份与主工作区原摘要一致。当前开发工作树 1,888 份目标源码，另由同一工作树 Windows 隔离离线构建普通前端 120 项，资产组合摘要 `b43b5f8774e42c9d430744d7ea1e945ba80dfddb59b8fb302d372e9281405348`。来宾核对包括源码、资产、设计与驱动在内 2,017 项输入，不含实际用户数据库或密钥。
- 首次项目试验的驱动在暂存同伴初始化行使用了未定义变量。删除该临时驱动行后，复验由固定 AArch64 进程使用 `runtime.py build-schema` 实际生成 Schema，清单 `5f1d8a1234514119ef9eb51ce7ec0efbc98717dec6db3300e60988f8638c54d4`，契约 `ed057e0ddadbcdbb47bd8e78c541cf009fd719c397ffe79579d3ae2684802fc3`。双环境业务和恢复正在运行。
- 实际系统总线可查看 systemd 的 `GetUnitByPIDFD` 方法。内部 Agent 维持原 L0 限制，受限角色的实际认证另验。生产 ARM64 主机、真实性能和外部服务另验。
