# WALL-E V1_0.6

项目正在从零实施。两份设计已完整逐段阅读，三组公共方案、火山模型配置及人工编辑持久来源已获用户确认。后端基础、文档算法及需求/正文/历史读取与属性修改能力176项测试通过；前端28项测试、完整TypeScript检查及282对真实编辑器快照验证通过。完整业务HTTP、页面与AI运行尚未实现，应用尚不可运行。

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
node tools/verify-storage.mjs
```

默认数据库为项目data/wall-e.sqlite，可用WALLE_DATABASE_PATH指定绝对路径。当前Schema版本3；升级先备份，无法证明的旧人工来源拒绝升级并保留原事实。重复初始化仅校验已有结构；未知版本保留数据并拒绝。入口只初始化/检查，不启动业务服务。验证记录保存在docs/verification；阶段计划见[实施计划](docs/实施计划.md)。当前没有服务在运行。

前端安装/基础验证范围见[前端说明](frontend/README.md)。项目根验证：`node tools/verify-frontend.mjs`。这不是页面或浏览器验收。
