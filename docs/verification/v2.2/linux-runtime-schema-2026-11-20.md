# WALL-E V2.2 固定运行包与 Schema 验证

2026-11-20（Asia/Hong_Kong）。专用 `walle-linux`，Ubuntu 24.04.5、ARM64、ext4。代码基线 `a0f40592702cb702ed928849ac540479c22c224f` 加开发工作区本轮源码及 V2.01 后端设计原件。未启动业务服务、使用既有业务数据、调用模型／计数 API、提交或推送。

| 项目 | 命令／实际证据 | 结果与边界 |
| --- | --- | --- |
| Git 归属 | `git --git-dir=…/repository.git worktree list --porcelain` | 两套独立目录和分支同时存在，均从指定提交创建；集成工作区未接纳开发改动。传输 bundle 已清理。 |
| 前端独立构建 | 两套 scope 分别运行 `npm ci --ignore-scripts --no-audit --no-fund`、`npm run format:check` 及 `npm run build` | Node 24.22.3／npm 11.19.1，分别安装 232 包，两套均通过格式及 TypeScript/Vite 构建，各 120 个 dist 文件。实际 node_modules、dist 和 npm cache 的设备／inode 不同。两套均有既有主包体积告警。 |
| A1 构建 | `build-cpython.sh`、`prepare_wheels.py`、`seal_runtime.py` | 固定 CPython 3.13.18、私有 SQLite 3.54.1、pip 26.2.2、原 31 项版本；目标 wheel 下载核对后离线按哈希安装，`pip check` 通过。r2 使用同一批 wheel 和 hash 锁再次离线安装，未重新下载。 |
| A1 正常入口 | `/usr/bin/python3 -I -B -S …/host-r2/runtime.py probe …` | 4323 个索引文件、19 个宿主库及实际进程映射通过；版本、源码身份、SQLite STRICT／外键反例、JSON、WAL、FULL、触发器深度 100 通过。错误清单摘要、外部 PYTHONPATH 和改写过的 wheel 锁哈希被拒绝。系统 SQLite 仍为 3.45.1。 |
| A2 结构及重开 | 同一宿主入口的 `build-schema` 子命令 | 实际私有 SQLite 比对 73 表／301 对象，297 个原对象不变、2 项修改、2 项新增。在临时磁盘库执行 FRESH_ONLY、同事务写三项元数据、重开核对完整性并拒绝错环境。通过 `renameat2(RENAME_NOREPLACE)` 发布候选并从最终路径重读。使用相同 release ID 再发布得到 EEXIST，原 manifest SHA256 保持。尚未写入环境安装 pin。 |
| A3 锁机制 | `gcc -std=c17 -Wall -Wextra -Werror -fPIC -shared` 编译绑定，在两独立进程运行临时夹具 | 缺失锁拒绝，CLOEXEC 有效，外部观察报告原 PID，竞争失败和显式释放正确，符号链接及额外硬链接被拒。额外一次普通 open／close 确实释放进程记录锁。仅机制专项，未装入运行包或业务入口。 |
| Windows 静态及预检 | `.venv/Scripts/python.exe -B -m ruff format --no-cache --check backend/app tools/linux_runtime`，新增 Python 源码 F 规则，`git diff --check` | 通过。另用系统 SQLite 3.45.3 预检结构及绑定，覆盖升级属性拒绝；正式平台证据以上述 ARM64 实际执行为准。 |

首轮依赖准备将 CPython 的初始 README.txt 误当作污染，确认内容类别后只接受这个普通说明文件。随后 PyPI 元数据有一次读取超时，增加固定来源的有界重试后安装成功。封存 r1 时区分了无 ELF NEEDED 的模块和缺失动态库。r1 生成后因文件索引按 Path 而非 POSIX 字符串排序被宿主入口拒绝，未采用。保留 r1，r2 在新固定 prefix 重建并通过。

| 保留输入／候选 | 路径与摘要 |
| --- | --- |
| 运行包 | `/opt/walle-v22-validation/arm64-r2`，`0977906e961d67222f8e022b4aee86dae49e6268649455e3dec0dacee4420f97`；受保护宿主脚本在 `/opt/walle-v22-validation/host-r2/runtime.py`，本轮外部验证 pin 为同目录 `arm64-r2.sha256` |
| 依赖输入 | `~/walle-v22-validation/build-inputs/arm64-r1-wheels`，平台锁、wheel 来源及宿主库清单随 r2 元数据留存 |
| 结构候选 | `~/walle-v22-validation/scopes/development/schema-releases/db22-arm64-r2`，manifest SHA256 `97524d796ca64851355d08250a2a47ad95c0ca9cb844ca2299ec4c78121e66f0`，对象契约 SHA256 `ed057e0ddadbcdbb47bd8e78c541cf009fd719c397ffe79579d3ae2684802fc3` |

构建、传输、临时探针目录均按操作清理，当期保留平台包、构建输入和结构候选，以及两套独立构建依赖、缓存及输出。构建临时目录和 npm 调试日志已清理，监听复核无本轮新增进程。待补证包括 PKG-01／02 的完整破坏矩阵、PKG-05 的双发布者竞争／同步结果未知、A3 的受信根安装、持久控制和原操作恢复。业务启动、双 scope 浏览器及生产接入尚未验证。

## 固定入口复核

在 Ubuntu 验证机以普通验证身份执行。命令只探测固定运行包，使用本次临时目录，不启动 WALL-E 服务。

```bash
base=/opt/walle-v22-validation
temp=$(mktemp -d /tmp/walle-v22-reprobe.XXXXXXXX)
trap 'rm -rf -- "$temp"' EXIT
mkdir -m 0700 "$temp/home" "$temp/tmp"
pin=$(cat "$base/host-r2/arm64-r2.sha256")
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
    /usr/bin/python3 -I -B -S "$base/host-r2/runtime.py" probe \
    --root "$base/arm64-r2" --sha256 "$pin" \
    --home "$temp/home" --temporary "$temp/tmp"
```
