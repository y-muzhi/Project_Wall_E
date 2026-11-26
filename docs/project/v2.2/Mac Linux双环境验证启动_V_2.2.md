# WALL-E V2.2 Mac Linux 双环境验证启动文档

## 本次要确认什么

在 Mac 的 Linux 内建立开发和集成两套 WALL-E。分别以普通 Linux 用户准备依赖、修改源码、运行确定的离线任务、生成代码文件和构建产物，并确认另一套环境不能读写本套的受保护路径。随后分别通过 WALL-E 真实入口创建需求、编辑保存和重启读回。外部 Agent 或操作者可以在各自工作区执行；WALL-E 内部 Agent 的自动派发、执行和回传在 Linux L0 准入通过后独立核验。

## Windows 交付输入

- 固定源码提交为 `27905ede384e7b1a216eb735c969825c31507141`，源码提交整树为 `783a92e96ceed8c79425c60394d7c8a03e9cd61f`，集成分支已采用该提交。两分支末端另含 V2.2 文档。两侧源码导出已实际回读，清单 SHA256 为 `9a0afb0e5aaabfc8020b4e80cc9a993c7df62d21ae5326f5ab00ef5a1c9756a0`。交接时校验目录内 SHA256 清单与 Git 引用。
- Windows 交接目录为项目内 `output/v22-mac-linux-handoff`。复制整个目录到 Linux 本地磁盘。完整 Git bundle 提供 `codex/2.2` 和 `codex/2.2-integration`。主项目 V2.01 五份设计原稿单独供溯源与 Schema 构建，保留原字节。
- 固定运行输入提供 CPython、SQLite 及支持架构的锁定 wheel。前端仍需目标 Linux 的 Node/npm 与 `frontend/package-lock.json` 匹配，使用可用的 npm 缓存或已授权的包源。Windows 的 `node_modules`、测试数据库、用户配置和浏览器资料无需迁移。

## 先核对 Linux 现场

在目标 Linux 上执行 `uname -srm`、`cat /etc/os-release`、`id`、`findmnt --target <验证根>`、`git --version`、`node --version`、`npm --version`、`command -v gcc make caddy setpriv`、`df -h <验证根>`。固定包目前支持 Ubuntu 24.04 的 `aarch64` 或 `x86_64`，以 Linux 来宾自己报告的架构为准。记录两个专用用户和组、验收根的文件系统与挂载参数、验证用 HTTPS 端口是否空闲。源码、缓存、SQLite、套接字和产物放在 Linux 本地文件系统；共享目录只用于传输交接包。应用、维护和构建执行身份按环境独立。管理员负责系统身份、固定目录和网关，实际编译、文件产出及业务进程以对应非 root 用户运行。

## 验证顺序和入口

1. **验交接包。** 在 Linux 交接目录运行 `sha256sum -c SHA256SUMS`。在一个新建验证 Git 目录中用 `git bundle verify /绝对路径/walle-v22.bundle` 和 `git bundle list-heads /绝对路径/walle-v22.bundle` 核对两条分支。在两个执行用户自己的空目录下，分别以 `git clone --branch codex/2.2 /绝对路径/walle-v22.bundle <开发源码目录>` 和 `git clone --branch codex/2.2-integration /绝对路径/walle-v22.bundle <集成源码目录>` 检出。各自核对 `git status --short --branch`、`git rev-parse HEAD` 和固定源码提交是否为当前 HEAD 的祖先。创建各自专用验收分支，记录起点。固定程序输入由明确的交付对象导出，源码写入试验在各自工作目录。
2. **生成原生运行包。** 有原生 Ubuntu 构建工具链时，按来宾架构选择交接目录里的 `runtime-inputs`。以每个构建身份私有的空绝对 prefix 和 TMPDIR 运行 `tools/linux_runtime/build-cpython.sh <prefix> <sources目录> <arch>`。随后以 `<prefix>/bin/python3.13 -I -B -S tools/linux_runtime/prepare_wheels.py backend/requirements.lock <该架构的 wheels 目录> --architecture <arch> --wheel-manifest <该架构路径>/metadata/python-wheels.v1.json --wheel-manifest-sha256 <清单对应 SHA256>` 安装；用同一解释器和隔离参数执行 `tools/linux_runtime/seal_runtime.py <各自运行包ID> --architecture <arch>`。记录运行包 pin，然后按原 `runtime.py probe` 通过非 root 准入。封存后按固定运行包要求由安装阶段设置 root 所有权，应用进程仍为原非 root 身份。两套均使用自己的 prefix、HOME、TMPDIR 和缓存，按各自主机身份和真实确认目录填参。
3. **验证代码文件产出。** 两个执行用户分别在自己的验收分支运行一次同样的离线任务，生成一个带本环境标记的代码文件，执行它并用 `git status`、`stat` 和 `sha256sum` 确认内容及属主。两边使用相同相对文件名和不同标记。根据明确授权的测试路径做相互读取／写入反例，确认拒绝、对方字节保持，并记录具体失败操作、身份和错误码。然后在各自 `frontend` 用锁定依赖执行 `npm ci` 和 `npm run build`，核对两份 `node_modules`、缓存、日志和产物目录归属。无需模型调用。优先以用户先前失败的一类离线文件产出动作作为复现输入，并记录它在 Linux 的原始退出状态。
4. **部署双普通应用。** 用明确提交和 tree，通过 `tools/prepare-v22-release-source.py --git /usr/bin/git --repository <源码目录> --commit <完整SHA> --tree <完整tree> --output <独立输出目录>` 制备并复核固定输入，按 [R457 固定中转](../../verification/v2.2/local-x86-release-source-binding-r457-2026-11-25.md) 由 `manage_registry.py prepare-release-build` 生成受保护程序索引。启动普通环境前记录该索引及导出清单摘要。独立的正式候选登记继续用 `prepare-candidate-validation`。原 `runtime.py build-schema` 生成双份固定 Schema。以 `backend.app.infrastructure.environment_provision` 给两站独立登记配置、前端、数据库、稳定锁、日志、Unix 套接字和应用／维护身份。按 `runtime.py environment` 的 `prepare`、`continue`、`diagnose` 做各自第一次初始化，维护身份用 `serve_environment.py prepare-start`，应用身份用 `serve_environment.py serve`。Caddy 测试配置由 `environment_gateway.py` 以两个实际锚及独立入口生成。记录两个环境 ID、数据代次、构建摘要、应用和网关 PID／测试端口。历史已执行参数和实际输出见 [环境准备](../../verification/v2.2/linux-environment-a3-2026-11-20.md)、[当前普通安装](../../verification/v2.2/local-x86-v22-base-schema-pin-r482-2026-11-26.md)及 [固定源码登记](../../verification/v2.2/local-x86-release-source-binding-r457-2026-11-25.md)。
5. **验证真实业务和失败边界。** 两个 HTTPS origin 分别使用独立浏览器资料。每边创建需求、文档，编辑并保存不同标记。开发站停机时集成站仍可读取和刷新，开发站重启后原浏览器读回自己的正文，再独立重启集成站。交叉环境绑定须拒绝，两个执行身份与数据目录须保持隔离。按 [浏览器联验记录](../../verification/v2.2/local-x86-current-twin-browser-restart-r538-r540-2026-11-26.md) 检查实际返回与进程归属。
6. **结案与后续。** 将实际宿主、提交、操作、失败原因和未覆盖项记入 `docs/verification/v2.2/` 的 Markdown，更新 [实施进度](实现进度_V_2.2.md) 和 [需求映射](../../traceability/v2.2/需求实现映射_V_2.2.md)。只停测试人员启动的进程，再核对测试监听、套接字、锁和本场明确归属的临时产物。生产 8001、云采购、异机备份服务或真实模型调用另需授权。内部 Agent 若在原 AppArmor 等保护边界退出，按 [L0 验证](../../verification/v2.2/linux-agent-p2-a-l0-2026-11-20.md) 保存失败依据，继续普通环境和外部执行。

## 首场通过条件

两个独立 Linux 账号各自产出并运行真实代码文件，完成独立构建，所有反例按原权限拒绝。两个真实 WALL-E 入口均能保存、停启并读回自己的数据，单边停机期间另一边继续可用。同场记录目标冷启动时间及失败。外部执行与 WALL-E 内部自动执行分别填写结果。
