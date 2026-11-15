# V2.0 设置页原仓库登记恢复验证

2026-11-07，未提交的 V2 工作区，Chrome 及隔离 HTTP。正式 C01 已接入；设置只开放从现有待核对原记录显式恢复原键和原字节。

首轮浏览器用例在等待准备错误提示时失败。定位到共享客户端把所有写入 503 都标为未知。修正后仅 C01 的合法 CONFIG_NOT_READY 保留临时拒绝提示，仍沿原键重新查回执。STORAGE_UNAVAILABLE、C02 的非契约准备失败及传输错误仍按未知处理。node --test frontend/tests/v20-repository-operations.test.mjs 10 项通过。

最终 npm run typecheck、npm run format:check、npm test 通过，549 项，0 失败。tools/verify-v20-command-recovery.py --probe settings 通过，独立构建实际 SPA 和 Chrome（设置全流程含 1280／360 像素）。C01 原键和原字节经显式确认送达，显示实际准备失败，原回执重查未找到，原键继续关闭及未知关闭恢复。全设置 74 产品 GET、6 次明确写，退出 0 并清理原 Job 与临时构建。独立 C01 202／原操作／仓库的真实 ASGI 和 Git 另见[后端验证](repository-registration-service-2026-11-07.md)。新登记表单及实际部署仍待。
