# R163 云 x86_64 固定运行包目标代码

2026-11-23，独立工作区 `output/v22-dev-isolated`、`codex/2.2`。依据 V2.01 后端 4.11、7.2、8.1.1、8.2 及架构评审 3.1，目标 Ubuntu 24.04 Linux x86_64 使用同一原生构建链，生成自己的包和准入证据。

- `python -m pytest -q backend/tests/infrastructure/test_v22_linux_runtime_targets.py` 共 3 项通过。使用 Windows 隔离目录保存真实清单、输入锁和安装锁，分别设置 ARM64 与 x86_64 宿主输入。两种匹配的清单验收通过，跨架构运行清单、另一架构 SOABI、依赖清单、安装锁和未知平台输入被拒绝。该专项适配了宿主测量与权限。
- Git Bash `bash -n tools/linux_runtime/build-cpython.sh`、两入口 `--help` 和 Ruff F／I 通过。默认 ARM64 参数调用保留，显式 x86_64 选择从编译到封存。验证目标清单采用同一固定格式，原 ARM64 产品资料保持。
- 本机未安装 WSL Linux 发行版，现有验证机经只读核对为 ARM64。未取得 x86_64 Linux 原生运行包、本机依赖、实际动态库映射、固定候选或生产接入证据。
