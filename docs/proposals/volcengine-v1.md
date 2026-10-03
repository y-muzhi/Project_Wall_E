# 火山方舟接入细则 v1（待确认与实测）

用户已选择Doubao-Seed-2.1-pro系列（D-006）。本稿补Q-07，冻结六任务资源不改，真实调用和效果结论尚不存在。

## 官方事实与推荐配置

2026-10-03查询：官方[深度思考说明](https://docs.volcengine.com/docs/ark/deep-thinking?lang=zh)列出260628及260915版本，均支持显式关闭思考；新版本默认会返回思考摘要及加密内容。推荐冻结`doubao-seed-2-1-pro-260915`，version=`260915`，显式`thinking={"type":"disabled"}`，以对应已有180秒请求时限及8192输出预算。思考配置会影响质量和耗时，真实效果仍须独立评测，不能由程序测试推定。

[Chat API](https://docs.volcengine.com/docs/ark/chat-api?lang=zh)给出北京地域`https://ark.cn-beijing.volces.com/api/v3/chat/completions`。推荐沿用httpx 0.28.1，JSON非流式，temperature=0、max_tokens=8192、stream=false；不传top_p、tools、tool_choice或SDK自动重试。System装固定Prompt及冻结Schema，User装一个完整业务JSON。连接10秒、read180秒、write/pool10秒；编排最多3次，2/5秒等待。真实服务需证明模型/参数可用，失败不换模型、不静默改字段。

仅提取一个assistant.content；usage和供应方id按实际字段保存，未知null；不估算费用。length/审核拦截/工具调用/空结果不能作为有效业务输出。返回model不等于冻结ID时拒绝采用。reasoning、reasoning_content及encrypted_content全部剔除后再写审计，不回传模型、不公开。HTTP状态及错误编码须依据官方错误文档建立白名单并经可控服务器/真实服务分别验证，不能按字符串猜余额错误。

## 预算兼容仍需证据

官方[Tokenization API](https://docs.volcengine.com/docs/ark/tokenization-api?lang=en)提供文本分词总数，但其完整Chat消息封装开销与260915实际支持尚未验证。已批准资源的UTF-8字节保守计数明确附有“Provider证明待补”条件；不能仅凭模型窗口更大宣布兼容。将独立验证中文/emoji/转义JSON/冻结Schema、System+User总输入、usage及消息开销，并绑定同一版本。若需要改为远端分词或新增计数资源，先提交精确预算实现决策；不原地改变v1资源。

## 凭据及验证边界

密钥仅从本机进程环境WALLE_MODEL_API_KEY读取；未配置时CONFIG_INVALID，不产生虚假AI完成。本文不包含密钥，不要求密钥发入对话。

本次待确认仅为冻结260915及上述非思考请求/超时重试配置。真实兼容与tokenizer证明需要独立执行证据；完整48样本、评分者、阈值及付费预算仍开放，本文不批准144次效果调用。已批准基础层及不依赖模型的业务实现继续。
