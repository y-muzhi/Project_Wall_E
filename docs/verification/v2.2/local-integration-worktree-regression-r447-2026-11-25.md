# R447 当前集成工作区回归与前端构建

日期：2026-11-25。状态：当前源码隔离验证通过；固定候选、正式发布与生产接入未执行。

## 工作区与源码

- 开发工作区为独立仓库 `codex/2.2`，集成工作区为独立仓库 `codex/2.2-integration`；`.git` 目录与对象库物理路径各自独立，均无 objects alternates。两边 HEAD 均为 `deacba8a9545122f35a2f85c125a354205e06461`，索引均干净。
- 本报告写入前，已将 324 个未提交改动文件从开发工作树原子投影至独立集成工作树；共 2,653,882 字节，按相对路径、NUL 分隔和文件内容计算的组合 SHA256 为 `9169c476a2d1bca50d160419efdd2b1611f148efca403ffe0e40061d6c170fb1`。两边文件集合与逐文件内容摘要相同。投影仍为工作树改动，没有 Git commit；不代表受信正式交付或固定候选。
- 收尾复核确认：两个工作树各有 325 个未提交路径，路径集合及逐文件 SHA256 一致，HEAD 相同且索引干净；git diff --check 均通过。本轮 QEMU 进程和 R445–R449 隔离临时目录均无残留。

## V2.01 原始设计与分支基线副本

主工作区五份实施来源摘要为 README `bc4af5efc41989bc0d6ceeb4225a997bb311f5b581116f2a9ad58d0a46420e49`、大纲 `88426de112400fa8e8e23669414eb3fd741ef2ca06a256eee71a53fa326250ed`、架构 `3a878cb9cc6cda1c0b0ea8704c7cc95025cbe13a2957801491982ba542389cb6`、后端 `a3e435cb541d59cd66defeccbc619a3f85414e53bace4ff400ea1deb8c72b96d`、前端 `0a5c079e0b6c2c0bb2d4e6ef4a7511c1a5cdf161e8bcffc70e00d48d0a4384e0`。两个分支 HEAD 的 Git 树含 README、大纲、架构及后端四份文件；后端摘要相同，其余三份分别为 `6ce066ee41f344a327286b36714077ece4318697a83cf471ff3d304eb193e873`、`364853f1c9aea41b5a11a858c27f23d7498fb761734451d936f5b031e0ce85a6`、`613731208be442dec3f2e793aa9eed41212bf29bb1be4a725d5fe99090a026ea`。前端设计未纳入分支树。这些分支路径均在 HEAD，且当前无路径改动；开发工作树稀疏检出只展开后端文件。未覆盖或同步分支副本，实施来源仍按主工作区五份当前原稿和已记录摘要绑定。

## Linux 固定运行时专项

- 使用 Ubuntu 24.04 x86_64 无网来宾及固定 CPython 3.13.18／SQLite 3.54.1。测试载荷先核对 128 个当前源码文件摘要；QEMU 进程 54176，只有 loopback、无网卡和端口转发，来宾正常关机并返回 `WALLE_QA_DONE:0`。
- 第一次未适配的完整运行结果为 276 passed、2 skipped、1 failed。唯一失败的 `test_collect_publishes_only_verified_bytes` 是构建工具测试，固定运行包按设计没有 `pip`，故 `pip._vendor.packaging` 不存在；其余断言均通过。
- 随后仅在隔离来宾的 `/qa/tmp` 建立一次性 `pip._vendor.packaging` 兼容导入，映射到当前锁定的公共 `packaging 26.3`，没有修改产品源码或固定运行包。再次运行 `backend/tests/infrastructure/test_v22_*.py`，原 R447 首次结果为 277 passed、2 skipped、8.48 秒。随后仅修复一处新引入的 I001 import 顺序，重新生成核验 128 个当前源码摘要并在新 overlay 复跑完整套件，最终 **277 passed、2 skipped、8.07 秒**，`WALLE_QA_DONE:0`。该适配验证 Linux wheel 选择／硬链接发布路径，但不替代用正式构建器中的 pip 26.2.2 原生 vendored 模块再做构建工具验收。
- 来宾输出有一条 Starlette 关于 httpx 测试客户端的弃用警告，不影响本次断言结果。

## Windows 与前端检查

- Windows 宿主兼容 runner 对 `test_v22_registry_recovery_dispatch.py` 和 `test_v22_registry_recovery_disposition.py` 运行 105 项，全部通过。import 修复后，`test_v22_closed_artifact_publication.py` 运行 25 项通过、2 项平台跳过。另一次 Windows 兼容尝试因本机 Anaconda 缺少 Starlette，在收集 `test_v22_managed_program_release.py` 时退出；该模块已由固定 Linux 全量套件执行通过。Linux 全量固定运行时结果以上述原生 Ubuntu 来宾为准。
- `python -m ruff format --no-cache --check backend/app`：661 个文件已格式化。对 `environment_recovery_installation.py`、`backup_capture.py`、`manage_registry.py` 及两份恢复专项测试执行范围 Ruff：全部通过。`git diff --check` 通过。
- 未限定范围 `ruff check backend/app` 在 I001 修复前报告 361 项、修复后为 360 项。逐项对照 HEAD 行后，余下 21 项位于修改文件的未改行，另 339 项位于未修改文件；当前改动行没有 Ruff 诊断。全目录 Ruff 仍未通过，本批只完成必要范围检查。
- `npm run format:check` 通过。`npm test` 的单测调用后端纯文本归一化函数；本集成工作树没有 `.venv`，初次调用因此找不到解释器。使用测试已支持的 `WALLE_OFFLINE_TEST_PYTHON=D:\Anaconda3\python.exe` 重跑，**609 项全部通过**。
- `npm run build` 中的 `tsc --noEmit` 和 Vite 8.3.2 生产构建通过。产物留在隔离集成根的 `frontend/dist`。Vite 提示主 JS chunk 约 2.83 MB（gzip 828.50 kB），属于构建警告，尚未拆分。
- 完成双工作树逐文件隔离复核：两侧 `frontend/node_modules` 各有 8,402 个文件、`frontend/dist` 各有 120 个文件；两侧内容摘要完全相同，所有文件身份均不共享，也未发现链接或 junction。两边由各自依赖独立构建。

## 边界与后续

本轮没有运行浏览器或真实供应方调用，没有触碰 8001 用户服务、业务数据、云资源，也没有提交／推送。正式候选依赖受信的 Git 提交及登记来源；当前仅完成独立工作树间的未提交投影和离线验证，不能据此称候选或生产接入完成。接续时先用正式构建器原生 pip 26.2.2 覆盖 wheel 收集测试，再按已授权的候选来源流程运行固定候选验证。ARM64、COS 双宿主及生产采用仍分别待验。
