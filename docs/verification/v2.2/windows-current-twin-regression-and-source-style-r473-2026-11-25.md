# V2.2 R473 当前源码双工作区前端回归与源码检查

2026-11-25（香港时间）。工作区为 output/v22-dev-isolated（codex/2.2）与 output/v22-integration-isolated（codex/2.2-integration），两者 HEAD 均为 deacba8a9545122f35a2f85c125a354205e06461。Node v24.15.0、npm 11.12.1、Python 3.13.5。本批未启动服务或浏览器进程。

## 前端隔离与构建

- 两个工作区各自创建本地 .venv，include-system-site-packages=false，使用 Python 3.13.5；解释器基于同一系统安装，但各自的 site-packages 和测试入口独立。首次 npm test 因测试入口要求工作区 .venv 而失败，补齐后两侧各自 npm test 均为 609 项通过。
- 两侧各自运行 npm run typecheck、npm run format:check、npm run build 与 npm run build -- --config vite.management.config.ts，均通过。普通构建 120 个文件，index.html SHA256 为 9aded9f7776a9cd512d2665d25d0ad1897b4887d40a020d6de343148fa18932b；管理构建 3 个文件，index.html SHA256 为 1b507a7af77824d30aa56e30e37ee2b0ba3d07ef883fcd2aa4f46ecfa8199702。
- 对两个输出目录逐文件比较，普通与管理构建文件名、大小和摘要分别一致；两侧对应输出的 Windows 文件身份不同，未共享构建文件。普通前端存在既有的单个 JS chunk 超过 500 KB 警告。
- 本批未以 Windows 静态构建替代 Linux 运行包或浏览器验收。Linux 管理 HTTPS、角色浏览器及固定候选归属的实物结果分别见 R470、R471、R472。

## Python 源码检查

- Ruff 0.17.3 包与 ruff.exe 分别复制到两个工作区的本地 .venv，文件内容匹配锁定副本、物理文件身份不同；两个解释器均报告 0.17.3，pip check 无破损依赖。
- 各自运行 ruff format --no-cache --check backend/app tools/linux_runtime 及本批专项文件，672 个文件全部已格式化。对两侧 133 个变更 Python 文件以各自原 HEAD 文件内容对照 Ruff E/F/I 诊断：当前诊断 71 条、HEAD 基线 128 条，新增诊断为 0。变更文件中现存的 66 条 E501 均可在原 HEAD 找到；本批 37 处行宽拆分经 AST／SQL 片段等值核对，37／37 保留原表达式。
- 两个隔离前端测试套件、类型、格式和两种构建已通过；本批未重跑 Linux 后端 304 项专项。该数仍是 R467 记录的历史结果，Linux 当前管理与发布行为依据见 R470–R472。
- 未触碰主工作区文件、普通用户服务、业务数据或 Git 索引；未执行 Git 提交／推送、生产接入、真实模型／计数／付费调用或云采购。Windows 当前源码的静态构建和前端回归通过不代表生产接入完成。
