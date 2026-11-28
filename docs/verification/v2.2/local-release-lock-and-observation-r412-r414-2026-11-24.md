# R412–R414 启动锁、部署选择和冻结中的原回执

2026-11-24（香港时间），独立 `codex/2.2`，HEAD `deacba8a9545122f35a2f85c125a354205e06461` 加本地改动。专项只使用当前验证临时目录。查阅 V2.01 后端 4.2、4.11、4.12.3、7.10 及原 V2.2 独立细化。

| 检查 | 命令范围 | 修复前 | 修复后 |
| --- | --- | --- | --- |
| R412 Windows 普通启动 | `python -B -m pytest -q -p no:cacheprovider --basetemp <本轮临时目录> backend/tests/infrastructure/test_v22_startup_preflight.py` | 5 失败、1 通过。普通和有冻结本地续办的路径先读 SQLite，锁忙及拒绝被错误原因掩盖，直接调用也读库 | 6 通过。冻结恢复路径保留，锁忙无 SQLite 步骤，拒绝释放本次锁 |
| R413 部署选择边界 | `test_v22_managed_program_release.py -k guards_both`。同一 pytest 参数，补 Windows 的 Linux 常量和模块导入桩 | 3 失败，原代码在取得宿主共享锁前进入写入分支 | 3 通过。冻结及原控制变化无两种写入，成功时两种写入都处于同一保护范围 |
| R414 原开放结果 | 同一离线适配运行 `test_v22_release_open_history.py` | 7 失败，读控制和外层命令都被宿主新启动门槛错误拦截 | 7 通过。原关闭未准备、仅持有回执、已开放和正常停机分别核对，错回执或错原引用拒绝，外层维持只读准入 |

Windows 默认沙箱的 asyncio 测试一直未完成。经授权按同一隔离工作区和临时根执行后，实际 pytest 在 1 秒内返回。R413 与 R414 的 Windows 适配只证明控制流，不作为实际 Linux 文件锁、部署或外层操作的证据。R414 对照后的测试夹具改用项目现有时间格式，产品判断保持原规则。

## R417 原维护写入与冻结观察

同一独立 Windows 工作区运行 `test_v22_maintenance_transition.py`。旧实现 5 失败、2 通过。进入和取消操作在最后核对之后仍能开始写入，冻结时观察入口也被拦截。修复版 7 项通过，包括宿主在验证后冻结、正常进入／解除、在线操作拒绝和原计划只读。原生固定入口复验接续执行。

## 固定 Linux 回归

[Ubuntu Noble 官方镜像与校验表](https://cloud-images.ubuntu.com/minimal/releases/noble/release-20261105/)。只在准备公开系统工具时启用网络，之后的运行包、源码和业务样本均只在无网 Ubuntu 24.04.5 x86_64、ext4 来宾挂载。使用固定构建、依赖准备、封存及实际 `runtime.py probe`。最终运行包摘要 `c8a54e6342272206dec15db198a2cc2a4910760576722a2f490cbc7f0addc702`，实际 CPython 3.13.18、SQLite 3.54.1、31 项锁定依赖、19 个宿主动态库及 4,324 个运行文件通过准入。初次封存后运行根仍为 builder 私有模式，根目录按既有受信安装模式调整后复验，包文件和清单摘要没有改动。首个来宾 NoCloud 介质未识别，改用明确 DMI、只读 virtio 本地介质后通过。[NoCloud 官方契约](https://docs.cloud-init.io/en/latest/reference/datasources/nocloud.html)

- 对照在同一固定解释器、业务依赖、SQLite 和现有测试中只替换 6 个受影响的实现文件。R412–R414、R417 共 23 个新用例，旧版为 20 失败、3 通过。当前 `python3.13 -I -B -S` 先执行真实运行准入，再经 `pytest -q -p no:cacheprovider --basetemp <本轮专属目录> backend/tests/infrastructure/test_v22_*.py` 执行，最终 242 项通过、1 条既有 Starlette 提示。中间失败来自启动用例缺冒号、重配测试桩未接收离线准入关键字，以及运行目标测试缺封存的 pip 引导 wheel。修正测试夹具和试验入口后在同一固定包重跑。
- Windows 另跑旧工作线程恢复、幂等和原命令回执 14 项通过、14 项平台跳过、8 个子项通过。Ruff 格式 667 个相关文件和 `git diff --check` 通过。

正式新候选仍需实际集成交付、封存及从原维护关闭到真实应用开放的重复验收。
