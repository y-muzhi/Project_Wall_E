# WALL-E V1_0.6

项目正在从零实施。两份设计需要完整逐段阅读，公共方案、火山模型配置、人工来源/身份回执和完整事实证据/卡片等价v2资源已获用户确认。后端基础及文档/需求/消息/审计/本机HTTP网关、版本资源、可信输出、C07、编排、后台和正式API生命周期730项完整回归通过；前端59项测试及完整TypeScript检查通过，298对编辑器快照和最新16对实际SQLite保存回执保留原验证范围。13个只读及24个写入HTTP适配器与全部37前端绑定已接入，实际浏览器通过同源代理完成隔离实库调用及7份文档/1份历史配对校验；完整页面尚未实现，不能作为完整应用交付。

接续首先阅读 [实现进度](docs/实现进度.md) 和 [需求映射](docs/需求实现映射.md)。不能将本准备批次当作完整交付。

当前辅助工具只依赖本机 Node.js（实测 v24.15.0），无第三方包：

```powershell
node tools/spec-audit.mjs check
node tools/verify-primitives.mjs
node tools/spec-audit.mjs read frontend 352 500
# 仅在确实看完完整输出且没有截断后另行执行：
node tools/spec-audit.mjs confirm-read frontend 352 500
```

`index` 验证原文哈希/版本并生成标题与稳定锚点索引；不标记阅读或实现完成。`read` 每段最多18000字符，超限拒绝，缩小范围后重读。`confirm-read` 是人工确认入口，不自动证明操作者读过原文；台账记录必须与实际工具输出一致。`check` 验证当前原文和已记录阅读的哈希并计算未读区间。原始文档不写入仓库、不修改。

后端环境实测Python 3.13.5 / SQLite 3.45.3；精确第三方依赖见backend/requirements.lock。安装与当前可用的数据库入口：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock
.\.venv\Scripts\python.exe -m backend.app.infrastructure.database init
.\.venv\Scripts\python.exe -m backend.app.infrastructure.database check
.\.venv\Scripts\python.exe -m backend.app
node tools/verify-storage.mjs
```

默认数据库为项目data/wall-e.sqlite，可用WALLE_DATABASE_PATH指定绝对路径。当前Schema版本4；升级先备份，无法证明的旧人工来源或草稿分配历史拒绝升级并保留原事实。重复初始化仅校验已有结构；未知版本保留数据并拒绝。服务绑定127.0.0.1:8000，单进程、不启用reload，先校验已有库、取得OS锁并完成恢复，再接受HTTP；缺库拒绝启动。Ctrl+C退出由uvicorn调用关闭生命周期。模型凭据及正式计数兼容仍需配置/证明，缺失时AI运行真实失败，不生成示例业务结果。验证记录保存在docs/verification；[服务验证范围](docs/verification/service-notes.md)和[实施计划](docs/实施计划.md)列出待完成项。本轮仅使用隔离临时库测试，测试进程已关闭。

前端安装/基础验证范围见[前端说明](frontend/README.md)。项目根验证：`node tools/verify-frontend.mjs`。这不是页面或浏览器验收。
