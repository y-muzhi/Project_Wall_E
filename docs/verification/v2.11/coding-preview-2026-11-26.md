# 咖啡计算器代码产出试跑

2026-11-26，香港时间。V2.11 事项 22。本轮为本机交付样例，复用前次已核验的 OpenCode 1.19.5 和固定 MinGit。产品源码、正常 8001 和业务数据保持原状。

- 在临时目录启动 OpenCode `serve --hostname 127.0.0.1 --port <临时端口> --no-mdns`，配置中仅启用本机固定模型响应。健康接口带临时凭据返回 200，无有效凭据返回 401。实际会话及异步提示请求触发 OpenCode 的 `write` 工具。模拟端收到两次请求，其中一次携带工具结果。产出 `index.html` 共 2,499 字节。
- 在内存复用 `backend/tests/infrastructure/test_v20_delivery_git.py::exercise_delivery`，以同一文件作候选，验证差异、预期旧分支值、更新事务及提交读回。临时 Git 分支 `delivery` 的提交为 `390ad756735f76d213f9428a7899397c55c36f20`。从提交取回的文件与实际 OpenCode 输出完全一致，SHA-256 为 `7124d3d88c57f6feb0f47b043f570d792a7f4f1aa22ad54c76813aa055d3fc53`。预览件曾保存于 `output/coding-preview/index.html`，已随 2026-11-27 会话收尾移除。临时进程、仓库及原始日志已清理。
- 使用 `node --input-type=commonjs -` 在测试 DOM 中执行预览内的原始脚本，校验表单事件和四组结果，其中 20 克、每克粉 17 克水得到 340 克。Playwright CLI 离线包未命中，计算机操作的 Chrome 窗口读取超时，内置浏览器拒绝访问本地文件协议，未取得真实浏览器交互证据。
- 本轮覆盖 OpenCode 写文件、候选封存、实际 Git 读回和计算逻辑。正式 WALL-E 页面发起、人工接受、Windows 任务网络准入及真实供应方代码质量不在试跑证据内。正式启动阻塞见[本机 TASK 启动验证](coding-task-native-2026-11-26.md)。
