# V2.0 Coding 专用模型入口、发送与用量

2026-11-09 香港时间，Windows／NTFS、临时 Schema 200、实际隔离回环。基线 28a7c9e。范围为 BE 7.5.1—7.5.5、OBJ-CODE-USAGE 和原 START.ModelWindow。 [独立迭代](../../iterations/pending/v2.0/WALL-E.受控模型协议与预算准入迭代_V_2.0.md)

- `test_coding_model_request.py`、`test_task_start_session.py`、`test_v20_task_model_source.py`、`test_v20_opencode_instance_control.py` 组合 36 项通过（73.57 秒）。实际 IPv4 accept 与持久 QUEUED／OPEN、来源复核、重复 HTTP 头、关闭窗口及原生协议请求验证。Guard 源组合和模型响应在本次使用明确夹具。
- `test_coding_model_gateway.py` 8 项通过（97.49 秒）。在实际 SQLite 中先写原发送名额／预算及原 LLMUse；固定 URL 由 HTTPX MockTransport 捕获。覆盖同会话并发拒绝、前置核验变化、费用不足、断流、缺用量、用量回退、完整 SSE 按帧先存后转发、精确结算及重启。旧调用已进入发送时保留预留，新请求不会复用原编号。
- 命令统一使用 `tools.quality_gate.environment` 及自动清理 `--basetemp`，由 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short` 运行对应文件。前端严格类型、Prettier 及 566 项回归通过。
- 当前支持在完整调用时间内已证明同一价格的固定平价资源，需真实账单范围、价格版本、用量契约和完整输入上界证据。分档或价格切换无法证明时保持关闭；现有目录默认 Q20-MODEL 未就绪。正式供应商、真实 OpenCode／WFP 和正向组合仍待验收，未调用真实服务。
- 受管配置使用固定源码环境替换机制注入实例模型地址和专用凭据。 [OpenCode 配置加载源码](https://raw.githubusercontent.com/anomalyco/opencode/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/config/config.ts)
