# V1.5 v12单次真实技术观测

2026-10-24（Asia/Hong_Kong）。用户明确答复“授权技术观测及条件通过后的26样本（推荐）”。本记录独占申领时间=2026-10-24T12:47:47.747568+08:00。

先1批Tokenization＋1次Chat技术观测；准入LIVE_VERIFIED且首轮返回parse／validation均成功后，执行两领域26固定样本（两份超限样本仅计数、0Chat）。整批最多79计数／25Chat，逐Chat输入≤131072、输出≤8192、总量≤139264；Chat总量≤3481600。零重试、不自动换版本；未知结果、准入异常立即停止。不启动／更新用户服务，不写用户业务库，不调用模型裁判；旧槽及失败原结果保留。失败不复用／补发本槽。凭证仅从.env.local安全读入，值不记录。

manifest=3db3a635d5c639d6e1406e717bd7e84d380e70cb4796464fea101477a5810312；release=ad5e45c5e2373ece410d699c886e887c8179ac5303368c6e2fbc668341110a2e；profile=61941797052baa3c4a6cc1df54759b91d7fa933d2a4b98ec19d8b3b116cfc70e；model=deepseek-v4-1-flash-260910；app+observer SHA256=99778310bc6879a0666d23b715d610c953840fe97a054651293b92720135c302。设计及固定输入摘要核对通过。

状态：准备执行单次命令；实际结果以正常SQLite及计数审计为准。

命令：tools/observe-v15-once.py --execute --output-dir data/v15-observation-20261024-v12-once --allow-count-batches 1 --allow-chat-calls 1 --max-total-tokens 139264 --credential-file .env.local

退出码=0。工具摘要：

mode=ISOLATED_OBSERVATION
database=C:\Users\羊牧之\Documents\ChatGPT\Project_Wall_E 2\data\v15-observation-20261024-v12-once\observation.sqlite
release=ad5e45c5e2373ece410d699c886e887c8179ac5303368c6e2fbc668341110a2e
result=AI_FINISHED
admission=LIVE_VERIFIED
count_batches_sent=1
chat_calls_sent=1


## 技术条件实际核实

1批计数／1Chat／零重试；8项=[7067, 342, 92, 1, 1, 1, 91, 135]；S+U=7409；实际输入=7412、输出=2657、总量=10069、缓存=4096；gap=3、duration_ms=16893、finish_reason=stop。Chat请求ID=0217928172727284c81961e630bce638d970dc275335873a5d528；计数请求ID=021792817272028846a816464a9af9c0791e0f68a2ce03c6111fe。

run=COMPLETED；call／parse／validation=SUCCEEDED；admission=LIVE_VERIFIED；primary=NOT_REQUESTED；progress=APPLIED；根=IDLE；discussion_version=3；topics=3／evidence=1／pending=[]；正文0。原正常审计保留，未改旧失败。

条件满足：在同一明确授权下单次启动固定26样本EV。最多78计数／24Chat／3342336总token，使用本正常LLMUse1，不使用旧v11凭证。
