# V1.5空诊断修复后独立真实准入观测

2026-10-23（Asia/Hong_Kong）。用户新答复“授权新的一次有限观测”。旧槽data/v15-observation-20261023-once及失败记录保留，旧许可不复用。

本新槽最多1批Tokenization、1次Chat；输入上限131072、输出上限8192、总量上限139264、framing预留1024，零重试。不启动用户服务、不写用户业务库。仅技术兼容及用量观测，不包含13项语义EV或其他真实调用。

新独占目录data/v15-observation-20261023-after-empty-fix；创建后无论失败、中断、未知结果均不得重用。凭证由原.env.local安全读取，不记录值、不修改全局环境或凭证文件。

固定profile=deepseek-v2，model=deepseek-v4-1-flash-260910；profile摘要与冻结release一致；manifest=07e4364b97c980ba1b3e5dbc8f17b75ab1873eded1a85ddbe1b4df352ddfa755；release=51682604bd1665e2060238ac72373a105c11ea05d2a0008d4d835f40f9bf026e；程序源码SHA256=34d7d11f6249cca807e2c9ddf56abd999702ed5b0153928a44974b7094114e71。

状态：已占用本Markdown授权记录，准备单次执行；最终次数及状态以正常数据库和计数审计只读核对为准，未知不得重发。

执行退出码：0。工具摘要：

mode=ISOLATED_OBSERVATION
database=C:\Users\羊牧之\Documents\ChatGPT\Project_Wall_E 2\data\v15-observation-20261023-after-empty-fix\observation.sqlite
release=51682604bd1665e2060238ac72373a105c11ea05d2a0008d4d835f40f9bf026e
result=AI_FINISHED
admission=LIVE_VERIFIED
count_batches_sent=1
chat_calls_sent=1



## 只读核对的实际结果

新许可已消耗并结束：计数1批、Chat1次，零重试；LLMUse1／GuideRun1。8项实际计数[6764, 342, 92, 1, 1, 1, 91, 135]，system+user=7106；预计输入8130，实际输入7109、输出2374、总量9483，缓存0，Chat耗时17766毫秒，finish_reason=stop。实际framing gap=3，在0—1024预留内。模型身份与固定profile一致，精确文本及摘要匹配，正常准入引用已在本隔离库记录LIVE_VERIFIED，冻结v10文件仍OFFLINE_READY。

技术准入通过不代表业务语义通过：call_status=SUCCEEDED、parse_status=SUCCEEDED、validation_status=FAILED。正常运行COMPLETED／FINISHED，正文application_result=NOT_REQUESTED，讨论progress_result=REJECTED；结构／引用／来源验证拒绝本次进度，原返回保留可读。根IDLE、discussion_version=2（只有接受增量），正文0份，无候选。此问题继续离线定位，不能将本技术样本改写成EV通过，不能付费重跑。

Chat请求ID=0217927476480984c81961e630bce638d970dc27533587363c6eb；原计数请求ID=0217927476474428f4f8ecdaf0d8a16803f1d267b7ea40d7bfa7c。正常审计及SQLite在该独占目录保留；未导入其他库，未启动用户服务，未执行13项或其他真实效果评测。

## 观测后离线处理

只读重放原parsed.progress_delta及原ContextBasis，首个错误为ADD requires a unique temporary reference（原t-value）；另有topic.evidence_refs错误使用m1。原Wire current_request.content实际有完整原话，goal.text=null来自确定去重。程序及审计不改写；正式Prompt补充既有规则后新增v11／Prompt v3，release改变，保持OFFLINE_READY，v10凭证不可继承。没有额外API调用。

v11默认切换后，以SQLite mode=ro读取原v10 LLMUse1请求详情：READ_OK、八分区、八项计数及冻结139264预算均保持；GET不编译、不重新计数。

跨版本只读核对：当前v11准入验证器核对原v10正常LLMUse1明确ConfigInvalid；未安装凭证、未写库、未调用供应方。证明原技术证据不被自动授予新Prompt。
