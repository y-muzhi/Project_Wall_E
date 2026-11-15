# Coding 模型调用审计、等待及轮询验证

日期 2026-11-09，工作区基线 master 28a7c9e。隔离 SQLite、ASGI、HTTPX MockTransport 与本地 Chrome，正式设计保持原摘要。

- `tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider` 定向 `test_coding_model_gateway.py`、`test_task_runtime_stop.py`、`test_task_stop.py`、`test_task_start_session.py`，21 项通过。预算不够不会产生 LLMUse 或供应商调用，未知费用有原等待项；原停止在途返回的结果保留取消和原预留，不新开等待。
- API66／67 核对空页、无关任务、拒绝错误请求、原有序帧、缺帧描述和原费用，公开摘要没有原快照，详情读取不产生供应商请求。供应商标识保留不透明文本，脱敏快照剔除私有来源证明。
- Playwright 隔离浏览器 `tools/verify-v20-command-recovery.py --probe tasks` 已覆盖 360／1280，调用详情无预取、列表错误不变空、详情失败后重试、部分响应、内容搜索和关闭后焦点返回。任务按轮询自动显示模型预算等待后仍允许明确停止。360／1280 最终组合已通过；扩展复跑已验证隐藏暂停、可见／焦点同轮合并为一次读取、503 后保留上次状态并禁用写动作、退避后自动更新。浏览器只发送一笔开始和一笔停止，临时进程和输出已清理。
- `npm run typecheck`、`npm run format:check`、`npm test` 566 项通过。包含最新轮询与用量展示。锁定 Vite 的临时生产构建通过，临时输出清理确认。受限环境首次构建失败，迁至获准的隔离执行后通过。后端 Ruff 格式检查及新增核心文件 F401／F821 检查通过。

未覆盖正式供应商、账户阶梯价、账单匹配、增加预算及明确恢复。环境服务与业务库不参与隔离检查。

最终定向 `test_coding_model_gateway.py` 与 `test_coding_model_request.py` 共 32 项通过。覆盖供应商标识中的空格及前导零、缺帧索引的安全降级、原模型等待和停止期间费用保留。
