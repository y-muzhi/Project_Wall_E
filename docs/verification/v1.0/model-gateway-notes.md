# 模型网关验证范围

2026-10-05实施D-007固定单attempt HTTP适配器。请求只有已批准参数和System/User两消息；默认httpx transport retries=0、trust_env=false、follow_redirects=false，connect/read/write/pool为10/180/10/10秒。程序调用者仍须通过实际Builder和审计准备，网关不是公开HTTP入口。

错误白名单按[官方方舟推理错误表](https://docs.volcengine.com/docs/82379/1299023)建立：已知临时服务/限流可由编排在总额度内重试；余额、认证、权限、配额、参数和安全拒绝不可重试。相同HTTP 429的SetLimitExceeded/QuotaExceeded不按一般限流处理。未知非空编码不按前缀或文案猜测，不可重试；没有编码时使用已确认HTTP状态规则。原错误消息只进入私有脱敏审计，不对外透传。HTTP成功的content_filter/refusal与length分别给不可重试安全拒绝和可重新生成提示，仍须实际解析门禁，均没有可信成功结果。

[官方Chat API](https://docs.volcengine.com/docs/ark/chat-api?lang=en)的usage.prompt_tokens/completion_tokens、prompt_tokens_details及响应id按实际字段采集；缺失或类型不合法不估算，费用/币种不推算。超过共同精确整数范围的完整响应安全拒绝，不截断改写。wire解码容量按已批准4MiB审计容量上界保守限制；超限关闭读取且不保留部分原文为完整结果。凭据回显只保留私有脱敏审计，不把改写答案采用为成功。

专项用真正本机ThreadingHTTPServer和httpx AsyncHTTPTransport发送TCP请求；私有测试transport把固定外部URL转到隔离loopback，诊断密钥不是正式凭据。测试仅覆盖HTTP协议、故障和计量事实，不证明火山模型兼容。真实SQLite集成从实际C03/准备事务发出精确输入，证明请求前提交、网络等待不持有写锁、解析与Schema失败分阶段、独立三attempt事实及业务取消后晚到计量不重新打开运行。上下文扩预算仅为协议诊断夹具，没有启用生产预算。取消一个任务关闭自己的本地连接，不能保证远端停止计算、免费或退款。

首轮专项暴露诊断server主动断开后仍继续读的线程错误和超精确范围计量夹具的错误成功预期，均已修正；没有放宽生产Schema或审计范围。原native异步debug的慢回调提示来自本地TLS初始化/SQLite夹具，未称为生产console验证。

尚缺实际ORCH与30秒恢复/10秒停机后台、可信业务产出和C07、真正同版本模型/分词封装证据、评测样本阈值及付费预算。未请求正式Provider、未启动生产服务或默认生产库，373全设计验收未提升。
