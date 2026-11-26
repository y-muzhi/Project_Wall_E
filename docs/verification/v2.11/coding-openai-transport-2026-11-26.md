# Coding 接入 OpenAI 请求协议检查（2026-11-26）

本批按事项 22 修订 10 在 V2.11 工作区接入 GPT-6.2 Sol Chat Completions 请求格式。Coding 网关按固定模型配置选择供应方端点。OpenAI 请求保留原消息、工具与输出限额，使用 `max_completion_tokens`、`reasoning_effort=medium`、`store=false` 并请求最终 usage。网关复用现有 OpenAI 显式代理设置。协议来源见[模型文档](https://developers.openai.com/api/docs/models/gpt-6.2-sol)及[Chat Completions 文档](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。

- Windows Python 虚拟环境中通过 `tools/quality_python.py backend/tests/code_tasks/test_coding_model_request.py -q -p no:cacheprovider --tb=short` 运行离线专项，24 项通过。覆盖固定端点、消息与工具协议、输出限额及原方舟格式。临时目录已回收。
- 直接构造现有 `openai-sol-v1` 固定配置验证 `_fixed_price`，与方舟渠道记录组合返回 `hold`。准入仍按现有方舟规则关闭，后续需接通 OpenAI 账户与用量策略、流式解析实证、执行配置发布。
- Ruff 格式、涉及文件的静态检查及 `git diff --check` 通过。未发送供应方模型或计数请求，未修改业务数据或切换 8001。现有隔离证据中 WALL-E 后台到受管 OpenCode 控制端口仍超时。[Windows 检查](coding-windows-task-route-2026-11-26.md)
- 当前受限执行会话从 `curl.exe` 未连上本机 8001，`netstat` 未列出任何 TCP 连接。这次现场探测无法确认用户侧服务状态。

OpenAI 的标准 API 有公开价格。符合资格账户的 API 额度可能抵扣调用。本批未查询用户账户，也没有据此登记零价。[API 定价](https://developers.openai.com/api/docs/pricing) · [API 额度说明](https://help.openai.com/en/articles/20001626-api-credits-benefit-for-eligible-chatgpt-subscriptions)
