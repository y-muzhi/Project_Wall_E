# V1.5 v11独立单次真实技术观测

2026-10-23（Asia/Hong_Kong）。用户明确答复“授权 v11 这一次有限观测”。新独占槽data/v15-observation-20261023-v11-once；旧两槽及原结果保留，不复用旧许可。

最多1批Tokenization＋1次Chat，输入131072、输出8192、总139264、framing预留1024，零重试。不启动用户服务、不写用户业务库、不包含26个真实效果样本；本槽创建后失败／取消／未知均不得重用或自动补发。凭证由原.env.local安全读取，不打印／修改密钥或全局环境。

固定profile=deepseek-v2，model=deepseek-v4-1-flash-260910；profile摘要与冻结release相同。manifest=db892fff3c7570ee94c1d2980f1424f50152e33125f604f80073a0f1ce35f86e；release=d7f67c022e1276b21b2628e93f2de76c467ba5caacdb59ac35dc99b2807b4872；程序源码SHA256=561b77cdf78df3962c7b1d89c692d4d811fb680c4619e3adfd44e4be925b6406。

状态：本Markdown独占记录已建立，准备单次执行；实际次数及最终结果以正常数据库及计数审计核对为准。

退出码：0；工具摘要：

mode=ISOLATED_OBSERVATION
database=C:\Users\羊牧之\Documents\ChatGPT\Project_Wall_E 2\data\v15-observation-20261023-v11-once\observation.sqlite
release=d7f67c022e1276b21b2628e93f2de76c467ba5caacdb59ac35dc99b2807b4872
result=AI_FINISHED
admission=LIVE_VERIFIED
count_batches_sent=1
chat_calls_sent=1



## 正常证据只读核对

许可已消耗并结束：1批真实计数、1次Chat、零重试。8项原始计数[6964, 342, 92, 1, 1, 1, 91, 135]；S+U=7306，预计输入=8330。实际输入=7309、输出=2275、总量=9584、缓存=0，耗时=16856ms、finish_reason=stop；gap=3，符合0—1024经验预留。模型及profile、请求与计数摘要一致，隔离库有效准入LIVE_VERIFIED；冻结v11仍保持初始OFFLINE_READY字节。

业务：run=COMPLETED／FINISHED；call=SUCCEEDED、parse=SUCCEEDED、validation=FAILED；application_result=NOT_REQUESTED、progress_result=REJECTED。根=IDLE、discussion_version=2；topics=0、evidence=0、pending=[2]；正文0份。progress_error=讨论增量的结构、引用或来源不符合本轮依据，未更新讨论进度。。

Chat请求ID=021792751675784e78c31fe06d4434dfef0260629e4a08bc248b5；Tokenization请求ID=021792751675082efca7158d8a072a352f4e6ec3154e35ab81a06。正常SQLite及CountingJournal保留，不另存原始报告／JSON，不删除正常审计。未导入用户业务库、未启动用户服务、未执行26个真实效果样本；技术观测不作为完整EV或产品验收通过。

## 2026-10-24接续离线诊断

以SQLite mode=ro取得实际parsed.progress_delta及原ContextBasis，apply_progress首因明确为Topic evidence is missing。模型已用new_t1—4／new_e1—2，但四个主题evidence_refs仍是m1或m1／m2；消息m别名不是讨论依据e引用。原程序拒绝正确，无自动映射或修复，原样保留、pending=[2]。本许可已结束，后续只离线改实际模型可见Schema，不补调用。
