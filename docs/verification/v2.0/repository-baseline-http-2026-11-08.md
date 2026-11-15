# V2.0 C05 HTTP、原队列与结果续核验证

2026-11-08。工作区源码，Windows NTFS，固定 SQLite 和 MinGit，隔离仓库及数据库。后端设计与前端设计原文件保持原字节。本轮未更新用户服务或运行正式安装。

- 真实 ASGI POST、现有后台仓库队列、Guard 管道和 MinGit 到原快照 1 项通过。第一次接收为 202，原操作四步成功，重放仍是原 202，原 GET 公开最终快照 ID。队列在测试故意丢失唤醒信号时仍从数据库领取原操作。C01／C02 现有线程到 Guard 回归 2 项通过。
- 真实 ASGI 严格入参与无登记执行者 1 项通过。HEAD、额外 snapshot_id 返回 422，合法请求在队列未就绪时返回 CONFIG_NOT_READY 且没有保存原操作。原进度投影与重启步骤识别另外 2 项通过。
- 前一轮 C05 保存、篡改拒绝和同作用域证据续核 4 项通过。原引用缺失时核对步骤保持待执行，无写入重发。原引用恢复后重新读取完整对象并按 OBSERVED 保存同一原快照。
- 跨两个后端进程的 C05 实际恢复 1 项通过。原后端在 Git 已提交、原 scope 尚未清理时退出。新后端只向旧 scope 发送 OBSERVE／STOP／OBSERVE／RELEASE，随后仅为同一原操作第 3 步启动 CONFIG 与 OBJECT_BATCH，只读复核后保存原快照。旧引用内容一致，没有新 PIN／COMMIT、备用快照或原记录改绑。
- 仓库接收、Git 派发、回执与 Guard 等 9 个模块的离线后端回归 269 项通过。Schema200 发布验证 3 项通过。额外实际损坏引用用例 1 项通过，原操作结束为 REPOSITORY_UNSUPPORTED，原配置范围释放，未启动后续写入。
- 固定快照身份与引用共用读取已接到原操作结果及后续对象核对。真实 ASGI 原操作投影等 5 项通过，覆盖保存前后内容摘要不一致时拒绝结果；原元数据 23 项通过，覆盖 loose 优先、仅 packed、符号引用不跟随和大小写别名拒绝。最后版实际 C05 HTTP 和跨后端恢复 2 项复测通过。
- 前端 553 项通过，包括固定请求、同 key 同 body 重放和跨仓库回执拒绝。npm run typecheck、npm run format:check 及隔离 Vite 生产构建通过。此批新增客户端绑定，无页面改动。
- service.py 的错误契约接入触发固定来源核对。使用 tools/schema-v20-release.py 生成 db20-r20，manifest SHA256 b4b8e6b4465881e87aff8a58b755bb1b2d1226dfb0209142f14d52832a07ebad。与 r19 的 objects.v1.json、fresh.v1.sql、upgrade-151.v1.sql SHA256 全同，旧发布保留。初轮路由遗漏返回 404，补全实际注册后端到端测试通过。未进行正常库升级。

## 验证入口

Python 使用项目 .venv、tools/python-v20.py、tools/quality_python.py、tools.quality_gate.environment 和自动清理临时目录。Native C05 从 backend/tests/infrastructure/test_v20_guard_control_git_transport.py 选 BASELINE_HTTP、BASELINE_SAVE、BASELINE_RECOVERY、BASELINE_MALFORMED_REF，C01／C02 选 REGISTER_THREAD、OBSERVE_THREAD，跨后端 C05 选 restarted_baseline。ASGI 输入及步骤断点从 backend/tests/code_tasks/test_repository_baseline_acceptance.py 选择 test_snapshot_post、test_baseline_operation_get、test_restart_selects。前端执行 npm test；构建沿 tools.quality_gate 的 build 命令向临时目录输出。

未覆盖基线详情／文件页、任务创建页面、缺证据后用户主动唤醒续核、正式 Guard 安装、供应方及模型调用。最终 Ruff 格式和改动模块 lint、diff 检查通过。临时输出由验证入口清理。
