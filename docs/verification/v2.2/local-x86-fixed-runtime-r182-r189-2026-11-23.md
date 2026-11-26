# R182／R189 Ubuntu x86_64 固定运行包及 Schema200

2026-11-23，独立 `codex/2.2`。便携 QEMU 11.1.3 与本机已有 WHPX 在 Windows 主机内启动 Ubuntu 24.04.5 x86_64（Linux 6.8.0-147-generic，ext4，systemd 255）。Canonical 镜像 SHA256 `406630c08b5e545fcc7209854b129d47e3af822db128c9f19336593b5a2d3fe0`。编译阶段仅访问 Ubuntu APT 与 PyPI 官方公共依赖来源。验证阶段使用无网卡的独立覆盖盘，从已封存的只读母盘启动。没有主机端口、用户服务或业务库。[Canonical 镜像](https://cloud-images.ubuntu.com/minimal/releases/noble/release-20261105/)

- 在独立非 root 构建身份下运行项目原 `build-cpython.sh`、`prepare_wheels.py`、`seal_runtime.py`，得到 CPython 3.13.18、私有 SQLite 3.54.1、ABI `cpython-313-x86_64-linux-gnu`、31 个 wheel、4,324 个固定运行包文件及 19 个固定宿主库。实际依赖安装和 pip check 通过。封存运行清单 SHA256 `e01421575f94ad20fb008f6876be5889766a24b5465dcdf4d15da44b65b4a62d`。
- 首次准入拒绝默认测试 HOME 权限。当阶段专用目录改为 0700 后，真实固定入口 `runtime.py probe` 返回 ADMITTED。本轮未放宽受保护目录、文件、ABI、依赖和系统库准入。
- 原封存运行包的 C 锁与 `NativeEnvironmentFiles` 在实际 Linux 上取得独立进程持有 PID。第二进程同锁写入被拒绝。原持有者正常退出后，观察无持有者，新进程取得新锁代次。
- 第一次 Schema 测试介质漏装四个旧 Schema 源文件，入口按规则拒绝。按 V2.0 和 V2.2 代码中的来源清单补齐同一源码后，固定入口 `build-schema` 成功生成并重新核对 `v22-linux-x86-local-schema`。Schema SHA256 `b6f10886ccbbd96b0f5fd8e88e8ac4b00da6da99984cf1cfda925e702e53db2e`，对象契约 `ed057e0ddadbcdbb47bd8e78c541cf009fd719c397ffe79579d3ae2684802fc3`，与既有 ARM64 对象契约一致。实际 SQLite 新库通过归属、完整性与异环境绑定拒绝。

## 内部 Agent 原型边界

本机虚拟机上实际读取 cgroup v2，确认 systemd 存在 `GetUnitByPIDFD` 方法。受限非 root 用户对本轮自有子进程打开 pidfd、停止该进程并确认退出后的 pidfd 不再可发信号。实际 core_pattern 仍为管道模式，Docker 和 runsc 均未安装，当前 L0 未准入。没有启动带凭据原型、OpenCode 或实际模型。普通环境固定安装不依赖该原型。本证据不替代目标云原生网关、跨宿主 COS 或生产接入。
