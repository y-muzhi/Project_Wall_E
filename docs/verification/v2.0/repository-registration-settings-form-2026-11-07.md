# V2.0 仓库登记表单及原操作视图验证

2026-11-07，V2 未提交工作区。前端锁定依赖、Windows Node 24.15.0、隔离 Vite 构建及真实 Chrome。实现细节见[待合入迭代](../../iterations/pending/v2.0/WALL-E.仓库登记表单与原操作视图_V_2.0.md)。

- npm run typecheck、npm run format:check、npm test 均通过，551 项，0 失败。新增专项核对原202保留输入、错配拒绝、迟到完成不清后来草稿、分区隐藏退休原读取，以及回到可见后恢复已确认失败的原操作。
- .venv/Scripts/python.exe -B -X utf8 tools/verify-v20-command-recovery.py --probe settings --cli-entry <已安装Playwright CLI入口>。实际构建 SPA、Chrome、原生 IndexedDB／sessionStorage 及离线 HTTP。360 像素下仓库表单空／路径错误无写、切换分区保留草稿、提交进行中、202 仅接收且无仓库详情入口、读失败保留原状态、原失败保留输入并可继续编辑、第二次明确登记丢回执后按同一原键核对，重载恢复原操作和原草稿；确认成功后仅清对应草稿并按原仓库 ID 读详情。全设置 1280／360 像素回归通过，89 次产品 GET、8 次明确写，其中两次新仓库原登记，键分别唯一。实际退出 0，测试 Job、浏览器及临时构建已清理。
- 本批为产品前端与隔离 HTTP 验证。真实 C01 ASGI／Native 证据沿[后端记录](repository-registration-service-2026-11-07.md)。C02 刷新和实际 Windows 服务部署不在本批。
