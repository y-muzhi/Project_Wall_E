# V2.0 工作区开始任务和原请求恢复

2026-11-08（Asia/Hong_Kong）。FE BND-CODE-CONTROLS、SHR-FE20-ACTION、BE API35／17。源码接入原 C35 及共享 IndexedDB，请求体固定版本。原 202 必须绑定当前 task_id、原操作及下一 state_version。开始、停止等待、结果核对及同键恢复分别处理。未核实接收时保留原键，禁止新开始；已接收只查原操作，结果未知由用户明确核对。工作区显示当前已核实进度、配置未就绪与固定内容不可用。

- Windows Chrome 及实际 SPA 隔离构建。tools/verify-v20-command-recovery.py --probe tasks 使用既有本机浏览器入口。360／1280px 验证禁用说明、工作区准备、未知／未就绪与进度刷新。对一次明确开始截断已接收的 202，刷新后由用户按原键核对同一操作，服务记录仅一个开始 POST，原请求版本为 1。回归覆盖创建、代码文件、窄屏停止确认取消和原停止恢复，退出 0；浏览器、Job、临时构建和夹具已清理。
- npm run typecheck、npm run format:check 均通过。首次全量 563 通过、1 失败，旧测试预期 START 未绑定。同步该测试为验证无本地持久化时不发送，新增原 task_id、下一版本与任务状态校验。最终 node --test --test-reporter=spec tests/*.test.mjs 565 通过，0 失败，5.18 秒。
- 浏览器用离线 HTTP 夹具。实际后端原 START／Windows 属性的独立证据见 [LPAC 预检](lpac-start-attributes-2026-11-08.md)；本次没有安装系统组件、启动 OpenCode 或真实模型。浏览器尚未单独覆盖点击“停止等待”及可恢复的未接收同键重放；共享命令及外部中止行为由既有前端测试覆盖。
