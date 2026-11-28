# Mac Linux 双环境 AI 能力核对

2026-11-27（香港时间）。通过已配置的 SSH 路径进入 Mac 上的 Linux 虚拟机，在 Caddy 回环 HTTPS 网关分别以开发、集成站点的现有浏览器身份读取 `GET /api/v1/environment`。核对范围为现场运行能力，源码对照为本地 `master` 的 `990ed2d`，现场程序提交未比对。

- 开发和集成均返回 HTTP 200，阶段为 `READY`，准入为 `OPEN`。两套环境的 `DOCUMENT_READ`、`DOCUMENT_WRITE` 均为 `READY`。
- 两套环境的 `DOCUMENT_AI`、`TEST_PLAN_AI`、`INTERNAL_EXECUTION`、`INDEPENDENT_CHECK` 均为 `DISABLED`，原因均为 `CONFIG_DISABLED`。
- 通过 `/proc` 只核对两个运行进程中配置项是否存在。`OPENAI_API_KEY`、`WALLE_MODEL_API_KEY`、`WALLE_MODEL_PROFILE`、`WALLE_MODEL_ID`、`WALLE_MODEL_BASE_URL`、`WALLE_CODE_MODEL_BEARER`、`WALLE_CODE_MODEL_BASE_URL`、`CREDENTIALS_DIRECTORY` 均未出现在进程环境中。未读取或输出任何模型密钥内容作为检查结果。
- 本地源码对照中，`backend/app/infrastructure/environment_http.py` 的环境握手将上述四项标为禁用，普通环境的 API 准入只开放列明的读写路径。因此补入凭据本身不足以开放这些入口。

未执行模型请求、计数、内部任务或供应方验证，未修改配置或重启服务。
