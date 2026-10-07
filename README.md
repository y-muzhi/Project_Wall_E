# WALL-E V1_0.6

项目正在从零实施。两份设计需要完整逐段阅读，阅读台账与来源哈希见 [实现进度](docs/实现进度.md)。公共方案、火山模型配置、人工来源/身份回执、完整事实证据/卡片等价v2资源和计数补充方案已获用户确认。

工作台、新建需求、完整详情、人工草稿、评论、版本、AI会话与建议控件已接入37个真实API，产品根入口、路由与生产构建已接通。前端260项测试与TypeScript检查通过，真实根页面完成隔离数据库浏览器专项。后端814项完整回归通过，新增计数编排/审计/后台101项专项通过；最新准确范围见实现进度。TC-E2E-01—10在明确本机模型/历史夹具下的55个独立HTTP/原生SQLite分支通过，新增跨Python进程持久回执重放，运行`node tools/verify-product-flow.mjs`可重建证据。真实Provider兼容、效果与373项正式验收尚未闭合，不能作为完整应用交付。

新增人工草稿20个不同真实根页面分支验收与恢复基线修正，覆盖串行保存、失败/冲突、显式本地恢复、结束未知重放及正式评论隔离，范围与待验分支见 [人工验收记录](docs/verification/manual-browser-notes.md)。

接续首先阅读 [实现进度](docs/实现进度.md) 和 [需求映射](docs/需求实现映射.md)。不能将本准备批次当作完整交付。

实际应用安装、构建、初始化、启动与停止见 [运行说明](docs/运行说明.md)。正式入口为 `http://127.0.0.1:8000/requirements`；启动前需要构建 `frontend/dist` 并明确初始化数据库。

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


2026-10-07 D-014已接入：新启动的环境配置默认deepseek-v4-1-flash-260910（版本260910），精确白名单保留doubao-seed-2-1-pro-260915；历史请求按完整原Profile恢复，禁止同call_no重试换模型、交叉模型响应/计数/观测许可及参数类型偷换。新counting/v2策略无已证明封装余量，生产发送门禁仍关闭，不启用估计计数或扩大预算。110项相关回归及814项完整后端回归通过，原失败记录保留；范围见verification/deepseek-adoption-notes.md及deepseek-production-adoption-v1.json。没有新增付费调用，也没有重启8000查看服务；该进程仍使用此前已加载的代码。D-014批准稿原字节保留，当前采用状态由独立adoption记录表达。


2026-10-07：D-014默认DeepSeek精确版本已接入，历史Doubao验证保留，生产计数/发送门禁仍待独立兼容证明；本轮0付费调用。工作台WB-01—07使用41条真实API前置，18个独立浏览器分支通过，修复异常时间显示。正常前端构建已更新，可刷新现有查看页面；旧后端进程保持运行，新模型默认在下次明确启动时生效。详见[接入验证](docs/verification/deepseek-adoption-notes.md)和[工作台验收](docs/verification/workbench-browser-notes.md)。


2026-10-07详情继续验收：修复初始完整读取与人工开始的竞争；20个实际根页/原生SQLite分支通过，涵盖布局、离开/恢复、历史及分页；260＋独立4项前端测试、TypeScript及生产构建通过。现有查看页面可刷新。[验证范围与失败](docs/verification/detail-browser-notes.md)保留完整边界；全项目验收和真实模型兼容/效果仍在推进。


2026-10-07评论继续验收：修复删除冲突后无法关闭确认弹窗，补齐失效引用警告。24个实际根页/SQLite分支及独立关闭库审计通过，涵盖评论双状态、操作失败/取消/未知恢复/迟到、Unicode与精确分页；前端260＋另4项、TypeScript及生产构建通过。[范围与原始证据](docs/verification/comments-browser-notes.md)已保存，现有查看页面可刷新；整体验收和正式模型兼容/效果仍未完成。
