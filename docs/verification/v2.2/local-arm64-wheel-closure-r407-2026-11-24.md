# R407／R410 当前 Linux ARM64 wheel 输入与离线闭包

2026-11-24（香港时间）。V2.2 开发隔离工作区，依据 V2.01 后端 7.5、8.1.1。现行 `backend/requirements.lock` SHA256 `64c380d9efed55ab0bd9cb0f590d75d47fc87d1fe7c73b7922c6af6ff496d0c9`。目标标签为 CPython 3.13.18 的 `cp313`、Linux aarch64、manylinux 至 2.39。

- 复用 `prepare_wheels.py` 的官方 PyPI 版本查询、标签匹配、下载位置、大小和 SHA256 核对。实际取得 31 项锁定依赖和 1 项 pip 26.2.2，共 7,906,968 字节。临时输入清单 SHA256 `da1ace47863f1f37a029de51e50dd7718c0fbe7ee48520c675f4a14f30b48b0c`，固定安装锁 SHA256 `df3b4a526cde84bc0b5e7fc9caa6c1dbc8c2c1a3e6ef36f64174ab67b38bf08a`。
- 检查轮包 ZIP 内容和实际 ELF64 架构。两个原生文件分别来自 `pydantic-core==2.46.5` 和 `rpds-py==2026.6.3`，均为小端 AArch64 共享对象。对应 wheel SHA256 为 `193375f3548919d3f0b60936ca113ada3e38f264f91b9b8e0508efaad57be931` 与 `54f45a148e28767bf343d33a684693c70e451c6f4c0e9904709a723fafbdfc1f`。其余 29 项与引导 pip 为平台通用 wheel。
- 用已核对的 pip 执行 `--dry-run --ignore-installed --no-index --require-hashes --only-binary=:all: --implementation cp --abi cp313 --python-version 3.13.18`，只读选定离线目录。31 项闭包匹配。真实 x86_64 目标约束拒绝 ARM64 的必需轮包，错哈希拒绝实际 ARM64 文件。三次解析使用独立临时目录。
- R410 在无网卡 Linux 来宾用 `readelf --file-header --dynamic --version-info` 从原 wheel 提取后读取两份 ELF。两份所需动态库均为 `libc.so.6`、`libdl.so.2`、`libgcc_s.so.1` 和 `libpthread.so.0`，最高所需 glibc 符号版本为 `GLIBC_2.17`。该检查只读分析二进制字节。
- 当前验证覆盖依赖取得、实际文件架构、系统库和离线目标解析。ARM64 原生安装、程序运行、系统服务及候选开放仍待在相应主机完成。本轮未采购资源或访问云环境，轮包与解析临时文件随本轮清理。
