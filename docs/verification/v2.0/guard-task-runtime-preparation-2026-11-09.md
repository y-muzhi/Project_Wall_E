# V2.0 原任务运行包、实例环境与文件证据

2026-11-09（Asia/Hong_Kong），Windows x64／本机 NTFS，工作树基线 `28a7c9e`，固定 SQLite 3.54.1。对照 BE 7.3.1—7.3.4、7.4.4。 [独立迭代](../../iterations/pending/v2.0/WALL-E.执行器配置隔离与生效迭代_V_2.0.md)

## 原运行包持有与只读发布

- 受信来源清单与根在整个访问期持有，初查固定每个原卷／FileID，复制重开同一文件并在读锁中核对实际字节。目标使用原 runtime 角色，新建各子目录，核对原 DACL／标签、精确文件树、文件字节及 FileID。部分写入保留原范围，不能重新发布。
- 通过 `tools.quality_gate.environment`、隔离 `--basetemp`、`WALLE_TEST_CONTROLLER_POSITIVE=1` 执行 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short backend/tests/infrastructure/test_v20_opencode_runtime_bundle.py`，**9 项通过**（2.88 秒）。源和目标同字节替换均拒绝，取消留下原部分目录。自动清理目录已核对不存在。仅既有 Starlette 弃用提示。

## 实例私有配置与环境

- 原 config 角色的新只读配置根、原 scratch 角色的 home／data／cache／state／temp／AppData 均读回原 FileID 和保护 DACL／标签。配置路径仍指向 runtime/opencode.json，系统目录从 Win32 解析，环境由允许集合构造。测试将个人配置、TEST 覆盖及供应商凭据放入父环境，结果中未包含；原配置根污染、私有 home 新来源及受管系统目录出现均拒绝。
- 同一隔离命令选取 `test_v20_opencode_runtime_bundle.py` 与 `test_v20_opencode_managed_config.py`，**16 项通过**（6.13 秒）。系统来源正负边界使用隔离目录，Windows 与 NTFS 读取实际执行；未启动 OpenCode。临时目录已核对清理。

## 同一原 PREPARE 的文件证据

- Guard 接受安装侧登记的运行包路径和固定摘要。认证管道以原范围、原输入摘要及绑定引用分派 `PREPARE_FILES`。已有依据关闭和工作区发布均成立后才保存原准备意图，写入受管运行包及实例环境并保存四类证据摘要。原 `VERIFY_FILES` 只查已有记录及当前原对象。文件阶段保持业务 PREPARE 未确认，未分派 CREATE。
- 首轮完整管道成功与落盘后回复未知各 1 项，合计 **2 项通过**（20.01 秒）。最终回归额外覆盖任务固定但部署未登记的运行包引用、缺依据或工作区、重复及 STOP 后迟到查询。保护程序准入为夹具，Windows 管道、原进程、NTFS 目录、文件及回执为实际。
- 最终数据库无关组合 **132 项通过**（127.59 秒）。同一隔离命令覆盖 `test_authenticated_task_workspace_publication`、整组依据、来源预检、已封存 TASK、VERSION／CONFIG_PARSE、Host、Journal、owner、NTFS 角色、私有记录、WFP、工作区原组件、运行包／系统配置、固定程序和 OpenAPI 专项。仅既有 Starlette 弃用提示，四次隔离命令临时目录均已核对清理。应用 295 文件 Ruff 格式、12 个改动应用模块 Ruff lint 及 `git diff --check` 通过。
- 文件证据阶段不读取工作区正文。正式启动前仍需原后端按已封存清单重读全树并联合核对原程序、真实 LPAC／WFP、Job、入口、正式双账户和原生配置生效。前批 `db20-r29` 既有来源摘要差异保留，数据库依赖的仓库登记未复跑。
