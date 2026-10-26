# V1.5单次真实准入观测

2026-10-23（Asia/Hong_Kong）。用户明确答复“授权这一次有限观测”。只允许1批Tokenization、1次Chat，输入131072、输出8192、总量139264、framing预留1024、零重试，不启动服务、不写用户业务库。

本Markdown为独占授权记录，正常观测目录为data/v15-observation-20261023-once；目录一旦占用不得复用或另开目录重试。凭证来自原.env.local安全读取，未修改或打印密钥。

固定profile=deepseek-v2，model=deepseek-v4-1-flash-260910；manifest=07e4364b97c980ba1b3e5dbc8f17b75ab1873eded1a85ddbe1b4df352ddfa755；release=51682604bd1665e2060238ac72373a105c11ea05d2a0008d4d835f40f9bf026e；当前程序源码摘要=ccd9ff714fc7234ac4e7a221def7ac655c0b08c4d2878804635a448dbe97042c。

状态：准备执行，最终次数／结果必须核对正常数据库及计数审计；未知结果不得重复调用。

执行退出码：1。工具摘要：

mode=ISOLATED_OBSERVATION
database=C:\Users\羊牧之\Documents\ChatGPT\Project_Wall_E 2\data\v15-observation-20261023-once\observation.sqlite
release=51682604bd1665e2060238ac72373a105c11ea05d2a0008d4d835f40f9bf026e
result=AI_FAILED
admission=OFFLINE_READY
count_batches_sent=1
chat_calls_sent=0



## 实际结果及只读诊断

正常计数审计phase=SUCCEEDED，8项原始计数为system6764、user342、current_request92、structure1、documents1、recent_history1、goal_and_decisions91、position_topic135。三个空诊断文本供应方各返回1个token（各有1项token_ids／offset_mapping），不是计数服务失败。计数请求ID为0217927449252987820404c56ac6dd9ce215ba8b602495a5861b5。

原程序错误强制空文本计数为0，在真实计数后、Chat前拒绝。原run1=FAILED／CONFIG_INVALID／FINISHED，LLMUse=0，根IDLE，没有正文或进度提交。Chat额度未使用，但本次单次观测已经结束；不得复用授权、继续原槽或另开槽补调用。正常数据库及两份count审计保留，不是测试JSON报告。未将失败样本改写成成功，也未发布LIVE_VERIFIED。

修复后仅离线重放同一冻结canonical及原始TokenCounts：全部8个文本逐字节等于原prepared.request.text，原计数不重写，compile_counted与verify_counted通过；预计输入8130，预留输出8192后预计总量16322。无新Tokenization、无Chat、无凭证读取或正常库写入。程序验证修复不能替代缺失的真实Chat／framing证据，状态仍OFFLINE_READY。

修复及显式本地凭证导入的离线联合：`python -m pytest backend/tests/guide/test_v15_counting.py backend/tests/guide/test_v15_observation.py backend/tests/guide/test_v15_admission.py -q -p no:cacheprovider`，18 passed／86.37秒，1条既有Starlette弃用提示。独立新增凭证导入后observer8项通过46.67秒。完整24文件联合运行中，最终摘要单独落盘。

本轮最终完整联合：24文件159 passed／585.80秒（1条既有警告），详见offline-suite-2026-10-23.md；不含新的真实调用。结果文件唯一命名工具的私有临时探针通过，两次输出互不覆盖，探针产物清理。
