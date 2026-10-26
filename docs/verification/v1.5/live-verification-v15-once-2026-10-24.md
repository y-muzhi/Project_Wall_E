# V1.5 资源批次v15技术及26EV汇总

2026-10-24。用户本次完整条件批次已全部结束，零重试，未用最大次数不可续用。技术1计数／1Chat，LIVE_VERIFIED、parse／validation成功、progress APPLIED；实际输入8408／输出2244／总10652／缓存0／gap3。

EV26固定样本：28计数／24Chat，22个正常stop返回全部validation SUCCEEDED；2个真实length／8192输出、parse FAILED、正文NOT_APPLIED；2份必要全文0Chat、CONTEXT_LIMIT_EXCEEDED；6个候选后处理PASSED。原v14三项失败对应样本本次全部程序校验通过，旧失败保留。

整批实际29计数／25Chat，输入216280／输出49335／总265615／缓存139264，所有模型／请求／用量及framing在授权限内。24根IDLE、2陈旧批次保持SUGGESTION_REVIEWING，所有GuideRun无RUNNING。

技术LIVE只为隔离库正常审计证据，冻结资源文件仍OFFLINE_READY，未导入用户库；用户数据／服务／Git未操作。112正常证据聚合SHA256=d6c73a4bbc8c98049d34cec887757bd947eb2cfbd311d8071653a73a754ecc92。

程序表见live-ev-v15-program-review-2026-10-24.md，人工语义入口manual-semantic-review-v15-2026-10-24.md。程序边界已实测，人工逐项语义未签，不宣称整版验收全部完成。
