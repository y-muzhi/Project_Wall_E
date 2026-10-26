# V1.5 v12有限真实验收批次

2026-10-24（Asia/Hong_Kong）。用户明确答复“授权技术观测及条件通过后的26样本（推荐）”。本记录独占申领时间=2026-10-24T12:47:47.747568+08:00。

先1批Tokenization＋1次Chat技术观测；准入LIVE_VERIFIED且首轮返回parse／validation均成功后，执行两领域26固定样本（两份超限样本仅计数、0Chat）。整批最多79计数／25Chat，逐Chat输入≤131072、输出≤8192、总量≤139264；Chat总量≤3481600。零重试、不自动换版本；未知结果、准入异常立即停止。不启动／更新用户服务，不写用户业务库，不调用模型裁判；旧槽及失败原结果保留。失败不复用／补发本槽。凭证仅从.env.local安全读入，值不记录。

manifest=3db3a635d5c639d6e1406e717bd7e84d380e70cb4796464fea101477a5810312；release=ad5e45c5e2373ece410d699c886e887c8179ac5303368c6e2fbc668341110a2e；profile=61941797052baa3c4a6cc1df54759b91d7fa933d2a4b98ec19d8b3b116cfc70e；model=deepseek-v4-1-flash-260910；app+observer SHA256=99778310bc6879a0666d23b715d610c953840fe97a054651293b92720135c302。设计及固定输入摘要核对通过。

技术槽=data/v15-observation-20261024-v12-once；EV槽=data/v15-ev-20261024-v12-once。状态：许可已申领，技术观测待实际结果；EV必须核实条件后另行单次启动。

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

EV命令：tools/run-v15-evaluation.py --execute --output-dir data/v15-ev-20261024-v12-once --report docs/verification/v1.5/live-ev-v12-once-2026-10-24.md --source-database data/v15-observation-20261024-v12-once/observation.sqlite --llm-use-id 1 --credential-file .env.local --allow-count-batches 78 --allow-chat-calls 24 --max-total-tokens 3342336

EV退出码=0；控制台摘要：

movie/discuss-initial recorded; semantic_review=pending
movie/discuss-long-preference recorded; semantic_review=pending
movie/discuss-correction recorded; semantic_review=pending
movie/discuss-decline recorded; semantic_review=pending
movie/document-generate recorded; semantic_review=pending
movie/document-local-revise recorded; semantic_review=pending
movie/document-long-specification recorded; semantic_review=pending
movie/proposals-table-row recorded; semantic_review=pending
movie/proposals-user-edit recorded; semantic_review=pending
movie/proposals-stale-original recorded; semantic_review=pending
movie/analysis-local-impact recorded; semantic_review=pending
movie/analysis-old-new recorded; semantic_review=pending
movie/analysis-required-over-budget recorded; semantic_review=pending
laboratory/discuss-initial recorded; semantic_review=pending
laboratory/discuss-long-preference recorded; semantic_review=pending
laboratory/discuss-correction recorded; semantic_review=pending
laboratory/discuss-decline recorded; semantic_review=pending
laboratory/document-generate recorded; semantic_review=pending
laboratory/document-local-revise recorded; semantic_review=pending
laboratory/document-long-specification recorded; semantic_review=pending
laboratory/proposals-table-row recorded; semantic_review=pending
laboratory/proposals-user-edit recorded; semantic_review=pending
laboratory/proposals-stale-original recorded; semantic_review=pending
laboratory/analysis-local-impact recorded; semantic_review=pending
laboratory/analysis-old-new recorded; semantic_review=pending
laboratory/analysis-required-over-budget recorded; semantic_review=pending


## 批次结束核对

2026-10-24当前事实：本次获批v12有限批次已消耗并结束。技术1计数／1Chat通过，26固定EV实际26计数／24Chat（24计数成功、2失败）；合计27计数／25Chat，实际输入184149、输出35550、总219699、缓存123904，全部预算内、零重试。24份模型返回均stop，10份validation成功、14份失败，四份正文直接保存；六份候选未建立批次，两份必要全文计数失败且0Chat，两份长规格返回NEED_EVIDENCE，不能宣称真实超限／截断通过。总记录live-verification-v12-once-2026-10-24.md，逐项live-ev-v12-once-2026-10-24.md，只读定位live-v12-diagnostics-2026-10-24.md。当前继续已授权离线修复：章节来源解析遗漏、模型可见来源与表格行规则；不追加真实IO，人工语义待审，用户业务库及服务未更新。
