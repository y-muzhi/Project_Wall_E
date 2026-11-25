# V2.11 事项 20 合入及 8001 发布

2026-11-25（香港时间）。用户授权合入本地 `master` 并更新 8001。事项 20 的实现提交为 `88b7c02`，部署源码快照为 `7059587`。保留已发布的工作台、测试页、代码任务、完整模板及输入统计路径，接续 `e83854e` 的独立画板及全屏工具栏。Guard 的另行部署仍按原迭代处理。

## 合入及验收

| 环节 | 结果 |
| --- | --- |
| 合入 | 文档创建及人工草稿兼容画板与完整框架，文本修订与画板各自使用对应权限。保留全屏入口、历史画板和 WOFF2 类型登记。Git 检查通过，独立迭代修订 4 保留原摘要。 |
| 离线 | `npm run format:check`、`npm test`、`npm run build -- --configLoader runner --outDir <发布目录>` 通过，前端 654 项用例通过。合并后画板、模板、AI 审阅和库结构的后端专项 18 项通过。构建提示既有的主包体积阈值。 |
| 数据切换 | 演练库和正式升级副本均通过原结构、新结构、业务留存及完整性校验。切换前后核对 8 篇正式文档、1 份已保存草稿、20 个版本和 1 批待审建议。业务行摘要为 `b50958f5af9dd8eb5c548360c199faf3c80b269c7ae664fa8e0c040dbd957047`。100 个计数审计文件逐文件比对成功。保留源数据库及原审计，同步时源文件字节一致。 |
| 前后端 GET | 8001 监听由 PID 11040 切到 45120。首页、测试页、正式文档、人工草稿、待审批次、消息、历史调用及测试列表均正常。HTML SHA-256 为 `3dd8d8913e3e8e3f487084790c8969ef56a568eb145d34dfa4636ada406a1657`，主资源为 `assets/index-DJFrhcsL.js`。画板懒加载与 WOFF2 字体读取通过。额外保留上一版 590 份哈希资源，另有 358 份同字节资源复用。 |
| 生产浏览器 | Edge 从需求详情打开新建文档，确认前端设计文档、后端设计文档、画板可选。打开文档修订配置，确认「仅提出建议」可见。页面错误和写请求均为零。 |

## 服务现场

- 单入口为 `http://127.0.0.1:8001`。5197、8000、5173、5174 均无监听。
- 持久目录为 `data/service-runtime-v211-review-20261125`。部署源码在 `source-7059587`，静态前端为 `frontend-final`，新库及计数审计在 `store/walle.sqlite` 和同目录的 `walle.sqlite.count-audit`。运行日志为 `review-8001.out.log` 和 `review-8001.err.log`。
- 从部署源码根目录用原工作区 `.venv/Scripts/python.exe -B -X utf8 tools/openai-service.py --start --database <新库> --credential-file <原 OpenAI 配置文件> --port 8001 --proxy http://127.0.0.1:7890` 启动。设置 `WALLE_FORMATION_SCHEMA_LAYOUT=db21-document-review-r1`、`WALLE_OPENAI_FORMATION_RELEASE=openai-v6` 与 `WALLE_FRONTEND_DIST=<静态前端目录>`。讨论激活摘要由 `--activate-release 2e481df9293817e6406c3ef9425fd21ae77a7f0dad439dee3ea116ce04f49b32` 指定，文档由 `--activate-document-release e49cdb154a68a498d11f59eb0914f0b14bed803e59bf253abea38544f11f2928` 指定。
- 原回退源码和静态资源保存在 `data/service-runtime-v211-excalidraw-4e7c340/candidate`，原业务库路径沿上一发布。新版开始使用后如需回退，先核对两个库的新增业务记录并保留新版数据，再选择回退数据与窗口。
- 本次显式启用通过离线准入的文档资源。真实模型和计数调用为零，供应方 100,000 Token 容量及耗时待实际验证。Git 更新范围为本地 `master`。
