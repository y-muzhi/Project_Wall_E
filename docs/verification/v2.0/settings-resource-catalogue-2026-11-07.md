# V2.0 代码设置资源目录验证

2026-11-07，master 未提交 V2 工作区。Windows、锁定前端依赖、固定 SQLite 3.54.1、code20-r2。目录使用既有 API20 与实际发布资源，无接口、目录资源或数据库结构改动。

- npm run typecheck、npm run format:check、npm test 均通过，548 项，0 失败。现有前端目录契约测试改为读取实际 code20-r2，覆盖内容策略的严格字段、身份、未就绪顺序及同 kind 分页，拒绝未登记策略及附加规则。
- .venv/Scripts/python.exe -B -X utf8 tools/verify-v20-command-recovery.py --probe settings --cli-entry <已安装Playwright CLI入口>。隔离 Vite 构建、Chrome 和离线 HTTP。初轮发现旧创建表单在已存在原请求时由单行禁用说明撑宽至 373px，复跑定位到同一个表单网格，修为可收缩列与多行说明。修复后最终 360／1280 宽通过，显式分类、执行器空结果、原模型／MinGit 及 code20-r2 内容策略、原就绪原因、隔离旧分类、错误后重试。未选择无 GET。全设置回归 72 产品 GET、5 次既有明确写。退出 0，原 Job 和产物已清理。
- tools/python-v20.py tools/quality_python.py backend/tests/code_tasks/test_configuration_options.py，独立临时目录运行。首轮在 360 秒超时，无完整结果。冻结资源与准备专项 16 项通过，独立实际 ASGI API20 单项 6.26 秒通过，覆盖真实登记项、全部类别及页越界且无业务写。最后在独立测试进程完成全文件，34 项通过（75.76 秒）。首轮超时原因未证实。
- 本批验证只覆盖资源目录读取及界面。资源编辑、复制、发布、真实执行准入和供应方验收另行实施。
